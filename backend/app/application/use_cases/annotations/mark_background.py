from uuid import UUID

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.image import Image
from app.domain.enums import VerificationStatus
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException


class MarkImageAsBackgroundUseCase:
    """Mark an empty frame as a verified background (negative) sample."""

    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._uow = uow

    async def execute(self, image_id: UUID) -> Image:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")

        items = await self._annotations.list_by_image(image_id)
        active = [
            item
            for item in items
            if item.verification_status != VerificationStatus.REJECTED
        ]
        if active:
            raise DomainValidationException(
                "background requires an empty frame: remove all objects first"
            )

        image.mark_as_background()
        await self._images.update(image)
        await self._uow.commit()
        return image
