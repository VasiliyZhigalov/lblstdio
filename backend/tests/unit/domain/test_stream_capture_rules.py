from app.domain.enums import TripwireDirection
from app.domain.services.stream_capture_rules import (
    should_capture_timer,
    should_capture_tripwire,
)
from app.domain.services.tripwire import TripwireDebouncer


def test_timer_requires_uncertainty_and_interval():
    assert (
        should_capture_timer(
            now=10.0,
            last_timer_at=None,
            last_any_at=None,
            interval=5.0,
            cooldown=3.0,
            confidences=[0.8],
            unc_range=(0.7, 0.9),
        )
        is True
    )
    assert (
        should_capture_timer(
            now=12.0,
            last_timer_at=10.0,
            last_any_at=10.0,
            interval=5.0,
            cooldown=3.0,
            confidences=[0.8],
            unc_range=(0.7, 0.9),
        )
        is False
    )
    assert (
        should_capture_timer(
            now=20.0,
            last_timer_at=10.0,
            last_any_at=10.0,
            interval=5.0,
            cooldown=3.0,
            confidences=[0.95],
            unc_range=(0.7, 0.9),
        )
        is False
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
