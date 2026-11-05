from uuid import uuid4

import pytest

from app.application.use_cases.images.get_images_summary import GetImagesSummaryUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.enums import ImageStatus, SplitType
from app.domain.value_objects.bounding_box import BoundingBox


def _image(project_id, name: str, status: ImageStatus = ImageStatus.UNANNOTATED) -> Image:
    image = Image.create(
        project_id=project_id,
        file_path=name,
        file_name=name,
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    image.status = status
    return image


class _FakeImages:
    def __init__(self, images: list[Image]) -> None:
        self.images = images

    async def list_by_project(self, project_id):
        return [item for item in self.images if item.project_id == project_id]


class _FakeAnnotations:
    def __init__(self, items: list[Annotation]) -> None:
        self.items = items
        self.list_by_image_calls = 0
        self.list_by_image_ids_calls = 0

    async def list_by_image(self, image_id):
        self.list_by_image_calls += 1
        return [item for item in self.items if item.image_id == image_id]

    async def list_by_image_ids(self, image_ids):
        self.list_by_image_ids_calls += 1
        wanted = set(image_ids)
        return [item for item in self.items if item.image_id in wanted]


class _FakeLabels:
    def __init__(self, items=None) -> None:
        self.items = items or []
        self.list_by_image_ids_calls = 0

    async def list_by_image_ids(self, image_ids):
        self.list_by_image_ids_calls += 1
        wanted = set(image_ids)
        return [item for item in self.items if item.image_id in wanted]


@pytest.mark.asyncio
async def test_images_summary_aggregates_boxes_without_per_image_queries() -> None:
    project_id = uuid4()
    class_a = uuid4()
    class_b = uuid4()
    annotated = _image(project_id, "a.png", ImageStatus.VERIFIED)
    empty = _image(project_id, "b.png")
    boxes = [
        Annotation.create_manual(
            annotated.id, class_a, BoundingBox(0.5, 0.5, 0.1, 0.1)
        ),
        Annotation.create_manual(
            annotated.id, class_b, BoundingBox(0.3, 0.3, 0.1, 0.1)
        ),
        Annotation.create_manual(
            annotated.id, class_a, BoundingBox(0.7, 0.7, 0.1, 0.1)
        ),
    ]
    annotations = _FakeAnnotations(boxes)
    labels = _FakeLabels()

    summary = await GetImagesSummaryUseCase(
        _FakeImages([annotated, empty]), annotations, labels
    ).execute(project_id)

    assert annotations.list_by_image_calls == 0
    assert annotations.list_by_image_ids_calls == 1
    assert summary.class_counts == {class_a: 2, class_b: 1}
    assert [item.image_id for item in summary.images] == [annotated.id]
    assert summary.images[0].box_count == 3
    assert set(summary.images[0].class_ids) == {class_a, class_b}
    assert len(summary.images[0].annotations) == 3
