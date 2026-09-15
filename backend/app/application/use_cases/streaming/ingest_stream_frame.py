from __future__ import annotations

from uuid import UUID, uuid4

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.stream_source_repository import (
    IStreamSourceRepository,
)
from app.application.ports.services.image_metadata import IImageMetadataReader
from app.application.ports.services.model_predictor import Detection
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.application.use_cases.ml.batch_auto_label import bbox_from_detection
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.enums import ImageSourceType, SplitType
from app.domain.exceptions import ResourceNotFoundException


class IngestStreamFrameUseCase:
    """Persist a clean stream frame with MODEL_PREDICTION annotations for HITL review."""

    def __init__(
        self,
        streams: IStreamSourceRepository,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        classes: IClassRepository,
        storage: IFileStorage,
        metadata: IImageMetadataReader,
        uow: IUnitOfWork,
    ) -> None:
        self._streams = streams
        self._images = images
        self._annotations = annotations
        self._classes = classes
        self._storage = storage
        self._metadata = metadata
        self._uow = uow

    async def execute(
        self,
        stream_id: UUID,
        jpeg_bytes: bytes,
        detections: list[Detection],
        reason: str = "timer",
    ) -> Image:
        stream = await self._streams.get_by_id(stream_id)
        if stream is None:
            raise ResourceNotFoundException(f"stream source {stream_id} not found")

        width, height = self._metadata.read_size(jpeg_bytes)
        image_id = uuid4()
        filename = f"{image_id}.jpg"
        relative_dir = f"projects/{stream.project_id}/images"
        relative_path: str | None = None
        try:
            relative_path = await self._storage.save(relative_dir, filename, jpeg_bytes)
            image = Image.create(
                project_id=stream.project_id,
                file_path=relative_path,
                file_name=filename,
                width=width,
                height=height,
                split=SplitType.TRAIN,
                source_type=ImageSourceType.STREAM_INGEST,
                image_id=image_id,
                stream_source_id=stream.id,
            )

            project_classes = await self._classes.list_by_project(stream.project_id)
            class_by_index = {item.index_id: item for item in project_classes}
            annotations: list[Annotation] = []
            for det in detections:
                cls = class_by_index.get(det.class_index)
                if cls is None:
                    continue
                bbox = bbox_from_detection(det)
                if bbox is None:
                    continue
                annotations.append(
                    Annotation.create_prediction(
                        image_id=image.id,
                        class_id=cls.id,
                        bbox=bbox,
                        confidence=det.confidence,
                        model_version_id=stream.model_version_id,
                    )
                )

            image.recalculate_status(annotations)
            await self._images.add_many([image])
            await self._annotations.replace_for_image(image.id, annotations)
            stream.increment_captured()
            await self._streams.update(stream)
            await self._uow.commit()
            return image
        except Exception:
            if relative_path is not None:
                await self._storage.delete(relative_path)
            raise
