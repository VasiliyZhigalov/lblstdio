from uuid import uuid4

import pytest

from app.domain.entities.dataset_version import (
    SnapshotClassLabel,
    snapshot_entry_from_dict,
)
from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.enums import (
    ImageSourceType,
    ImageStatus,
    SourceType,
    SplitType,
    VerificationStatus,
)
from app.domain.exceptions import DomainValidationException


def _image() -> Image:
    return Image.create(
        project_id=uuid4(),
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
        source_type=ImageSourceType.MANUAL_UPLOAD,
    )


def test_manual_label_verifies_image() -> None:
    image = _image()
    label = ImageLabel.create_manual(image.id, uuid4())
    image.recalculate_status_from_label(label)
    assert label.source == SourceType.MANUAL
    assert label.verification_status == VerificationStatus.VERIFIED
    assert label.confidence == 1.0
    assert image.status == ImageStatus.VERIFIED


def test_prediction_requires_review() -> None:
    image = _image()
    label = ImageLabel.create_prediction(image.id, uuid4(), 0.91)
    image.recalculate_status_from_label(label)
    assert image.status == ImageStatus.REQUIRES_REVIEW
    assert image.can_be_included_in_dataset() is False


def test_confirm_prediction_auto_verifies() -> None:
    image = _image()
    label = ImageLabel.create_prediction(image.id, uuid4(), 0.91)
    label.confirm()
    image.recalculate_status_from_label(label)
    assert label.verification_status == VerificationStatus.AUTO_VERIFIED
    assert image.status == ImageStatus.AUTO_VERIFIED


def test_assign_manual_after_prediction() -> None:
    label = ImageLabel.create_prediction(uuid4(), uuid4(), 0.4)
    new_class = uuid4()
    label.assign_manual(new_class)
    assert label.class_id == new_class
    assert label.source == SourceType.MANUAL
    assert label.verification_status == VerificationStatus.VERIFIED
    assert label.confidence == 1.0


def test_clear_label_unannotates() -> None:
    image = _image()
    image.recalculate_status_from_label(ImageLabel.create_manual(image.id, uuid4()))
    image.recalculate_status_from_label(None)
    assert image.status == ImageStatus.UNANNOTATED


def test_prediction_confidence_range() -> None:
    with pytest.raises(DomainValidationException, match="confidence"):
        ImageLabel.create_prediction(uuid4(), uuid4(), 1.2)


def test_snapshot_class_label_roundtrip() -> None:
    cid = uuid4()
    raw = SnapshotClassLabel(class_id=cid, class_index=2).to_dict()
    assert "x_center" not in raw
    restored = snapshot_entry_from_dict(raw)
    assert isinstance(restored, SnapshotClassLabel)
    assert restored.class_index == 2
    assert restored.class_id == cid


def test_snapshot_annotation_still_parsed_when_bbox_present() -> None:
    from app.domain.entities.dataset_version import SnapshotAnnotation

    cid = uuid4()
    raw = SnapshotAnnotation(
        class_id=cid,
        class_index=1,
        x_center=0.5,
        y_center=0.5,
        width=0.2,
        height=0.1,
    ).to_dict()
    restored = snapshot_entry_from_dict(raw)
    assert isinstance(restored, SnapshotAnnotation)
