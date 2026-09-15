from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.enums import AutoLabelJobStatus
from app.domain.exceptions import DomainValidationException


@dataclass
class AutoLabelJob:
    id: UUID
    project_id: UUID
    model_version_id: UUID
    confidence_threshold: float
    status: AutoLabelJobStatus
    image_ids: list[UUID]
    total_images_processed: int = 0
    total_predictions_generated: int = 0
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if not 0.01 <= self.confidence_threshold <= 0.95:
            raise DomainValidationException(
                "confidence_threshold must be in [0.01, 0.95]"
            )

    @classmethod
    def create(
        cls,
        project_id: UUID,
        model_version_id: UUID,
        image_ids: list[UUID],
        confidence_threshold: float = 0.05,
        job_id: UUID | None = None,
    ) -> AutoLabelJob:
        return cls(
            id=job_id or uuid4(),
            project_id=project_id,
            model_version_id=model_version_id,
            confidence_threshold=confidence_threshold,
            status=AutoLabelJobStatus.PENDING,
            image_ids=list(image_ids),
        )

    def mark_running(self) -> None:
        self.status = AutoLabelJobStatus.RUNNING

    def mark_completed(self, processed: int, predictions: int) -> None:
        self.status = AutoLabelJobStatus.COMPLETED
        self.total_images_processed = processed
        self.total_predictions_generated = predictions
        self.finished_at = datetime.now(UTC)

    def mark_failed(self, message: str) -> None:
        self.status = AutoLabelJobStatus.FAILED
        self.error_message = message
        self.finished_at = datetime.now(UTC)
