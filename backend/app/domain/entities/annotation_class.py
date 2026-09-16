from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.domain.exceptions import DomainValidationException

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass
class AnnotationClass:
    id: UUID
    project_id: UUID
    name: str
    color_hex: str
    index_id: int

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise DomainValidationException("name must not be empty")
        if not _HEX_COLOR.match(self.color_hex):
            raise DomainValidationException(
                "color must be a HEX value in the form #RRGGBB"
            )
        if self.index_id < 0:
            raise DomainValidationException("index_id must be >= 0")

    @classmethod
    def create(
        cls,
        project_id: UUID,
        name: str,
        color_hex: str,
        index_id: int,
        class_id: UUID | None = None,
    ) -> AnnotationClass:
        return cls(
            id=class_id or uuid4(),
            project_id=project_id,
            name=name,
            color_hex=color_hex,
            index_id=index_id,
        )

    def rename(self, name: str) -> None:
        normalized = name.strip()
        if not normalized:
            raise DomainValidationException("name must not be empty")
        self.name = normalized
