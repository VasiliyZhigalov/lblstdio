from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.enums import StreamSourceType
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig


@dataclass
class StreamSource:
    id: UUID
    project_id: UUID
    name: str
    source_type: StreamSourceType
    source_uri: str
    is_active: bool
    model_version_id: UUID | None
    config: StreamTriggerConfig
    captured_frames_count: int
    created_at: datetime

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.source_uri = self.source_uri.strip()
        if not self.name:
            raise DomainValidationException("stream name must not be empty")
        if not self.source_uri:
            raise DomainValidationException("source_uri must not be empty")
        if self.captured_frames_count < 0:
            raise DomainValidationException("captured_frames_count must be >= 0")

    @classmethod
    def create(
        cls,
        project_id: UUID,
        name: str,
        source_type: StreamSourceType,
        source_uri: str,
        *,
        stream_id: UUID | None = None,
        model_version_id: UUID | None = None,
        config: StreamTriggerConfig | None = None,
    ) -> StreamSource:
        return cls(
            id=stream_id or uuid4(),
            project_id=project_id,
            name=name,
            source_type=source_type,
            source_uri=source_uri,
            is_active=False,
            model_version_id=model_version_id,
            config=config or StreamTriggerConfig(),
            captured_frames_count=0,
            created_at=datetime.now(UTC),
        )

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    def update_config(self, config: StreamTriggerConfig) -> None:
        self.config = config

    def set_model(self, model_version_id: UUID | None) -> None:
        self.model_version_id = model_version_id

    def increment_captured(self) -> None:
        self.captured_frames_count += 1
