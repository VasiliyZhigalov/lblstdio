from __future__ import annotations

from pathlib import Path

from app.application.ports.services.model_predictor import Detection, IModelPredictor


def _norm(path: str) -> str:
    return Path(path).resolve().as_posix()


class UltralyticsPredictor(IModelPredictor):
    def predict(
        self,
        weights_path: str,
        image_paths: list[str],
        confidence_threshold: float,
        iou_threshold: float = 0.7,
    ) -> dict[str, list[Detection]]:
        if not image_paths:
            return {}
        from ultralytics import YOLO

        model = YOLO(weights_path)
        results = model.predict(
            source=image_paths,
            conf=confidence_threshold,
            iou=iou_threshold,
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
