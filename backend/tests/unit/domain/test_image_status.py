from uuid import uuid4

from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.enums import ImageSourceType, ImageStatus, SplitType
from app.domain.value_objects.bounding_box import BoundingBox


def _image() -> Image:
    return Image.create(
        project_id=uuid4(),
        file_path="projects/x/images/a.png",
        file_name="a.png",
        width=100,
        height=80,
        split=SplitType.TRAIN,
        source_type=ImageSourceType.MANUAL_UPLOAD,
    )


def _box() -> BoundingBox:
    return BoundingBox(x_center=0.5, y_center=0.5, width=0.2, height=0.1)


class TestImageStatusDerivation:
    def test_new_image_is_unannotated(self) -> None:
        image = _image()

        assert image.status == ImageStatus.UNANNOTATED
        assert image.can_be_included_in_export() is True

    def test_manual_boxes_make_image_verified(self) -> None:
        image = _image()
        annotations = [
            Annotation.create_manual(
                image_id=image.id, class_id=uuid4(), bbox=_box()
            )
        ]

        image.recalculate_status(annotations)

        assert image.status == ImageStatus.VERIFIED
        assert image.can_be_included_in_export() is True

    def test_pending_prediction_blocks_export(self) -> None:
        image = _image()
        annotations = [
            Annotation.create_prediction(
                image_id=image.id,
                class_id=uuid4(),
                bbox=_box(),
                confidence=0.8,
            )
        ]

        image.recalculate_status(annotations)

        assert image.status == ImageStatus.REQUIRES_REVIEW
        assert image.can_be_included_in_export() is False

    def test_rejected_image_is_excluded_from_export(self) -> None:
        image = _image()
        image.reject()

        assert image.status == ImageStatus.REJECTED
        assert image.can_be_included_in_export() is False
