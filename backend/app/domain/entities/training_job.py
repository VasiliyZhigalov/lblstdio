from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.domain.enums import TrainingJobStatus
from app.domain.exceptions import DomainValidationException


@dataclass
class TrainingJob:
    id: UUID
    project_id: UUID
    dataset_version_id: UUID
    status: TrainingJobStatus
    epochs: int
    batch_size: int
    imgsz: int
    device: str
    base_weights: str
    patience: int = 20
    metrics_history: list[dict[str, Any]] = field(default_factory=list)
    current_epoch: int = 0
    stopped_early: bool = False
    model_version_id: UUID | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.epochs < 1:
            raise DomainValidationException("epochs must be >= 1")
        if self.batch_size < 1:
            raise DomainValidationException("batch_size must be >= 1")
        if self.imgsz < 32:
            raise DomainValidationException("imgsz must be >= 32")
        if self.patience < 0:
            raise DomainValidationException("patience must be >= 0")

    @classmethod
    def create(
        cls,
        project_id: UUID,
        dataset_version_id: UUID,
        *,
        epochs: int = 100,
        batch_size: int = 16,
        imgsz: int = 640,
        device: str = "auto",
        base_weights: str = "yolov8n.pt",
        patience: int = 20,
        job_id: UUID | None = None,
    ) -> TrainingJob:
        return cls(
            id=job_id or uuid4(),
            project_id=project_id,
            dataset_version_id=dataset_version_id,
            status=TrainingJobStatus.QUEUED,
            epochs=epochs,
            batch_size=batch_size,
            imgsz=imgsz,
            device=device,
            base_weights=base_weights,
            patience=patience,
        )

    def mark_running(self) -> None:
        self.status = TrainingJobStatus.RUNNING
        self.started_at = datetime.now(UTC)
        self.error_message = None

    def append_epoch_metrics(self, metrics: dict[str, Any]) -> None:
        self.metrics_history.append(metrics)
        epoch = int(metrics.get("epoch", len(self.metrics_history)))
        self.current_epoch = epoch

    def mark_completed(
        self, model_version_id: UUID, *, stopped_early: bool = False
    ) -> None:
        self.status = TrainingJobStatus.COMPLETED
        self.model_version_id = model_version_id
        self.finished_at = datetime.now(UTC)
        self.stopped_early = stopped_early

    def mark_failed(self, message: str) -> None:
        self.status = TrainingJobStatus.FAILED
        self.error_message = message
        self.finished_at = datetime.now(UTC)

    @property
    def progress_percent(self) -> float:
        if self.status == TrainingJobStatus.COMPLETED:
            return 100.0
        if self.epochs <= 0:
            return 0.0
        return min(100.0, round(100.0 * self.current_epoch / self.epochs, 1))
