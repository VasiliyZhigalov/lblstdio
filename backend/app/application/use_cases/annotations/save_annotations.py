from uuid import UUID

from app.application.dto import BoxInput
from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.annotation import Annotation
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.value_objects.bounding_box import BoundingBox


class SaveAnnotationsUseCase:
    def __init__(
        self,
        images: IImageRepository,
        classes: IClassRepository,
        annotations: IAnnotationRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._images = images
        self._classes = classes
        self._annotations = annotations
        self._uow = uow

    async def execute(
        self, image_id: UUID, boxes: list[BoxInput]
    ) -> list[Annotation]:
        image = await self._images.get_by_id(image_id)
        if image is None:
            raise ResourceNotFoundException(f"image {image_id} not found")

        project_classes = await self._classes.list_by_project(image.project_id)
        known_ids = {item.id for item in project_classes}

        annotations: list[Annotation] = []
        for box in boxes:
            if box.class_id not in known_ids:
                raise DomainValidationException(
                    f"class {box.class_id} does not belong to this project"
                )
            bbox = BoundingBox(
                x_center=box.x_center,
                y_center=box.y_center,
                width=box.width,
                height=box.height,
            )
            annotations.append(
                Annotation.create_manual(
                    image_id=image_id,
                    class_id=box.class_id,
                    bbox=bbox,
                    annotation_id=box.annotation_id,
                )
            )

        await self._annotations.replace_for_image(image_id, annotations)
        image.recalculate_status(annotations)
        await self._images.update(image)
        await self._uow.commit()
        return annotations
