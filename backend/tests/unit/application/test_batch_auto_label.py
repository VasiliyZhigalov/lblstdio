from uuid import UUID, uuid4

import pytest

from app.application.ports.services.model_predictor import Detection
from app.application.use_cases.ml.batch_auto_label import BatchAutoLabelUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.model_version import ModelVersion
from app.domain.enums import (
    AutoLabelJobStatus,
    ImageStatus,
    SourceType,
    SplitType,
    VerificationStatus,
)
from app.domain.value_objects.bounding_box import BoundingBox


class _FakeModels:
    def __init__(self, model: ModelVersion) -> None:
        self.model = model

    async def get_by_id(self, version_id: UUID) -> ModelVersion | None:
        return self.model if self.model.id == version_id else None


class _FakeImages:
    def __init__(self, images: list[Image]) -> None:
        self.by_id = {item.id: item for item in images}

    async def list_by_project(self, project_id: UUID) -> list[Image]:
        return [item for item in self.by_id.values() if item.project_id == project_id]

    async def update(self, image: Image) -> None:
        self.by_id[image.id] = image


class _FakeAnnotations:
    def __init__(self) -> None:
        self.store: dict[UUID, list[Annotation]] = {}

    async def list_by_image(self, image_id: UUID) -> list[Annotation]:
        return list(self.store.get(image_id, []))

    async def replace_for_image(self, image_id: UUID, annotations: list[Annotation]) -> None:
        self.store[image_id] = list(annotations)


class _FakeClasses:
    def __init__(self, items: list[AnnotationClass]) -> None:
        self.items = items

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        return list(self.items)


class _FakeJobs:
    def __init__(self) -> None:
        self.store = {}

    async def add(self, job) -> None:
        self.store[job.id] = job

    async def update(self, job) -> None:
        self.store[job.id] = job

    async def get_by_id(self, job_id):
        return self.store.get(job_id)


class _FakeStorage:
    def get_absolute_path(self, relative_path: str) -> str:
        return f"/abs/{relative_path}"


class _FakePredictor:
    def __init__(self, mapping: dict[str, list[Detection]]) -> None:
        self.mapping = mapping
        self.calls = []

    def predict(self, weights_path, image_paths, confidence_threshold):
        self.calls.append((weights_path, list(image_paths), confidence_threshold))
        return {path: list(self.mapping.get(path, [])) for path in image_paths}


class _FakeUow:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _setup():
    project_id = uuid4()
    class_id = uuid4()
    annotation_class = AnnotationClass(
        id=class_id,
        project_id=project_id,
        name="crack",
        color_hex="#FF0000",
        index_id=0,
    )
    image = Image.create(
        project_id=project_id,
        file_path="projects/p/images/a.jpg",
        file_name="a.jpg",
        width=100,
        height=80,
        split=SplitType.TRAIN,
    )
    model = ModelVersion.create(
        project_id=project_id,
        dataset_version_id=uuid4(),
        training_job_id=uuid4(),
        version_number=1,
        weights_path="projects/p/models/v1/best.pt",
        map50=0.8,
    )
    abs_path = f"/abs/{image.file_path}"
    predictor = _FakePredictor(
        {
            abs_path: [
                Detection(
                    class_index=0,
                    confidence=0.84,
                    x_center=0.5,
                    y_center=0.4,
                    width=0.2,
                    height=0.15,
                )
            ]
        }
    )
    images = _FakeImages([image])
    annotations = _FakeAnnotations()
    jobs = _FakeJobs()
    use_case = BatchAutoLabelUseCase(
        _FakeModels(model),
        images,
        annotations,
        _FakeClasses([annotation_class]),
        jobs,
        _FakeStorage(),
        predictor,
        _FakeUow(),
    )
    return use_case, image, model, annotations, images, jobs, predictor


@pytest.mark.asyncio
async def test_auto_label_boxes_are_pending_review_never_verified() -> None:
    use_case, image, model, annotations, images, jobs, _ = _setup()
    job = await use_case.execute(
        image.project_id,
        model.id,
        image_ids=[image.id],
        confidence_threshold=0.5,
    )
    assert job.status == AutoLabelJobStatus.COMPLETED
    assert job.total_predictions_generated == 1
    boxes = annotations.store[image.id]
    assert len(boxes) == 1
    assert boxes[0].source == SourceType.MODEL_PREDICTION
    assert boxes[0].verification_status == VerificationStatus.PENDING_REVIEW
    assert boxes[0].verification_status != VerificationStatus.VERIFIED
    assert boxes[0].confidence == pytest.approx(0.84)
    assert boxes[0].model_version_id == model.id
    assert images.by_id[image.id].status == ImageStatus.REQUIRES_REVIEW


@pytest.mark.asyncio
async def test_auto_label_all_unannotated_selects_pool() -> None:
    use_case, image, model, annotations, images, _, predictor = _setup()
    other = Image.create(
        project_id=image.project_id,
        file_path="projects/p/images/b.jpg",
        file_name="b.jpg",
        width=100,
        height=80,
        split=SplitType.VALID,
    )
    other.status = ImageStatus.VERIFIED
    images.by_id[other.id] = other
    predictor.mapping[f"/abs/{other.file_path}"] = [
        Detection(0, 0.9, 0.5, 0.5, 0.1, 0.1)
    ]
    job = await use_case.execute(
        image.project_id,
        model.id,
        all_unannotated=True,
        confidence_threshold=0.5,
    )
    assert job.total_images_processed == 1
    assert image.id in job.image_ids
    assert other.id not in job.image_ids


@pytest.mark.asyncio
async def test_auto_label_skips_invalid_detections_and_completes() -> None:
    use_case, image, model, annotations, images, jobs, predictor = _setup()
    abs_path = f"/abs/{image.file_path}"
    predictor.mapping[abs_path] = [
        Detection(0, 0.9, 0.5, 0.5, 0.2, 0.2),
        Detection(0, 0.9, 0.01, 0.01, 0.5, 0.5),  # would extend outside without clamp
        Detection(0, 0.9, 0.5, 0.5, 0.0, 0.2),  # invalid zero width -> skip
    ]
    job = await use_case.execute(
        image.project_id,
        model.id,
        image_ids=[image.id],
        confidence_threshold=0.5,
    )
    assert job.status == AutoLabelJobStatus.COMPLETED
    assert job.total_predictions_generated >= 1
    assert image.id in annotations.store


@pytest.mark.asyncio
async def test_auto_label_marks_failed_when_persist_raises() -> None:
    use_case, image, model, annotations, images, jobs, predictor = _setup()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("db write failed")

    annotations.replace_for_image = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="db write failed"):
        await use_case.execute(
            image.project_id,
            model.id,
            image_ids=[image.id],
            confidence_threshold=0.5,
        )
    stored = list(jobs.store.values())[0]
    assert stored.status == AutoLabelJobStatus.FAILED
    assert "db write failed" in (stored.error_message or "")
