"""Resolve Ultralytics device string: cuda index if available, else cpu."""

from __future__ import annotations

from app.application.ports.services.training_device import ITrainingDeviceResolver
from app.application.services.device_policy import normalize_device_request


def resolve_training_device(requested: str = "auto") -> str:
    value = normalize_device_request(requested)
    if value not in {"", "auto"}:
        if value in {"cuda", "cuda:0", "0", "gpu"}:
            return "0"
        if value.startswith("cuda:"):
            return value.split(":", 1)[1]
        return value
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
    except Exception:
        pass
    return "cpu"


def describe_training_device(resolved: str) -> str:
    value = (resolved or "cpu").strip().lower()
    if value in {"cpu"}:
        return "CPU"
    if value in {"0", "cuda", "cuda:0", "gpu"}:
        return "GPU (CUDA:0)"
    if value.isdigit():
        return f"GPU (CUDA:{value})"
    if value.startswith("cuda:"):
        return f"GPU ({value.upper()})"
    return value.upper()


def probe_training_device(requested: str = "auto") -> dict[str, str]:
    resolved = resolve_training_device(requested)
    return {
        "requested": requested or "auto",
        "device": resolved,
        "label": describe_training_device(resolved),
        "backend": "gpu" if resolved not in {"cpu"} else "cpu",
    }


class UltralyticsDeviceResolver(ITrainingDeviceResolver):
    def resolve(self, requested: str) -> str:
        return resolve_training_device(requested)
