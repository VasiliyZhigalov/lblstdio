from uuid import uuid4

import pytest

from app.application.use_cases.images.delete_image import DeleteImageUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.enums import SplitType
from app.domain.exceptions import ResourceNotFoundException
from app.domain.value_objects.bounding_box import BoundingBox


class _FakeImages:
    def __init__(self, image: Image | None) -> None:
        self.image = image
        self.deleted_id = None

    async def get_by_id(self, image_id):
        if self.image is None or self.image.id != image_id:
            return None
        return self.image

    async def delete(self, image_id) -> None:
        self.deleted_id = image_id
        self.image = None


class _FakeAnnotations:
    def __init__(self, items=None) -> None:
        self.items = list(items or [])
        self.replaced = None

    async def replace_for_image(self, image_id, annotations) -> None:
        self.replaced = (image_id, list(annotations))
        self.items = list(annotations)


class _FakeStorage:
    def __init__(self) -> None:
        self.deleted_paths: list[str] = []

    async def delete(self, relative_path: str) -> None:
        self.deleted_paths.append(relative_path)


class _FakeUow:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_delete_image_removes_annotations_row_and_file() -> None:
    image = Image.create(
        project_id=uuid4(),
        file_path="proj/a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    boxes = [
        Annotation.create_manual(image.id, uuid4(), BoundingBox(0.5, 0.5, 0.1, 0.1))
    ]
    images = _FakeImages(image)
    annotations = _FakeAnnotations(boxes)
    storage = _FakeStorage()
    uow = _FakeUow()

    await DeleteImageUseCase(images, annotations, storage, uow).execute(image.id)

    assert images.deleted_id == image.id
    assert annotations.replaced == (image.id, [])
    assert storage.deleted_paths == ["proj/a.png"]
    assert uow.committed is True


@pytest.mark.asyncio
async def test_delete_image_not_found() -> None:
    use_case = DeleteImageUseCase(
        _FakeImages(None), _FakeAnnotations(), _FakeStorage(), _FakeUow()
    )
    with pytest.raises(ResourceNotFoundException):
        await use_case.execute(uuid4())
