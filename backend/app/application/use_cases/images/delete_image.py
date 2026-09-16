from uuid import UUID

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.exceptions import ResourceNotFoundException


class DeleteImageUseCase:
    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        storage: IFileStorage,
        uow: IUnitOfWork,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._storage = storage
        self._uow = uow

    async def execute(self, image_id: UUID) -> None:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")

        await self._annotations.replace_for_image(image_id, [])
        await self._images.delete(image_id)
        await self._uow.commit()
        try:
            await self._storage.delete(image.file_path)
        except Exception:
            # DB row is already gone; orphaned file is best-effort cleanup.
            pass
