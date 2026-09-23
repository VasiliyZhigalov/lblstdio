from random import Random
from uuid import UUID

import pytest

from app.application.use_cases.dataset.create_dataset_version import (
    CreateDatasetVersionUseCase,
)
from app.application.use_cases.dataset.export_yolo import ExportYOLOUseCase
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.dataset_version import SnapshotClassLabel
from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, ProjectTaskType, SplitType
from app.domain.exceptions import DomainValidationException, UnverifiedDataException
from app.infrastructure.storage.zip_packer import ZipArchivePacker
from tests.unit.application.test_create_dataset_version import (
    _FakeAnnotations,
    _FakeAugmentation,
    _FakeClasses,
    _FakeImages,
    _FakeProjects,
    _FakeStorage,
    _FakeUow,
    _FakeVersions,
    _make_image,
)
from tests.unit.application.test_export_yolo import _FakeStorage as _ExportStorage
import zipfile
import io


class _FakeLabels:
    def __init__(self, by_image: dict[UUID, ImageLabel]) -> None:
        self.by_image = by_image

    async def list_by_image_ids(self, image_ids: list[UUID]) -> list[ImageLabel]:
        return [self.by_image[item] for item in image_ids if item in self.by_image]


def _verified_labeled(
    project_id: UUID, class_id: UUID, name: str
) -> tuple[Image, ImageLabel]:
    image = _make_image(
        project_id, split=SplitType.TRAIN, status=ImageStatus.VERIFIED, file_path=name
    )
    label = ImageLabel.create_manual(image.id, class_id)
    return image, label


@pytest.mark.asyncio
async def test_classification_dataset_writes_class_folders_without_aug() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    good = AnnotationClass.create(project.id, "good", "#00FF00", 0)
    bad = AnnotationClass.create(project.id, "bad", "#FF0000", 1)
    images: list[Image] = []
    labels: dict[UUID, ImageLabel] = {}
    storage = _FakeStorage()
    for index in range(6):
        cls = good if index < 3 else bad
        image, label = _verified_labeled(project.id, cls.id, f"{index}.png")
        images.append(image)
        labels[image.id] = label
        storage.files[image.file_path] = b"img"
    augmentation = _FakeAugmentation()
    use_case = CreateDatasetVersionUseCase(
        _FakeProjects(project),
        _FakeImages(images),
        _FakeAnnotations({}),
        _FakeClasses([good, bad]),
        _FakeVersions(),
        storage,
        augmentation,
        _FakeUow(),
        min_verified_images=6,
        labels=_FakeLabels(labels),
    )
    version = await use_case.execute(project.id, rng=Random(0))
    assert version.yaml_path == f"projects/{project.id}/datasets/v1"
    assert not any(path.endswith("data.yaml") for path in storage.files)
    assert any("/train/good/" in path for path in storage.files)
    assert any("/val/" in path for path in storage.files)
    assert not any("/valid/" in path for path in storage.files)
    assert augmentation.calls == []
    assert all(
        isinstance(item.snapshot_annotations[0], SnapshotClassLabel)
        for item in version.items
    )
    assert version.train_file_count == version.train_count


@pytest.mark.asyncio
async def test_classification_dataset_skips_classes_without_images() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    good = AnnotationClass.create(project.id, "good", "#00FF00", 0)
    unused = AnnotationClass.create(project.id, "unused", "#0000FF", 1)
    image, label = _verified_labeled(project.id, good.id, "a.png")
    storage = _FakeStorage()
    storage.files[image.file_path] = b"img"
    version = await CreateDatasetVersionUseCase(
        _FakeProjects(project),
        _FakeImages([image]),
        _FakeAnnotations({}),
        _FakeClasses([good, unused]),
        _FakeVersions(),
        storage,
        _FakeAugmentation(),
        _FakeUow(),
        min_verified_images=1,
        labels=_FakeLabels({image.id: label}),
    ).execute(project.id, rng=Random(0))
    written = [path for path in storage.files if path.startswith(version.yaml_path)]
    assert written
    assert all(".keep" not in path for path in written)
    assert all("unused" not in path for path in written)


@pytest.mark.asyncio
async def test_classification_dataset_rejects_colliding_folder_names() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    first = AnnotationClass.create(project.id, "a/b", "#00FF00", 0)
    second = AnnotationClass.create(project.id, "a_b", "#FF0000", 1)
    images: list[Image] = []
    labels: dict[UUID, ImageLabel] = {}
    storage = _FakeStorage()
    for annotation_class, name in ((first, "a.png"), (second, "b.png")):
        image, label = _verified_labeled(project.id, annotation_class.id, name)
        images.append(image)
        labels[image.id] = label
        storage.files[image.file_path] = b"img"
    use_case = CreateDatasetVersionUseCase(
        _FakeProjects(project),
        _FakeImages(images),
        _FakeAnnotations({}),
        _FakeClasses([first, second]),
        _FakeVersions(),
        storage,
        _FakeAugmentation(),
        _FakeUow(),
        min_verified_images=1,
        labels=_FakeLabels(labels),
    )
    with pytest.raises(DomainValidationException, match="same folder"):
        await use_case.execute(project.id, rng=Random(0))


@pytest.mark.asyncio
async def test_classification_dataset_blocks_pending_review() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    cls = AnnotationClass.create(project.id, "good", "#00FF00", 0)
    image = _make_image(
        project.id,
        split=SplitType.TRAIN,
        status=ImageStatus.REQUIRES_REVIEW,
        file_path="p.png",
    )
    label = ImageLabel.create_prediction(image.id, cls.id, 0.9)
    use_case = CreateDatasetVersionUseCase(
        _FakeProjects(project),
        _FakeImages([image]),
        _FakeAnnotations({}),
        _FakeClasses([cls]),
        _FakeVersions(),
        _FakeStorage(),
        _FakeAugmentation(),
        _FakeUow(),
        min_verified_images=1,
        labels=_FakeLabels({image.id: label}),
    )
    with pytest.raises(UnverifiedDataException):
        await use_case.execute(project.id)


@pytest.mark.asyncio
async def test_classification_export_packs_class_folders() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    good = AnnotationClass.create(project.id, "good", "#00FF00", 0)
    image = Image.create(
        project_id=project.id,
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    image.status = ImageStatus.VERIFIED
    label = ImageLabel.create_manual(image.id, good.id)
    packed = await ExportYOLOUseCase(
        _FakeProjects(project),
        _FakeClasses([good]),
        _FakeImages([image]),
        _FakeAnnotations({}),
        _ExportStorage({"a.png": b"PNG"}),
        ZipArchivePacker(),
        labels=_FakeLabels({image.id: label}),
    ).execute(project.id)
    names = zipfile.ZipFile(io.BytesIO(packed)).namelist()
    assert any(name.startswith(f"train/good/{image.id}") for name in names)
    assert "data.yaml" not in names
