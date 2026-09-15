from app.domain.enums import TripwireDirection
from app.domain.services.tripwire import (
    TripwireDebouncer,
    crossing_direction,
    segments_intersect,
)


def test_segments_intersect_when_crossing():
    assert segments_intersect((0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0)) is True


def test_segments_do_not_intersect_when_parallel():
    assert segments_intersect((0.0, 0.2), (1.0, 0.2), (0.0, 0.8), (1.0, 0.8)) is False


def test_crossing_direction_forward_left_to_right():
    # horizontal line left→right; motion top→bottom is FORWARD by convention
    direction = crossing_direction((0.5, 0.2), (0.5, 0.8), (0.0, 0.5), (1.0, 0.5))
    assert direction == TripwireDirection.FORWARD


def test_debouncer_blocks_same_track_within_window():
    debouncer = TripwireDebouncer(debounce_seconds=3.0)
    assert debouncer.allow(track_id=7, now=100.0) is True
    assert debouncer.allow(track_id=7, now=101.0) is False
    assert debouncer.allow(track_id=7, now=104.0) is True
