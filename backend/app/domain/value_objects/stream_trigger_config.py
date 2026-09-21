from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.domain.enums import TripwireDirection
from app.domain.exceptions import DomainValidationException


@dataclass(frozen=True)
class StreamTriggerConfig:
    """Capture triggers for a live stream.

    Primary harvest mode is track-stability (ByteTrack continuity), not a
    wall-clock timer. Tripwire remains an optional event-driven path.
    """

    track_stable_enabled: bool = True
    track_stable_min_frames: int = 12
    track_stable_max_size_variation: float = 0.35
    track_stable_min_avg_conf: float = 0.75
    track_stable_interval_seconds: float = 5.0
    tripwire_enabled: bool = False
    tripwire_line: tuple[float, float, float, float] | None = None
    tripwire_classes: tuple[UUID, ...] = field(default_factory=tuple)
    tripwire_direction: TripwireDirection = TripwireDirection.ANY
    tripwire_debounce_seconds: float = 3.0
    cooldown_seconds: float = 3.0

    def __post_init__(self) -> None:
        if self.track_stable_min_frames < 2:
            raise DomainValidationException("track_stable_min_frames must be >= 2")
        if self.track_stable_max_size_variation < 0:
            raise DomainValidationException(
                "track_stable_max_size_variation must be >= 0"
            )
        if not 0.0 < self.track_stable_min_avg_conf <= 1.0:
            raise DomainValidationException(
                "track_stable_min_avg_conf must be in (0, 1]"
            )
        if self.track_stable_interval_seconds <= 0:
            raise DomainValidationException(
                "track_stable_interval_seconds must be > 0"
            )
        if self.tripwire_debounce_seconds < 0:
            raise DomainValidationException("tripwire_debounce_seconds must be >= 0")
        if self.cooldown_seconds < 0:
            raise DomainValidationException("cooldown_seconds must be >= 0")

        if self.tripwire_line is not None:
            if len(self.tripwire_line) != 4:
                raise DomainValidationException("tripwire_line must be (x1,y1,x2,y2)")
            for value in self.tripwire_line:
                if not 0.0 <= value <= 1.0:
                    raise DomainValidationException(
                        "tripwire_line coordinates must be in [0, 1]"
                    )
