from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.domain.enums import DatasetVersionStatus, SplitType
from app.domain.exceptions import DomainValidationException

DEFAULT_MIN_VERIFIED_IMAGES = 10


@dataclass(frozen=True)
class AugmentationConfig:
    resize_width: int = 640
    resize_height: int = 640
    horizontal_flip: bool = True
    vertical_flip: bool = False
    rotate: bool = True
    shear: bool = True
    hue_saturation: bool = True
    brightness_contrast: bool = True
    blur: bool = False
    noise: bool = False
    grayscale: bool = False
    cutout: bool = False
    # Deprecated: kept for older snapshots; prefer rotate/shear.
    shift_scale_rotate: bool = False
    multiplier: int = 3

    def __post_init__(self) -> None:
        if self.resize_width <= 0 or self.resize_height <= 0:
            raise DomainValidationException("resize dimensions must be positive")
        if not 1 <= self.multiplier <= 5:
            raise DomainValidationException("multiplier must be in [1, 5]")

    @property
    def effective_rotate(self) -> bool:
        return self.rotate or self.shift_scale_rotate

    @property
    def effective_shear(self) -> bool:
        return self.shear or self.shift_scale_rotate


@dataclass(frozen=True)
class SnapshotAnnotation:
    class_id: UUID
    class_index: int
    x_center: float
    y_center: float
    width: float
    height: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_id": str(self.class_id),
            "class_index": self.class_index,
            "x_center": self.x_center,
            "y_center": self.y_center,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SnapshotAnnotation:
        return cls(
            class_id=UUID(str(raw["class_id"])),
            class_index=int(raw["class_index"]),
            x_center=float(raw["x_center"]),
            y_center=float(raw["y_center"]),
            width=float(raw["width"]),
            height=float(raw["height"]),
        )


@dataclass
class DatasetItem:
    id: UUID
    dataset_version_id: UUID
    image_id: UUID
    split: SplitType
    snapshot_annotations: list[SnapshotAnnotation]
    source_file_name: str

    def snapshot_as_dicts(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.snapshot_annotations]


@dataclass
class DatasetVersion:
    id: UUID
    project_id: UUID
    version_number: int
    name: str
    status: DatasetVersionStatus
    train_count: int
    valid_count: int
    test_count: int
    train_file_count: int
    valid_file_count: int
    test_file_count: int
    yaml_path: str
    created_at: datetime
    augmentation: AugmentationConfig
    items: list[DatasetItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.version_number < 1:
            raise DomainValidationException("version_number must be >= 1")
        if not self.name.strip():
            raise DomainValidationException("version name must not be empty")

    @classmethod
    def create(
        cls,
        project_id: UUID,
        version_number: int,
        name: str | None = None,
        augmentation: AugmentationConfig | None = None,
        version_id: UUID | None = None,
    ) -> DatasetVersion:
        number = version_number
        return cls(
            id=version_id or uuid4(),
            project_id=project_id,
            version_number=number,
            name=(name or f"v{number}").strip(),
            status=DatasetVersionStatus.PREPARING,
            train_count=0,
            valid_count=0,
            test_count=0,
            train_file_count=0,
            valid_file_count=0,
            test_file_count=0,
            yaml_path="",
            created_at=datetime.now(UTC),
            augmentation=augmentation or AugmentationConfig(),
            items=[],
        )

    def mark_ready(
        self,
        *,
        train_count: int,
        valid_count: int,
        test_count: int,
        train_file_count: int,
        valid_file_count: int,
        test_file_count: int,
        yaml_path: str,
        items: list[DatasetItem],
    ) -> None:
        self.train_count = train_count
        self.valid_count = valid_count
        self.test_count = test_count
        self.train_file_count = train_file_count
        self.valid_file_count = valid_file_count
        self.test_file_count = test_file_count
        self.yaml_path = yaml_path
        self.items = list(items)
        self.status = DatasetVersionStatus.READY

    def mark_failed(self) -> None:
        self.status = DatasetVersionStatus.FAILED

    def rename(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise DomainValidationException("version name must not be empty")
        self.name = cleaned
