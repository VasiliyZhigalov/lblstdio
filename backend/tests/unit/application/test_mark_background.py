from uuid import uuid4

import pytest

from app.application.use_cases.annotations.mark_background import (
    MarkImageAsBackgroundUseCase,
)
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.enums import ImageStatus, SplitType
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.bounding_box import BoundingBox


class _FakeImages:
    def __init__(self, image: Image) -> None:
        self.image = image

    async def get_by_id(self, image_id):
        return self.image if self.image.id == image_id else None

    async def update(self, image: Image) -> None:
        self.image = image


class _FakeAnnotations:
    def __init__(self, items=None) -> None:
        self.items = list(items or [])

    async def list_by_image(self, image_id):
        return list(self.items)


class _FakeUow:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_mark_background_on_empty_frame() -> None:
    image = Image.create(
        project_id=uuid4(),
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    use_case = MarkImageAsBackgroundUseCase(
        _FakeImages(image), _FakeAnnotations(), _FakeUow()
    )
    result = await use_case.execute(image.id)
    assert result.status == ImageStatus.VERIFIED
    assert result.is_background is True
    assert result.can_be_included_in_dataset() is True


@pytest.mark.asyncio
async def test_mark_background_rejects_non_empty_frame() -> None:
    image = Image.create(
        project_id=uuid4(),
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    boxes = [
        Annotation.create_manual(
            image.id, uuid4(), BoundingBox(0.5, 0.5, 0.1, 0.1)
        )
    ]
    use_case = MarkImageAsBackgroundUseCase(
        _FakeImages(image), _FakeAnnotations(boxes), _FakeUow()
    )
    with pytest.raises(DomainValidationException, match="empty"):
        await use_case.execute(image.id)
