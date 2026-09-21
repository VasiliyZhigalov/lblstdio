import pytest

from app.domain.enums import TripwireDirection
from app.domain.services.stream_capture_rules import (
    TrackStableSample,
    best_confidence_index,
  class_is_allowed,
    is_track_series_stable,
    should_capture_track_stable,
    should_capture_tripwire,
    size_variation,
)
from app.domain.services.tripwire import TripwireDebouncer


def _samples(confs: list[float], area: float = 0.04) -> list[TrackStableSample]:
    return [TrackStableSample(confidence=c, area=area) for c in confs]


def test_class_is_allowed_accepts_all_when_filter_is_empty():
    assert class_is_allowed(3, None) is True
    assert class_is_allowed(3, frozenset()) is True
    assert class_is_allowed(3, frozenset({1, 3})) is True
    assert class_is_allowed(2, frozenset({1, 3})) is False


def test_size_variation_relative_span():
    assert size_variation([0.04, 0.04]) == 0.0
    assert size_variation([0.04, 0.05]) == pytest.approx(0.25)
    assert size_variation([]) == float("inf")
    assert size_variation([0.0, 0.1]) == float("inf")


def test_series_needs_n_avg_conf_and_size_stability():
    assert (
        is_track_series_stable(
            _samples([0.8] * 12),
            min_frames=12,
            min_avg_conf=0.75,
            max_size_variation=0.35,
        )
        is True
    )
    assert (
        is_track_series_stable(
            _samples([0.8] * 11),
            min_frames=12,
            min_avg_conf=0.75,
            max_size_variation=0.35,
        )
        is False
    )
    assert (
        is_track_series_stable(
            _samples([0.7] * 12),
            min_frames=12,
            min_avg_conf=0.75,
            max_size_variation=0.35,
        )
        is False
    )
    jumpy = [
        TrackStableSample(0.9, 0.02),
        *[TrackStableSample(0.9, 0.04) for _ in range(11)],
    ]
    assert (
        is_track_series_stable(
            jumpy, min_frames=12, min_avg_conf=0.75, max_size_variation=0.35
        )
        is False
    )


def test_best_confidence_index_picks_max():
    samples = [
        TrackStableSample(0.7, 0.04),
        TrackStableSample(0.95, 0.04),
        TrackStableSample(0.8, 0.04),
    ]
    assert best_confidence_index(samples) == 1


def test_should_capture_returns_best_index_and_respects_interval():
    samples = _samples([0.7 + i * 0.01 for i in range(12)])
    assert (
        should_capture_track_stable(
            samples=samples,
            now=10.0,
            last_saved_at=None,
            interval_seconds=5.0,
            min_frames=12,
            min_avg_conf=0.75,
            max_size_variation=0.35,
        )
        == 11
    )
    assert (
        should_capture_track_stable(
            samples=samples,
            now=12.0,
            last_saved_at=10.0,
            interval_seconds=5.0,
            min_frames=12,
            min_avg_conf=0.75,
            max_size_variation=0.35,
        )
        is None
    )
    assert (
        should_capture_track_stable(
            samples=samples,
            now=16.0,
            last_saved_at=10.0,
            interval_seconds=5.0,
            min_frames=12,
            min_avg_conf=0.75,
            max_size_variation=0.35,
        )
        == 11
    )


def test_tripwire_respects_direction_and_debounce():
    debouncer = TripwireDebouncer(3.0)
    kwargs = dict(
        track_id=1,
        p_prev=(0.5, 0.2),
        p_curr=(0.5, 0.8),
        line=(0.0, 0.5, 1.0, 0.5),
        direction=TripwireDirection.FORWARD,
        classes_ok=True,
        debouncer=debouncer,
        now=100.0,
        last_any_at=None,
        cooldown=0.0,
    )
    assert should_capture_tripwire(**kwargs) is True
    kwargs["now"] = 101.0
    assert should_capture_tripwire(**kwargs) is False
