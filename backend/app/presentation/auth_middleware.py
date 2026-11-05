import re
from fastapi import Request
from starlette.responses import JSONResponse
from app.infrastructure.auth import COOKIE, current_user
from app.infrastructure.db.project_annotators import image_permission, project_access

ID = r"[0-9a-fA-F-]{36}"
READ_SUFFIXES = {"", "/classes", "/annotation-queue"}


def full(patterns, path):
    return any(re.fullmatch(p, path) for p in patterns)


async def authorize(request: Request, call_next):
    path = request.url.path.rstrip("/")
    protected = path.startswith("/api/") or path in {"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
    if not protected or not request.app.state.auth_enabled or request.method == "OPTIONS":
        return await call_next(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "Запрос с другого сайта запрещён"}, status_code=403)
    if path in {"/api/v1/auth/status", "/api/v1/auth/setup", "/api/v1/auth/login"}:
        return await call_next(request)
    async with request.app.state.session_factory() as session:
        actor = await current_user(session, request.cookies.get(COOKIE))
    if actor is None:
        return JSONResponse({"detail": "Войдите в приложение"}, status_code=401)
    request.state.user = actor
    if actor["role"] == "ADMIN" or path in {"/api/v1/auth/me", "/api/v1/auth/logout"}:
        return await call_next(request)
    if request.method == "GET" and path == "/api/v1/projects":
        return await call_next(request)
    project = re.fullmatch(rf"/api/v1/projects/({ID})(/.*)?", path)
    image = re.fullmatch(rf"/api/v1/images/({ID})(.*)", path)
    if project:
        suffix = project.group(2) or ""
        readable = request.method == "GET" and suffix in READ_SUFFIXES
        claim = request.method == "POST" and suffix == "/annotation-queue/claim"
        action = request.method == "POST" and re.fullmatch(rf"/annotation-queue/{ID}/action", suffix or "")
        if not (readable or claim or action):
            return JSONResponse({"detail": "Доступно только администратору"}, status_code=403)
        async with request.app.state.session_factory() as session:
            access = await project_access(session, actor["id"], project.group(1))
        if access == "none" or (access == "lease" and claim):
            return JSONResponse({"detail": "Проект вам не назначен"}, status_code=403)
        return await call_next(request)
    if image:
        suffix = image.group(2)
        image_write = {
            "PUT": [r"/annotations", r"/label"],
            "POST": [r"/verify-all", r"/reject-pending", r"/mark-background", r"/label/confirm", r"/label/reject", rf"/annotations/{ID}/verify"],
            "DELETE": [r"/label", rf"/annotations/{ID}"],
        }
        route_ok = request.method == "GET" and suffix in {"", "/file", "/thumbnail"} or full(image_write.get(request.method, []), suffix)
        if not route_ok:
            return JSONResponse({"detail": "Доступно только администратору"}, status_code=403)
        async with request.app.state.session_factory() as session:
            allowed, detail = await image_permission(session, actor["id"], image.group(1))
        if not allowed:
            return JSONResponse({"detail": detail}, status_code=403)
        return await call_next(request)
    return JSONResponse({"detail": "Доступно только администратору"}, status_code=403)
