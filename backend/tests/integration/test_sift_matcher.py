from pathlib import Path

import cv2
import numpy as np
import pytest

from app.domain.exceptions import KeypointMatchingFailedException
from app.domain.value_objects.bounding_box import BoundingBox
from app.infrastructure.ml.sift_matcher import (
    MIN_ROI_SIDE_PX,
    SiftKeypointMatcher,
    box_iou,
    padded_roi_xyxy,
)


def _textured_scene(width: int = 400, height: int = 320) -> np.ndarray:
    rng = np.random.default_rng(7)
    image = rng.integers(20, 80, (height, width, 3), dtype=np.uint8)
    patch = rng.integers(40, 220, (90, 110, 3), dtype=np.uint8)
    patch[::4, :] = 255
    patch[:, ::5] = 12
    cv2.putText(patch, "OBJ", (8, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (240, 240, 10), 3)
    image[70:160, 90:200] = patch
    return image


def _warp(image: np.ndarray, dx: float, dy: float, angle_deg: float) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    matrix[0, 2] += dx
    matrix[1, 2] += dy
    return cv2.warpAffine(image, matrix, (width, height), borderValue=(8, 8, 8))


def _yolo_from_xyxy(
    x1: float, y1: float, x2: float, y2: float, width: int, height: int
) -> BoundingBox:
    return BoundingBox(
        x_center=((x1 + x2) / 2) / width,
        y_center=((y1 + y2) / 2) / height,
        width=(x2 - x1) / width,
        height=(y2 - y1) / height,
    )


class TestPaddedRoi:
    def test_small_box_expands_to_min_side(self) -> None:
        x0, y0, x1, y1 = padded_roi_xyxy((100.0, 100.0, 120.0, 115.0), 400, 320)
        assert (x1 - x0) >= MIN_ROI_SIDE_PX - 1
        assert (y1 - y0) >= MIN_ROI_SIDE_PX - 1

    def test_edge_box_shifts_inward(self) -> None:
        x0, y0, x1, y1 = padded_roi_xyxy((0.0, 0.0, 10.0, 10.0), 400, 320)
        assert x0 == 0
        assert y0 == 0
        assert (x1 - x0) >= MIN_ROI_SIDE_PX - 1
        assert (y1 - y0) >= MIN_ROI_SIDE_PX - 1


class TestSiftKeypointMatcher:
    def test_object_shift_against_static_background(self, tmp_path: Path) -> None:
        """ROI crops must ignore static bg so object translation is recovered."""
        rng = np.random.default_rng(11)
        dx = 36
        height, width = 240, 320
        bg = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
        obj = rng.integers(40, 220, (70, 90, 3), dtype=np.uint8)
        obj[::4, :] = 255
        obj[:, ::5] = 12
        cv2.putText(obj, "OBJ", (8, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (240, 240, 10), 3)
        source = bg.copy()
        target = bg.copy()
        source[80:150, 60:150] = obj
        target[80:150, 60 + dx : 150 + dx] = obj

        source_path = tmp_path / "src.png"
        target_path = tmp_path / "dst.png"
        cv2.imencode(".png", source)[1].tofile(str(source_path))
        cv2.imencode(".png", target)[1].tofile(str(target_path))

        box = _yolo_from_xyxy(60, 80, 150, 150, width, height)
        result = SiftKeypointMatcher().project_boxes(
            str(source_path),
            str(target_path),
            [box],
            width,
            height,
            width,
            height,
        )
        assert result.boxes[0] is not None
        assert result.transform.tx == pytest.approx(dx, abs=6)
        got_cx = result.boxes[0].bbox.x_center * width
        assert got_cx == pytest.approx(105 + dx, abs=6)

    def test_projected_box_covers_shifted_rotated_object(self, tmp_path: Path) -> None:
        source = _textured_scene()
        target = _warp(source, dx=50, dy=0, angle_deg=5)
        source_path = tmp_path / "a.png"
        target_path = tmp_path / "b.png"
        cv2.imencode(".png", source)[1].tofile(str(source_path))
        cv2.imencode(".png", target)[1].tofile(str(target_path))

        source_box = _yolo_from_xyxy(90, 70, 200, 160, 400, 320)
        projected = SiftKeypointMatcher().project_box(
            str(source_path),
            str(target_path),
            source_box,
            400,
            320,
            400,
            320,
        )

        height, width = target.shape[:2]
        expected_px = (
            source_box.x_center * width - source_box.width * width / 2,
            source_box.y_center * height - source_box.height * height / 2,
            source_box.x_center * width + source_box.width * width / 2,
            source_box.y_center * height + source_box.height * height / 2,
        )
        center = (width / 2.0, height / 2.0)
        matrix = cv2.getRotationMatrix2D(center, 5.0, 1.0)
        matrix[0, 2] += 50
        corners = np.array(
            [
                [expected_px[0], expected_px[1]],
                [expected_px[2], expected_px[1]],
                [expected_px[2], expected_px[3]],
                [expected_px[0], expected_px[3]],
            ],
            dtype=np.float32,
        )
        mapped = cv2.transform(corners.reshape(1, -1, 2), matrix).reshape(-1, 2)
        expected = BoundingBox(
            x_center=float(np.clip(mapped[:, 0].mean() / width, 0.0, 1.0)),
            y_center=float(np.clip(mapped[:, 1].mean() / height, 0.0, 1.0)),
            width=float(np.clip((mapped[:, 0].max() - mapped[:, 0].min()) / width, 1e-3, 1.0)),
            height=float(np.clip((mapped[:, 1].max() - mapped[:, 1].min()) / height, 1e-3, 1.0)),
        )
        assert box_iou(projected.bbox, expected) >= 0.85
        assert 0.0 < projected.match_score <= 1.0

    def test_project_boxes_shares_one_image_wide_transform(self, tmp_path: Path) -> None:
        source = _textured_scene()
        target = _warp(source, dx=40, dy=10, angle_deg=0)
        source_path = tmp_path / "a.png"
        target_path = tmp_path / "b.png"
        cv2.imencode(".png", source)[1].tofile(str(source_path))
        cv2.imencode(".png", target)[1].tofile(str(target_path))

        boxes = [
            _yolo_from_xyxy(90, 70, 200, 160, 400, 320),
            _yolo_from_xyxy(250, 180, 320, 250, 400, 320),
        ]
        # Add a second textured patch so second box has context in full-frame match.
        source2 = source.copy()
        source2[180:250, 250:320] = source[70:140, 90:160]
        target2 = _warp(source2, dx=40, dy=10, angle_deg=0)
        cv2.imencode(".png", source2)[1].tofile(str(source_path))
        cv2.imencode(".png", target2)[1].tofile(str(target_path))

        results = SiftKeypointMatcher().project_boxes(
            str(source_path),
            str(target_path),
            boxes,
            400,
            320,
            400,
            320,
        )
        assert len(results.boxes) == 2
        assert results.boxes[0] is not None
        assert results.boxes[0].match_score == results.boxes[1].match_score
        assert abs(results.transform.tx) > 1.0 or abs(results.transform.ty) > 1.0

    def test_unrelated_images_raise_matching_failed(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(3)
        part = np.zeros((160, 200, 3), dtype=np.uint8)
        part[40:100, 50:130] = rng.integers(30, 220, (60, 80, 3), dtype=np.uint8)
        street = rng.integers(0, 255, (160, 200, 3), dtype=np.uint8)
        source_path = tmp_path / "part.png"
        target_path = tmp_path / "street.png"
        cv2.imencode(".png", part)[1].tofile(str(source_path))
        cv2.imencode(".png", street)[1].tofile(str(target_path))

        with pytest.raises(KeypointMatchingFailedException, match="Разметьте вручную"):
            SiftKeypointMatcher().project_box(
                str(source_path),
                str(target_path),
                BoundingBox(0.45, 0.44, 0.40, 0.38),
                200,
                160,
                200,
                160,
            )
