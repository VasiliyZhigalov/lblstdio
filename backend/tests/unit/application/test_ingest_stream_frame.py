from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.application.ports.services.model_predictor import Detection
from app.application.use_cases.streaming.ingest_stream_frame import IngestStreamFrameUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import (
    ImageSourceType,
    ImageStatus,
    SourceType,
    StreamSourceType,
    VerificationStatus,
)


class _FakeStreams:
    def __init__(self, stream: StreamSource) -> None:
        self.stream = stream

    async def get_by_id(self, stream_id: UUID) -> StreamSource | None:
        return self.stream if self.stream.id == stream_id else None

    async def update(self, stream: StreamSource) -> None:
        self.stream = stream


class _FakeImages:
    def __init__(self) -> None:
        self.by_id: dict[UUID, Image] = {}

    async def add_many(self, images: list[Image]) -> None:
        for image in images:
            self.by_id[image.id] = image

    async def update(self, image: Image) -> None:
        self.by_id[image.id] = image


class _FakeAnnotations:
    def __init__(self) -> None:
        self.store: dict[UUID, list[Annotation]] = {}

    async def replace_for_image(self, image_id: UUID, annotations: list[Annotation]) -> None:
        self.store[image_id] = list(annotations)


class _FakeClasses:
    def __init__(self, items: list[AnnotationClass]) -> None:
        self.items = items

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        return [item for item in self.items if item.project_id == project_id]


class _FakeStorage:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, bytes]] = []
        self.deleted: list[str] = []

    async def save(self, relative_dir: str, filename: str, data: bytes) -> str:
        path = f"{relative_dir}/{filename}"
        self.saved.append((relative_dir, filename, data))
        return path

    async def delete(self, relative_path: str) -> None:
        self.deleted.append(relative_path)


class _FakeMetadata:
    def read_size(self, data: bytes) -> tuple[int, int]:
        return (640, 480)


class _FakeUow:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ingest_creates_hitl_image_and_predictions() -> None:
    project_id = uuid4()
    stream = StreamSource.create(
        project_id=project_id,
        name="Cam",
        source_type=StreamSourceType.RTSP,
        source_uri="rtsp://x",
    )
    stream.set_model(uuid4())
    annotation_class = AnnotationClass.create(project_id, "car", "#00FF00", 0)
    streams = _FakeStreams(stream)
    images = _FakeImages()
    annotations = _FakeAnnotations()
    storage = _FakeStorage()
    uow = _FakeUow()

    use_case = IngestStreamFrameUseCase(
        streams=streams,
        images=images,
        annotations=annotations,
        classes=_FakeClasses([annotation_class]),
        storage=storage,
        metadata=_FakeMetadata(),
        uow=uow,
    )

    jpeg = b"fake-jpeg"
    detections = [
        Detection(0, 0.77, 0.5, 0.4, 0.2, 0.15),
        Detection(99, 0.9, 0.3, 0.3, 0.1, 0.1),  # unknown class index -> skip
    ]
    image = await use_case.execute(stream.id, jpeg, detections, reason="timer")

    assert storage.saved
    assert storage.saved[0][0] == f"projects/{project_id}/images"
    assert storage.saved[0][1].endswith(".jpg")
    assert image.source_type == ImageSourceType.STREAM_INGEST
    assert image.status == ImageStatus.REQUIRES_REVIEW
    assert image.stream_source_id == stream.id
    boxes = annotations.store[image.id]
    assert len(boxes) == 1
    assert boxes[0].source == SourceType.MODEL_PREDICTION
    assert boxes[0].verification_status == VerificationStatus.PENDING_REVIEW
    assert boxes[0].confidence == pytest.approx(0.77)
    assert boxes[0].model_version_id == stream.model_version_id
    assert streams.stream.captured_frames_count == 1
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_timer_ingest_without_detections_is_unannotated() -> None:
    project_id = uuid4()
    stream = StreamSource.create(
        project_id=project_id,
        name="Cam",
        source_type=StreamSourceType.RTSP,
        source_uri="rtsp://x",
    )
    streams = _FakeStreams(stream)
    images = _FakeImages()
    annotations = _FakeAnnotations()
    use_case = IngestStreamFrameUseCase(
        streams=streams,
        images=images,
        annotations=annotations,
        classes=_FakeClasses([]),
        storage=_FakeStorage(),
        metadata=_FakeMetadata(),
        uow=_FakeUow(),
    )

    image = await use_case.execute(stream.id, b"fake-jpeg", [], reason="timer")

    assert image.status == ImageStatus.UNANNOTATED
    assert annotations.store[image.id] == []
