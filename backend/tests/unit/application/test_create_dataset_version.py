from random import Random
from uuid import UUID, uuid4

import pytest

from app.application.ports.services.augmentation import AugmentedSample, LabeledBox
from app.application.use_cases.dataset.create_dataset_version import (
    CreateDatasetVersionUseCase,
)
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.dataset_version import (
    DEFAULT_MIN_VERIFIED_IMAGES,
    AugmentationConfig,
    DatasetVersion,
)
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import (
    DatasetVersionStatus,
    ImageStatus,
    SplitType,
    VerificationStatus,
)
from app.domain.exceptions import (
    InsufficientVerifiedDataException,
    UnverifiedDataException,
)
from app.domain.value_objects.bounding_box import BoundingBox
from app.domain.value_objects.split_ratios import SplitRatios

class _FakeProjects:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self.project if self.project.id == project_id else None


class _FakeImages:
    def __init__(self, images: list[Image]) -> None:
        self.images = images

    async def list_by_project(self, project_id: UUID) -> list[Image]:
        return [item for item in self.images if item.project_id == project_id]


class _FakeAnnotations:
    def __init__(self, by_image: dict[UUID, list[Annotation]]) -> None:
        self.by_image = by_image

    async def list_by_image_ids(self, image_ids: list[UUID]) -> list[Annotation]:
        result: list[Annotation] = []
        for image_id in image_ids:
            result.extend(self.by_image.get(image_id, []))
        return result


class _FakeClasses:
    def __init__(self, classes: list[AnnotationClass]) -> None:
        self.classes = classes

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        return [item for item in self.classes if item.project_id == project_id]


class _FakeVersions:
    def __init__(self) -> None:
        self.store: dict[UUID, DatasetVersion] = {}
        self.next_number = 1

    async def add(self, version: DatasetVersion) -> None:
        self.store[version.id] = version

    async def update(self, version: DatasetVersion) -> None:
        self.store[version.id] = version

    async def get_by_id(self, version_id: UUID) -> DatasetVersion | None:
        return self.store.get(version_id)

    async def list_by_project(self, project_id: UUID) -> list[DatasetVersion]:
        return [item for item in self.store.values() if item.project_id == project_id]

    async def next_version_number(self, project_id: UUID) -> int:
        return self.next_number

    async def delete(self, version_id: UUID) -> None:
        self.store.pop(version_id, None)


class _FakeUow:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def save(self, relative_dir: str, filename: str, data: bytes) -> str:
        path = f"{relative_dir.rstrip('/')}/{filename}"
        self.files[path] = data
        return path

    async def read(self, relative_path: str) -> bytes:
        return self.files[relative_path]

    def get_absolute_path(self, relative_path: str) -> str:
        return f"/abs/{relative_path}"

    async def delete_directory(self, relative_dir: str) -> None:
        self.deleted.append(relative_dir)
        prefix = relative_dir.rstrip("/") + "/"
        for path in list(self.files):
            if path.startswith(prefix) or path == relative_dir:
                del self.files[path]


class _FakeAugmentation:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, int]] = []

    def generate_samples(
        self,
        image_bytes: bytes,
        boxes: list[LabeledBox],
        config: AugmentationConfig,
        *,
        apply_augmentation: bool,
    ) -> list[AugmentedSample]:
        self.calls.append((apply_augmentation, config.multiplier))
        if not apply_augmentation or config.multiplier <= 1:
            return [
                AugmentedSample(image_bytes=image_bytes, boxes=list(boxes), suffix="")
            ]
        samples = [
            AugmentedSample(image_bytes=image_bytes, boxes=list(boxes), suffix="")
        ]
        for index in range(1, config.multiplier):
            samples.append(
                AugmentedSample(
                    image_bytes=image_bytes + bytes([index]),
                    boxes=list(boxes),
                    suffix=f"_aug_{index}",
                )
            )
        return samples


