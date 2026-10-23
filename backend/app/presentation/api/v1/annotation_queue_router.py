from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from app.application.use_cases.annotations.queue import AnnotationQueue
from app.infrastructure.db.annotation_queue import SqliteAnnotationQueue, session_owner, require_write, QueueConflict
from app.presentation.dependencies import get_session
from app.presentation.api.v1.project_data_router import DataQuery

router = APIRouter(tags=["annotation-queue"])


def owner(request: Request): return session_owner(request.headers.get("X-Annotation-Session"))


def use_case(session=Depends(get_session)): return AnnotationQueue(SqliteAnnotationQueue(session))


class EnqueueRequest(BaseModel):
    filters: DataQuery = Field(default_factory=DataQuery)
    ids: list[UUID] = Field(default_factory=list, max_length=5000)
    all_matching: bool = False


class ClaimRequest(BaseModel):
    image_id: UUID | None = None


class ActionRequest(BaseModel):
    action: Literal["heartbeat", "release", "finish", "skip", "clear", "trash", "background"]
    revision: int = Field(ge=0)
    reason: str = Field(default="", max_length=2000)


@router.get("/projects/{project_id}/annotation-queue")
async def queue(project_id: UUID, state: Literal["all", "available", "mine", "DONE", "ISSUE"] = "all", offset: int = 0, limit: int = 48, actor=Depends(owner), uc=Depends(use_case)):
    return await uc.list(project_id, actor, state, offset, limit)


@router.post("/projects/{project_id}/annotation-queue/enqueue")
async def enqueue(project_id: UUID, payload: EnqueueRequest, session=Depends(get_session)):
    return await SqliteAnnotationQueue(session).enqueue(project_id, payload.filters.model_dump(mode="json", exclude_none=True), [str(i) for i in payload.ids], payload.all_matching)


@router.post("/projects/{project_id}/annotation-queue/claim")
async def claim(project_id: UUID, payload: ClaimRequest, actor=Depends(owner), uc=Depends(use_case)):
    return await uc.claim(project_id, actor, payload.image_id)


@router.post("/projects/{project_id}/annotation-queue/{image_id}/action")
async def action(project_id: UUID, image_id: UUID, payload: ActionRequest, actor=Depends(owner), uc=Depends(use_case)):
    return await uc.action(project_id, image_id, actor, payload.action, payload.revision, payload.reason)


async def guard_annotation_mutation(request: Request, response: Response, session=Depends(get_session)):
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}: return
    image_id = request.path_params.get("image_id")
    if image_id is None: return
    raw = request.headers.get("X-Annotation-Revision")
    try: revision = int(raw) if raw is not None else None
    except ValueError: raise HTTPException(409, "Некорректная версия кадра")
    actor = session_owner(request.headers.get("X-Annotation-Session")) if request.headers.get("X-Annotation-Session") else None
    updated = await require_write(session, image_id, actor, revision)
    if updated is not None: response.headers["X-Annotation-Revision"] = str(updated)
