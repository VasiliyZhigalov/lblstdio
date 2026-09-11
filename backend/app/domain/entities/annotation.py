from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.enums import SourceType, VerificationStatus
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.bounding_box import BoundingBox


@dataclass
class Annotation:
    id: UUID
    image_id: UUID
    class_id: UUID
    bbox: BoundingBox
    source: SourceType
    verification_status: VerificationStatus
    confidence: float
    verified_at: datetime | None = None
    model_version_id: UUID | None = None
    source_annotation_id: UUID | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise DomainValidationException("confidence must be in [0, 1]")
        if self.source == SourceType.MANUAL:
            if self.verification_status != VerificationStatus.VERIFIED:
                raise DomainValidationException(
                    "MANUAL annotations must have verification_status=VERIFIED"
                )
            if self.confidence != 1.0:
                raise DomainValidationException(
                    "MANUAL annotations must have confidence=1.0"
                )
        if (
            self.source
            in (SourceType.MODEL_PREDICTION, SourceType.KEYPOINT_PROPAGATION)
            and self.verification_status == VerificationStatus.PENDING_REVIEW
            and self.verified_at is not None
        ):
            raise DomainValidationException(
                "pending automatic annotations cannot have verified_at set"
            )

    @classmethod
    def create_manual(
        cls,
        image_id: UUID,
        class_id: UUID,
        bbox: BoundingBox,
        annotation_id: UUID | None = None,
    ) -> Annotation:
        now = datetime.now(UTC)
        return cls(
            id=annotation_id or uuid4(),
            image_id=image_id,
            class_id=class_id,
            bbox=bbox,
            source=SourceType.MANUAL,
            verification_status=VerificationStatus.VERIFIED,
            confidence=1.0,
            verified_at=now,
        )

    @classmethod
    def create_prediction(
        cls,
        image_id: UUID,
        class_id: UUID,
        bbox: BoundingBox,
        confidence: float,
        annotation_id: UUID | None = None,
        model_version_id: UUID | None = None,
    ) -> Annotation:
        return cls(
            id=annotation_id or uuid4(),
            image_id=image_id,
            class_id=class_id,
            bbox=bbox,
            source=SourceType.MODEL_PREDICTION,
            verification_status=VerificationStatus.PENDING_REVIEW,
            confidence=confidence,
            model_version_id=model_version_id,
        )

    @classmethod
    def create_from_keypoints(
        cls,
        image_id: UUID,
        class_id: UUID,
        bbox: BoundingBox,
        source_annotation_id: UUID,
        annotation_id: UUID | None = None,
        confidence: float = 1.0,
    ) -> Annotation:
        return cls(
            id=annotation_id or uuid4(),
            image_id=image_id,
            class_id=class_id,
            bbox=bbox,
            source=SourceType.KEYPOINT_PROPAGATION,
            verification_status=VerificationStatus.PENDING_REVIEW,
            confidence=confidence,
            source_annotation_id=source_annotation_id,
        )

    def verify(self, at: datetime | None = None) -> None:
        self.verification_status = VerificationStatus.VERIFIED
        self.verified_at = at or datetime.now(UTC)

    def reject(self) -> None:
        self.verification_status = VerificationStatus.REJECTED

    @property
    def is_exportable(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED
