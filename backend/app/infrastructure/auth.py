import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError
from app.infrastructure.db.tables import UserRow, LoginSessionRow, AuthSetupRow
from app.infrastructure.db.dialect import dialect_insert

COOKIE = "lblstdio_session"
SESSION_SECONDS = 12 * 60 * 60
ITERATIONS = 600_000

def now(): return datetime.now(timezone.utc)
def token_hash(token): return hashlib.sha256(token.encode()).hexdigest()
def public(user):return {"id":user.id,"username":user.username,"role":user.role,"is_active":bool(user.is_active)}
def username(value):
    value=value.strip().casefold()
    if not re.fullmatch(r"[\w.-]{3,40}",value):raise HTTPException(422,"Логин: от 3 до 40 букв, цифр, точек, дефисов или подчёркиваний")
    return value

def hash_password(password):
    if len(password)<8 or len(password)>128:raise HTTPException(422,"Пароль должен содержать от 8 до 128 символов")
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"

def verify_password(password,encoded):
    try:
        _,iterations,salt,digest=encoded.split('$')
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(iterations)).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError):return False

async def current_user(session,token):
    if not token or len(token)>200:return None
    row=await session.scalar(select(UserRow).join(LoginSessionRow,UserRow.id==LoginSessionRow.user_id).where(LoginSessionRow.token_hash==token_hash(token),LoginSessionRow.expires_at>now(),UserRow.is_active==1))
    return public(row) if row else None

async def issue_session(session,user):
    token=secrets.token_urlsafe(32)
    await session.execute(delete(LoginSessionRow).where(LoginSessionRow.expires_at<=now()))
    session.add(LoginSessionRow(token_hash=token_hash(token),user_id=user.id,expires_at=now()+timedelta(seconds=SESSION_SECONDS)))
    await session.commit()
    return token

async def create_user(session,login,password,role,*,initial=False):
    login=username(login)
    if role not in {'ADMIN','ANNOTATOR'}:raise HTTPException(422,"Неизвестная роль")
    password_hash=hash_password(password)
    if initial:
        if await session.scalar(select(func.count()).select_from(UserRow)):raise HTTPException(409,"Администратор уже создан")
        result=await session.execute(dialect_insert(session, AuthSetupRow).values(id=1).on_conflict_do_nothing())
        if result.rowcount!=1:raise HTTPException(409,"Первоначальная настройка уже выполнена")
    row=UserRow(id=str(uuid4()),username=login,password_hash=password_hash,role=role,is_active=1,created_at=now())
    session.add(row)
    try:await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409,"Пользователь с таким логином уже существует")
    return row
