from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.application.ports.services.model_predictor import Detection
from app.domain.entities.annotation import Annotation
from app.domain.enums import VerificationStatus
from app.domain.value_objects.bounding_box import BoundingBox


@dataclass(frozen=True)
class AuditResult:
    image_id: UUID
    suspicious: bool
    reasons: tuple[str, ...]
    annotation_count: int
    prediction_count: int
    minimum_iou: float | None
    minimum_confidence: float | None


def _iou(left: BoundingBox, right: Detection) -> float:
    left_x1 = left.x_center - left.width / 2
    left_y1 = left.y_center - left.height / 2
    left_x2 = left.x_center + left.width / 2
    left_y2 = left.y_center + left.height / 2
    right_x1 = right.x_center - right.width / 2
    right_y1 = right.y_center - right.height / 2
    right_x2 = right.x_center + right.width / 2
    right_y2 = right.y_center + right.height / 2
    intersection = max(0.0, min(left_x2, right_x2) - max(left_x1, right_x1)) * max(
        0.0, min(left_y2, right_y2) - max(left_y1, right_y1)
    )
    left_area = left.width * left.height
    right_area = right.width * right.height
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def audit_annotations(
    annotations: list[Annotation],
    predictions: list[Detection],
    *,
    confidence_threshold: float,
    iou_threshold: float,
    class_indices: dict[UUID, int],
    image_id: UUID,
) -> AuditResult:
    reasons: list[str] = []
    active = [
        item
        for item in annotations
        if item.verification_status != VerificationStatus.REJECTED
    ]
    expected = [
        item
        for item in active
        if item.class_id in class_indices
    ]
    available = set(range(len(predictions)))
    matched_ious: list[float] = []

    for annotation in expected:
        class_index = class_indices[annotation.class_id]
        candidates = [
            index
            for index in available
            if predictions[index].class_index == class_index
        ]
        if not candidates:
            reasons.append("missing_prediction")
            continue
        best = max(
            candidates,
            key=lambda index: _iou(annotation.bbox, predictions[index]),
        )
        score = _iou(annotation.bbox, predictions[best])
        available.remove(best)
        matched_ious.append(score)
        if score < iou_threshold:
            reasons.append("low_iou")

    if available:
        reasons.append("extra_prediction")
    low_confidence = [
        item.confidence for item in predictions if item.confidence < confidence_threshold
    ]
    if low_confidence:
        reasons.append("low_confidence")

    return AuditResult(
        image_id=image_id,
        suspicious=bool(reasons),
        reasons=tuple(dict.fromkeys(reasons)),
        annotation_count=len(expected),
        prediction_count=len(predictions),
        minimum_iou=min(matched_ious) if matched_ious else None,
        minimum_confidence=min(
            (item.confidence for item in predictions), default=None
        ),
    )
