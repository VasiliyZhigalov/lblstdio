import zipfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from app.application.use_cases.dataset.export_yolo import ExportYOLOUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import SplitType
from app.domain.exceptions import ResourceNotFoundException
from app.domain.value_objects.bounding_box import BoundingBox
from app.infrastructure.storage.local_storage import LocalFileStorage
from app.infrastructure.storage.zip_packer import ZipArchivePacker


@contextmanager
def _open_zip(path: Path):
    try:
        with zipfile.ZipFile(path) as archive:
            yield archive
    finally:
        path.unlink(missing_ok=True)


class _FakeProjects:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get_by_id(self, project_id):
        return self.project if self.project.id == project_id else None


class _FakeClasses:
    def __init__(self, classes: list[AnnotationClass]) -> None:
        self.classes = classes

    async def list_by_project(self, project_id):
        return [item for item in self.classes if item.project_id == project_id]


class _FakeImages:
    def __init__(self, images: list[Image]) -> None:
        self.images = images

    async def list_by_project(self, project_id):
        return [item for item in self.images if item.project_id == project_id]


class _FakeAnnotations:
    def __init__(self, annotations: list[Annotation]) -> None:
        self.annotations = annotations

    async def list_by_image_ids(self, image_ids):
        wanted = set(image_ids)
        return [item for item in self.annotations if item.image_id in wanted]


class _FakeStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def read(self, relative_path: str) -> bytes:
        return self.files[relative_path]


def _box(x: float = 0.5, y: float = 0.5, w: float = 0.2, h: float = 0.1) -> BoundingBox:
    return BoundingBox(x_center=x, y_center=y, width=w, height=h)


@pytest.fixture
def export_fixture():
    project = Project.create("Export Me")
    class_a = AnnotationClass.create(project.id, "class_a", "#111111", 0)
    class_b = AnnotationClass.create(project.id, "class_b", "#222222", 1)

    train_ready = Image.create(
        project_id=project.id,
        file_path="projects/p/images/frame.png",
        file_name="frame.png",
        width=100,
        height=80,
        split=SplitType.TRAIN,
    )
    pending = Image.create(
        project_id=project.id,
        file_path="projects/p/images/pending.png",
        file_name="pending.png",
        width=100,
        height=80,
        split=SplitType.TRAIN,
    )
    empty_valid = Image.create(
        project_id=project.id,
        file_path="projects/p/images/empty.jpg",
        file_name="empty.jpg",
        width=10,
        height=10,
        split=SplitType.VALID,
    )

    verified_boxes = [
        Annotation.create_manual(train_ready.id, class_a.id, _box(0.4, 0.6, 0.1, 0.2)),
        Annotation.create_manual(train_ready.id, class_b.id, _box(0.7, 0.3, 0.15, 0.25)),
    ]
    train_ready.recalculate_status(verified_boxes)

    pending_box = Annotation.create_prediction(
        pending.id, class_a.id, _box(), confidence=0.66
    )
    pending.recalculate_status([pending_box])

    use_case = ExportYOLOUseCase(
        projects=_FakeProjects(project),
        classes=_FakeClasses([class_a, class_b]),
        images=_FakeImages([train_ready, pending, empty_valid]),
        annotations=_FakeAnnotations(verified_boxes + [pending_box]),
        storage=_FakeStorage(
            {
                train_ready.file_path: b"TRAIN-BYTES",
                pending.file_path: b"PENDING-BYTES",
                empty_valid.file_path: b"EMPTY-BYTES",
            }
        ),
        packer=ZipArchivePacker(),
    )
    return use_case, project, train_ready, pending, empty_valid


class TestExportYOLOUseCase:
    @pytest.mark.asyncio
    async def test_zip_structure_yaml_and_label_math(self, export_fixture) -> None:
        use_case, project, train_ready, pending, empty_valid = export_fixture

        path = await use_case.execute(project.id)
        with _open_zip(path) as archive:
            names = set(archive.namelist())

            assert "data.yaml" in names
            assert f"train/images/{train_ready.id}.png" in names
            assert f"train/labels/{train_ready.id}.txt" in names
            assert f"valid/images/{empty_valid.id}.jpg" in names
            assert f"valid/labels/{empty_valid.id}.txt" in names
            assert "train/images/" in names or any(
                item.startswith("train/images/") for item in names
            )
            assert "test/images/" in names or any(
                item.startswith("test/images/") for item in names
            )

            data = yaml.safe_load(archive.read("data.yaml"))
            assert data["names"][0] == "class_a"
            assert data["names"][1] == "class_b"
            assert data["train"] == "train/images"
            assert data["val"] == "valid/images"
            assert data["test"] == "test/images"
            assert data["nc"] == 2

            label = archive.read(f"train/labels/{train_ready.id}.txt").decode("utf-8").strip().splitlines()
            assert label == [
                "0 0.400000 0.600000 0.100000 0.200000",
                "1 0.700000 0.300000 0.150000 0.250000",
            ]
            assert archive.read(f"valid/labels/{empty_valid.id}.txt") == b""
            assert archive.read(f"train/images/{train_ready.id}.png") == b"TRAIN-BYTES"

    @pytest.mark.asyncio
    async def test_excludes_incomplete_lifecycle_entities(self, export_fixture) -> None:
        use_case, project, _, pending, _ = export_fixture

        path = await use_case.execute(project.id)
        with _open_zip(path) as archive:
            names = archive.namelist()

        assert f"train/images/{pending.file_name}" not in names
        assert f"train/labels/{pending.id}.txt" not in names
        assert all("PENDING-BYTES" not in name for name in names)

    @pytest.mark.asyncio
    async def test_same_stem_different_extension_does_not_collide(
        self, export_fixture
    ) -> None:
        use_case, project, train_ready, pending, empty_valid = export_fixture
        twin = Image.create(
            project_id=project.id,
            file_path="projects/p/images/frame.jpg",
            file_name="frame.jpg",
            width=10,
            height=10,
            split=SplitType.TRAIN,
        )
        use_case._images.images.append(twin)
        use_case._storage.files[twin.file_path] = b"TWIN"

        path = await use_case.execute(project.id)
        with _open_zip(path) as archive:
            names = archive.namelist()
        assert f"train/images/{train_ready.id}.png" in names
        assert f"train/images/{twin.id}.jpg" in names
        assert f"train/labels/{train_ready.id}.txt" in names
        assert f"train/labels/{twin.id}.txt" in names

    @pytest.mark.asyncio
    async def test_missing_project_raises_not_found(self, export_fixture) -> None:
        use_case, *_ = export_fixture
        with pytest.raises(ResourceNotFoundException):
            await use_case.execute(uuid4())


class _CountingStorage(LocalFileStorage):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.reads = 0

    async def read(self, relative_path: str) -> bytes:
        self.reads += 1
        return await super().read(relative_path)


@pytest.mark.asyncio
async def test_export_streams_on_disk_images_without_reading_bytes(tmp_path: Path) -> None:
    storage = _CountingStorage(tmp_path)
    project = Project.create("Disk")
    annotation_class = AnnotationClass.create(project.id, "class_a", "#111111", 0)
    relative = await storage.save("images", "frame.png", b"TRAIN-BYTES")
    image = Image.create(
        project_id=project.id,
        file_path=relative,
        file_name="frame.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    use_case = ExportYOLOUseCase(
        projects=_FakeProjects(project),
        classes=_FakeClasses([annotation_class]),
        images=_FakeImages([image]),
        annotations=_FakeAnnotations([]),
        storage=storage,
        packer=ZipArchivePacker(),
    )

    path = await use_case.execute(project.id)
    with _open_zip(path) as archive:
        assert archive.read(f"train/images/{image.id}.png") == b"TRAIN-BYTES"
    assert storage.reads == 0
