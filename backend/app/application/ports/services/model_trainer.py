from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrainingConfig:
    data_yaml_path: str
    output_dir: str
    epochs: int = 100
    batch_size: int = 16
    imgsz: int = 640
    device: str = "cpu"
    base_weights: str = "yolov8n.pt"
    patience: int = 20


@dataclass
class TrainingResult:
    best_weights_path: str
    metrics_history: list[dict[str, Any]] = field(default_factory=list)
    map50: float | None = None
    map50_95: float | None = None
    precision: float | None = None
    recall: float | None = None
    stopped_early: bool = False
    epochs_trained: int | None = None


EpochCallback = Callable[[dict[str, Any]], None]


class IModelTrainer(ABC):
    @abstractmethod
    def train(
        self,
        config: TrainingConfig,
        on_epoch_end: EpochCallback | None = None,
    ) -> TrainingResult:
        """Run training (blocking). Must not be called on the asyncio event-loop thread."""
        raise NotImplementedError
