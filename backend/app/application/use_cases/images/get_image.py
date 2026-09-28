from uuid import UUID

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.image_label_repository import IImageLabelRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.enums import ImageStatus, SplitType
from app.domain.exceptions import ResourceNotFoundException


class GetImageUseCase:
    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        labels: IImageLabelRepository | None = None,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._labels = labels

    async def execute(
        self, image_id: UUID
    ) -> tuple[Image, list[Annotation], ImageLabel | None]:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")
        boxes = await self._annotations.list_by_image(image_id)
        label = None
        if self._labels is not None:
            label = await self._labels.get_by_image_id(image_id)
        return image, boxes, label


class ListImagesUseCase:
    def __init__(self, images: IImageRepository) -> None:
        self._images = images

    async def execute(
        self,
        project_id: UUID,
        split: SplitType | None = None,
        status: ImageStatus | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Image]:
        return await self._images.list_page(
            project_id,
            split=split,
            status=status,
            offset=offset,
            limit=limit,
        )
