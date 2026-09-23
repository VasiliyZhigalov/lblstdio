from uuid import UUID
import asyncio

from app.application.dto import BoxInput, DebugArrow, PropagateBoxesResult
from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.services.task_policy import require_task
from app.application.ports.services.keypoint_matcher import IKeypointMatcher
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.annotation import Annotation
from app.domain.enums import ProjectTaskType
from app.domain.exceptions import (
    DomainValidationException,
    KeypointMatchingFailedException,
    ResourceNotFoundException,
)


class PropagateBoxViaKeypointsUseCase:
    def __init__(
        self,
        images: IImageRepository,
        classes: IClassRepository,
        annotations: IAnnotationRepository,
        storage: IFileStorage,
        matcher: IKeypointMatcher,
        uow: IUnitOfWork,
        projects: IProjectRepository | None = None,
    ) -> None:
        self._images = images
        self._classes = classes
        self._annotations = annotations
        self._storage = storage
        self._matcher = matcher
        self._uow = uow
        self._projects = projects

    async def execute(
        self,
        source_image_id: UUID,
        target_image_id: UUID,
        source_box: BoxInput,
    ) -> Annotation:
        result = await self.execute_many(
            source_image_id, target_image_id, [source_box]
        )
        return result.annotations[0]

    async def execute_many(
        self,
        source_image_id: UUID,
        target_image_id: UUID,
        source_boxes: list[BoxInput],
    ) -> PropagateBoxesResult:
        if source_image_id == target_image_id:
            raise DomainValidationException(
                "перенос возможен только на другой кадр"
            )
        if not source_boxes:
            raise DomainValidationException("нужна хотя бы одна рамка для переноса")

        source = await self._images.get_by_id(source_image_id)
        target = await self._images.get_by_id(target_image_id)
        if source is None:
            raise ResourceNotFoundException(f"image {source_image_id} not found")
        if target is None:
            raise ResourceNotFoundException(f"image {target_image_id} not found")
        if source.project_id != target.project_id:
            raise DomainValidationException(
                "source and target images must belong to the same project"
            )
        if self._projects is not None:
            project = await self._projects.get_by_id(target.project_id)
            if project is None:
                raise ResourceNotFoundException(
                    f"project {target.project_id} not found"
                )
            require_task(project, ProjectTaskType.DETECTION)

        project_classes = await self._classes.list_by_project(target.project_id)
        known_ids = {item.id for item in project_classes}

        source_annotations = await self._annotations.list_by_image(source.id)
        by_id = {item.id: item for item in source_annotations}

        donors: list[Annotation] = []
        for source_box in source_boxes:
            if source_box.annotation_id is None:
                raise DomainValidationException(
                    "source_box.id is required for keypoint propagation"
                )
            donor = by_id.get(source_box.annotation_id)
            if donor is None:
                raise ResourceNotFoundException(
                    f"annotation {source_box.annotation_id} not found on source image"
                )
            if donor.class_id not in known_ids:
                raise DomainValidationException(
                    f"class {donor.class_id} does not belong to this project"
                )
            donors.append(donor)

        match_result = await asyncio.to_thread(
            self._matcher.project_boxes,
            self._storage.get_absolute_path(source.file_path),
            self._storage.get_absolute_path(target.file_path),
            [donor.bbox for donor in donors],
            source.width,
            source.height,
            target.width,
            target.height,
        )

        created: list[Annotation] = []
        debug_arrows: list[DebugArrow] = []

        for donor, projected in zip(donors, match_result.boxes, strict=True):
            # Identity place on target (same normalized coords) → transformed place.
            from_x = donor.bbox.x_center * target.width
            from_y = donor.bbox.y_center * target.height
            if projected is None:
                debug_arrows.append(
                    DebugArrow(from_x=from_x, from_y=from_y, to_x=from_x, to_y=from_y)
                )
                continue
            to_x = projected.bbox.x_center * target.width
            to_y = projected.bbox.y_center * target.height
            debug_arrows.append(
                DebugArrow(from_x=from_x, from_y=from_y, to_x=to_x, to_y=to_y)
            )
            created.append(
                Annotation.create_from_keypoints(
                    image_id=target.id,
                    class_id=donor.class_id,
                    bbox=projected.bbox,
                    source_annotation_id=donor.id,
                    confidence=projected.match_score,
                )
            )

        if not created:
            raise KeypointMatchingFailedException(
                "Не удалось найти объект на этом кадре. Разметьте вручную"
            )

        existing = await self._annotations.list_by_image(target.id)
        merged = [*existing, *created]
        await self._annotations.replace_for_image(target.id, merged)
        target.recalculate_status(merged)
        await self._images.update(target)
        await self._uow.commit()
        return PropagateBoxesResult(
            annotations=created,
            transform=match_result.transform,
            debug_arrows=debug_arrows,
        )
