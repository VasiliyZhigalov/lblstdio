from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.entities.annotation import Annotation
from app.domain.enums import ImageSourceType, ImageStatus, SplitType, VerificationStatus
from app.domain.exceptions import DomainValidationException


@dataclass
class Image:
    id: UUID
    project_id: UUID
    file_path: str
    file_name: str
    width: int
    height: int
    split: SplitType
    source_type: ImageSourceType
    status: ImageStatus
    created_at: datetime
    stream_source_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise DomainValidationException("image dimensions must be positive")
        if not self.file_name.strip():
            raise DomainValidationException("file_name must not be empty")

    @classmethod
    def create(
        cls,
        project_id: UUID,
        file_path: str,
        file_name: str,
        width: int,
        height: int,
        split: SplitType,
        source_type: ImageSourceType = ImageSourceType.MANUAL_UPLOAD,
        image_id: UUID | None = None,
        stream_source_id: UUID | None = None,
    ) -> Image:
        return cls(
            id=image_id or uuid4(),
            project_id=project_id,
            file_path=file_path,
            file_name=file_name,
            width=width,
            height=height,
            split=split,
            source_type=source_type,
            status=ImageStatus.UNANNOTATED,
            created_at=datetime.now(UTC),
            stream_source_id=stream_source_id,
        )

    def recalculate_status(self, annotations: Sequence[Annotation]) -> None:
        if self.status == ImageStatus.REJECTED:
            return
        active = [
            item
            for item in annotations
            if item.verification_status != VerificationStatus.REJECTED
        ]
        if any(
            item.verification_status == VerificationStatus.PENDING_REVIEW
            for item in active
        ):
            self.status = ImageStatus.REQUIRES_REVIEW
        elif not active:
            self.status = ImageStatus.UNANNOTATED
        else:
            self.status = ImageStatus.VERIFIED

    def reject(self) -> None:
        self.status = ImageStatus.REJECTED

    def can_be_included_in_export(self) -> bool:
        return self.status in (ImageStatus.UNANNOTATED, ImageStatus.VERIFIED)

    def can_be_included_in_dataset(self) -> bool:
        return self.status == ImageStatus.VERIFIED
