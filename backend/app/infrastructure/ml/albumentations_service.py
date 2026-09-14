from __future__ import annotations

import inspect
from collections.abc import Sequence

import albumentations as A
import cv2
import numpy as np

from app.application.ports.services.augmentation import (
    AugmentedSample,
    IAugmentationService,
    LabeledBox,
)
from app.domain.entities.dataset_version import AugmentationConfig


def _encode_jpeg(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise RuntimeError("failed to encode JPEG")
    return buffer.tobytes()


def _decode_image(image_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("unable to decode image bytes")
    return image


def _boxes_to_albumentations(
    boxes: Sequence[LabeledBox],
) -> tuple[list[list[float]], list[int]]:
    coords = [
        [box.x_center, box.y_center, box.width, box.height] for box in boxes
    ]
    labels = [box.class_index for box in boxes]
    return coords, labels


def _albumentations_to_boxes(
    coords: Sequence[Sequence[float]], labels: Sequence[int]
) -> list[LabeledBox]:
    return [
        LabeledBox(
            x_center=float(coord[0]),
            y_center=float(coord[1]),
            width=float(coord[2]),
            height=float(coord[3]),
            class_index=int(label),
        )
        for coord, label in zip(coords, labels, strict=True)
    ]


def _supports_param(cls: type, name: str) -> bool:
    try:
        return name in inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        return False


def _pad_fill_kwargs() -> dict:
    if _supports_param(A.PadIfNeeded, "fill"):
        return {"fill": 0}
    return {"value": 0}


def _shift_fill_kwargs() -> dict:
    # Prefer Affine on albumentations 2.x; fall back to ShiftScaleRotate on 1.x.
    if hasattr(A, "Affine") and _supports_param(A.Affine, "fill"):
        return {"fill": 0}
    if _supports_param(A.ShiftScaleRotate, "fill"):
        return {"fill": 0}
    return {"value": 0}


class AlbumentationsAugmentationService(IAugmentationService):
    def _letterbox(self, config: AugmentationConfig) -> A.Compose:
        return A.Compose(
            [
                A.LongestMaxSize(max_size=max(config.resize_width, config.resize_height)),
                A.PadIfNeeded(
                    min_height=config.resize_height,
                    min_width=config.resize_width,
                    border_mode=cv2.BORDER_CONSTANT,
                    **_pad_fill_kwargs(),
                ),
            ],
            bbox_params=A.BboxParams(
                format="yolo",
                label_fields=["class_labels"],
                min_visibility=0.0,
            ),
        )

    def _geometric_aug(self) -> A.BasicTransform:
        fill_kwargs = _shift_fill_kwargs()
        if hasattr(A, "Affine") and _supports_param(A.Affine, "translate_percent"):
            return A.Affine(
                translate_percent={"x": (-0.1, 0.1), "y": (-0.1, 0.1)},
                scale=(0.9, 1.1),
                rotate=(-10, 10),
                border_mode=cv2.BORDER_CONSTANT,
                p=0.5,
                **fill_kwargs,
            )
        return A.ShiftScaleRotate(
            shift_limit=0.1,
            scale_limit=0.1,
            rotate_limit=10,
            border_mode=cv2.BORDER_CONSTANT,
            p=0.5,
            **fill_kwargs,
        )

    def _augment_pipeline(self, config: AugmentationConfig) -> A.Compose:
        transforms: list[A.BasicTransform] = [
            A.LongestMaxSize(max_size=max(config.resize_width, config.resize_height)),
            A.PadIfNeeded(
                min_height=config.resize_height,
                min_width=config.resize_width,
                border_mode=cv2.BORDER_CONSTANT,
                **_pad_fill_kwargs(),
            ),
        ]
        if config.horizontal_flip:
            transforms.append(A.HorizontalFlip(p=0.5))
        if config.brightness_contrast:
            transforms.append(A.RandomBrightnessContrast(p=0.5))
        if config.shift_scale_rotate:
            transforms.append(self._geometric_aug())
        if config.blur:
            transforms.append(
                A.OneOf(
                    [
                        A.MotionBlur(blur_limit=5, p=1.0),
                        A.GaussianBlur(blur_limit=(3, 5), p=1.0),
                    ],
                    p=0.3,
                )
            )
        return A.Compose(
            transforms,
            bbox_params=A.BboxParams(
                format="yolo",
                label_fields=["class_labels"],
                min_visibility=0.0,
            ),
        )

    def _apply(
        self,
        pipeline: A.Compose,
        image: np.ndarray,
        boxes: Sequence[LabeledBox],
    ) -> AugmentedSample:
        coords, labels = _boxes_to_albumentations(boxes)
        result = pipeline(image=image, bboxes=coords, class_labels=labels)
        out_boxes = _albumentations_to_boxes(result["bboxes"], result["class_labels"])
        return AugmentedSample(
            image_bytes=_encode_jpeg(result["image"]),
            boxes=out_boxes,
            suffix="",
        )

    def generate_samples(
        self,
        image_bytes: bytes,
        boxes: Sequence[LabeledBox],
        config: AugmentationConfig,
        *,
        apply_augmentation: bool,
    ) -> list[AugmentedSample]:
        image = _decode_image(image_bytes)
        letterbox = self._letterbox(config)
        base = self._apply(letterbox, image, boxes)
        base = AugmentedSample(
            image_bytes=base.image_bytes,
            boxes=base.boxes,
            suffix="",
        )

        if not apply_augmentation or config.multiplier <= 1:
            return [base]

        samples = [base]
        augment = self._augment_pipeline(config)
        for index in range(1, config.multiplier):
            variant = self._apply(augment, image, boxes)
            samples.append(
                AugmentedSample(
                    image_bytes=variant.image_bytes,
                    boxes=variant.boxes,
                    suffix=f"_aug_{index}",
                )
            )
        return samples

    def horizontal_flip_once(
        self,
        image_bytes: bytes,
        boxes: Sequence[LabeledBox],
    ) -> AugmentedSample:
        """Deterministic helper used by integration tests."""
        image = _decode_image(image_bytes)
        pipeline = A.Compose(
            [A.HorizontalFlip(p=1.0)],
            bbox_params=A.BboxParams(
                format="yolo",
                label_fields=["class_labels"],
                min_visibility=0.0,
            ),
        )
        return self._apply(pipeline, image, boxes)
