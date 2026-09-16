"""Box-guided SIFT similarity for annotation propagation.

Pipeline:
  1) SIFT on source only inside padded ROIs of donor boxes (larger pad for small boxes)
  2) Match those features against the full target frame → one shared 2×3 similarity
  3) Apply that matrix to every annotation box
"""

from __future__ import annotations

import cv2
import numpy as np

from app.application.dto import ProjectedBox, ProjectBoxesResult, TransformDebug
from app.application.ports.services.keypoint_matcher import IKeypointMatcher
from app.domain.exceptions import KeypointMatchingFailedException
from app.domain.value_objects.bounding_box import BoundingBox

MIN_MATCHES = 4
SCALE_MIN = 0.4
SCALE_MAX = 2.5
SIFT_RATIO = 0.75
CROP_PADDING = 0.125
# Small boxes expand so SIFT sees enough texture (px on source image).
MIN_ROI_SIDE_PX = 128
FAIL_MESSAGE = "Не удалось найти объект на этом кадре. Разметьте вручную"


def box_iou(left: BoundingBox, right: BoundingBox) -> float:
    def _xyxy(box: BoundingBox) -> tuple[float, float, float, float]:
        return (
            box.x_center - box.width / 2,
            box.y_center - box.height / 2,
            box.x_center + box.width / 2,
            box.y_center + box.height / 2,
        )

    ax1, ay1, ax2, ay2 = _xyxy(left)
    bx1, by1, bx2, by2 = _xyxy(right)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = left.width * left.height + right.width * right.height - inter
    if union <= 0:
        return 0.0
    return inter / union


def yolo_to_xyxy(box: BoundingBox, width: int, height: int) -> tuple[float, float, float, float]:
    x1 = (box.x_center - box.width / 2) * width
    y1 = (box.y_center - box.height / 2) * height
    x2 = (box.x_center + box.width / 2) * width
    y2 = (box.y_center + box.height / 2) * height
    return x1, y1, x2, y2


