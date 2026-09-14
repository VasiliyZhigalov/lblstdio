from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.entities.dataset_version import AugmentationConfig


@dataclass(frozen=True)
class LabeledBox:
    """YOLO-normalized box with class index for augmentation."""

    x_center: float
    y_center: float
    width: float
    height: float
    class_index: int


@dataclass(frozen=True)
class AugmentedSample:
    image_bytes: bytes
    boxes: list[LabeledBox]
    suffix: str


class IAugmentationService(ABC):
    @abstractmethod
    def generate_samples(
        self,
        image_bytes: bytes,
        boxes: Sequence[LabeledBox],
        config: AugmentationConfig,
        *,
        apply_augmentation: bool,
    ) -> list[AugmentedSample]:
        """
        Always apply letterbox/preprocess.

        When apply_augmentation is False, return a single preprocessed sample.
        When True, return ``config.multiplier`` samples: index 0 is preprocess-only,
        the rest are randomly augmented copies (or a single sample if multiplier == 1).
        """
        raise NotImplementedError
