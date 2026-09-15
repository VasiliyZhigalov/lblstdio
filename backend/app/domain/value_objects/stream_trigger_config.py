from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.domain.enums import TripwireDirection
from app.domain.exceptions import DomainValidationException


@dataclass(frozen=True)
class StreamTriggerConfig:
    timer_enabled: bool = False
    timer_interval_seconds: float = 5.0
    tripwire_enabled: bool = False
    tripwire_line: tuple[float, float, float, float] | None = None
    tripwire_classes: tuple[UUID, ...] = field(default_factory=tuple)
    tripwire_direction: TripwireDirection = TripwireDirection.ANY
    tripwire_debounce_seconds: float = 3.0
    uncertainty_range: tuple[float, float] = (0.70, 0.90)
    cooldown_seconds: float = 3.0

    def __post_init__(self) -> None:
        if self.timer_interval_seconds <= 0:
            raise DomainValidationException("timer_interval_seconds must be > 0")
        if self.tripwire_debounce_seconds < 0:
            raise DomainValidationException("tripwire_debounce_seconds must be >= 0")
        if self.cooldown_seconds < 0:
            raise DomainValidationException("cooldown_seconds must be >= 0")

        unc_min, unc_max = self.uncertainty_range
        if not (0.0 <= unc_min < unc_max <= 1.0):
            raise DomainValidationException(
                "uncertainty_range must satisfy 0 <= min < max <= 1"
            )

        if self.tripwire_line is not None:
            if len(self.tripwire_line) != 4:
                raise DomainValidationException("tripwire_line must be (x1,y1,x2,y2)")
            for value in self.tripwire_line:
                if not 0.0 <= value <= 1.0:
                    raise DomainValidationException(
                        "tripwire_line coordinates must be in [0, 1]"
                    )
