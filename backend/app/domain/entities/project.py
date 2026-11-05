from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.enums import ProjectTaskType
from app.domain.exceptions import DomainValidationException

_UNSET = object()


@dataclass
class Project:
    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    task_type: ProjectTaskType = ProjectTaskType.DETECTION

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise DomainValidationException("project name must not be empty")

    @classmethod
    def create(
        cls,
        name: str,
        description: str | None = None,
        project_id: UUID | None = None,
        task_type: ProjectTaskType = ProjectTaskType.DETECTION,
    ) -> Project:
        now = datetime.now(UTC)
        return cls(
            id=project_id or uuid4(),
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
            task_type=task_type,
        )

    def rename(
        self,
        name: str,
        description: str | None | object = _UNSET,
    ) -> None:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise DomainValidationException("project name must not be empty")
        if description is _UNSET:
            cleaned_description = self.description
        elif description is None or not str(description).strip():
            cleaned_description = None
        else:
            cleaned_description = str(description).strip()
        self.name = cleaned_name
        self.description = cleaned_description
        self.updated_at = datetime.now(UTC)
