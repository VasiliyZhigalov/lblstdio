from uuid import UUID

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.annotation import Annotation
from app.domain.enums import VerificationStatus
from app.domain.exceptions import ResourceNotFoundException


class VerifyAnnotationUseCase:
    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._uow = uow

    async def execute(self, image_id: UUID, annotation_id: UUID) -> Annotation:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")

        items = await self._annotations.list_by_image(image_id)
        found = next((item for item in items if item.id == annotation_id), None)
        if found is None:
            raise ResourceNotFoundException(f"annotation {annotation_id} not found")

        found.verify()
        await self._annotations.replace_for_image(image_id, items)
        image.recalculate_status(items)
        await self._images.update(image)
        await self._uow.commit()
        return found


class VerifyAllAnnotationsUseCase:
    """Approve every PENDING_REVIEW box on the frame (HITL express verify)."""

    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._uow = uow

    async def execute(self, image_id: UUID) -> list[Annotation]:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")

        items = await self._annotations.list_by_image(image_id)
        for item in items:
            if item.verification_status == VerificationStatus.PENDING_REVIEW:
                item.verify()

        await self._annotations.replace_for_image(image_id, items)
        image.recalculate_status(items)
        await self._images.update(image)
        await self._uow.commit()
        return items


class RejectAllPendingAnnotationsUseCase:
    """Delete every PENDING_REVIEW box on the frame."""

    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._uow = uow

    async def execute(self, image_id: UUID) -> list[Annotation]:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")

        items = await self._annotations.list_by_image(image_id)
        remaining = [
            item
            for item in items
            if item.verification_status != VerificationStatus.PENDING_REVIEW
        ]
        await self._annotations.replace_for_image(image_id, remaining)
        image.recalculate_status(remaining)
        await self._images.update(image)
        await self._uow.commit()
        return remaining


class DeleteAnnotationUseCase:
    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._uow = uow

    async def execute(self, image_id: UUID, annotation_id: UUID) -> list[Annotation]:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")

        items = await self._annotations.list_by_image(image_id)
        remaining = [item for item in items if item.id != annotation_id]
        if len(remaining) == len(items):
            raise ResourceNotFoundException(f"annotation {annotation_id} not found")

        await self._annotations.replace_for_image(image_id, remaining)
        image.recalculate_status(remaining)
        await self._images.update(image)
        await self._uow.commit()
        return remaining
