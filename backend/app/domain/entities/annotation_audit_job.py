from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.enums import AnnotationAuditJobStatus
from app.domain.exceptions import DomainValidationException


@dataclass
class AnnotationAuditJob:
    id: UUID
    project_id: UUID
    model_version_id: UUID
    image_ids: list[UUID]
    confidence_threshold: float
    iou_threshold: float
    status: AnnotationAuditJobStatus = AnnotationAuditJobStatus.PENDING
    total_images: int = 0
    processed_images: int = 0
    suspicious_images: int = 0
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if not 0.01 <= self.confidence_threshold <= 0.99:
            raise DomainValidationException("confidence_threshold must be in [0.01, 0.99]")
        if not 0.01 <= self.iou_threshold <= 0.99:
            raise DomainValidationException("iou_threshold must be in [0.01, 0.99]")

    @classmethod
    def create(
        cls,
        project_id: UUID,
        model_version_id: UUID,
        image_ids: list[UUID],
        confidence_threshold: float,
        iou_threshold: float,
    ) -> AnnotationAuditJob:
        return cls(
            id=uuid4(),
            project_id=project_id,
            model_version_id=model_version_id,
            image_ids=list(image_ids),
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
        )

    def mark_running(self) -> None:
        self.status = AnnotationAuditJobStatus.RUNNING

    def mark_completed(self, processed: int, suspicious: int) -> None:
        self.status = AnnotationAuditJobStatus.COMPLETED
        self.total_images = processed
        self.processed_images = processed
        self.suspicious_images = suspicious
        self.finished_at = datetime.now(UTC)

    def mark_failed(self, message: str) -> None:
        self.status = AnnotationAuditJobStatus.FAILED
        self.error_message = message
        self.finished_at = datetime.now(UTC)
