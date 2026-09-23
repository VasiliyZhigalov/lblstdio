from uuid import UUID

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.application.services.task_policy import require_task
from app.domain.entities.image import Image
from app.domain.enums import ProjectTaskType, VerificationStatus
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException


class MarkImageAsBackgroundUseCase:
    """Mark an empty frame as a verified background (negative) sample."""

    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        uow: IUnitOfWork,
        projects: IProjectRepository | None = None,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._uow = uow
        self._projects = projects

    async def execute(self, image_id: UUID) -> Image:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")

        if self._projects is not None:
            project = await self._projects.get_by_id(image.project_id)
            if project is None:
                raise ResourceNotFoundException(f"project {image.project_id} not found")
            require_task(project, ProjectTaskType.DETECTION)

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