def _make_image(
    project_id: UUID,
    *,
    split: SplitType,
    status: ImageStatus,
    file_path: str = "img.png",
) -> Image:
    image = Image.create(
        project_id=project_id,
        file_path=file_path,
        file_name=file_path,
        width=100,
        height=100,
        split=split,
    )
    image.status = status
    return image


@pytest.mark.asyncio
async def test_create_version_rejects_pending_review() -> None:
    project = Project.create("Gate")
    class_id = uuid4()
    image = _make_image(project.id, split=SplitType.TRAIN, status=ImageStatus.REQUIRES_REVIEW)
    pending = Annotation.create_from_keypoints(
        image_id=image.id,
        class_id=class_id,
        bbox=BoundingBox(0.5, 0.5, 0.2, 0.2),
        source_annotation_id=uuid4(),
    )
    storage = _FakeStorage()
    storage.files[image.file_path] = b"img"
    use_case = CreateDatasetVersionUseCase(
        _FakeProjects(project),
        _FakeImages([image]),
        _FakeAnnotations({image.id: [pending]}),
        _FakeClasses(
            [
                AnnotationClass(
                    id=class_id,
                    project_id=project.id,
                    name="crack",
                    color_hex="#FF0000",
                    index_id=0,
                )
            ]
        ),
        _FakeVersions(),
        storage,
        _FakeAugmentation(),
        _FakeUow(),
        min_verified_images=1,
    )

    with pytest.raises(UnverifiedDataException):
        await use_case.execute(project.id)
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_create_version_rejects_insufficient_verified() -> None:
    project = Project.create("Tiny")
    use_case = CreateDatasetVersionUseCase(
        _FakeProjects(project),
        _FakeImages([]),
        _FakeAnnotations({}),
        _FakeClasses([]),
        _FakeVersions(),
        _FakeStorage(),
        _FakeAugmentation(),
        _FakeUow(),
        min_verified_images=DEFAULT_MIN_VERIFIED_IMAGES,
    )

    with pytest.raises(InsufficientVerifiedDataException):
        await use_case.execute(project.id)


@pytest.mark.asyncio
async def test_create_version_writes_train_aug_and_plain_valid_test() -> None:
    project = Project.create("Ready")
    class_id = uuid4()
    annotation_class = AnnotationClass(
        id=class_id,
        project_id=project.id,
        name="crack",
        color_hex="#FF0000",
        index_id=0,
    )
    train = _make_image(
        project.id, split=SplitType.TRAIN, status=ImageStatus.VERIFIED, file_path="t.png"
    )
    valid = _make_image(
        project.id, split=SplitType.VALID, status=ImageStatus.VERIFIED, file_path="v.png"
    )
    test = _make_image(
        project.id, split=SplitType.TEST, status=ImageStatus.VERIFIED, file_path="x.png"
    )
    boxes = {
        train.id: [
            Annotation.create_manual(
                train.id, class_id, BoundingBox(0.5, 0.5, 0.2, 0.2)
            )
        ],
        valid.id: [
            Annotation.create_manual(
                valid.id, class_id, BoundingBox(0.4, 0.4, 0.1, 0.1)
            )
        ],
        test.id: [
            Annotation.create_manual(
                test.id, class_id, BoundingBox(0.6, 0.6, 0.1, 0.1)
            )
        ],
    }
    storage = _FakeStorage()
    storage.files["t.png"] = b"train-bytes"
    storage.files["v.png"] = b"valid-bytes"
    storage.files["x.png"] = b"test-bytes"
    versions = _FakeVersions()
    aug = _FakeAugmentation()
    uow = _FakeUow()
    use_case = CreateDatasetVersionUseCase(
        _FakeProjects(project),
        _FakeImages([train, valid, test]),
        _FakeAnnotations(boxes),
        _FakeClasses([annotation_class]),
        versions,
        storage,
        aug,
        uow,
        min_verified_images=3,
    )

    result = await use_case.execute(
        project.id,
        AugmentationConfig(multiplier=3, horizontal_flip=True),
        rng=Random(0),
    )

    assert result.status == DatasetVersionStatus.READY
    assert result.train_count == 1
    assert result.valid_count == 1
    assert result.test_count == 1
    assert result.train_file_count == 3
    assert result.valid_file_count == 1
    assert result.test_file_count == 1
    assert result.yaml_path.endswith("data.yaml")
    assert len(result.items) == 3
    assert {item.split for item in result.items} == {
        SplitType.TRAIN,
        SplitType.VALID,
        SplitType.TEST,
    }
    assert uow.commits == 1
    assert list(versions.store.values())[0].status == DatasetVersionStatus.READY

    train_images = [
        path
        for path in storage.files
        if "/train/images/" in path and path.endswith(".jpg")
    ]
    valid_images = [
        path
        for path in storage.files
        if "/valid/images/" in path and path.endswith(".jpg")
    ]
    test_images = [
        path
        for path in storage.files
        if "/test/images/" in path and path.endswith(".jpg")
    ]
    assert len(train_images) == 3
    assert len(valid_images) == 1
    assert len(test_images) == 1

    yaml_text = storage.files[result.yaml_path].decode("utf-8")
    assert "crack" in yaml_text
    assert aug.calls.count((True, 3)) == 1
    assert aug.calls.count((False, 3)) == 2


