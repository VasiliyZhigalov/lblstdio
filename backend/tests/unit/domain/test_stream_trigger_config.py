import pytest

from app.domain.enums import TripwireDirection
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig


def test_defaults_are_valid():
    cfg = StreamTriggerConfig()
    assert cfg.uncertainty_range == (0.70, 0.90)
    assert cfg.cooldown_seconds == 3.0
    assert cfg.tripwire_direction == TripwireDirection.ANY


def test_rejects_inverted_uncertainty_range():
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(uncertainty_range=(0.9, 0.5))


def test_rejects_line_coords_outside_unit_square():
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(tripwire_line=(0.0, 0.0, 1.5, 1.0))
