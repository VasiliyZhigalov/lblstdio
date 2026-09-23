from uuid import UUID

from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.image import Image
from app.domain.exceptions import ResourceNotFoundException


class SetImageTestHoldoutUseCase:
    """Pin an image as a manual test frame, or return it to the trainable pool."""

    def __init__(self, images: IImageRepository, uow: IUnitOfWork) -> None:
        self._images = images
        self._uow = uow

    async def execute(self, image_id: UUID, holdout: bool) -> Image:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")
        image.set_test_holdout(holdout)
        await self._images.update(image)
        await self._uow.commit()
        return image
