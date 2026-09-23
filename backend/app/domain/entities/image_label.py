from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.enums import SourceType, VerificationStatus
from app.domain.exceptions import DomainValidationException


@dataclass
class ImageLabel:
    id: UUID
    image_id: UUID
    class_id: UUID
    source: SourceType
    verification_status: VerificationStatus
    confidence: float
    verified_at: datetime | None = None
    model_version_id: UUID | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise DomainValidationException("confidence must be in [0, 1]")
        if self.source == SourceType.MANUAL:
            if self.verification_status != VerificationStatus.VERIFIED:
                raise DomainValidationException(
                    "MANUAL labels must have verification_status=VERIFIED"
                )
            if self.confidence != 1.0:
                raise DomainValidationException("MANUAL labels must have confidence=1.0")
        if (
            self.source == SourceType.MODEL_PREDICTION
            and self.verified_at is not None
            and self.verification_status == VerificationStatus.PENDING_REVIEW
        ):
            raise DomainValidationException(
                "pending automatic labels cannot have verified_at set"
            )

    @classmethod
    def create_manual(
        cls,
        image_id: UUID,
        class_id: UUID,
        label_id: UUID | None = None,
    ) -> ImageLabel:
        now = datetime.now(UTC)
        return cls(
            id=label_id or uuid4(),
            image_id=image_id,
            class_id=class_id,
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
        confidence: float,
        label_id: UUID | None = None,
        model_version_id: UUID | None = None,
    ) -> ImageLabel:
        return cls(
            id=label_id or uuid4(),
            image_id=image_id,
            class_id=class_id,
            source=SourceType.MODEL_PREDICTION,
            verification_status=VerificationStatus.PENDING_REVIEW,
            confidence=confidence,
            model_version_id=model_version_id,
        )

    def confirm(self) -> None:
        now = datetime.now(UTC)
        if self.source == SourceType.MODEL_PREDICTION:
            self.verification_status = VerificationStatus.AUTO_VERIFIED
        else:
            self.verification_status = VerificationStatus.VERIFIED
        self.verified_at = now

    def assign_manual(self, class_id: UUID) -> None:
        self.class_id = class_id
        self.source = SourceType.MANUAL
        self.verification_status = VerificationStatus.VERIFIED
        self.confidence = 1.0
        self.verified_at = datetime.now(UTC)
        self.model_version_id = None
