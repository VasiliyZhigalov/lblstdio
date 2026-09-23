import io
import zipfile
from uuid import uuid4

import pytest
from PIL import Image as PILImage

from app.application.use_cases.dataset.export_crops import ExportCropsUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import ProjectTaskType, SplitType
from app.domain.exceptions import ResourceNotFoundException, TaskTypeMismatchException
from app.domain.value_objects.bounding_box import BoundingBox
from app.infrastructure.storage.zip_packer import ZipArchivePacker
from tests.unit.application.test_export_yolo import (
    _FakeAnnotations,
    _FakeClasses,
    _FakeImages,
    _FakeProjects,
    _FakeStorage,
)


def _png(
    width: int,
    height: int,
    regions: list[tuple[tuple[int, int, int, int], tuple[int, int, int]]],
) -> bytes:
    image = PILImage.new("RGB", (width, height), (0, 0, 0))
    for (x1, y1, x2, y2), color in regions:
        for x in range(x1, x2):
            for y in range(y1, y2):
                image.putpixel((x, y), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _box(x: float, y: float, w: float, h: float) -> BoundingBox:
    return BoundingBox(x_center=x, y_center=y, width=w, height=h)


@pytest.fixture
def crops_fixture():
    project = Project.create("Export/Me")
    class_a = AnnotationClass.create(project.id, "class_a", "#111111", 0)
    class_b = AnnotationClass.create(project.id, "class_b", "#222222", 1)
    class_c = AnnotationClass.create(project.id, "class_c", "#333333", 2)

    frame = Image.create(
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

    box_a0 = Annotation.create_manual(frame.id, class_a.id, _box(0.4, 0.6, 0.1, 0.2))
    box_a1 = Annotation.create_manual(frame.id, class_a.id, _box(0.8, 0.2, 0.2, 0.2))
    box_b = Annotation.create_manual(frame.id, class_b.id, _box(0.15, 0.5, 0.1, 0.1))
    rejected = Annotation.create_manual(frame.id, class_a.id, _box(0.5, 0.5, 0.2, 0.2))
    rejected.reject()
    frame.recalculate_status([box_a0, box_a1, box_b, rejected])

    pending_box = Annotation.create_prediction(pending.id, class_a.id, _box(0.5, 0.5, 0.2, 0.2), 0.4)
    pending.recalculate_status([pending_box])

    frame_bytes = _png(
        100,
        80,
        [
            ((35, 40, 45, 56), (10, 20, 30)),
            ((70, 8, 90, 24), (200, 10, 10)),
            ((10, 36, 20, 44), (1, 2, 3)),
        ],
    )
    use_case = ExportCropsUseCase(
        projects=_FakeProjects(project),
        classes=_FakeClasses([class_a, class_b, class_c]),
        images=_FakeImages([frame, pending]),
        annotations=_FakeAnnotations([box_a0, box_a1, box_b, rejected, pending_box]),
        storage=_FakeStorage({frame.file_path: frame_bytes}),
        packer=ZipArchivePacker(),
    )
    return use_case, project, frame


class TestExportCropsUseCase:
    @pytest.mark.asyncio
    async def test_zip_groups_crops_by_class(self, crops_fixture) -> None:
        use_case, project, frame = crops_fixture

        payload, filename = await use_case.execute(project.id)

        assert filename == "Export_Me_crop.zip"
        archive = zipfile.ZipFile(io.BytesIO(payload))
        names = set(archive.namelist())
        root = "Export_Me_crop"
        assert f"{root}/class_c/" in names
        assert f"{root}/class_a/{frame.id}_0.png" in names
        assert f"{root}/class_a/{frame.id}_1.png" in names
        assert f"{root}/class_b/{frame.id}_0.png" in names
        class_a_crops = {
            name
            for name in names
            if name.startswith(f"{root}/class_a/") and name.endswith(".png")
        }
        assert class_a_crops == {
            f"{root}/class_a/{frame.id}_0.png",
            f"{root}/class_a/{frame.id}_1.png",
        }

        first = PILImage.open(io.BytesIO(archive.read(f"{root}/class_a/{frame.id}_0.png")))
        second = PILImage.open(io.BytesIO(archive.read(f"{root}/class_a/{frame.id}_1.png")))
        third = PILImage.open(io.BytesIO(archive.read(f"{root}/class_b/{frame.id}_0.png")))
        assert first.size == (10, 16)
        assert second.size == (20, 16)
        assert third.size == (10, 8)
        assert first.getpixel((0, 0)) == (10, 20, 30)
        assert second.getpixel((0, 0)) == (200, 10, 10)
        assert third.getpixel((0, 0)) == (1, 2, 3)

    @pytest.mark.asyncio
    async def test_classification_project_is_rejected(self, crops_fixture) -> None:
        use_case, _, _ = crops_fixture
        project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
        use_case._projects.project = project

        with pytest.raises(TaskTypeMismatchException):
            await use_case.execute(project.id)

    @pytest.mark.asyncio
    async def test_missing_project_raises_not_found(self, crops_fixture) -> None:
        use_case, *_ = crops_fixture
        with pytest.raises(ResourceNotFoundException):
            await use_case.execute(uuid4())

    @pytest.mark.asyncio
    async def test_archive_filename_matches_zip_stem(self, crops_fixture) -> None:
        use_case, project, _frame = crops_fixture
        assert await use_case.archive_filename(project.id) == "Export_Me_crop.zip"
