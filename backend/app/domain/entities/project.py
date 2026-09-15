from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.exceptions import DomainValidationException


@dataclass
class Project:
    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

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
    ) -> Project:
        now = datetime.now(UTC)
        return cls(
            id=project_id or uuid4(),
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
        )

    def rename(self, name: str, description: str | None = None) -> None:
        self.name = name.strip()
        if not self.name:
            raise DomainValidationException("project name must not be empty")
        if description is None or not str(description).strip():
            self.description = None
        else:
            self.description = str(description).strip()
        self.updated_at = datetime.now(UTC)
