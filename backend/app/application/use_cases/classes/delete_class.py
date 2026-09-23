from uuid import UUID

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_label_repository import IImageLabelRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.enums import ProjectTaskType
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.services.class_index import compact_indices


class DeleteClassUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        classes: IClassRepository,
        uow: IUnitOfWork,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        labels: IImageLabelRepository | None = None,
    ) -> None:
        self._projects = projects
        self._classes = classes
        self._uow = uow
        self._images = images
        self._annotations = annotations
        self._labels = labels

    async def execute(self, class_id: UUID, project_id: UUID | None = None) -> None:
        annotation_class = await self._classes.get_by_id(class_id)
        if annotation_class is None:
            raise ResourceNotFoundException(f"class {class_id} not found")
        if project_id is not None:
            project = await self._projects.get_by_id(project_id)
            if project is None or annotation_class.project_id != project_id:
                raise ResourceNotFoundException(f"class {class_id} not found")

        owner_id = annotation_class.project_id
        await self._classes.delete(class_id)
        remaining = await self._classes.list_by_project(owner_id)
        compacted = compact_indices(remaining)
        if compacted:
            await self._classes.update_many(compacted)

        owner = await self._projects.get_by_id(owner_id)
        images = await self._images.list_by_project(owner_id)
        if owner is not None and owner.task_type == ProjectTaskType.CLASSIFICATION:
            if self._labels is None:
                raise DomainValidationException(
                    "image label repository is not configured"
                )
            for image in images:
                label = await self._labels.get_by_image_id(image.id)
                if label is not None and label.class_id == class_id:
                    await self._labels.delete_by_image_id(image.id)
                    label = None
                image.recalculate_status_from_label(label)
                await self._images.update(image)
        else:
            for image in images:
                boxes = await self._annotations.list_by_image(image.id)
                image.recalculate_status(boxes)
                await self._images.update(image)

        await self._uow.commit()
