import asyncio
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

import anyio

from app.application.ports.repositories.annotation_audit_job_repository import (
    IAnnotationAuditJobRepository,
)
from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.services.model_predictor import Detection, IModelPredictor
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.application.services.annotation_audit import AuditResult, audit_annotations
from app.application.services.task_policy import require_task
from app.application.use_cases.ml.batch_auto_label import bbox_from_detection
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_audit_job import AnnotationAuditJob
from app.domain.enums import (
    AnnotationAuditJobStatus,
    ImageStatus,
    ProjectTaskType,
    VerificationStatus,
)
from app.domain.exceptions import (
    DomainValidationException,
    ModelWeightsMissingException,
    ResourceNotFoundException,
)

class AuditAnnotationsUseCase:
    def __init__(
        self,
        models: IModelVersionRepository,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        classes: IClassRepository,
        storage: IFileStorage,
        predictor: IModelPredictor,
        uow: IUnitOfWork,
        *,
        projects: IProjectRepository | None = None,
    ) -> None:
        self._models = models
        self._images = images
        self._annotations = annotations
        self._classes = classes
        self._storage = storage
        self._predictor = predictor
        self._uow = uow
        self._projects = projects

    async def execute(
        self,
        project_id: UUID,
        model_version_id: UUID,
        *,
        image_ids: Sequence[UUID] | None = None,
        confidence_threshold: float = 0.5,
        iou_threshold: float = 0.5,
        progress: Callable[[int], None] | None = None,
        async_progress: Callable[[int], Awaitable[None]] | None = None,
        batch_size: int = 8,
    ) -> list[AuditResult]:
        model = await self._models.get_by_id(model_version_id)
        if model is None or model.project_id != project_id:
            raise ResourceNotFoundException(f"model version {model_version_id} not found")
        if self._projects is not None:
            project = await self._projects.get_by_id(project_id)
            if project is None:
                raise ResourceNotFoundException(f"project {project_id} not found")
            require_task(project, ProjectTaskType.DETECTION)
        if not 0.01 <= confidence_threshold <= 0.99:
            raise DomainValidationException("confidence_threshold must be in [0.01, 0.99]")
        if not 0.01 <= iou_threshold <= 0.99:
            raise DomainValidationException("iou_threshold must be in [0.01, 0.99]")

        try:
            weights_path = self._storage.get_absolute_path(model.weights_path)
        except Exception as exc:
            raise ModelWeightsMissingException(
                f"weights not found: {model.weights_path}"
            ) from exc

        project_images = await self._images.list_by_project(project_id)
        by_id = {item.id: item for item in project_images}
        if image_ids is None:
            selected = [
                item
                for item in project_images
                if item.status
                in (ImageStatus.VERIFIED, ImageStatus.AUTO_VERIFIED)
            ]
        else:
            missing = [item for item in image_ids if item not in by_id]
            if missing:
                raise ResourceNotFoundException(
                    f"image(s) not found: {', '.join(str(item) for item in missing)}"
                )
            selected = [by_id[item] for item in image_ids]
        if not selected:
            raise DomainValidationException("no confirmed images selected for audit")
        unconfirmed = [
            item
            for item in selected
            if item.status not in (ImageStatus.VERIFIED, ImageStatus.AUTO_VERIFIED)
        ]
        if unconfirmed:
            raise DomainValidationException(
                "annotation audit accepts only confirmed images"
            )

        classes = await self._classes.list_by_project(project_id)
        class_indices = {item.id: item.index_id for item in classes}
        class_by_index = {item.index_id: item for item in classes}
        annotations = await self._annotations.list_by_image_ids(
            [item.id for item in selected]
        )
        by_image: dict[UUID, list] = {item.id: [] for item in selected}
        for annotation in annotations:
            by_image.setdefault(annotation.image_id, []).append(annotation)

        results: list[AuditResult] = []
        size = max(1, batch_size)
        for start in range(0, len(selected), size):
            batch = selected[start : start + size]
            paths = [self._storage.get_absolute_path(item.file_path) for item in batch]
            predictions = await anyio.to_thread.run_sync(
                self._predictor.predict,
                weights_path,
                paths,
                0.1,
                0.7,
            )
            for image, path in zip(batch, paths, strict=True):
                detections = predictions.get(path, [])
                existing = by_image[image.id]
                kept = [
                    box
                    for box in existing
                    if box.verification_status != VerificationStatus.PENDING_REVIEW
                ]
                result = audit_annotations(
                    kept,
                    detections,
                    confidence_threshold=confidence_threshold,
                    iou_threshold=iou_threshold,
                    class_indices=class_indices,
                    image_id=image.id,
                )
                merged = kept
                if result.suspicious:
                    overlays = self._detections_to_annotations(
                        image.id, detections, class_by_index, model_version_id
                    )
                    merged = kept + overlays
                await self._annotations.replace_for_image(image.id, merged)
                by_image[image.id] = merged
                image.recalculate_status(merged)
                if result.suspicious:
                    image.status = ImageStatus.REQUIRES_RECHECK
                await self._images.update(image)
                results.append(result)
                if progress is not None:
                    progress(len(results))
                if async_progress is not None:
                    await async_progress(len(results))

        await self._uow.commit()
        return results

    def _detections_to_annotations(
        self,
        image_id: UUID,
        detections: list[Detection],
        class_by_index: dict[int, object],
        model_version_id: UUID,
    ) -> list[Annotation]:
        result: list[Annotation] = []
        for det in detections:
            cls = class_by_index.get(det.class_index)
            if cls is None:
                continue
            bbox = bbox_from_detection(det)
            if bbox is None:
                continue
            result.append(
                Annotation.create_prediction(
                    image_id=image_id,
                    class_id=cls.id,  # type: ignore[attr-defined]
                    bbox=bbox,
                    confidence=det.confidence,
                    model_version_id=model_version_id,
                )
            )
        return result


