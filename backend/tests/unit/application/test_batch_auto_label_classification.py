from uuid import UUID, uuid4

import pytest

from app.application.ports.services.model_predictor import Classification
from app.application.use_cases.ml.batch_auto_label import BatchAutoLabelUseCase
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.entities.model_version import ModelVersion
from app.domain.entities.project import Project
from app.domain.enums import (
    AutoLabelJobStatus,
    ImageStatus,
    ProjectTaskType,
    SourceType,
    SplitType,
    VerificationStatus,
)
from app.domain.exceptions import DomainValidationException


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
        self.store: dict[UUID, list] = {}
        self.replace_calls = 0

    async def list_by_image(self, image_id: UUID):
        return list(self.store.get(image_id, []))

    async def replace_for_image(self, image_id: UUID, annotations) -> None:
        self.replace_calls += 1
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


class _FakeDetPredictor:
    def predict(self, weights_path, image_paths, confidence_threshold, iou_threshold=0.7):
        return {path: [] for path in image_paths}


class _FakeClsPredictor:
    def __init__(
        self,
        mapping: dict[str, Classification],
        names: dict[int, str] | None = None,
    ) -> None:
        self.mapping = mapping
        self.names = names or {0: "good"}
        self.calls: list[tuple] = []

    def class_names(self, weights_path: str) -> dict[int, str]:
        return dict(self.names)

    def predict(self, weights_path, image_paths, confidence_threshold):
        self.calls.append((weights_path, list(image_paths), confidence_threshold))
        return {path: self.mapping[path] for path in image_paths if path in self.mapping}


class _FakeLabels:
    def __init__(self) -> None:
        self.by_image: dict[UUID, ImageLabel] = {}

    async def get_by_image_id(self, image_id: UUID) -> ImageLabel | None:
        return self.by_image.get(image_id)

    async def list_by_image_ids(self, image_ids) -> list[ImageLabel]:
        return [self.by_image[item] for item in image_ids if item in self.by_image]

    async def upsert(self, label: ImageLabel) -> None:
        self.by_image[label.image_id] = label

    async def delete_by_image_id(self, image_id: UUID) -> None:
        self.by_image.pop(image_id, None)


class _FakeProjects:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self.project if self.project.id == project_id else None


class _FakeUow:
    async def commit(self) -> None:
        return None


