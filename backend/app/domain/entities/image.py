from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.entities.annotation import Annotation
from app.domain.entities.image_label import ImageLabel
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
    is_background: bool = False

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
            is_background=False,
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
            self.is_background = False
            confirmed = any(
                item.verification_status
                in (VerificationStatus.VERIFIED, VerificationStatus.AUTO_VERIFIED)
                for item in active
            )
            self.status = (
                ImageStatus.REQUIRES_RECHECK if confirmed else ImageStatus.REQUIRES_REVIEW
            )
        elif not active:
            self.status = (
                ImageStatus.VERIFIED if self.is_background else ImageStatus.UNANNOTATED
            )
        else:
            self.is_background = False
            self.status = (
                ImageStatus.AUTO_VERIFIED
                if all(
                    item.verification_status == VerificationStatus.AUTO_VERIFIED
                    for item in active
                )
                else ImageStatus.VERIFIED
            )

    def recalculate_status_from_label(self, label: ImageLabel | None) -> None:
        if self.status == ImageStatus.REJECTED:
            return
        if label is None:
            self.status = ImageStatus.UNANNOTATED
            return
        if label.verification_status == VerificationStatus.PENDING_REVIEW:
            self.status = ImageStatus.REQUIRES_REVIEW
            return
        if label.verification_status == VerificationStatus.AUTO_VERIFIED:
            self.status = ImageStatus.AUTO_VERIFIED
            return
        self.status = ImageStatus.VERIFIED

    def set_test_holdout(self, holdout: bool) -> None:
        """Pin or unpin the image as a manual test frame excluded from training."""
        self.split = SplitType.TEST if holdout else SplitType.TRAIN

    def mark_as_background(self) -> None:
        """Confirm empty frame as a negative / background sample for the dataset."""
        if self.status == ImageStatus.REJECTED:
            raise DomainValidationException("rejected image cannot be marked as background")
        self.is_background = True
        self.status = ImageStatus.VERIFIED

    def clear_background(self) -> None:
        self.is_background = False
        if self.status == ImageStatus.VERIFIED:
            self.status = ImageStatus.UNANNOTATED

    def reject(self) -> None:
        self.status = ImageStatus.REJECTED
        self.is_background = False

    def can_be_included_in_export(self) -> bool:
        return self.status in (
            ImageStatus.UNANNOTATED,
            ImageStatus.VERIFIED,
            ImageStatus.AUTO_VERIFIED,
        )

    def can_be_included_in_dataset(self) -> bool:
        return self.status in (ImageStatus.VERIFIED, ImageStatus.AUTO_VERIFIED)
