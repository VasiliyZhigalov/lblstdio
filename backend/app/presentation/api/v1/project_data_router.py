import asyncio
from pathlib import Path
from uuid import UUID
from uuid import uuid4
import shutil
from datetime import date

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.application.use_cases.images.project_data import ProjectDataUseCase
from app.infrastructure.db.repositories.project_data_repository import SqliteProjectDataRepository
from app.infrastructure.db.tables import ImageRow
from app.presentation.dependencies import get_session, get_storage
from app.presentation.dependencies import get_delete_class_use_case

router = APIRouter(tags=["project-data"])


@router.delete("/projects/{project_id}/data/classes/{class_id}")
async def delete_unused_class(project_id: UUID, class_id: UUID, session=Depends(get_session), uc=Depends(get_delete_class_use_case)):
    guard = ProjectDataUseCase(SqliteProjectDataRepository(session))
    await guard.ensure_class_unused(project_id, class_id)
    await uc.execute(class_id, project_id)
    return {"ok": True}


class DataQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = 48
    offset: int = 0
    q: str = Field(default="", max_length=255)
    sort: Literal["newest", "oldest", "name", "uncertainty", "objects"] = "newest"
    status: str | None = None
    split: str | None = None
    source_type: str | None = None
    stream_source_id: str | None = None
    class_id: str | None = None
    annotation_source: str | None = None
    min_objects: int | None = Field(default=None, ge=0)
    max_objects: int | None = Field(default=None, ge=0)
    min_width: int | None = Field(default=None, ge=0)
    min_height: int | None = Field(default=None, ge=0)
    min_conf: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    max_conf: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    min_area: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    max_area: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    background: bool | None = None
    trash: bool = False
    duplicates: bool = False
    after: date | None = None
    before: date | None = None
    tag: str | None = Field(default=None, max_length=64)
    version_id: str | None = None
    quality: Literal["dark", "blur"] | None = None
    orientation: Literal["landscape", "portrait", "square"] | None = None
    format: Literal["jpg", "png", "webp"] | None = None


class DataAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["tag", "review", "trash", "restore"]
    filters: DataQuery = Field(default_factory=DataQuery)
    ids: list[UUID] = Field(default_factory=list, max_length=5000)
    all_matching: bool = False
    tag: str = Field(default="", max_length=64)


class StartImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, str] = Field(default_factory=dict)
    names: list[str] | None = None


@router.post("/projects/{project_id}/data/analyze")
async def analyze(project_id: UUID, request: Request):
    return await request.app.state.data_imports.analyze(project_id)


@router.post("/projects/{project_id}/data/dictionary/preview")
async def dictionary(project_id: UUID, request: Request):
    import yaml
    from app.domain.exceptions import DomainValidationException
    async with request.form() as form:
        file = form.get("file")
        if not isinstance(file, UploadFile): raise HTTPException(422, "Выберите файл словаря")
        content = await file.read(1024*1024+1)
        if len(content) > 1024*1024: raise HTTPException(413, "Словарь больше 1 МБ")
    try:
        data = yaml.safe_load(content.decode("utf-8-sig"))
        raw = data.get("names", data) if isinstance(data, dict) else data
        if isinstance(raw, dict): raw = [raw[k] for k in sorted(raw, key=lambda k: int(k))]
        if not isinstance(raw, list): raise ValueError()
        names = [str(n).strip() for n in raw]
        if any(not n for n in names): raise ValueError()
        return {"names": names}
    except (ValueError, TypeError, yaml.YAMLError) as exc: raise DomainValidationException("Некорректный словарь: нужен names со списком классов") from exc


