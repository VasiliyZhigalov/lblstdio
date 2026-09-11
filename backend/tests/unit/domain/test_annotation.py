from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.entities.annotation import Annotation
from app.domain.enums import SourceType, VerificationStatus
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.bounding_box import BoundingBox


def _box() -> BoundingBox:
    return BoundingBox(x_center=0.5, y_center=0.5, width=0.2, height=0.1)


class TestManualAnnotationNormalization:
    def test_manual_box_is_verified_with_full_confidence(self) -> None:
        annotation = Annotation.create_manual(
            image_id=uuid4(),
            class_id=uuid4(),
            bbox=_box(),
        )

        assert annotation.source == SourceType.MANUAL
        assert annotation.verification_status == VerificationStatus.VERIFIED
        assert annotation.confidence == 1.0
        assert annotation.verified_at is not None
        assert annotation.verified_at.tzinfo is not None

    def test_manual_source_cannot_be_pending_review(self) -> None:
        with pytest.raises(DomainValidationException, match="MANUAL"):
            Annotation(
                id=uuid4(),
                image_id=uuid4(),
                class_id=uuid4(),
                bbox=_box(),
                source=SourceType.MANUAL,
                verification_status=VerificationStatus.PENDING_REVIEW,
                confidence=1.0,
            )

    def test_automatic_source_starts_as_pending_review(self) -> None:
        annotation = Annotation.create_prediction(
            image_id=uuid4(),
            class_id=uuid4(),
            bbox=_box(),
            confidence=0.84,
        )

        assert annotation.source == SourceType.MODEL_PREDICTION
        assert annotation.verification_status == VerificationStatus.PENDING_REVIEW
        assert annotation.confidence == 0.84
        assert annotation.verified_at is None

    def test_verify_transitions_pending_to_verified(self) -> None:
        annotation = Annotation.create_prediction(
            image_id=uuid4(),
            class_id=uuid4(),
            bbox=_box(),
            confidence=0.7,
        )
        moment = datetime(2026, 9, 11, tzinfo=UTC)

        annotation.verify(at=moment)

        assert annotation.verification_status == VerificationStatus.VERIFIED
        assert annotation.verified_at == moment
