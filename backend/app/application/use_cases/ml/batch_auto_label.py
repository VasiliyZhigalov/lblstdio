from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from uuid import UUID

import anyio
from PIL import Image as PILImage

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.auto_label_job_repository import (
    IAutoLabelJobRepository,
)
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.application.ports.services.model_predictor import Detection, IModelPredictor
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.annotation import Annotation
from app.domain.entities.auto_label_job import AutoLabelJob
from app.domain.enums import AutoLabelJobStatus, ImageStatus, VerificationStatus
from app.domain.services.augmentation_consistency import (
    all_runs_are_consistent,
    transform_center_scale,
    transform_horizontal_flip,
)
from app.domain.exceptions import (
    DomainValidationException,
    ModelWeightsMissingException,
    ResourceNotFoundException,
)
from app.domain.value_objects.bounding_box import BoundingBox

_ORPHAN_MESSAGE = "interrupted by server restart"
_CONSISTENCY_SCALE = 1.08


def _inverse_center_scale(det: Detection) -> Detection:
    return transform_center_scale(det, 1 / _CONSISTENCY_SCALE)


def _write_consistency_images(
    image_path: str,
    destination: Path,
    raw: bytes,
) -> tuple[str, str]:
    with PILImage.open(BytesIO(raw)) as source:
        image = source.convert("RGB")
        flipped = image.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
        flip_path = destination / f"{Path(image_path).stem}_flip.jpg"
        flipped.save(flip_path, format="JPEG")

        width, height = image.size
        scaled = image.resize(
            (round(width * _CONSISTENCY_SCALE), round(height * _CONSISTENCY_SCALE))
        )
        left = (scaled.width - width) // 2
        top = (scaled.height - height) // 2
        stretched = scaled.crop((left, top, left + width, top + height))
        stretch_path = destination / f"{Path(image_path).stem}_stretch.jpg"
        stretched.save(stretch_path, format="JPEG")
    return str(flip_path), str(stretch_path)


def bbox_from_detection(det: Detection) -> BoundingBox | None:
    """Clamp YOLO xywhn into a valid normalized box; skip if impossible."""
    w = float(det.width)
    h = float(det.height)
    if w <= 0 or h <= 0:
        return None
    w = min(w, 1.0)
    h = min(h, 1.0)
    x = min(max(float(det.x_center), 0.0), 1.0)
    y = min(max(float(det.y_center), 0.0), 1.0)
    half_w, half_h = w / 2.0, h / 2.0
    if x - half_w < 0.0:
        x = half_w
    if x + half_w > 1.0:
        x = 1.0 - half_w
    if y - half_h < 0.0:
        y = half_h
    if y + half_h > 1.0:
        y = 1.0 - half_h
    try:
        return BoundingBox(x, y, w, h)
    except DomainValidationException:
        return None


class BatchAutoLabelUseCase:
    """Enqueue model inference jobs that create PENDING_REVIEW predictions."""

    def __init__(
        self,
        models: IModelVersionRepository,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        classes: IClassRepository,
        jobs: IAutoLabelJobRepository,
        storage: IFileStorage,
        predictor: IModelPredictor,
        uow: IUnitOfWork,
        runner: AutoLabelJobRunner | None = None,
    ) -> None:
        self._models = models
        self._images = images
        self._annotations = annotations
        self._classes = classes
        self._jobs = jobs
        self._storage = storage
        self._predictor = predictor
        self._uow = uow
        self._runner = runner

    async def execute(
        self,
        project_id: UUID,
        model_version_id: UUID,
        *,
        image_ids: Sequence[UUID] | None = None,
        all_unannotated: bool = False,
        confidence_threshold: float = 0.05,
        iou_threshold: float = 0.7,
        consistency_iou_threshold: float = 0.8,
    ) -> AutoLabelJob:
        model = await self._models.get_by_id(model_version_id)
        if model is None or model.project_id != project_id:
            raise ResourceNotFoundException(f"model version {model_version_id} not found")

        try:
            self._storage.get_absolute_path(model.weights_path)
        except Exception as exc:
            raise ModelWeightsMissingException(
                f"weights not found: {model.weights_path}"
            ) from exc

        project_images = await self._images.list_by_project(project_id)
        by_id = {item.id: item for item in project_images}

        if all_unannotated:
            selected = [
                item
                for item in project_images
                if item.status == ImageStatus.UNANNOTATED
            ]
        elif image_ids is not None:
            missing = [image_id for image_id in image_ids if image_id not in by_id]
            if missing:
                raise ResourceNotFoundException(
                    f"image(s) not found: {', '.join(str(item) for item in missing)}"
                )
            selected = [by_id[image_id] for image_id in image_ids]
        else:
            raise DomainValidationException(
                "provide image_ids or set all_unannotated=true"
            )

        if not selected:
            raise DomainValidationException("no images selected for auto-labeling")

        job = AutoLabelJob.create(
            project_id=project_id,
            model_version_id=model_version_id,
            image_ids=[item.id for item in selected],
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            consistency_iou_threshold=consistency_iou_threshold,
        )
        await self._jobs.add(job)
        await self._uow.commit()

        if self._runner is not None:
            self._runner.schedule(job.id)
        else:
            await self.process_job(job.id)

        return await self._jobs.get_by_id(job.id) or job

    async def process_job(self, job_id: UUID) -> AutoLabelJob:
        job = await self._jobs.get_by_id(job_id)
        if job is None:
            raise ResourceNotFoundException(f"auto-label job {job_id} not found")
        if job.status in {AutoLabelJobStatus.COMPLETED, AutoLabelJobStatus.FAILED}:
            return job

        model = await self._models.get_by_id(job.model_version_id)
        if model is None:
            job.mark_failed("model version missing")
            await self._jobs.update(job)
            await self._uow.commit()
            return job

        try:
            weights_abs = self._storage.get_absolute_path(model.weights_path)
        except Exception as exc:
            job.mark_failed(f"weights not found: {model.weights_path}")
            await self._jobs.update(job)
            await self._uow.commit()
            raise ModelWeightsMissingException(
                f"weights not found: {model.weights_path}"
            ) from exc

        project_images = await self._images.list_by_project(job.project_id)
        by_id = {item.id: item for item in project_images}
        selected = [by_id[image_id] for image_id in job.image_ids if image_id in by_id]
        if not selected:
            job.mark_failed("no images available for auto-labeling")
            await self._jobs.update(job)
            await self._uow.commit()
            return job

        job.mark_running()
        await self._jobs.update(job)
        await self._uow.commit()

        try:
            classes = await self._classes.list_by_project(job.project_id)
            class_by_index = {item.index_id: item for item in classes}
            abs_paths = [
                self._storage.get_absolute_path(item.file_path) for item in selected
            ]
            path_to_image = {
                self._storage.get_absolute_path(item.file_path): item
                for item in selected
            }

            predictions = await anyio.to_thread.run_sync(
                self._predictor.predict,
                weights_abs,
                abs_paths,
                job.confidence_threshold,
                job.iou_threshold,
            )

            with tempfile.TemporaryDirectory(prefix="lblstdio-consistency-") as tmp:
                augmented_paths: dict[UUID, tuple[str, str]] = {}
                for image in selected:
                    original_path = self._storage.get_absolute_path(image.file_path)
                    raw = await self._storage.read(image.file_path)
                    augmented_paths[image.id] = await anyio.to_thread.run_sync(
                        _write_consistency_images,
                        original_path,
                        Path(tmp),
                        raw,
                    )

                flip_paths = [paths[0] for paths in augmented_paths.values()]
                stretch_paths = [paths[1] for paths in augmented_paths.values()]
                flip_predictions = await anyio.to_thread.run_sync(
                    self._predictor.predict,
                    weights_abs,
                    flip_paths,
                    job.confidence_threshold,
                    job.iou_threshold,
                )
                stretch_predictions = await anyio.to_thread.run_sync(
                    self._predictor.predict,
                    weights_abs,
                    stretch_paths,
                    job.confidence_threshold,
                    job.iou_threshold,
                )

            total_predictions = 0
            for abs_path, detections in predictions.items():
                image = path_to_image.get(abs_path)
                if image is None:
                    continue
                existing = await self._annotations.list_by_image(image.id)
                kept = [
                    box
                    for box in existing
                    if box.verification_status != VerificationStatus.PENDING_REVIEW
                    or box.model_version_id != model.id
                ]
                created = self._detections_to_annotations(
                    image.id, detections, class_by_index, model.id
                )
                flip_path, stretch_path = augmented_paths[image.id]
                is_consistent = all_runs_are_consistent(
                    detections,
                    (
                        (
                            flip_predictions.get(flip_path, []),
                            transform_horizontal_flip,
                        ),
                        (
                            stretch_predictions.get(stretch_path, []),
                            _inverse_center_scale,
                        ),
                    ),
                    confidence_threshold=job.confidence_threshold,
                    iou_threshold=job.consistency_iou_threshold,
                )
                if is_consistent:
                    for annotation in created:
                        annotation.auto_verify()
                merged = kept + created
                await self._annotations.replace_for_image(image.id, merged)
                image.recalculate_status(merged)
                await self._images.update(image)
                total_predictions += len(created)

            job.mark_completed(len(selected), total_predictions)
            await self._jobs.update(job)
            await self._uow.commit()
            return job
        except Exception as exc:
            job.mark_failed(str(exc))
            await self._jobs.update(job)
            await self._uow.commit()
            raise

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


