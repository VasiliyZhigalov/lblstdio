from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.enums import TripwireDirection
from app.domain.services.tripwire import (
    TripwireDebouncer,
    crossing_direction,
    segments_intersect,
)


@dataclass(frozen=True)
class TrackStableSample:
    confidence: float
    area: float


def class_is_allowed(
    class_index: int,
    allowed_class_indices: frozenset[int] | None,
) -> bool:
    """Return whether a detection can trigger frame capture.

    None allows every class. An empty set allows none.
    """
    if allowed_class_indices is None:
        return True
    return class_index in allowed_class_indices


def confidence_in_band(confidence: float, low: float, high: float) -> bool:
    return low <= confidence <= high


def detections_matching_classes(detections: Sequence, allowed: frozenset[int] | None) -> list:
    """Detections that pass the class filter.

    None allows every class. An empty set allows none.
    """
    return [item for item in detections if class_is_allowed(item.class_index, allowed)]


def size_variation(areas: Sequence[float]) -> float:
    """Relative area span: max/min - 1. Zero areas → infinitely unstable."""
    if not areas:
        return float("inf")
    lo = min(areas)
    if lo <= 0:
        return float("inf")
    return max(areas) / lo - 1.0


def is_track_series_stable(
    samples: Sequence[TrackStableSample],
    *,
    min_frames: int,
    min_avg_conf: float,
    max_size_variation: float,
) -> bool:
    if len(samples) < min_frames:
        return False
    window = samples[-min_frames:]
    avg_conf = sum(item.confidence for item in window) / len(window)
    if avg_conf < min_avg_conf:
        return False
    return size_variation([item.area for item in window]) <= max_size_variation


def best_confidence_index(samples: Sequence[TrackStableSample]) -> int:
    if not samples:
        raise ValueError("samples must not be empty")
    best_i = 0
    best_conf = samples[0].confidence
    for i, sample in enumerate(samples):
        if sample.confidence > best_conf:
            best_conf = sample.confidence
            best_i = i
    return best_i


def should_capture_track_stable(
    *,
    samples: Sequence[TrackStableSample],
    now: float,
    last_saved_at: float | None,
    interval_seconds: float,
    min_frames: int,
    min_avg_conf: float,
    max_size_variation: float,
) -> int | None:
    """Return index of best frame to save, or None if not ready."""
    if last_saved_at is not None and (now - last_saved_at) < interval_seconds:
        return None
    if not is_track_series_stable(
        samples,
        min_frames=min_frames,
        min_avg_conf=min_avg_conf,
        max_size_variation=max_size_variation,
    ):
        return None
    window = samples[-min_frames:]
    # Index relative to full `samples` list (window is a suffix).
    return len(samples) - min_frames + best_confidence_index(window)


def should_capture_tripwire(
    *,
    track_id: int,
    p_prev: tuple[float, float],
    p_curr: tuple[float, float],
    line: tuple[float, float, float, float],
    direction: TripwireDirection,
    classes_ok: bool,
    debouncer: TripwireDebouncer,
    now: float,
    last_any_at: float | None,
    cooldown: float,
) -> bool:
    if not classes_ok:
        return False
    if last_any_at is not None and (now - last_any_at) < cooldown:
        return False
    a = (line[0], line[1])
    b = (line[2], line[3])
    if not segments_intersect(p_prev, p_curr, a, b):
        return False
    crossed = crossing_direction(p_prev, p_curr, a, b)
    if direction != TripwireDirection.ANY and crossed != direction:
        return False
    return debouncer.allow(track_id, now)