def padded_roi_xyxy(
    xyxy: tuple[float, float, float, float],
    image_width: int,
    image_height: int,
    *,
    padding: float = CROP_PADDING,
    min_side_px: float = MIN_ROI_SIDE_PX,
) -> tuple[int, int, int, int]:
    """Expand box by relative padding, then grow to min_side_px (shift inward at edges)."""
    x1, y1, x2, y2 = xyxy
    box_w = max(0.0, x2 - x1)
    box_h = max(0.0, y2 - y1)
    pad_x = box_w * padding
    pad_y = box_h * padding

    roi_w = box_w + 2.0 * pad_x
    roi_h = box_h + 2.0 * pad_y
    if roi_w < min_side_px:
        pad_x += (min_side_px - roi_w) / 2.0
    if roi_h < min_side_px:
        pad_y += (min_side_px - roi_h) / 2.0

    x0 = int(max(0, np.floor(x1 - pad_x)))
    y0 = int(max(0, np.floor(y1 - pad_y)))
    x1c = int(min(image_width, np.ceil(x2 + pad_x)))
    y1c = int(min(image_height, np.ceil(y2 + pad_y)))

    # If clipped by image border, try to keep min side by shifting inward.
    need_w = int(min(image_width, max(x1c - x0, int(np.ceil(min_side_px)))))
    need_h = int(min(image_height, max(y1c - y0, int(np.ceil(min_side_px)))))
    if x1c - x0 < need_w:
        if x0 == 0:
            x1c = min(image_width, need_w)
        elif x1c >= image_width:
            x0 = max(0, image_width - need_w)
        else:
            extra = need_w - (x1c - x0)
            x0 = max(0, x0 - extra // 2)
            x1c = min(image_width, x0 + need_w)
            x0 = max(0, x1c - need_w)
    if y1c - y0 < need_h:
        if y0 == 0:
            y1c = min(image_height, need_h)
        elif y1c >= image_height:
            y0 = max(0, image_height - need_h)
        else:
            extra = need_h - (y1c - y0)
            y0 = max(0, y0 - extra // 2)
            y1c = min(image_height, y0 + need_h)
            y0 = max(0, y1c - need_h)

    if x1c <= x0:
        x1c = min(image_width, x0 + 1)
    if y1c <= y0:
        y1c = min(image_height, y0 + 1)
    return x0, y0, x1c, y1c


def scale_ok(matrix: np.ndarray, lo: float = SCALE_MIN, hi: float = SCALE_MAX) -> bool:
    a, b = float(matrix[0, 0]), float(matrix[0, 1])
    return lo <= float(np.hypot(a, b)) <= hi


def _sift() -> cv2.SIFT:
    if not hasattr(cv2, "SIFT_create"):
        raise KeypointMatchingFailedException("OpenCV SIFT недоступен в этой сборке")
    # Lower contrast threshold so small/flat ROIs still yield keypoints.
    return cv2.SIFT_create(nfeatures=2000, contrastThreshold=0.02)


def sift_pairs_from_rois(
    prev_gray: np.ndarray,
    curr_gray: np.ndarray,
    rois: list[tuple[int, int, int, int]],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Detect SIFT inside each source ROI crop, match against full target frame."""
    sift = _sift()
    pts_prev: list[tuple[float, float]] = []
    descriptors: list[np.ndarray] = []
    for x0, y0, x1, y1 in rois:
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        crop = prev_gray[y0:y1, x0:x1]
        kps, desc = sift.detectAndCompute(crop, None)
        if desc is None or not kps:
            continue
        for kp in kps:
            pts_prev.append((float(kp.pt[0] + x0), float(kp.pt[1] + y0)))
        descriptors.append(desc)

    if len(pts_prev) < MIN_MATCHES or not descriptors:
        return None

    desc_prev = np.vstack(descriptors)
    keypoints_curr, desc_curr = sift.detectAndCompute(curr_gray, None)
    if desc_curr is None or len(keypoints_curr) < MIN_MATCHES:
        return None

    knn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(desc_prev, desc_curr, k=2)
    good = []
    for pair in knn:
        if len(pair) < 2:
            continue
        best, second = pair
        if best.distance < SIFT_RATIO * second.distance:
            good.append(best)
    if len(good) < MIN_MATCHES:
        return None
    pts0 = np.float32([pts_prev[match.queryIdx] for match in good])
    pts1 = np.float32([keypoints_curr[match.trainIdx].pt for match in good])
    return pts0, pts1


def estimate_similarity(
    pts0: np.ndarray, pts1: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Similarity (translate / rotate / uniform scale) from source→target matches.

    Port of yoloe_label.scripts.keypoint_match.estimate_similarity.
    Returns (matrix 2x3, inlier_pts0, inlier_pts1).
    """
    if pts0 is None or pts1 is None or len(pts0) < 3 or len(pts1) < 3:
        return None
    p0 = pts0.reshape(-1, 2).astype(np.float32)
    p1 = pts1.reshape(-1, 2).astype(np.float32)
    if len(p0) >= 4:
        matrix, inliers = cv2.estimateAffinePartial2D(
            p0, p1, method=cv2.RANSAC, ransacReprojThreshold=3.0
        )
        if matrix is not None and scale_ok(matrix) and inliers is not None:
            mask = inliers.ravel().astype(bool)
            if int(mask.sum()) >= 3:
                return matrix.astype(np.float64), p0[mask], p1[mask]
    dxy = p1 - p0
    dx = float(np.median(dxy[:, 0]))
    dy = float(np.median(dxy[:, 1]))
    matrix = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float64)
    return matrix, p0, p1


def transform_bbox(
    bbox_xyxy: tuple[float, float, float, float], matrix: np.ndarray
) -> tuple[float, float, float, float]:
    """Apply 2×3 similarity to the four corners, return axis-aligned bounds."""
    x1, y1, x2, y2 = bbox_xyxy
    corners = np.array(
        [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]],
        dtype=np.float32,
    )
    mapped = cv2.transform(corners, matrix.astype(np.float32))[0]
    return (
        float(mapped[:, 0].min()),
        float(mapped[:, 1].min()),
        float(mapped[:, 0].max()),
        float(mapped[:, 1].max()),
    )


def estimate_boxes_similarity(
    source_bgr: np.ndarray,
    target_bgr: np.ndarray,
    source_boxes: list[BoundingBox],
) -> tuple[np.ndarray, float]:
    """One shared similarity from SIFT features inside padded donor ROIs."""
    if not source_boxes:
        raise KeypointMatchingFailedException(FAIL_MESSAGE)

    src_h, src_w = source_bgr.shape[:2]
    rois = [
        padded_roi_xyxy(yolo_to_xyxy(box, src_w, src_h), src_w, src_h)
        for box in source_boxes
    ]

    try:
        pairs = sift_pairs_from_rois(
            cv2.cvtColor(source_bgr, cv2.COLOR_BGR2GRAY),
            cv2.cvtColor(target_bgr, cv2.COLOR_BGR2GRAY),
            rois,
        )
    except KeypointMatchingFailedException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise KeypointMatchingFailedException(FAIL_MESSAGE) from exc

    if pairs is None:
        raise KeypointMatchingFailedException(FAIL_MESSAGE)

    pts0, pts1 = pairs
    estimated = estimate_similarity(pts0, pts1)
    if estimated is None:
        raise KeypointMatchingFailedException(FAIL_MESSAGE)

    matrix, inliers0, _inliers1 = estimated
    score = float(len(inliers0) / max(len(pts0), 1))
    return matrix.astype(np.float64), min(1.0, max(0.0, score))


def matrix_to_transform_debug(matrix: np.ndarray, match_score: float) -> TransformDebug:
    """Decode OpenCV partial-affine [[a,-b,tx],[b,a,ty]] into human-readable params."""
    a = float(matrix[0, 0])
    b = float(matrix[1, 0])
    tx = float(matrix[0, 2])
    ty = float(matrix[1, 2])
    scale = float(np.hypot(a, b))
    rotation_deg = float(np.degrees(np.arctan2(b, a)))
    return TransformDebug(
        tx=tx,
        ty=ty,
        rotation_deg=rotation_deg,
        scale=scale,
        match_score=match_score,
        matrix=(
            (float(matrix[0, 0]), float(matrix[0, 1]), float(matrix[0, 2])),
            (float(matrix[1, 0]), float(matrix[1, 1]), float(matrix[1, 2])),
        ),
    )


def apply_similarity_to_boxes(
    source_boxes: list[BoundingBox],
    matrix: np.ndarray,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    match_score: float,
) -> list[ProjectedBox | None]:
    """Apply the same 2×3 matrix to every YOLO box."""
    projected: list[ProjectedBox | None] = []
    for box in source_boxes:
        xyxy = yolo_to_xyxy(box, source_width, source_height)
        mapped = transform_bbox(xyxy, matrix)
        bbox = _xyxy_to_yolo(mapped, target_width, target_height)
        if bbox is None:
            projected.append(None)
        else:
            projected.append(ProjectedBox(bbox=bbox, match_score=match_score))
    return projected


def _xyxy_to_yolo(
    xyxy: tuple[float, float, float, float], width: int, height: int
) -> BoundingBox | None:
    x1, y1, x2, y2 = xyxy
    x1 = min(max(0.0, x1), float(width))
    y1 = min(max(0.0, y1), float(height))
    x2 = min(max(0.0, x2), float(width))
    y2 = min(max(0.0, y2), float(height))
    if x2 <= x1 + 1.0 or y2 <= y1 + 1.0:
        return None
    return BoundingBox(
        x_center=((x1 + x2) / 2) / width,
        y_center=((y1 + y2) / 2) / height,
        width=(x2 - x1) / width,
        height=(y2 - y1) / height,
    )


def _read_bgr(path: str) -> np.ndarray | None:
    encoded = np.fromfile(path, dtype=np.uint8)
    if encoded.size == 0:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


class SiftKeypointMatcher(IKeypointMatcher):
    def project_box(
        self,
        source_image_path: str,
        target_image_path: str,
        source_box: BoundingBox,
        source_width: int,
        source_height: int,
        target_width: int,
        target_height: int,
    ) -> ProjectedBox:
        result = self.project_boxes(
            source_image_path,
            target_image_path,
            [source_box],
            source_width,
            source_height,
            target_width,
            target_height,
        )
        if not result.boxes or result.boxes[0] is None:
            raise KeypointMatchingFailedException(FAIL_MESSAGE)
        return result.boxes[0]

    def project_boxes(
        self,
        source_image_path: str,
        target_image_path: str,
        source_boxes: list[BoundingBox],
        source_width: int,
        source_height: int,
        target_width: int,
        target_height: int,
    ) -> ProjectBoxesResult:
        source_bgr = _read_bgr(source_image_path)
        target_bgr = _read_bgr(target_image_path)
        if source_bgr is None or target_bgr is None:
            raise KeypointMatchingFailedException(FAIL_MESSAGE)

        src_h, src_w = source_bgr.shape[:2]
        dst_h, dst_w = target_bgr.shape[:2]
        if abs(src_w - source_width) > 1 or abs(src_h - source_height) > 1:
            raise KeypointMatchingFailedException(FAIL_MESSAGE)
        if abs(dst_w - target_width) > 1 or abs(dst_h - target_height) > 1:
            raise KeypointMatchingFailedException(FAIL_MESSAGE)

        matrix, score = estimate_boxes_similarity(source_bgr, target_bgr, source_boxes)
        projected = apply_similarity_to_boxes(
            source_boxes,
            matrix,
            src_w,
            src_h,
            dst_w,
            dst_h,
            score,
        )
        if all(item is None for item in projected):
            raise KeypointMatchingFailedException(FAIL_MESSAGE)
        return ProjectBoxesResult(
            boxes=projected,
            transform=matrix_to_transform_debug(matrix, score),
        )
