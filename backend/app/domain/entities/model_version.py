from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.exceptions import DomainValidationException


@dataclass
class ModelVersion:
    id: UUID
    project_id: UUID
    dataset_version_id: UUID
    training_job_id: UUID
    version_number: int
    weights_path: str
    map50: float | None
    map50_95: float | None
    precision: float | None
    recall: float | None
    name: str = ""
    is_active_for_stream: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.version_number < 1:
            raise DomainValidationException("version_number must be >= 1")
        if not self.weights_path.strip():
            raise DomainValidationException("weights_path must not be empty")
        if not self.name.strip():
            object.__setattr__(self, "name", f"Model v{self.version_number}")

    @classmethod
    def create(
        cls,
        project_id: UUID,
        dataset_version_id: UUID,
        training_job_id: UUID,
        version_number: int,
        weights_path: str,
        *,
        map50: float | None = None,
        map50_95: float | None = None,
        precision: float | None = None,
        recall: float | None = None,
        name: str | None = None,
        model_id: UUID | None = None,
    ) -> ModelVersion:
        return cls(
            id=model_id or uuid4(),
            project_id=project_id,
            dataset_version_id=dataset_version_id,
            training_job_id=training_job_id,
            version_number=version_number,
            weights_path=weights_path,
            map50=map50,
            map50_95=map50_95,
            precision=precision,
            recall=recall,
            name=(name or f"Model v{version_number}").strip(),
            is_active_for_stream=True,
        )

    def rename(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise DomainValidationException("model name must not be empty")
        self.name = cleaned

    @property
    def display_name(self) -> str:
        score = f" (mAP {self.map50 * 100:.0f}%)" if self.map50 is not None else ""
        return f"{self.name}{score}"
