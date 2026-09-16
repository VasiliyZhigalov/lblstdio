from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.ports.services.model_predictor import Detection
from app.domain.entities.stream_source import StreamSource
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig


@dataclass
class StreamStatus:
    is_running: bool
    state: str
    fps: float = 0.0
    captured_count: int = 0
    last_capture_at: datetime | None = None
    error_message: str | None = None


@dataclass
class IngestJob:
    stream_id: UUID
    jpeg_bytes: bytes
    detections: list[Detection]
    reason: str
    captured_at: float


class IStreamRunner(Protocol):
    def start(
        self,
        stream: StreamSource,
        weights_abs_path: str,
        *,
        allowed_class_indices: frozenset[int] | None = None,
    ) -> None: ...

    def wait_until_ready(self, stream_id: UUID, timeout: float = 30.0) -> StreamStatus: ...

    def update_triggers(
        self,
        stream_id: UUID,
        config: StreamTriggerConfig,
        *,
        allowed_class_indices: frozenset[int] | None = None,
    ) -> None: ...

    def stop(self, stream_id: UUID) -> None: ...

    def stop_project(self, project_id: UUID) -> None: ...

    def stop_all(self) -> None: ...

    def get_status(self, stream_id: UUID) -> StreamStatus: ...

    def latest_jpeg(self, stream_id: UUID) -> bytes | None: ...

    def ack_ingest(
        self, stream_id: UUID, *, success: bool, captured_at: float
    ) -> None: ...

    def push_ingest_for_tests(self, job: IngestJob) -> None: ...