class AuditAnnotationsRunner:
    def __init__(
        self,
        session_factory,
        storage: IFileStorage,
        predictor: IModelPredictor,
        *,
        max_concurrent: int = 1,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._predictor = predictor
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))
        self._running: set[asyncio.Task] = set()

    async def start(
        self,
        project_id: UUID,
        model_version_id: UUID,
        *,
        image_ids: Sequence[UUID] | None = None,
        max_images: int = 32,
        confidence_threshold: float,
        iou_threshold: float,
    ) -> AnnotationAuditJob:
        from app.infrastructure.db.repositories.annotation_audit_job_repository import (
            SqliteAnnotationAuditJobRepository,
        )
        from app.infrastructure.db.repositories.project_repository import (
            SqliteProjectRepository,
        )
        from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        async with self._session_factory() as session:
            project = await SqliteProjectRepository(session).get_by_id(project_id)
            if project is None:
                raise ResourceNotFoundException(f"project {project_id} not found")
            require_task(project, ProjectTaskType.DETECTION)
            jobs = SqliteAnnotationAuditJobRepository(session)
            active = await jobs.find_active(project_id, model_version_id)
            if active is not None:
                return active
            if image_ids is None:
                from app.infrastructure.db.repositories.image_repository import (
                    SqliteImageRepository,
                )

                images = await SqliteImageRepository(session).list_by_project(project_id)
                image_ids = [
                    item.id
                    for item in images
                    if item.status in (ImageStatus.VERIFIED, ImageStatus.AUTO_VERIFIED)
                ]
            image_ids = list(image_ids)[:max_images]
            job = AnnotationAuditJob.create(
                project_id,
                model_version_id,
                list(image_ids),
                confidence_threshold,
                iou_threshold,
            )
            job.total_images = len(job.image_ids)
            await jobs.add(job)
            await SqlAlchemyUnitOfWork(session).commit()
        running = asyncio.create_task(
            self._run(job.id)
        )
        self._running.add(running)
        running.add_done_callback(self._running.discard)
        return job

    async def get(self, task_id: UUID) -> AnnotationAuditJob | None:
        from app.infrastructure.db.repositories.annotation_audit_job_repository import (
            SqliteAnnotationAuditJobRepository,
        )

        async with self._session_factory() as session:
            return await SqliteAnnotationAuditJobRepository(session).get_by_id(task_id)

    async def _run(self, job_id: UUID) -> None:
        async with self._semaphore:
            try:
                from app.infrastructure.db.repositories.annotation_repository import (
                    SqliteAnnotationRepository,
                )
                from app.infrastructure.db.repositories.class_repository import (
                    SqliteClassRepository,
                )
                from app.infrastructure.db.repositories.image_repository import (
                    SqliteImageRepository,
                )
                from app.infrastructure.db.repositories.model_version_repository import (
                    SqliteModelVersionRepository,
                )
                from app.infrastructure.db.repositories.project_repository import (
                    SqliteProjectRepository,
                )
                from app.infrastructure.db.repositories.annotation_audit_job_repository import (
                    SqliteAnnotationAuditJobRepository,
                )
                from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

                async with self._session_factory() as session:
                    jobs = SqliteAnnotationAuditJobRepository(session)
                    job = await jobs.get_by_id(job_id)
                    if job is None:
                        return
                    job.mark_running()
                    await jobs.update(job)
                    await SqlAlchemyUnitOfWork(session).commit()
                    use_case = AuditAnnotationsUseCase(
                        SqliteModelVersionRepository(session),
                        SqliteImageRepository(session),
                        SqliteAnnotationRepository(session),
                        SqliteClassRepository(session),
                        self._storage,
                        self._predictor,
                        SqlAlchemyUnitOfWork(session),
                        projects=SqliteProjectRepository(session),
                    )
                    results = await use_case.execute(
                        job.project_id,
                        job.model_version_id,
                        image_ids=job.image_ids,
                        confidence_threshold=job.confidence_threshold,
                        iou_threshold=job.iou_threshold,
                        async_progress=lambda value: self._save_progress(
                            jobs, session, job, value
                        ),
                        batch_size=8,
                    )
                    job.mark_completed(
                        len(results), sum(item.suspicious for item in results)
                    )
                    await jobs.update(job)
                    await SqlAlchemyUnitOfWork(session).commit()
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._mark_failed(job_id, "cancelled during shutdown")
                )
                raise
            except Exception as exc:
                await self._mark_failed(job_id, str(exc))

    async def _mark_failed(self, job_id: UUID, message: str) -> None:
        from app.infrastructure.db.repositories.annotation_audit_job_repository import (
            SqliteAnnotationAuditJobRepository,
        )
        from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        async with self._session_factory() as session:
            jobs = SqliteAnnotationAuditJobRepository(session)
            job = await jobs.get_by_id(job_id)
            if job is None or job.status in {
                AnnotationAuditJobStatus.COMPLETED,
                AnnotationAuditJobStatus.FAILED,
            }:
                return
            job.mark_failed(message)
            await jobs.update(job)
            await SqlAlchemyUnitOfWork(session).commit()

    async def fail_orphaned_jobs(self) -> int:
        from app.infrastructure.db.repositories.annotation_audit_job_repository import (
            SqliteAnnotationAuditJobRepository,
        )
        from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        async with self._session_factory() as session:
            jobs = SqliteAnnotationAuditJobRepository(session)
            orphaned = await jobs.list_by_statuses(
                (AnnotationAuditJobStatus.PENDING, AnnotationAuditJobStatus.RUNNING)
            )
            for job in orphaned:
                job.mark_failed("interrupted by server restart")
                await jobs.update(job)
            if orphaned:
                await SqlAlchemyUnitOfWork(session).commit()
            return len(orphaned)

    async def _save_progress(
        self,
        jobs: IAnnotationAuditJobRepository,
        session,
        job: AnnotationAuditJob,
        processed: int,
    ) -> None:
        job.processed_images = processed
        await jobs.update(job)
        await session.commit()

    async def close(self) -> None:
        for task in tuple(self._running):
            task.cancel()
        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)
