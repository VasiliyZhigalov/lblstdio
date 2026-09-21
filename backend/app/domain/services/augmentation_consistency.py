from __future__ import annotations

from collections.abc import Callable, Iterable

from app.application.ports.services.model_predictor import Detection


def _corners(det: Detection) -> tuple[float, float, float, float]:
    return (
        det.x_center - det.width / 2,
        det.y_center - det.height / 2,
        det.x_center + det.width / 2,
        det.y_center + det.height / 2,
    )


def box_iou(left: Detection, right: Detection) -> float:
    lx1, ly1, lx2, ly2 = _corners(left)
    rx1, ry1, rx2, ry2 = _corners(right)
    intersection = max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(
        0.0, min(ly2, ry2) - max(ly1, ry1)
    )
    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def transform_horizontal_flip(det: Detection) -> Detection:
    return Detection(
        class_index=det.class_index,
        confidence=det.confidence,
        x_center=1.0 - det.x_center,
        y_center=det.y_center,
        width=det.width,
        height=det.height,
    )


def transform_center_scale(det: Detection, scale: float = 1.08) -> Detection:
    return Detection(
        class_index=det.class_index,
        confidence=det.confidence,
        x_center=(det.x_center - 0.5) * scale + 0.5,
        y_center=(det.y_center - 0.5) * scale + 0.5,
        width=det.width * scale,
        height=det.height * scale,
    )


def _all_confident(detections: Iterable[Detection], threshold: float) -> bool:
    return all(item.confidence >= threshold for item in detections)


def detections_are_consistent(
    reference: list[Detection],
    transformed: list[Detection],
    *,
    confidence_threshold: float,
    iou_threshold: float,
    inverse_transform: Callable[[Detection], Detection] | None = None,
) -> bool:
    if not reference or len(reference) != len(transformed):
        return False
    if not _all_confident(reference, confidence_threshold):
        return False
    if not _all_confident(transformed, confidence_threshold):
        return False

    restored = [
        inverse_transform(item) if inverse_transform else item
        for item in transformed
    ]
    available = set(range(len(restored)))
    for expected in reference:
        candidates = [
            index
            for index in available
            if restored[index].class_index == expected.class_index
        ]
        if not candidates:
            return False
        best = max(candidates, key=lambda index: box_iou(expected, restored[index]))
        if box_iou(expected, restored[best]) < iou_threshold:
            return False
        available.remove(best)
    return not available


def all_runs_are_consistent(
    reference: list[Detection],
    runs: Iterable[tuple[list[Detection], Callable[[Detection], Detection] | None]],
    *,
    confidence_threshold: float,
    iou_threshold: float,
) -> bool:
    return all(
        detections_are_consistent(
            reference,
            detections,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            inverse_transform=inverse_transform,
        )
        for detections, inverse_transform in runs
    )
