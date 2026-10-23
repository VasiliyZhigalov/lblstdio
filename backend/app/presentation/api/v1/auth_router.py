import asyncio
import hashlib
import secrets
import time
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy import select, delete, update, func
from app.infrastructure.auth import COOKIE, SESSION_SECONDS, current_user, create_user, issue_session, public, verify_password, hash_password, token_hash
from app.infrastructure.db.tables import UserRow, LoginSessionRow
from app.presentation.dependencies import get_session

router=APIRouter(prefix='/auth',tags=['auth'])
_attempts={}

class Credentials(BaseModel):
    username:str=Field(min_length=1,max_length=40)
    password:str=Field(min_length=1,max_length=128)
class NewUser(Credentials):
    role:Literal['ADMIN','ANNOTATOR']='ANNOTATOR'
class UpdateUser(BaseModel):
    role:Literal['ADMIN','ANNOTATOR']|None=None
    is_active:bool|None=None
    password:str|None=Field(default=None,min_length=8,max_length=128)

def admin(request):
    if not getattr(request.state,'user',None) or request.state.user['role']!='ADMIN':raise HTTPException(403,'Доступно только администратору')

def cookie(response,token,request):
    response.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=SESSION_SECONDS,path='/')

@router.get('/status')
async def status(request:Request,session=Depends(get_session)):
    enabled=request.app.state.auth_enabled
    count=await session.scalar(select(func.count()).select_from(UserRow))
    return {'enabled':enabled,'needs_setup':enabled and count==0}

@router.post('/setup',status_code=201)
async def setup(payload:Credentials,request:Request,response:Response,session=Depends(get_session)):
    if not request.app.state.auth_enabled:raise HTTPException(404,'Авторизация отключена в тестовом приложении')
    user=await create_user(session,payload.username,payload.password,'ADMIN',initial=True)
    cookie(response,await issue_session(session,user),request)
    return public(user)

@router.post('/login')
async def login(payload:Credentials,request:Request,response:Response,session=Depends(get_session)):
    key=(request.client.host if request.client else '',payload.username.strip().casefold())
    attempts=[at for at in _attempts.get(key,[]) if at>time.monotonic()-60]
    if len(attempts)>=10:raise HTTPException(429,'Слишком много попыток. Подождите минуту')
    user=await session.scalar(select(UserRow).where(UserRow.username==key[1]))
    if user is None:
        await asyncio.to_thread(hashlib.pbkdf2_hmac,'sha256',payload.password.encode(),b'unknown-user-salt',600_000)
        valid=False
    else:valid=await asyncio.to_thread(verify_password,payload.password,user.password_hash)
    if not valid or not user.is_active:
        _attempts[key]=attempts+[time.monotonic()]
        raise HTTPException(401,'Неверный логин или пароль')
    _attempts.pop(key,None)
    cookie(response,await issue_session(session,user),request)
    return public(user)

@router.get('/me')
async def me(request:Request):
    if not getattr(request.state,'user',None):raise HTTPException(401,'Войдите в приложение')
    return request.state.user

@router.post('/logout',status_code=204)
async def logout(request:Request,response:Response,session=Depends(get_session)):
    token=request.cookies.get(COOKIE)
    if token:await session.execute(delete(LoginSessionRow).where(LoginSessionRow.token_hash==token_hash(token)))
    await session.commit();response.delete_cookie(COOKIE,path='/')

@router.get('/users')
async def users(request:Request,session=Depends(get_session)):
    admin(request)
    return [public(u) for u in await session.scalars(select(UserRow).order_by(UserRow.created_at))]

@router.post('/users',status_code=201)
async def add_user(payload:NewUser,request:Request,session=Depends(get_session)):
    admin(request)
    return public(await create_user(session,payload.username,payload.password,payload.role))

@router.patch('/users/{user_id}')
async def update_user(user_id:UUID,payload:UpdateUser,request:Request,session=Depends(get_session)):
    admin(request)
    user=await session.get(UserRow,str(user_id))
    if not user:raise HTTPException(404,'Пользователь не найден')
    # Serialize account administration so two admins cannot disable each other concurrently.
    await session.execute(update(UserRow).where(UserRow.id==str(user_id)).values(is_active=UserRow.is_active))
    await session.refresh(user)
    actor=await session.get(UserRow,request.state.user['id'],populate_existing=True)
    if not actor or not actor.is_active or actor.role!='ADMIN':raise HTTPException(403,'Доступ администратора изменился')
    if str(user_id)==request.state.user['id'] and (payload.is_active is False or payload.role=='ANNOTATOR'):raise HTTPException(409,'Нельзя отключить себя или снять свою роль администратора')
    if payload.role is not None:user.role=payload.role
    if payload.is_active is not None:user.is_active=int(payload.is_active)
    if payload.password is not None:user.password_hash=hash_password(payload.password)
    if payload.password is not None or payload.is_active is False or payload.role is not None:
        await session.execute(delete(LoginSessionRow).where(LoginSessionRow.user_id==str(user_id)))
    await session.commit()
    return public(user)
