"""Validate training device request strings (no torch / infra imports)."""

from __future__ import annotations

import re

from app.domain.exceptions import DomainValidationException

_DEVICE_RE = re.compile(r"^(auto|cpu|cuda|gpu|cuda:\d+|\d+)$", re.IGNORECASE)


def normalize_device_request(device: str | None) -> str:
    value = (device or "auto").strip().lower() or "auto"
    if not _DEVICE_RE.fullmatch(value):
        raise DomainValidationException(
            "device must be one of: auto, cpu, cuda, gpu, <index>, cuda:<index>"
        )
    return value
