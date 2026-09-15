from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.auto_label_job_repository import (
    IAutoLabelJobRepository,
)
from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.repositories.training_job_repository import (
    ITrainingJobRepository,
)
from app.application.ports.storage.archive_packer import IArchivePacker
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.model_version import ModelVersion
from app.domain.enums import TrainingJobStatus
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException

_ACTIVE_TRAINING = {TrainingJobStatus.QUEUED, TrainingJobStatus.RUNNING}
_VERSION_ALLOC_ATTEMPTS = 5
_MAX_UPLOAD_BYTES = 512 * 1024 * 1024
logger = logging.getLogger(__name__)


def _parent_rel(relative_path: str) -> str:
    return Path(relative_path).parent.as_posix()


def _train_work_rel(project_id: UUID, job_id: UUID) -> str:
    return f"projects/{project_id}/models/_train_{job_id}"


async def _safe_delete_directory(storage: IFileStorage, relative_dir: str) -> None:
    try:
        await storage.delete_directory(relative_dir)
    except Exception:
        logger.warning("failed to delete directory %s", relative_dir, exc_info=True)


class RenameModelVersionUseCase:
    def __init__(
        self,
        models: IModelVersionRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._models = models
        self._uow = uow

    async def execute(
        self, project_id: UUID, model_id: UUID, name: str
    ) -> ModelVersion:
        model = await self._models.get_by_id(model_id)
        if model is None or model.project_id != project_id:
            raise ResourceNotFoundException(f"model {model_id} not found")
        model.rename(name)
        await self._models.update(model)
        await self._uow.commit()
        return model


class ExportModelVersionUseCase:
    def __init__(
        self,
        models: IModelVersionRepository,
        storage: IFileStorage,
        packer: IArchivePacker,
    ) -> None:
        self._models = models
        self._storage = storage
        self._packer = packer

    async def execute(self, project_id: UUID, model_id: UUID) -> tuple[bytes, str]:
        model = await self._models.get_by_id(model_id)
        if model is None or model.project_id != project_id:
            raise ResourceNotFoundException(f"model {model_id} not found")
        try:
            weights = await self._storage.read(model.weights_path)
        except Exception as exc:
            raise DomainValidationException(
                f"weights not found: {model.weights_path}"
            ) from exc

        metadata = {
            "id": str(model.id),
            "project_id": str(model.project_id),
            "dataset_version_id": (
                str(model.dataset_version_id) if model.dataset_version_id else None
            ),
            "training_job_id": (
                str(model.training_job_id) if model.training_job_id else None
            ),
            "version_number": model.version_number,
            "name": model.name,
            "display_name": model.display_name,
            "weights_path": model.weights_path,
            "map50": model.map50,
            "map50_95": model.map50_95,
            "precision": model.precision,
            "recall": model.recall,
            "is_active_for_stream": model.is_active_for_stream,
            "created_at": model.created_at.isoformat(),
        }
        weights_name = Path(model.weights_path).name or "best.pt"
        archive = self._packer.pack(
            {
                weights_name: weights,
                "metadata.json": json.dumps(metadata, indent=2).encode("utf-8"),
            }
        )
        safe_name = "".join(
            ch if ch.isalnum() or ch in "-_." else "_" for ch in model.name
        )
        filename = f"model-{safe_name or model.version_number}.zip"
        return archive, filename


class DeleteModelVersionUseCase:
    def __init__(
        self,
        models: IModelVersionRepository,
        jobs: ITrainingJobRepository,
        auto_jobs: IAutoLabelJobRepository,
        annotations: IAnnotationRepository,
        storage: IFileStorage,
        uow: IUnitOfWork,
    ) -> None:
        self._models = models
        self._jobs = jobs
        self._auto_jobs = auto_jobs
        self._annotations = annotations
        self._storage = storage
        self._uow = uow

    async def execute(self, project_id: UUID, model_id: UUID) -> None:
        model = await self._models.get_by_id(model_id)
        if model is None or model.project_id != project_id:
            raise ResourceNotFoundException(f"model {model_id} not found")

        job = None
        if model.training_job_id is not None:
            job = await self._jobs.get_by_id(model.training_job_id)
        if job is not None and job.status in _ACTIVE_TRAINING:
            raise DomainValidationException(
                "cannot delete model while its training job is queued or running"
            )

        if job is not None and job.model_version_id == model.id:
            job.model_version_id = None
            await self._jobs.update(job)

        await self._auto_jobs.delete_by_model_version(model.id)
        await self._annotations.clear_model_version_refs(model.id)
        await self._models.delete(model.id)
        await self._uow.commit()

        dirs_to_delete: list[str] = []
        if model.weights_path:
            dirs_to_delete.append(_parent_rel(model.weights_path))
        if model.training_job_id is not None:
            dirs_to_delete.append(
                _train_work_rel(model.project_id, model.training_job_id)
            )
        for relative_dir in dirs_to_delete:
            await _safe_delete_directory(self._storage, relative_dir)


class UploadModelVersionUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        models: IModelVersionRepository,
        storage: IFileStorage,
        uow: IUnitOfWork,
    ) -> None:
        self._projects = projects
        self._models = models
        self._storage = storage
        self._uow = uow

    async def execute(
        self,
        project_id: UUID,
        *,
        filename: str,
        data: bytes,
        name: str | None = None,
    ) -> ModelVersion:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")

        safe_filename = Path(filename or "").name
        if not safe_filename.lower().endswith(".pt"):
            raise DomainValidationException("only .pt YOLO weight files are supported")
        if not data:
            raise DomainValidationException("uploaded weights file is empty")
        if len(data) > _MAX_UPLOAD_BYTES:
            raise DomainValidationException(
                f"weights file exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"
            )

        display_name = (name or "").strip() or Path(safe_filename).stem.strip() or None

        model: ModelVersion | None = None
        weights_rel: str | None = None
        for attempt in range(_VERSION_ALLOC_ATTEMPTS):
            version_number = await self._models.next_version_number(project_id)
            dest_rel_dir = f"projects/{project_id}/models/v{version_number}"
            weights_rel = await self._storage.save(dest_rel_dir, "best.pt", data)
            candidate = ModelVersion.create_uploaded(
                project_id=project_id,
                version_number=version_number,
                weights_path=weights_rel,
                name=display_name,
            )
            try:
                await self._models.deactivate_stream_models(project_id)
                await self._models.add(candidate)
                await self._uow.commit()
                model = candidate
                break
            except IntegrityError:
                await self._uow.rollback()
                await _safe_delete_directory(self._storage, dest_rel_dir)
                if attempt + 1 >= _VERSION_ALLOC_ATTEMPTS:
                    raise
                continue

        if model is None or weights_rel is None:
            raise DomainValidationException("failed to allocate model version number")
        return model
