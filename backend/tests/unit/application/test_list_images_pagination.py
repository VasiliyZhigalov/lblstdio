from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.use_cases.images.get_image import ListImagesUseCase
from app.domain.entities.image import Image
from app.domain.enums import ImageListSort, ImageStatus, SplitType


def _image(project_id, name: str, *, created_offset: int = 0) -> Image:
    image = Image.create(
        project_id=project_id,
        file_path=name,
        file_name=name,
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    image.created_at = datetime.now(UTC) + timedelta(seconds=created_offset)
    return image


class _RecordingImages:
    def __init__(self, images: list[Image]) -> None:
        self.images = images
        self.calls: list[dict] = []

    async def list_by_project(self, project_id):
        raise AssertionError("list must not load the full project then slice in Python")

    async def list_page(
        self, project_id, *, split=None, status=None, offset=0, limit=None, sort=None
    ):
        self.calls.append(
            {
                "project_id": project_id,
                "split": split,
                "status": status,
                "offset": offset,
                "limit": limit,
                "sort": sort,
            }
        )
        return list(self.images)


@pytest.mark.asyncio
async def test_list_images_delegates_pagination_to_repository() -> None:
    project_id = uuid4()
    images = [_image(project_id, f"{index}.png", created_offset=index) for index in range(3)]
    repo = _RecordingImages(images)

    listed = await ListImagesUseCase(repo).execute(
        project_id,
        split=SplitType.TRAIN,
        status=ImageStatus.UNANNOTATED,
        offset=1,
        limit=1,
    )

    assert repo.calls == [
        {
            "project_id": project_id,
            "split": SplitType.TRAIN,
            "status": ImageStatus.UNANNOTATED,
            "offset": 1,
            "limit": 1,
            "sort": None,
        }
    ]
    assert listed == images


@pytest.mark.asyncio
async def test_list_images_forwards_uncertainty_sort() -> None:
    project_id = uuid4()
    repo = _RecordingImages([])

    await ListImagesUseCase(repo).execute(project_id, sort=ImageListSort.UNCERTAINTY)

    assert repo.calls[0]["sort"] == ImageListSort.UNCERTAINTY