def _setup(
    *,
    predictions: dict[str, Classification] | None = None,
    names: dict[int, str] | None = None,
):
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    annotation_class = AnnotationClass.create(project.id, "good", "#00FF00", 0)
    high = Image.create(
        project_id=project.id,
        file_path="projects/p/images/high.jpg",
        file_name="high.jpg",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    low = Image.create(
        project_id=project.id,
        file_path="projects/p/images/low.jpg",
        file_name="low.jpg",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    model = ModelVersion.create(
        project_id=project.id,
        dataset_version_id=uuid4(),
        training_job_id=uuid4(),
        version_number=1,
        weights_path="projects/p/models/v1/best.pt",
        map50=0.8,
    )
    mapping = predictions or {
        f"/abs/{high.file_path}": Classification(0, 0.93),
        f"/abs/{low.file_path}": Classification(0, 0.01),
    }
    labels = _FakeLabels()
    annotations = _FakeAnnotations()
    images = _FakeImages([high, low])
    jobs = _FakeJobs()
    cls_predictor = _FakeClsPredictor(mapping, names=names)
    use_case = BatchAutoLabelUseCase(
        _FakeModels(model),
        images,
        annotations,
        _FakeClasses([annotation_class]),
        jobs,
        _FakeStorage(),
        _FakeDetPredictor(),
        _FakeUow(),
        projects=_FakeProjects(project),
        labels=labels,
        classification_predictor=cls_predictor,
    )
    return use_case, high, low, model, labels, annotations, images, jobs, annotation_class


@pytest.mark.asyncio
async def test_classification_auto_label_writes_pending_label_above_threshold() -> None:
    use_case, high, low, model, labels, annotations, images, jobs, annotation_class = (
        _setup()
    )
    job = await use_case.execute(
        high.project_id,
        model.id,
        image_ids=[high.id, low.id],
        confidence_threshold=0.5,
    )

    assert job.status == AutoLabelJobStatus.COMPLETED
    assert annotations.replace_calls == 0
    pending = labels.by_image[high.id]
    assert pending.class_id == annotation_class.id
    assert pending.source == SourceType.MODEL_PREDICTION
    assert pending.verification_status == VerificationStatus.PENDING_REVIEW
    assert pending.confidence == pytest.approx(0.93)
    assert pending.model_version_id == model.id
    assert images.by_id[high.id].status == ImageStatus.REQUIRES_REVIEW
    assert low.id not in labels.by_image
    assert images.by_id[low.id].status == ImageStatus.UNANNOTATED


@pytest.mark.asyncio
async def test_classification_auto_label_skips_verified_labels() -> None:
    use_case, high, low, model, labels, annotations, images, _, annotation_class = (
        _setup()
    )
    verified = ImageLabel.create_manual(high.id, annotation_class.id)
    await labels.upsert(verified)
    high.recalculate_status_from_label(verified)
    await images.update(high)

    job = await use_case.execute(
        high.project_id,
        model.id,
        image_ids=[high.id, low.id],
        confidence_threshold=0.5,
    )
    assert job.status == AutoLabelJobStatus.COMPLETED
    assert labels.by_image[high.id].source == SourceType.MANUAL
    assert high.id not in [
        item for item in labels.by_image if labels.by_image[item].source == SourceType.MODEL_PREDICTION
    ]
    assert annotations.replace_calls == 0


@pytest.mark.asyncio
async def test_classification_auto_label_maps_model_index_by_folder_name() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    zebra = AnnotationClass.create(project.id, "zebra", "#111111", 0)
    apple = AnnotationClass.create(project.id, "apple", "#222222", 1)
    image = Image.create(
        project_id=project.id,
        file_path="projects/p/images/frame.jpg",
        file_name="frame.jpg",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    path = f"/abs/{image.file_path}"
    model = ModelVersion.create(
        project_id=project.id,
        dataset_version_id=uuid4(),
        training_job_id=uuid4(),
        version_number=1,
        weights_path="projects/p/models/v1/best.pt",
        top1=0.9,
    )
    labels = _FakeLabels()
    images = _FakeImages([image])
    use_case = BatchAutoLabelUseCase(
        _FakeModels(model),
        images,
        _FakeAnnotations(),
        _FakeClasses([zebra, apple]),
        _FakeJobs(),
        _FakeStorage(),
        _FakeDetPredictor(),
        _FakeUow(),
        projects=_FakeProjects(project),
        labels=labels,
        classification_predictor=_FakeClsPredictor(
            {path: Classification(0, 0.88)},
            names={0: "apple", 1: "zebra"},
        ),
    )
    job = await use_case.execute(
        project.id,
        model.id,
        image_ids=[image.id],
        confidence_threshold=0.5,
    )
    assert job.status == AutoLabelJobStatus.COMPLETED
    assert labels.by_image[image.id].class_id == apple.id


@pytest.mark.asyncio
async def test_classification_auto_label_clears_pending_below_threshold() -> None:
    use_case, _high, low, model, labels, _annotations, images, _jobs, annotation_class = (
        _setup()
    )
    pending = ImageLabel.create_prediction(low.id, annotation_class.id, 0.4)
    await labels.upsert(pending)
    low.recalculate_status_from_label(pending)
    await images.update(low)

    await use_case.execute(
        low.project_id,
        model.id,
        image_ids=[low.id],
        confidence_threshold=0.5,
    )
    assert low.id not in labels.by_image
    assert images.by_id[low.id].status == ImageStatus.UNANNOTATED


@pytest.mark.asyncio
async def test_classification_auto_label_fails_when_model_classes_mismatch() -> None:
    use_case, high, low, model, _, annotations, _, jobs, _ = _setup(
        names={0: "other"}
    )
    with pytest.raises(DomainValidationException, match="do not match"):
        await use_case.execute(
            high.project_id,
            model.id,
            image_ids=[high.id],
            confidence_threshold=0.5,
        )
    stored = list(jobs.store.values())[0]
    assert stored.status == AutoLabelJobStatus.FAILED
    assert annotations.replace_calls == 0
