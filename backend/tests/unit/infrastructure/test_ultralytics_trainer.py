from multiprocessing import Queue
from pathlib import Path
from types import SimpleNamespace

from app.infrastructure.ml.ultralytics_trainer import (
    _extract_metrics,
    _extract_val_metrics,
    _training_worker,
    split_has_images,
)


def test_extract_metrics_does_not_treat_top5_as_accuracy() -> None:
    trainer = SimpleNamespace(
        epoch=0,
        loss_items=None,
        metrics={"metrics/accuracy_top5": 0.4},
    )
    assert _extract_metrics(trainer)["accuracy"] is None


def test_training_worker_rejects_checkpoint_task_mismatch(tmp_path, monkeypatch) -> None:
    class _YOLO:
        def __init__(self, weights: str, task: str | None = None, verbose: bool = False) -> None:
            self.task = "detect"
            self.weights = weights

        def add_callback(self, *_args, **_kwargs) -> None:
            raise AssertionError("should not train a mismatched checkpoint")

        def train(self, **_kwargs):
            raise AssertionError("should not train a mismatched checkpoint")

    ultralytics = SimpleNamespace(YOLO=_YOLO)
    monkeypatch.setitem(__import__("sys").modules, "ultralytics", ultralytics)

    result_queue: Queue = Queue()
    _training_worker(
        {
            "base_weights": "yolov8n.pt",
            "task": "classification",
            "data_yaml_path": str(tmp_path),
            "output_dir": str(tmp_path),
            "epochs": 1,
            "batch_size": 1,
            "imgsz": 32,
            "device": "cpu",
            "patience": 1,
        },
        Queue(),
        result_queue,
    )
    result = result_queue.get(timeout=5)
    assert result["ok"] is False
    assert "detect" in result["error"]
    assert "classify" in result["error"]


def test_training_worker_records_top1_not_top5(tmp_path, monkeypatch) -> None:
    weights = tmp_path / "run" / "weights"
    weights.mkdir(parents=True)
    (weights / "best.pt").write_bytes(b"pt")
    seen: dict[str, str | None] = {}

    class _YOLO:
        def __init__(self, weights_path: str, task: str | None = None, verbose: bool = False) -> None:
            self.task = "classify"
            seen["task"] = task

        def add_callback(self, *_args, **_kwargs) -> None:
            return None

        def train(self, **_kwargs):
            return SimpleNamespace(
                save_dir=str(tmp_path / "run"),
                results_dict={
                    "metrics/accuracy_top1": 0.81,
                    "metrics/accuracy_top5": 0.99,
                },
            )

    ultralytics = SimpleNamespace(YOLO=_YOLO)
    monkeypatch.setitem(__import__("sys").modules, "ultralytics", ultralytics)

    result_queue: Queue = Queue()
    _training_worker(
        {
            "base_weights": "yolov8n-cls.pt",
            "task": "classification",
            "data_yaml_path": str(tmp_path),
            "output_dir": str(tmp_path),
            "epochs": 1,
            "batch_size": 1,
            "imgsz": 32,
            "device": "cpu",
            "patience": 1,
        },
        Queue(),
        result_queue,
    )
    result = result_queue.get(timeout=5)
    assert result["ok"] is True
    assert result["top1"] == 0.81
    assert result["test_metrics"] is None
    assert seen["task"] == "classify"
    assert Path(result["best_weights_path"]).name == "best.pt"


def test_extract_val_metrics_reads_detection_box() -> None:
    metrics = _extract_val_metrics(
        SimpleNamespace(
            box=SimpleNamespace(map50=0.42, map=0.31, mp=0.5, mr=0.4),
            top1=None,
            results_dict={},
        )
    )
    assert metrics["map50"] == 0.42
    assert metrics["map50_95"] == 0.31
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.4
    assert metrics["top1"] is None


def test_training_worker_evaluates_test_split(tmp_path, monkeypatch) -> None:
    weights = tmp_path / "run" / "weights"
    weights.mkdir(parents=True)
    (weights / "best.pt").write_bytes(b"pt")
    dataset = tmp_path / "dataset"
    (dataset / "test" / "images").mkdir(parents=True)
    (dataset / "test" / "images" / "holdout.jpg").write_bytes(b"img")
    data_yaml = tmp_path / "data.yaml"
    data_yaml.write_text(
        "path: "
        + dataset.as_posix()
        + "\ntrain: train/images\nval: valid/images\ntest: test/images\n",
        encoding="utf-8",
    )
    assert split_has_images(str(data_yaml))
    seen: dict[str, object] = {}

    class _YOLO:
        def __init__(self, weights_path: str, task: str | None = None, verbose: bool = False) -> None:
            self.task = "detect"
            self.weights_path = weights_path

        def add_callback(self, *_args, **_kwargs) -> None:
            return None

        def train(self, **_kwargs):
            return SimpleNamespace(
                save_dir=str(tmp_path / "run"),
                results_dict={"metrics/mAP50(B)": 0.7},
            )

        def val(self, **kwargs):
            seen["split"] = kwargs.get("split")
            seen["data"] = kwargs.get("data")
            return SimpleNamespace(
                box=SimpleNamespace(map50=0.55, map=0.4, mp=0.6, mr=0.5),
                top1=None,
                results_dict={},
            )

    monkeypatch.setitem(
        __import__("sys").modules,
        "ultralytics",
        SimpleNamespace(YOLO=_YOLO),
    )
    result_queue: Queue = Queue()
    _training_worker(
        {
            "base_weights": "yolov8n.pt",
            "task": "detection",
            "data_yaml_path": str(data_yaml),
            "output_dir": str(tmp_path),
            "epochs": 1,
            "batch_size": 1,
            "imgsz": 32,
            "device": "cpu",
            "patience": 1,
        },
        Queue(),
        result_queue,
    )
    result = result_queue.get(timeout=5)
    assert result["ok"] is True
    assert seen["split"] == "test"
    assert result["test_metrics"]["map50"] == 0.55
    assert result["test_metrics"]["precision"] == 0.6
