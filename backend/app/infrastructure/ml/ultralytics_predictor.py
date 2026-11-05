from __future__ import annotations

from pathlib import Path

from app.application.ports.services.model_predictor import (
    Classification,
    Detection,
    IClassificationPredictor,
    IModelPredictor,
)


_PREDICT_BATCH = 4


def _norm(path: str) -> str:
    return Path(path).resolve().as_posix()


def _cached_model(cache: dict[str, object], weights_path: str):
    model = cache.get(weights_path)
    if model is None:
        from ultralytics import YOLO

        model = YOLO(weights_path)
        cache[weights_path] = model
    return model


class UltralyticsPredictor(IModelPredictor):
    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    def release(self) -> None:
        """Drop model references before handing GPU memory to training."""
        self._models.clear()

    def predict(
        self,
        weights_path: str,
        image_paths: list[str],
        confidence_threshold: float,
        iou_threshold: float = 0.7,
    ) -> dict[str, list[Detection]]:
        if not image_paths:
            return {}
        model = _cached_model(self._models, weights_path)
        results = model.predict(
            source=image_paths,
            conf=confidence_threshold,
            iou=iou_threshold,
            batch=_PREDICT_BATCH,
            stream=True,
            verbose=False,
        )
        by_resolved = {_norm(path): path for path in image_paths}
        output: dict[str, list[Detection]] = {path: [] for path in image_paths}
        for result in results:
            path = _norm(getattr(result, "path", "") or "")
            matched = by_resolved.get(path)
            if matched is None:
                continue
            boxes = getattr(result, "boxes", None)
            if boxes is None or len(boxes) == 0:
                continue
            xywhn = boxes.xywhn.cpu().tolist()
            confs = boxes.conf.cpu().tolist()
            clss = boxes.cls.cpu().tolist()
            dets: list[Detection] = []
            for xywh, conf, cls_idx in zip(xywhn, confs, clss, strict=False):
                x_c, y_c, w, h = xywh
                dets.append(
                    Detection(
                        class_index=int(cls_idx),
                        confidence=float(conf),
                        x_center=float(x_c),
                        y_center=float(y_c),
                        width=float(w),
                        height=float(h),
                    )
                )
            output[matched] = dets
        return output


def _yolo_class_names(model) -> dict[int, str]:
    names = getattr(model, "names", {}) or {}
    return {int(index): str(name) for index, name in names.items()}


class UltralyticsClassificationPredictor(IClassificationPredictor):
    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    def release(self) -> None:
        """Drop model references before handing GPU memory to training."""
        self._models.clear()

    def class_names(self, weights_path: str) -> dict[int, str]:
        return _yolo_class_names(_cached_model(self._models, weights_path))

    def predict(
        self,
        weights_path: str,
        image_paths: list[str],
        confidence_threshold: float,
    ) -> dict[str, Classification]:
        if not image_paths:
            return {}
        model = _cached_model(self._models, weights_path)
        results = model.predict(
            source=image_paths,
            batch=_PREDICT_BATCH,
            stream=True,
            verbose=False,
        )
        by_resolved = {_norm(path): path for path in image_paths}
        output: dict[str, Classification] = {}
        for result in results:
            path = _norm(getattr(result, "path", "") or "")
            matched = by_resolved.get(path)
            if matched is None:
                continue
            probs = getattr(result, "probs", None)
            if probs is None:
                continue
            top1 = getattr(probs, "top1", None)
            top1conf = getattr(probs, "top1conf", None)
            if top1 is None or top1conf is None:
                continue
            output[matched] = Classification(
                class_index=int(top1),
                confidence=float(top1conf),
            )
        return output
