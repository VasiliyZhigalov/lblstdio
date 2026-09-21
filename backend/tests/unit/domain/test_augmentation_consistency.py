import pytest

from app.application.ports.services.model_predictor import Detection
from app.domain.services.augmentation_consistency import (
    all_runs_are_consistent,
    box_iou,
    transform_center_scale,
    transform_horizontal_flip,
)


def _detection(
    x: float = 0.4,
    y: float = 0.5,
    width: float = 0.2,
    height: float = 0.3,
    confidence: float = 0.9,
    class_index: int = 0,
) -> Detection:
    return Detection(class_index, confidence, x, y, width, height)


def test_iou_is_one_for_same_box() -> None:
    assert box_iou(_detection(), _detection()) == pytest.approx(1.0)


def test_consistency_restores_flip_and_scale() -> None:
    original = [_detection()]
    flipped = [transform_horizontal_flip(original[0])]
    scaled = [transform_center_scale(original[0])]

    assert all_runs_are_consistent(
        original,
        (
            (flipped, transform_horizontal_flip),
            (scaled, lambda item: transform_center_scale(item, 1 / 1.08)),
        ),
        confidence_threshold=0.5,
        iou_threshold=0.8,
    )


@pytest.mark.parametrize(
    "other",
    [
        [],
        [_detection(class_index=1)],
        [_detection(x=0.1)],
        [_detection(confidence=0.4)],
    ],
)
def test_consistency_rejects_invalid_runs(other: list[Detection]) -> None:
    assert not all_runs_are_consistent(
        [_detection()],
        ((other, None),),
        confidence_threshold=0.5,
        iou_threshold=0.8,
    )
