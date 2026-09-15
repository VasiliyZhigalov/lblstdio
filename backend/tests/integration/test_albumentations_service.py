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


def test_train_multiplier_variants_are_unique(
    service: AlbumentationsAugmentationService,
) -> None:
    from app.domain.entities.dataset_version import AugmentationConfig

    rng = np.random.default_rng(0)
    image = rng.integers(0, 255, (320, 320, 3), dtype=np.uint8)
    boxes = [LabeledBox(0.5, 0.5, 0.2, 0.2, class_index=0)]
    samples = service.generate_samples(
        _png_bytes(image),
        boxes,
        AugmentationConfig(multiplier=3, horizontal_flip=True, brightness_contrast=True),
        apply_augmentation=True,
    )
    assert len(samples) == 3
    payloads = [item.image_bytes for item in samples]
    assert len(set(payloads)) == 3


def test_letterbox_resize_default_640(
    service: AlbumentationsAugmentationService,
) -> None:
    from app.domain.entities.dataset_version import AugmentationConfig

    image = np.full((200, 400, 3), 90, dtype=np.uint8)
    boxes = [LabeledBox(0.5, 0.5, 0.2, 0.2, class_index=0)]
    samples = service.generate_samples(
        _png_bytes(image),
        boxes,
        AugmentationConfig(multiplier=1),
        apply_augmentation=False,
    )
    decoded = np.array(PILImage.open(io.BytesIO(samples[0].image_bytes)))
    assert decoded.shape[0] == 640
    assert decoded.shape[1] == 640
    assert len(samples[0].boxes) == 1


def test_enabled_ops_pipeline_keeps_valid_boxes(
    service: AlbumentationsAugmentationService,
) -> None:
    from app.domain.entities.dataset_version import AugmentationConfig

    rng = np.random.default_rng(1)
    image = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    boxes = [LabeledBox(0.4, 0.4, 0.2, 0.2, class_index=0)]
    samples = service.generate_samples(
        _png_bytes(image),
        boxes,
        AugmentationConfig(
            multiplier=4,
            horizontal_flip=True,
            vertical_flip=True,
            rotate=True,
            shear=True,
            hue_saturation=True,
            brightness_contrast=True,
            blur=True,
            noise=True,
            grayscale=True,
            cutout=True,
        ),
        apply_augmentation=True,
    )
    assert len(samples) == 4
    for sample in samples:
        decoded = np.array(PILImage.open(io.BytesIO(sample.image_bytes)))
        assert decoded.shape[0] == 640
        assert decoded.shape[1] == 640
        for box in sample.boxes:
            assert 0.0 <= box.x_center <= 1.0
            assert 0.0 <= box.y_center <= 1.0
            assert 0.0 < box.width <= 1.0
            assert 0.0 < box.height <= 1.0
