from __future__ import annotations

from app.domain.enums import TripwireDirection
from app.domain.services.tripwire import (
    TripwireDebouncer,
    crossing_direction,
    segments_intersect,
)


def should_capture_timer(
    *,
    now: float,
    last_timer_at: float | None,
    last_any_at: float | None,
    interval: float,
    cooldown: float,
    confidences: list[float],
    unc_range: tuple[float, float],
) -> bool:
    if last_timer_at is not None and (now - last_timer_at) < interval:
        return False
    if last_any_at is not None and (now - last_any_at) < cooldown:
        return False
    lo, hi = unc_range
    return any(lo <= c <= hi for c in confidences)


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
