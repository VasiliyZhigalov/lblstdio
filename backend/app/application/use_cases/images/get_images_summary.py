from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.image_label_repository import IImageLabelRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.domain.entities.annotation import Annotation
from app.domain.enums import ImageStatus


@dataclass(frozen=True)
class ImageAnnotationSummary:
    image_id: UUID
    box_count: int
    class_ids: list[UUID]
    annotations: list[Annotation]


@dataclass(frozen=True)
class ImagesSummary:
    class_counts: dict[UUID, int]
    label_counts: dict[UUID, int]
    images: list[ImageAnnotationSummary]


class GetImagesSummaryUseCase:
    def __init__(
        self,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        labels: IImageLabelRepository,
    ) -> None:
        self._images = images
        self._annotations = annotations
        self._labels = labels

    async def execute(self, project_id: UUID) -> ImagesSummary:
        images = await self._images.list_by_project(project_id)
        annotated = [item for item in images if item.status != ImageStatus.UNANNOTATED]
        boxes = await self._annotations.list_by_image_ids([item.id for item in annotated])
        labels = await self._labels.list_by_image_ids([item.id for item in images])

        by_image: dict[UUID, list[Annotation]] = defaultdict(list)
        class_counts: dict[UUID, int] = defaultdict(int)
        for box in boxes:
            by_image[box.image_id].append(box)
            class_counts[box.class_id] += 1

        label_counts: dict[UUID, int] = defaultdict(int)
        for label in labels:
            label_counts[label.class_id] += 1

        summaries = [
            ImageAnnotationSummary(
                image_id=image.id,
                box_count=len(by_image[image.id]),
                class_ids=list(
                    dict.fromkeys(
                        box.class_id for box in by_image[image.id] if box.class_id
                    )
                ),
                annotations=by_image[image.id],
            )
            for image in annotated
        ]
        return ImagesSummary(
            class_counts=dict(class_counts),
            label_counts=dict(label_counts),
            images=summaries,
        )
