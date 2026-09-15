from __future__ import annotations

import json
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
from app.domain.entities.model_version import ModelVersion
from app.domain.enums import DatasetVersionStatus, TrainingJobStatus
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException

_ACTIVE_TRAINING = {TrainingJobStatus.QUEUED, TrainingJobStatus.RUNNING}


def _parent_rel(relative_path: str) -> str:
    return Path(relative_path).parent.as_posix()


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
        await self._auto_jobs.delete_by_model_versions(model_ids)
        for model in linked_models:
            await self._annotations.clear_model_version_refs(model.id)
            await self._models.delete(model.id)
            if model.weights_path:
                try:
                    await self._storage.delete_directory(_parent_rel(model.weights_path))
                except Exception:
                    pass

        await self._jobs.delete_by_dataset_version(version_id)
        await self._versions.delete(version_id)
        await self._uow.commit()

        if version.yaml_path:
            try:
                await self._storage.delete_directory(_parent_rel(version.yaml_path))
            except Exception:
                pass


class RenameModelVersionUseCase:
    def __init__(
        self,
        models: IModelVersionRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._models = models
        self._uow = uow

    async def execute(self, model_id: UUID, name: str) -> ModelVersion:
        model = await self._models.get_by_id(model_id)
        if model is None:
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

    async def execute(self, model_id: UUID) -> tuple[bytes, str]:
        model = await self._models.get_by_id(model_id)
        if model is None:
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
            "dataset_version_id": str(model.dataset_version_id),
            "training_job_id": str(model.training_job_id),
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

    async def execute(self, model_id: UUID) -> None:
        model = await self._models.get_by_id(model_id)
        if model is None:
            raise ResourceNotFoundException(f"model {model_id} not found")

        job = await self._jobs.get_by_id(model.training_job_id)
        if job is not None and job.status in _ACTIVE_TRAINING:
            raise DomainValidationException(
                "cannot delete model while its training job is queued or running"
            )

        await self._auto_jobs.delete_by_model_version(model.id)
        await self._annotations.clear_model_version_refs(model.id)
        await self._models.delete(model.id)
        await self._uow.commit()

        if model.weights_path:
            try:
                await self._storage.delete_directory(_parent_rel(model.weights_path))
            except Exception:
                pass
