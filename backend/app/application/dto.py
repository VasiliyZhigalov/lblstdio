from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    content: bytes


@dataclass(frozen=True)
class BoxInput:
    class_id: UUID
    x_center: float
    y_center: float
    width: float
    height: float
    annotation_id: UUID | None = None
