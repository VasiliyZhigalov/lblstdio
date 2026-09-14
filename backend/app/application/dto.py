from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.value_objects.bounding_box import BoundingBox


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


@dataclass(frozen=True)
class ProjectedBox:
    bbox: BoundingBox
    match_score: float


@dataclass(frozen=True)
class TransformDebug:
    """Similarity source→target for UI debug overlay."""

    tx: float
    ty: float
    rotation_deg: float
    scale: float
    match_score: float
    matrix: tuple[tuple[float, float, float], tuple[float, float, float]]


@dataclass(frozen=True)
class DebugArrow:
    """Pixel arrow on the target image: where box was (identity) → where it landed."""

    from_x: float
    from_y: float
    to_x: float
    to_y: float


@dataclass(frozen=True)
class ProjectBoxesResult:
    boxes: list[ProjectedBox | None]
    transform: TransformDebug


@dataclass(frozen=True)
class PropagateBoxesResult:
    annotations: list  # list[Annotation] — avoid circular import typing noise
    transform: TransformDebug
    debug_arrows: list[DebugArrow]
