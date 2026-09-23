from uuid import UUID, uuid4

import pytest

from app.application.dto import BoxInput
from app.application.use_cases.annotations.save_annotations import SaveAnnotationsUseCase
from app.application.use_cases.labels.save_image_label import (
    ClearImageLabelUseCase,
    ConfirmImageLabelUseCase,
    SaveImageLabelUseCase,
)
from app.application.use_cases.projects.create_project import CreateProjectUseCase
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, ProjectTaskType, SplitType, VerificationStatus
from app.domain.exceptions import TaskTypeMismatchException


class _FakeProjects:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.items = [project]

    async def add(self, project: Project) -> None:
        self.items.append(project)
        self.project = project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self.project if self.project.id == project_id else None


class _FakeImages:
    def __init__(self, image: Image) -> None:
        self.images = [image]

    async def get_by_id(self, image_id: UUID) -> Image | None:
        return next((item for item in self.images if item.id == image_id), None)

    async def update(self, image: Image) -> None:
        self.images = [image if item.id == image.id else item for item in self.images]


class _FakeClasses:
    def __init__(self, classes: list[AnnotationClass]) -> None:
        self.classes = classes

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        return [item for item in self.classes if item.project_id == project_id]


class _FakeLabels:
    def __init__(self) -> None:
        self.by_image: dict[UUID, ImageLabel] = {}

    async def get_by_image_id(self, image_id: UUID) -> ImageLabel | None:
        return self.by_image.get(image_id)

    async def upsert(self, label: ImageLabel) -> None:
        self.by_image[label.image_id] = label

    async def delete_by_image_id(self, image_id: UUID) -> None:
        self.by_image.pop(image_id, None)


class _FakeAnnotations:
    def __init__(self) -> None:
        self.store: dict = {}

    async def list_by_image(self, image_id: UUID):
        return list(self.store.get(image_id, []))

    async def replace_for_image(self, image_id: UUID, annotations) -> None:
        self.store[image_id] = list(annotations)


class _FakeUow:
    async def commit(self) -> None:
        return None


def _cls_setup():
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    image = Image.create(
        project_id=project.id,
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    annotation_class = AnnotationClass.create(project.id, "good", "#00FF00", 0)
    images = _FakeImages(image)
    labels = _FakeLabels()
    return project, image, annotation_class, images, labels


@pytest.mark.asyncio
async def test_save_manual_label_on_classification_project() -> None:
    project, image, annotation_class, images, labels = _cls_setup()
    label = await SaveImageLabelUseCase(
        _FakeProjects(project), images, _FakeClasses([annotation_class]), labels, _FakeUow()
    ).execute(image.id, annotation_class.id)
    assert label.verification_status == VerificationStatus.VERIFIED
    assert images.images[0].status == ImageStatus.VERIFIED


@pytest.mark.asyncio
async def test_save_label_rejected_on_detection_project() -> None:
    project = Project.create("Det")
    image = Image.create(
        project_id=project.id,
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    annotation_class = AnnotationClass.create(project.id, "good", "#00FF00", 0)
    with pytest.raises(TaskTypeMismatchException):
        await SaveImageLabelUseCase(
            _FakeProjects(project),
            _FakeImages(image),
            _FakeClasses([annotation_class]),
            _FakeLabels(),
            _FakeUow(),
        ).execute(image.id, annotation_class.id)


@pytest.mark.asyncio
async def test_save_annotations_rejected_on_classification_project() -> None:
    project, image, annotation_class, images, _labels = _cls_setup()
    with pytest.raises(TaskTypeMismatchException):
        await SaveAnnotationsUseCase(
            images,
            _FakeClasses([annotation_class]),
            _FakeAnnotations(),
            _FakeUow(),
            projects=_FakeProjects(project),
        ).execute(
            image.id,
            [
                BoxInput(
                    class_id=annotation_class.id,
                    x_center=0.5,
                    y_center=0.5,
                    width=0.2,
                    height=0.1,
                )
            ],
        )


@pytest.mark.asyncio
async def test_create_classification_project() -> None:
    projects = _FakeProjects(Project.create("tmp"))
    created = await CreateProjectUseCase(projects, _FakeUow()).execute(
        "X", None, ProjectTaskType.CLASSIFICATION
    )
    assert created.task_type == ProjectTaskType.CLASSIFICATION


@pytest.mark.asyncio
async def test_confirm_and_clear_label() -> None:
    project, image, annotation_class, images, labels = _cls_setup()
    prediction = ImageLabel.create_prediction(image.id, annotation_class.id, 0.9)
    await labels.upsert(prediction)
    image.recalculate_status_from_label(prediction)
    await images.update(image)

    confirmed = await ConfirmImageLabelUseCase(
        _FakeProjects(project), images, labels, _FakeUow()
    ).execute(image.id)
    assert confirmed.verification_status == VerificationStatus.AUTO_VERIFIED
    assert images.images[0].status == ImageStatus.AUTO_VERIFIED

    await ClearImageLabelUseCase(
        _FakeProjects(project), images, labels, _FakeUow()
    ).execute(image.id)
    assert labels.by_image == {}
    assert images.images[0].status == ImageStatus.UNANNOTATED
