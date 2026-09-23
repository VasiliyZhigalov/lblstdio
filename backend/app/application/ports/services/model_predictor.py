from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    class_index: int
    confidence: float
    x_center: float
    y_center: float
    width: float
    height: float


@dataclass(frozen=True)
class Classification:
    class_index: int
    confidence: float


class IModelPredictor(ABC):
    @abstractmethod
    def predict(
        self,
        weights_path: str,
        image_paths: list[str],
        confidence_threshold: float,
        iou_threshold: float = 0.7,
    ) -> dict[str, list[Detection]]:
        """Return mapping of absolute image path → detections (normalized YOLO boxes)."""
        raise NotImplementedError


class IClassificationPredictor(ABC):
    @abstractmethod
    def class_names(self, weights_path: str) -> dict[int, str]:
        """Return model class index → name (Ultralytics `model.names`)."""
        raise NotImplementedError

    @abstractmethod
    def predict(
        self,
        weights_path: str,
        image_paths: list[str],
        confidence_threshold: float,
    ) -> dict[str, Classification]:
        """Return mapping of absolute image path → top-1 classification."""
        raise NotImplementedError
