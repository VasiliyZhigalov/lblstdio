from uuid import UUID

from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_label_repository import IImageLabelRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.application.services.task_policy import require_task
from app.domain.entities.image_label import ImageLabel
from app.domain.enums import ProjectTaskType
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException


async def _load_classification_image(
    images: IImageRepository,
    projects: IProjectRepository,
    image_id: UUID,
):
    image = await images.get_by_id(image_id)
    if image is None:
        raise ResourceNotFoundException(f"image {image_id} not found")
    project = await projects.get_by_id(image.project_id)
    if project is None:
        raise ResourceNotFoundException(f"project {image.project_id} not found")
    require_task(project, ProjectTaskType.CLASSIFICATION)
    return image


class SaveImageLabelUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        images: IImageRepository,
        classes: IClassRepository,
        labels: IImageLabelRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._projects = projects
        self._images = images
        self._classes = classes
        self._labels = labels
        self._uow = uow

    async def execute(self, image_id: UUID, class_id: UUID) -> ImageLabel:
        image = await _load_classification_image(self._images, self._projects, image_id)
        known = {item.id for item in await self._classes.list_by_project(image.project_id)}
        if class_id not in known:
            raise DomainValidationException(
                f"class {class_id} does not belong to this project"
            )
        existing = await self._labels.get_by_image_id(image_id)
        if existing is None:
            label = ImageLabel.create_manual(image_id, class_id)
        else:
            existing.assign_manual(class_id)
            label = existing
        await self._labels.upsert(label)
        image.recalculate_status_from_label(label)
        await self._images.update(image)
        await self._uow.commit()
        return label


class ClearImageLabelUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        images: IImageRepository,
        labels: IImageLabelRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._projects = projects
        self._images = images
        self._labels = labels
        self._uow = uow

    async def execute(self, image_id: UUID) -> None:
        image = await _load_classification_image(self._images, self._projects, image_id)
        await self._labels.delete_by_image_id(image_id)
        image.recalculate_status_from_label(None)
        await self._images.update(image)
        await self._uow.commit()


class ConfirmImageLabelUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        images: IImageRepository,
        labels: IImageLabelRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._projects = projects
        self._images = images
        self._labels = labels
        self._uow = uow

    async def execute(self, image_id: UUID) -> ImageLabel:
        image = await _load_classification_image(self._images, self._projects, image_id)
        label = await self._labels.get_by_image_id(image_id)
        if label is None:
            raise ResourceNotFoundException(f"label for image {image_id} not found")
        label.confirm()
        await self._labels.upsert(label)
        image.recalculate_status_from_label(label)
        await self._images.update(image)
        await self._uow.commit()
        return label
