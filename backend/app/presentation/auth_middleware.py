import re
from fastapi import Request
from starlette.responses import JSONResponse
from sqlalchemy import select
from app.infrastructure.auth import COOKIE, current_user
from app.infrastructure.db.tables import AnnotationTaskRow, ImageRow

ID=r"[0-9a-fA-F-]{36}"
READ=[r"/api/v1/projects",rf"/api/v1/projects/{ID}",rf"/api/v1/projects/{ID}/classes",rf"/api/v1/projects/{ID}/annotation-queue"]
POST=[rf"/api/v1/projects/{ID}/annotation-queue/claim",rf"/api/v1/projects/{ID}/annotation-queue/{ID}/action"]
IMAGE_WRITE={
    "PUT":[r"/annotations",r"/label"],
    "POST":[r"/verify-all",r"/reject-pending",r"/mark-background",r"/label/confirm",r"/label/reject",rf"/annotations/{ID}/verify"],
    "DELETE":[r"/label",rf"/annotations/{ID}"],
}

def full(patterns,path):return any(re.fullmatch(p,path) for p in patterns)

async def authorize(request: Request,call_next):
    path=request.url.path.rstrip('/')
    protected=path.startswith('/api/') or path in {'/health','/docs','/redoc','/openapi.json','/docs/oauth2-redirect'}
    if not protected or not request.app.state.auth_enabled or request.method=='OPTIONS':return await call_next(request)
    if request.method not in {'GET','HEAD','OPTIONS'}:
        origin=request.headers.get('origin')
        if origin and origin!=f"{request.url.scheme}://{request.url.netloc}":return JSONResponse({'detail':'Запрос с другого сайта запрещён'},status_code=403)
    if path in {'/api/v1/auth/status','/api/v1/auth/setup','/api/v1/auth/login'}:return await call_next(request)
    async with request.app.state.session_factory() as session:
        actor=await current_user(session,request.cookies.get(COOKIE))
    if actor is None:return JSONResponse({'detail':'Войдите в приложение'},status_code=401)
    request.state.user=actor
    if actor['role']=='ADMIN' or path in {'/api/v1/auth/me','/api/v1/auth/logout'}:return await call_next(request)
    allowed=request.method=='GET' and full(READ,path) or request.method=='POST' and full(POST,path)
    match=re.fullmatch(rf"/api/v1/images/({ID})(.*)",path)
    if match:
        suffix=match.group(2)
        allowed=request.method=='GET' and suffix in {'','/file','/thumbnail'} or full(IMAGE_WRITE.get(request.method,[]),suffix)
        if allowed:
            async with request.app.state.session_factory() as session:
                queued=await session.scalar(select(AnnotationTaskRow.image_id).join(ImageRow,ImageRow.id==AnnotationTaskRow.image_id).where(AnnotationTaskRow.image_id==match.group(1),AnnotationTaskRow.state.in_(['QUEUED','WORKING']),ImageRow.deleted_at.is_(None)))
            if not queued:return JSONResponse({'detail':'Кадр не входит в очередь разметки'},status_code=403)
    if not allowed:return JSONResponse({'detail':'Доступно только администратору'},status_code=403)
    return await call_next(request)
