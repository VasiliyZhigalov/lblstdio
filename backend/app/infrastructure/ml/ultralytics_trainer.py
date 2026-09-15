from __future__ import annotations

import queue
import traceback
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from app.application.ports.services.model_trainer import (
    EpochCallback,
    IModelTrainer,
    TrainingConfig,
    TrainingResult,
)


def _extract_metrics(trainer: Any) -> dict[str, Any]:
    epoch = int(getattr(trainer, "epoch", 0)) + 1
    loss = None
    loss_items = getattr(trainer, "loss_items", None)
    if loss_items is not None:
        try:
            loss = float(sum(float(x) for x in loss_items))
        except Exception:
            loss = None
    metrics = getattr(trainer, "metrics", {}) or {}
    def _get(*keys: str) -> float | None:
        for key in keys:
            if key in metrics:
                try:
                    return float(metrics[key])
                except (TypeError, ValueError):
                    return None
        return None

    return {
        "epoch": epoch,
        "train_loss": loss,
        "val_loss": _get("val/box_loss", "box_loss"),
        "map50": _get("metrics/mAP50(B)", "mAP50"),
        "map50_95": _get("metrics/mAP50-95(B)", "mAP50-95"),
        "precision": _get("metrics/precision(B)", "precision"),
        "recall": _get("metrics/recall(B)", "recall"),
    }


def _training_worker(config: dict[str, Any], progress_queue, result_queue) -> None:
    try:
        from ultralytics import YOLO

        model = YOLO(config["base_weights"])
        history: list[dict[str, Any]] = []

        def on_fit_epoch_end(trainer: Any) -> None:
            metrics = _extract_metrics(trainer)
            history.append(metrics)
            progress_queue.put(metrics)

        model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
        results = model.train(
            data=config["data_yaml_path"],
            epochs=config["epochs"],
            batch=config["batch_size"],
            imgsz=config["imgsz"],
            device=config["device"],
            patience=int(config.get("patience", 20)),
            project=config["output_dir"],
            name="run",
            exist_ok=True,
            verbose=False,
            plots=False,
            save=True,
        )
        save_dir = Path(str(getattr(results, "save_dir", Path(config["output_dir"]) / "run")))
        best = save_dir / "weights" / "best.pt"
        if not best.is_file():
            # fallback last.pt
            best = save_dir / "weights" / "last.pt"
        final_metrics = {}
        try:
            final_metrics = dict(getattr(results, "results_dict", {}) or {})
        except Exception:
            final_metrics = {}

        def _final(*keys: str) -> float | None:
            for key in keys:
                if key in final_metrics:
                    try:
                        return float(final_metrics[key])
                    except (TypeError, ValueError):
                        return None
            return None

        epochs_trained = len(history)
        planned = int(config.get("epochs", epochs_trained) or epochs_trained)
        result_queue.put(
            {
                "ok": True,
                "best_weights_path": str(best),
                "map50": _final("metrics/mAP50(B)", "mAP50"),
                "map50_95": _final("metrics/mAP50-95(B)", "mAP50-95"),
                "precision": _final("metrics/precision(B)", "precision"),
                "recall": _final("metrics/recall(B)", "recall"),
                "epochs_trained": epochs_trained,
                "stopped_early": epochs_trained < planned,
            }
        )
    except Exception as exc:
        result_queue.put(
            {
                "ok": False,
                "error": f"{exc}\n{traceback.format_exc()}",
            }
        )


class ProcessUltralyticsTrainer(IModelTrainer):
    """Runs Ultralytics YOLO.train() in an isolated spawn process."""

    def train(
        self,
        config: TrainingConfig,
        on_epoch_end: EpochCallback | None = None,
    ) -> TrainingResult:
        ctx = get_context("spawn")
        progress_queue = ctx.Queue()
        result_queue = ctx.Queue()
        payload = {
            "data_yaml_path": config.data_yaml_path,
            "output_dir": config.output_dir,
            "epochs": config.epochs,
            "batch_size": config.batch_size,
            "imgsz": config.imgsz,
            "device": config.device,
            "base_weights": config.base_weights,
            "patience": config.patience,
        }
        process = ctx.Process(
            target=_training_worker,
            args=(payload, progress_queue, result_queue),
        )
        process.start()
        history: list[dict[str, Any]] = []
        result: dict[str, Any] | None = None
        while True:
            try:
                metrics = progress_queue.get(timeout=0.25)
                history.append(metrics)
                if on_epoch_end is not None:
                    on_epoch_end(metrics)
            except queue.Empty:
                pass
            try:
                result = result_queue.get_nowait()
                break
            except queue.Empty:
                if not process.is_alive():
                    break
        process.join(timeout=30)
        if result is None:
            try:
                result = result_queue.get(timeout=5)
            except queue.Empty:
                raise RuntimeError("training process exited without result")
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "training failed")
        epochs_trained = int(result.get("epochs_trained") or len(history))
        stopped_early = bool(result.get("stopped_early", epochs_trained < config.epochs))
        return TrainingResult(
            best_weights_path=result["best_weights_path"],
            metrics_history=history,
            map50=result.get("map50"),
            map50_95=result.get("map50_95"),
            precision=result.get("precision"),
            recall=result.get("recall"),
            stopped_early=stopped_early,
            epochs_trained=epochs_trained,
        )