@pytest.mark.asyncio
async def test_dataset_version_is_immutable_after_source_edit() -> None:
    project = Project.create("Immutable")
    class_id = uuid4()
    annotation_class = AnnotationClass(
        id=class_id,
        project_id=project.id,
        name="dent",
        color_hex="#00FF00",
        index_id=0,
    )
    train = _make_image(
        project.id, split=SplitType.TRAIN, status=ImageStatus.VERIFIED, file_path="t.png"
    )
    valid = _make_image(
        project.id, split=SplitType.VALID, status=ImageStatus.VERIFIED, file_path="v.png"
    )
    test = _make_image(
        project.id, split=SplitType.TEST, status=ImageStatus.VERIFIED, file_path="x.png"
    )
    boxes = {
        train.id: [
            Annotation.create_manual(train.id, class_id, BoundingBox(0.5, 0.5, 0.2, 0.2))
        ],
        valid.id: [
            Annotation.create_manual(valid.id, class_id, BoundingBox(0.4, 0.4, 0.1, 0.1))
        ],
        test.id: [
            Annotation.create_manual(test.id, class_id, BoundingBox(0.6, 0.6, 0.1, 0.1))
        ],
    }
    storage = _FakeStorage()
    storage.files["t.png"] = b"original-train"
    storage.files["v.png"] = b"original-valid"
    storage.files["x.png"] = b"original-test"
    use_case = CreateDatasetVersionUseCase(
        _FakeProjects(project),
        _FakeImages([train, valid, test]),
        _FakeAnnotations(boxes),
        _FakeClasses([annotation_class]),
        _FakeVersions(),
        storage,
        _FakeAugmentation(),
        _FakeUow(),
        min_verified_images=3,
    )
    result = await use_case.execute(
        project.id, AugmentationConfig(multiplier=1), rng=Random(0)
    )
    snapshot_path = [
        path for path in storage.files if "/train/images/" in path and path.endswith(".jpg")
    ][0]
    frozen = storage.files[snapshot_path]
    label_path = snapshot_path.replace("/images/", "/labels/").replace(".jpg", ".txt")
    frozen_label = storage.files[label_path]

    storage.files["t.png"] = b"mutated-after-version"

    assert storage.files[snapshot_path] == frozen
    assert storage.files[label_path] == frozen_label
    train_item = next(item for item in result.items if item.image_id == train.id)
    assert train_item.snapshot_annotations[0].x_center == 0.5
