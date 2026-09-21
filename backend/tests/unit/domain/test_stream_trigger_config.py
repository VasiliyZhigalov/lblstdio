import pytest

from app.domain.enums import TripwireDirection
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig


def test_defaults_are_valid():
    cfg = StreamTriggerConfig()
    assert cfg.track_stable_enabled is True
    assert cfg.timer_enabled is False
    assert cfg.timer_interval_seconds == 5.0
    assert cfg.track_stable_min_frames == 12
    assert cfg.track_stable_max_size_variation == 0.35
    assert cfg.track_stable_min_avg_conf == 0.75
    assert cfg.track_stable_interval_seconds == 5.0
    assert cfg.cooldown_seconds == 3.0
    assert cfg.tripwire_direction == TripwireDirection.ANY


def test_rejects_invalid_track_stable_params():
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(track_stable_min_frames=1)
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(track_stable_max_size_variation=-0.1)
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(track_stable_min_avg_conf=0.0)
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(timer_interval_seconds=0.0)


def test_rejects_line_coords_outside_unit_square():
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(tripwire_line=(0.0, 0.0, 1.5, 1.0))
