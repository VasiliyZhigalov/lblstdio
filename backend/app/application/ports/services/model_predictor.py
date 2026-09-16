from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Detection:
    class_index: int
    confidence: float
    x_center: float
    y_center: float
    width: float
    height: float


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