class GetAutoLabelJobUseCase:
    def __init__(self, jobs: IAutoLabelJobRepository) -> None:
        self._jobs = jobs

    async def execute(self, job_id: UUID) -> AutoLabelJob:
        job = await self._jobs.get_by_id(job_id)
        if job is None:
            raise ResourceNotFoundException(f"auto-label job {job_id} not found")
        return job


class AutoLabelJobRunner:
    """Background runner for batch auto-label jobs."""

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
        self._sem = asyncio.Semaphore(max(1, max_concurrent))
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, job_id: UUID) -> None:
        task = asyncio.create_task(self._run(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run_inline(self, job_id: UUID) -> None:
        await self._run(job_id)

    async def fail_orphaned_jobs(self) -> int:
        from app.infrastructure.db.repositories.auto_label_job_repository import (
            SqliteAutoLabelJobRepository,
        )
        from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        async with self._session_factory() as session:
            jobs = SqliteAutoLabelJobRepository(session)
            uow = SqlAlchemyUnitOfWork(session)
            orphans = await jobs.list_by_statuses(
                (AutoLabelJobStatus.PENDING, AutoLabelJobStatus.RUNNING)
            )
            for job in orphans:
                job.mark_failed(_ORPHAN_MESSAGE)
                await jobs.update(job)
            if orphans:
                await uow.commit()
            return len(orphans)

    async def _run(self, job_id: UUID) -> None:
        async with self._sem:
            await self._run_locked(job_id)

    async def _run_locked(self, job_id: UUID) -> None:
        from app.infrastructure.db.repositories.annotation_repository import (
            SqliteAnnotationRepository,
        )
        from app.infrastructure.db.repositories.auto_label_job_repository import (
            SqliteAutoLabelJobRepository,
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
        from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        async with self._session_factory() as session:
            use_case = BatchAutoLabelUseCase(
                SqliteModelVersionRepository(session),
                SqliteImageRepository(session),
                SqliteAnnotationRepository(session),
                SqliteClassRepository(session),
                SqliteAutoLabelJobRepository(session),
                self._storage,
                self._predictor,
                SqlAlchemyUnitOfWork(session),
            )
            try:
                await use_case.process_job(job_id)
            except Exception:
                # process_job already marks FAILED when possible
                pass
