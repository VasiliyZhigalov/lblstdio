from __future__ import annotations

import asyncio
import queue
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.application.ports.repositories.dataset_version_repository import (
    IDatasetVersionRepository,
)
from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.repositories.training_job_repository import (
    ITrainingJobRepository,
)
from app.application.ports.services.model_trainer import IModelTrainer, TrainingConfig
from app.application.ports.services.training_device import ITrainingDeviceResolver
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.application.services.device_policy import normalize_device_request
from app.domain.entities.model_version import ModelVersion
from app.domain.entities.training_job import TrainingJob
from app.domain.enums import DatasetVersionStatus, TrainingJobStatus
from app.domain.exceptions import (
    DatasetNotReadyException,
    DomainValidationException,
    ModelWeightsMissingException,
    ResourceNotFoundException,
)

_ALLOWED_PRETRAINED = frozenset(
    {
        "yolov8n.pt",
        "yolov8s.pt",
        "yolov8m.pt",
        "yolov8l.pt",
        "yolov8x.pt",
    }
)

_ORPHAN_MESSAGE = "interrupted by server restart"
_VERSION_ALLOC_ATTEMPTS = 5


class TrainModelUseCase:
    """Enqueue YOLO training on a READY dataset version."""

    def __init__(
        self,
        projects: IProjectRepository,
        versions: IDatasetVersionRepository,
        jobs: ITrainingJobRepository,
        storage: IFileStorage,
        uow: IUnitOfWork,
        models: IModelVersionRepository | None = None,
        runner: TrainingJobRunner | None = None,
        device_resolver: ITrainingDeviceResolver | Callable[[str], str] | None = None,
    ) -> None:
        self._projects = projects
        self._versions = versions
        self._jobs = jobs
        self._storage = storage
        self._uow = uow
        self._models = models
        self._runner = runner
        self._device_resolver = device_resolver

    async def execute(
        self,
        project_id: UUID,
        dataset_version_id: UUID,
        *,
        epochs: int = 100,
        batch_size: int = 16,
        imgsz: int = 640,
        device: str = "auto",
        base_weights: str | None = "yolov8n.pt",
        base_model_version_id: UUID | None = None,
        patience: int = 20,
    ) -> TrainingJob:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")

        version = await self._versions.get_by_id(dataset_version_id)
        if version is None or version.project_id != project_id:
            raise ResourceNotFoundException(
                f"dataset version {dataset_version_id} not found"
            )
        if version.status != DatasetVersionStatus.READY:
            raise DatasetNotReadyException(
                f"dataset version must be READY, got {version.status.value}"
            )
        if not version.yaml_path:
            raise DatasetNotReadyException("dataset version has no data.yaml")

        self._storage.get_absolute_path(version.yaml_path)

        resolved_weights = await self._resolve_base_weights(
            project_id, base_weights, base_model_version_id
        )
        requested = normalize_device_request(device)
        if self._device_resolver is None:
            resolved_device = requested
        elif hasattr(self._device_resolver, "resolve"):
            resolved_device = self._device_resolver.resolve(requested)  # type: ignore[union-attr]
        else:
            resolved_device = self._device_resolver(requested)  # type: ignore[operator]

        job = TrainingJob.create(
            project_id=project_id,
            dataset_version_id=dataset_version_id,
            epochs=epochs,
            batch_size=batch_size,
            imgsz=imgsz,
            device=resolved_device,
            base_weights=resolved_weights,
            patience=patience,
        )
        await self._jobs.add(job)
        await self._uow.commit()

        if self._runner is not None:
            self._runner.schedule(job.id)

        return job

    async def _resolve_base_weights(
        self,
        project_id: UUID,
        base_weights: str | None,
        base_model_version_id: UUID | None,
    ) -> str:
        if base_model_version_id is not None:
            if self._models is None:
                raise DomainValidationException("model repository is not configured")
            model = await self._models.get_by_id(base_model_version_id)
            if model is None or model.project_id != project_id:
                raise ResourceNotFoundException(
                    f"model version {base_model_version_id} not found"
                )
            try:
                abs_path = self._storage.get_absolute_path(model.weights_path)
            except Exception as exc:
                raise ModelWeightsMissingException(
                    f"weights not found: {model.weights_path}"
                ) from exc
            if not Path(abs_path).is_file():
                raise ModelWeightsMissingException(
                    f"weights file missing: {model.weights_path}"
                )
            return abs_path

        name = (base_weights or "yolov8n.pt").strip()
        if name not in _ALLOWED_PRETRAINED:
            raise DomainValidationException(
                f"unsupported base_weights '{name}'; "
                f"allowed: {', '.join(sorted(_ALLOWED_PRETRAINED))}"
            )
        return name


