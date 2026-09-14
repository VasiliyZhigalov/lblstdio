import io

import numpy as np
import pytest
from PIL import Image as PILImage

from app.application.ports.services.augmentation import LabeledBox
from app.infrastructure.ml.albumentations_service import AlbumentationsAugmentationService


def _png_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    PILImage.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def service() -> AlbumentationsAugmentationService:
    return AlbumentationsAugmentationService()


def test_horizontal_flip_keeps_center_box(service: AlbumentationsAugmentationService) -> None:
    image = np.zeros((1000, 1000, 3), dtype=np.uint8)
    image[:, :500] = (30, 30, 30)
    image[:, 500:] = (200, 200, 200)
    boxes = [LabeledBox(0.5, 0.5, 0.2, 0.2, class_index=0)]

    result = service.horizontal_flip_once(_png_bytes(image), boxes)

    assert len(result.boxes) == 1
    assert result.boxes[0].x_center == pytest.approx(0.5, abs=1e-5)
    assert result.boxes[0].y_center == pytest.approx(0.5, abs=1e-5)


def test_horizontal_flip_mirrors_left_edge_box(
    service: AlbumentationsAugmentationService,
) -> None:
    image = np.full((1000, 1000, 3), 40, dtype=np.uint8)
    boxes = [LabeledBox(0.1, 0.5, 0.1, 0.1, class_index=0)]

    result = service.horizontal_flip_once(_png_bytes(image), boxes)

    assert len(result.boxes) == 1
    assert result.boxes[0].x_center == pytest.approx(0.9, abs=1e-5)
    assert result.boxes[0].y_center == pytest.approx(0.5, abs=1e-5)
