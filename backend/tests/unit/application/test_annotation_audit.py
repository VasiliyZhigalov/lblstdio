from uuid import UUID, uuid4

import pytest

from app.application.ports.services.model_predictor import Detection
from app.application.services.annotation_audit import audit_annotations
from app.application.use_cases.ml.audit_annotations import AuditAnnotationsUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.model_version import ModelVersion
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, ProjectTaskType, SourceType, SplitType, VerificationStatus
from app.domain.exceptions import TaskTypeMismatchException
from app.domain.value_objects.bounding_box import BoundingBox


def _annotation(class_id, x_center=0.5) -> Annotation:
    return Annotation.create_manual(
        image_id=uuid4(),
        class_id=class_id,
        bbox=BoundingBox(x_center, 0.5, 0.2, 0.2),
    )


def test_audit_marks_low_iou_prediction_as_suspicious() -> None:
    class_id = uuid4()
    annotation = _annotation(class_id)
    result = audit_annotations(
        [annotation],
        [Detection(0, 0.9, 0.1, 0.5, 0.2, 0.2)],
        confidence_threshold=0.5,
        iou_threshold=0.5,
        class_indices={class_id: 0},
        image_id=annotation.image_id,
    )

    assert result.suspicious is True
    assert "low_iou" in result.reasons


def test_audit_accepts_matching_predictions() -> None:
    class_id = uuid4()
    annotation = _annotation(class_id)
    result = audit_annotations(
        [annotation],
        [Detection(0, 0.9, 0.5, 0.5, 0.2, 0.2)],
        confidence_threshold=0.5,
        iou_threshold=0.5,
        class_indices={class_id: 0},
        image_id=annotation.image_id,
    )

    assert result.suspicious is False
    assert result.minimum_iou == pytest.approx(1.0)


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
    def __init__(self, store: dict[UUID, list[Annotation]]) -> None:
        self.store = store

    async def list_by_image_ids(self, image_ids) -> list[Annotation]:
        result: list[Annotation] = []
        for image_id in image_ids:
            result.extend(self.store.get(image_id, []))
        return result

    async def replace_for_image(self, image_id: UUID, annotations: list[Annotation]) -> None:
        self.store[image_id] = list(annotations)


class _FakeClasses:
    def __init__(self, items: list[AnnotationClass]) -> None:
        self.items = items

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        return list(self.items)


class _FakeStorage:
    def get_absolute_path(self, relative_path: str) -> str:
        return f"/abs/{relative_path}"


class _FakePredictor:
    def __init__(self, mapping: dict[str, list[Detection]]) -> None:
        self.mapping = mapping

    def predict(self, weights_path, image_paths, confidence_threshold, iou_threshold=0.7):
        return {path: list(self.mapping.get(path, [])) for path in image_paths}


class _FakeUow:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_suspicious_audit_keeps_labels_and_overlays_model_boxes() -> None:
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
    image.status = ImageStatus.VERIFIED
    original = Annotation.create_manual(
        image.id, class_id, BoundingBox(0.5, 0.5, 0.2, 0.2)
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
    annotations = _FakeAnnotations({image.id: [original]})
    images = _FakeImages([image])
    use_case = AuditAnnotationsUseCase(
        _FakeModels(model),
        images,
        annotations,
        _FakeClasses([annotation_class]),
        _FakeStorage(),
        _FakePredictor(
            {
                abs_path: [
                    Detection(0, 0.9, 0.15, 0.5, 0.2, 0.2),
                ]
            }
        ),
        _FakeUow(),
    )

    results = await use_case.execute(
        project_id,
        model.id,
        image_ids=[image.id],
        confidence_threshold=0.5,
        iou_threshold=0.5,
    )

    stored = annotations.store[image.id]
    assert results[0].suspicious is True
    assert images.by_id[image.id].status == ImageStatus.REQUIRES_RECHECK
    assert original in stored or any(item.id == original.id for item in stored)
    overlays = [
        item
        for item in stored
        if item.source == SourceType.MODEL_PREDICTION
        and item.verification_status == VerificationStatus.PENDING_REVIEW
    ]
    assert len(overlays) == 1
    assert overlays[0].bbox.x_center == pytest.approx(0.15)


class _FakeProjects:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self.project if self.project.id == project_id else None


@pytest.mark.asyncio
async def test_audit_rejected_on_classification_project() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    image = Image.create(
        project_id=project.id,
        file_path="projects/p/images/a.jpg",
        file_name="a.jpg",
        width=100,
        height=80,
        split=SplitType.TRAIN,
    )
    image.status = ImageStatus.VERIFIED
    model = ModelVersion.create(
        project_id=project.id,
        dataset_version_id=uuid4(),
        training_job_id=uuid4(),
        version_number=1,
        weights_path="projects/p/models/v1/best.pt",
        map50=0.8,
    )
    use_case = AuditAnnotationsUseCase(
        _FakeModels(model),
        _FakeImages([image]),
        _FakeAnnotations({}),
        _FakeClasses([]),
        _FakeStorage(),
        _FakePredictor({}),
        _FakeUow(),
        projects=_FakeProjects(project),
    )
    with pytest.raises(TaskTypeMismatchException):
        await use_case.execute(project.id, model.id, image_ids=[image.id])