class GetTrainingJobUseCase:
    def __init__(self, jobs: ITrainingJobRepository) -> None:
        self._jobs = jobs

    async def execute(self, job_id: UUID) -> TrainingJob:
        job = await self._jobs.get_by_id(job_id)
        if job is None:
            raise ResourceNotFoundException(f"training job {job_id} not found")
        return job


class ListModelVersionsUseCase:
    def __init__(self, models: IModelVersionRepository) -> None:
        self._models = models

    async def execute(self, project_id: UUID) -> list[ModelVersion]:
        return await self._models.list_by_project(project_id)


class TrainingJobRunner:
    """Runs training off the event loop and persists epoch metrics live."""

    def __init__(
        self,
        session_factory,
        storage: IFileStorage,
        trainer: IModelTrainer,
        *,
        device_resolver: ITrainingDeviceResolver | Callable[[str], str] | None = None,
        max_concurrent: int = 1,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._trainer = trainer
        self._device_resolver = device_resolver
        self._sem = asyncio.Semaphore(max(1, max_concurrent))
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, job_id: UUID) -> None:
        task = asyncio.create_task(self._run(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run_inline(self, job_id: UUID) -> None:
        await self._run(job_id)

    async def fail_orphaned_jobs(self) -> int:
        """Mark QUEUED/RUNNING jobs as FAILED after process restart."""
        from app.infrastructure.db.repositories.training_job_repository import (
            SqliteTrainingJobRepository,
        )
        from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        async with self._session_factory() as session:
            jobs = SqliteTrainingJobRepository(session)
            uow = SqlAlchemyUnitOfWork(session)
            orphans = await jobs.list_by_statuses(
                (TrainingJobStatus.QUEUED, TrainingJobStatus.RUNNING)
            )
            for job in orphans:
                job.mark_failed(_ORPHAN_MESSAGE)
                await jobs.update(job)
            if orphans:
                await uow.commit()
            return len(orphans)

    def _resolve_device(self, requested: str) -> str:
        if self._device_resolver is None:
            return requested
        if hasattr(self._device_resolver, "resolve"):
            return self._device_resolver.resolve(requested)  # type: ignore[union-attr]
        return self._device_resolver(requested)  # type: ignore[operator]

    async def _run(self, job_id: UUID) -> None:
        async with self._sem:
            await self._run_locked(job_id)

    async def _run_locked(self, job_id: UUID) -> None:
        from app.infrastructure.db.repositories.dataset_version_repository import (
            SqliteDatasetVersionRepository,
        )
        from app.infrastructure.db.repositories.model_version_repository import (
            SqliteModelVersionRepository,
        )
        from app.infrastructure.db.repositories.training_job_repository import (
            SqliteTrainingJobRepository,
        )
        from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        async with self._session_factory() as session:
            jobs = SqliteTrainingJobRepository(session)
            versions = SqliteDatasetVersionRepository(session)
            models = SqliteModelVersionRepository(session)
            uow = SqlAlchemyUnitOfWork(session)

            job = await jobs.get_by_id(job_id)
            if job is None:
                return
            if job.status in {TrainingJobStatus.COMPLETED, TrainingJobStatus.FAILED}:
                return

            work_rel = f"projects/{job.project_id}/models/_train_{job.id}"

            async def _fail(message: str) -> None:
                fresh = await jobs.get_by_id(job_id)
                if fresh is None:
                    return
                if fresh.status in {
                    TrainingJobStatus.COMPLETED,
                    TrainingJobStatus.FAILED,
                }:
                    return
                fresh.mark_failed(message)
                await jobs.update(fresh)
                await uow.commit()

            try:
                version = await versions.get_by_id(job.dataset_version_id)
                if version is None:
                    await _fail("dataset version missing")
                    return

                job.mark_running()
                await jobs.update(job)
                await uow.commit()

                device = self._resolve_device(job.device)
                yaml_abs = self._storage.get_absolute_path(version.yaml_path)
                work_abs = self._storage.get_absolute_path(work_rel)
                Path(work_abs).mkdir(parents=True, exist_ok=True)

                epoch_queue: queue.Queue = queue.Queue()
                loop = asyncio.get_running_loop()

                def on_epoch(metrics: dict) -> None:
                    epoch_queue.put(metrics)

                train_future = loop.run_in_executor(
                    None,
                    lambda: self._trainer.train(
                        TrainingConfig(
                            data_yaml_path=yaml_abs,
                            output_dir=work_abs,
                            epochs=job.epochs,
                            batch_size=job.batch_size,
                            imgsz=job.imgsz,
                            device=device,
                            base_weights=job.base_weights,
                            patience=job.patience,
                        ),
                        on_epoch_end=on_epoch,
                    ),
                )

                while not train_future.done():
                    drained = False
                    while True:
                        try:
                            metrics = epoch_queue.get_nowait()
                        except queue.Empty:
                            break
                        drained = True
                        job.append_epoch_metrics(metrics)
                    if drained:
                        await jobs.update(job)
                        await uow.commit()
                    await asyncio.sleep(0.4)

                result = await train_future

                while True:
                    try:
                        metrics = epoch_queue.get_nowait()
                    except queue.Empty:
                        break
                    job.append_epoch_metrics(metrics)

                if result.metrics_history:
                    known = {
                        (m.get("epoch"), m.get("map50")) for m in job.metrics_history
                    }
                    for item in result.metrics_history:
                        key = (item.get("epoch"), item.get("map50"))
                        if key not in known:
                            job.append_epoch_metrics(item)

                await jobs.update(job)
                await uow.commit()

                best_src = Path(result.best_weights_path)
                if not best_src.is_file():
                    await _fail(f"best.pt missing at {result.best_weights_path}")
                    return

                model = None
                for attempt in range(_VERSION_ALLOC_ATTEMPTS):
                    version_number = await models.next_version_number(job.project_id)
                    dest_rel_dir = (
                        f"projects/{job.project_id}/models/v{version_number}"
                    )
                    dest_abs_dir = Path(self._storage.get_absolute_path(dest_rel_dir))
                    dest_abs_dir.mkdir(parents=True, exist_ok=True)
                    dest_abs = dest_abs_dir / "best.pt"
                    await asyncio.to_thread(shutil.copy2, best_src, dest_abs)
                    weights_rel = f"{dest_rel_dir}/best.pt"

                    await models.deactivate_stream_models(job.project_id)
                    candidate = ModelVersion.create(
                        project_id=job.project_id,
                        dataset_version_id=job.dataset_version_id,
                        training_job_id=job.id,
                        version_number=version_number,
                        weights_path=weights_rel,
                        map50=result.map50,
                        map50_95=result.map50_95,
                        precision=result.precision,
                        recall=result.recall,
                    )
                    try:
                        await models.add(candidate)
                        model = candidate
                        break
                    except IntegrityError:
                        await session.rollback()
                        if attempt + 1 >= _VERSION_ALLOC_ATTEMPTS:
                            raise
                        continue

                if model is None:
                    await _fail("failed to allocate model version number")
                    return

                if result.epochs_trained:
                    job.current_epoch = result.epochs_trained
                job.mark_completed(
                    model.id,
                    stopped_early=bool(result.stopped_early),
                )
                await jobs.update(job)
                await uow.commit()
            except Exception as exc:
                try:
                    await _fail(str(exc))
                except Exception:
                    pass
            finally:
                try:
                    await self._storage.delete_directory(work_rel)
                except Exception:
                    pass