@router.post("/projects/{project_id}/data/imports/preview")
async def preview_import(project_id: UUID, request: Request):
    manager = request.app.state.data_imports
    root = manager.root / str(uuid4())
    root.mkdir()
    try:
        staged, total = [], 0
        async with request.form(max_files=10005, max_fields=10010) as form:
            kind = str(form.get("kind", "images"))
            if kind not in {"images", "dataset", "model"}: raise HTTPException(422, "Неизвестный тип импорта")
            paths = form.getlist("relative_paths")
            files = form.getlist("files")
            for i, file in enumerate(files):
                if not isinstance(file, UploadFile): continue
                original = str(paths[i]) if i < len(paths) else file.filename
                target = root / (str(i) + Path(file.filename or "").suffix.lower())
                size = 0
                with target.open("wb") as output:
                    while chunk := await file.read(1024*1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > 512*1024**2 or total > 1024**3: raise HTTPException(413, "Файл больше 512 МБ или загрузка больше 1 ГБ")
                        output.write(chunk)
                staged.append((original, target))
            if not staged: raise HTTPException(422, "Выберите файлы")
        return await manager.prepare(project_id, kind, staged, root)
    except BaseException:
        await asyncio.to_thread(shutil.rmtree, root, True)
        raise


@router.get("/projects/{project_id}/data/imports")
async def import_history(project_id: UUID, request: Request):
    return await request.app.state.data_imports.list(project_id)


@router.post("/projects/{project_id}/data/imports/{job_id}/start")
async def start_import(project_id: UUID, job_id: UUID, payload: StartImport, request: Request):
    return await request.app.state.data_imports.start(project_id, job_id, payload.model_dump(exclude_none=True))


@router.post("/projects/{project_id}/data/imports/{job_id}/cancel")
async def cancel_import(project_id: UUID, job_id: UUID, request: Request):
    return await request.app.state.data_imports.cancel_or_rollback(project_id, job_id)


@router.post("/projects/{project_id}/data/imports/{job_id}/rollback")
async def rollback_import(project_id: UUID, job_id: UUID, request: Request):
    return await request.app.state.data_imports.cancel_or_rollback(project_id, job_id, True)


def use_case(session: AsyncSession = Depends(get_session)):
    return ProjectDataUseCase(SqliteProjectDataRepository(session))


@router.post("/projects/{project_id}/data/query")
async def page(project_id: UUID, filters: DataQuery, uc=Depends(use_case)):
    return await uc.page(project_id, filters.model_dump(exclude_none=True, mode="json"))


@router.get("/projects/{project_id}/data/statistics")
async def statistics(project_id: UUID, uc=Depends(use_case)):
    return await uc.statistics(project_id)


@router.get("/projects/{project_id}/data/cameras")
async def cameras(project_id: UUID, request: Request, uc=Depends(use_case)):
    rows = await uc.cameras(project_id)
    for row in rows:
        runtime = request.app.state.stream_runner.get_status(UUID(row["id"]))
        row.update(state=runtime.state, fps=runtime.fps, error=runtime.error_message)
    return rows


@router.put("/projects/{project_id}/data/cameras/{stream_id}")
async def link(project_id: UUID, stream_id: UUID, payload: dict, uc=Depends(use_case)):
    await uc.link_camera(project_id, stream_id, bool(payload.get("linked", True)))
    return {"ok": True}


@router.post("/projects/{project_id}/data/actions")
async def action(project_id: UUID, payload: DataAction, uc=Depends(use_case)):
    return await uc.mutate(project_id, payload.model_dump(exclude_none=True, mode="json"))


@router.get("/images/{image_id}/thumbnail")
async def thumbnail(image_id: UUID, request: Request, session=Depends(get_session), storage=Depends(get_storage)):
    row = await session.get(ImageRow, str(image_id))
    if row is None: raise HTTPException(404, "Изображение не найдено")
    original = Path(storage.get_absolute_path(row.file_path))
    if not original.is_file(): raise HTTPException(404, "Файл изображения не найден")
    target = request.app.state.storage_root / "_thumbnails" / f"{image_id}-{original.stat().st_mtime_ns}.jpg"
    if not target.exists():
        def create():
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(original) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((480, 360))
                # Each writer uses its own temporary file; replace publishes a complete JPEG.
                import tempfile
                with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".jpg", delete=False) as temp:
                    temp_path = Path(temp.name)
                try:
                    image.save(temp_path, "JPEG", quality=78)
                    temp_path.replace(target)
                finally:
                    temp_path.unlink(missing_ok=True)
        await asyncio.to_thread(create)
    return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
