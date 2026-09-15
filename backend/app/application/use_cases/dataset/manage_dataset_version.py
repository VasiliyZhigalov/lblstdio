from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.auto_label_job_repository import (
    IAutoLabelJobRepository,
)
from app.application.ports.repositories.dataset_version_repository import (
    IDatasetVersionRepository,
)
from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.application.ports.repositories.training_job_repository import (
    ITrainingJobRepository,
)
from app.application.ports.storage.archive_packer import IArchivePacker
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.dataset_version import DatasetVersion
from app.domain.enums import DatasetVersionStatus, TrainingJobStatus
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException

_ACTIVE_TRAINING = {TrainingJobStatus.QUEUED, TrainingJobStatus.RUNNING}
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


class RenameDatasetVersionUseCase:
    def __init__(
        self,
        versions: IDatasetVersionRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._versions = versions
        self._uow = uow

    async def execute(self, version_id: UUID, name: str) -> DatasetVersion:
        version = await self._versions.get_by_id(version_id)
        if version is None:
            raise ResourceNotFoundException(f"dataset version {version_id} not found")
        version.rename(name)
        await self._versions.update(version)
        await self._uow.commit()
        return version


class ExportDatasetVersionUseCase:
    def __init__(
        self,
        versions: IDatasetVersionRepository,
        storage: IFileStorage,
        packer: IArchivePacker,
    ) -> None:
        self._versions = versions
        self._storage = storage
        self._packer = packer

    async def execute(self, version_id: UUID) -> tuple[bytes, str]:
        version = await self._versions.get_by_id(version_id)
        if version is None:
            raise ResourceNotFoundException(f"dataset version {version_id} not found")
        if version.status != DatasetVersionStatus.READY:
            raise DomainValidationException(
                "only READY dataset versions can be exported"
            )
        if not version.yaml_path:
            raise DomainValidationException("dataset version has no yaml_path")

        root_rel = _parent_rel(version.yaml_path)
        files = await self._storage.list_files(root_rel)
        if not files:
            raise DomainValidationException(
                f"dataset folder is empty or missing: {root_rel}"
            )
        archive = self._packer.pack(files)
        safe_name = "".join(
            ch if ch.isalnum() or ch in "-_." else "_" for ch in version.name
        )
        filename = f"dataset-{safe_name or version.version_number}.zip"
        return archive, filename


class DeleteDatasetVersionUseCase:
    def __init__(
        self,
        versions: IDatasetVersionRepository,
        models: IModelVersionRepository,
        jobs: ITrainingJobRepository,
        auto_jobs: IAutoLabelJobRepository,
        annotations: IAnnotationRepository,
        storage: IFileStorage,
        uow: IUnitOfWork,
    ) -> None:
        self._versions = versions
        self._models = models
        self._jobs = jobs
        self._auto_jobs = auto_jobs
        self._annotations = annotations
        self._storage = storage
        self._uow = uow

    async def execute(self, version_id: UUID) -> None:
        version = await self._versions.get_by_id(version_id)
        if version is None:
            raise ResourceNotFoundException(f"dataset version {version_id} not found")

        training_jobs = await self._jobs.list_by_dataset_version(version_id)
        if any(job.status in _ACTIVE_TRAINING for job in training_jobs):
            raise DomainValidationException(
                "cannot delete dataset while training is queued or running"
            )

        linked_models = await self._models.list_by_dataset_version(version_id)
        model_ids = [item.id for item in linked_models]
        dirs_to_delete: list[str] = []
        for model in linked_models:
            if model.weights_path:
                dirs_to_delete.append(_parent_rel(model.weights_path))
            if model.training_job_id is not None:
                dirs_to_delete.append(
                    _train_work_rel(model.project_id, model.training_job_id)
                )
        for job in training_jobs:
            dirs_to_delete.append(_train_work_rel(job.project_id, job.id))
        if version.yaml_path:
            dirs_to_delete.append(_parent_rel(version.yaml_path))

        await self._auto_jobs.delete_by_model_versions(model_ids)
        for model in linked_models:
            await self._annotations.clear_model_version_refs(model.id)
            await self._models.delete(model.id)

        await self._jobs.delete_by_dataset_version(version_id)
        await self._versions.delete(version_id)
        await self._uow.commit()

        seen: set[str] = set()
        for relative_dir in dirs_to_delete:
            if relative_dir in seen:
                continue
            seen.add(relative_dir)
            await _safe_delete_directory(self._storage, relative_dir)
