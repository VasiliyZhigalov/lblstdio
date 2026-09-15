"""Tripwire geometry helpers for stream capture.

FORWARD = positive cross product of directed line A→B with motion vector
(approx. left→right / top→bottom relative to A→B). BACKWARD = negative.
"""

from __future__ import annotations

from app.domain.enums import TripwireDirection

Point = tuple[float, float]


def _ccw(a: Point, b: Point, c: Point) -> float:
    return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    """Return True if segment a1→a2 properly or improperly intersects b1→b2."""
    d1 = _ccw(a1, a2, b1)
    d2 = _ccw(a1, a2, b2)
    d3 = _ccw(b1, b2, a1)
    d4 = _ccw(b1, b2, a2)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    # Collinear touching endpoints / overlaps are not needed for tripwire v1.
    return False


def crossing_direction(
    p_prev: Point,
    p_curr: Point,
    line_a: Point,
    line_b: Point,
) -> TripwireDirection:
    """Classify motion relative to directed line A→B via cross(line, motion)."""
    lx = line_b[0] - line_a[0]
    ly = line_b[1] - line_a[1]
    mx = p_curr[0] - p_prev[0]
    my = p_curr[1] - p_prev[1]
    cross = lx * my - ly * mx
    if cross > 0:
        return TripwireDirection.FORWARD
    return TripwireDirection.BACKWARD


class TripwireDebouncer:
    def __init__(self, debounce_seconds: float) -> None:
        self._debounce_seconds = float(debounce_seconds)
        self._last_allowed: dict[int, float] = {}

    def allow(self, track_id: int, now: float) -> bool:
        last = self._last_allowed.get(track_id)
        if last is not None and (now - last) < self._debounce_seconds:
            return False
        self._last_allowed[track_id] = now
        return True
