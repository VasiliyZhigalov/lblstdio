from dataclasses import dataclass

from app.domain.exceptions import DomainValidationException


@dataclass(frozen=True)
class SplitRatios:
    train: float = 0.7
    valid: float = 0.2
    test: float = 0.1

    def __post_init__(self) -> None:
        for name, value in (
            ("train", self.train),
            ("valid", self.valid),
            ("test", self.test),
        ):
            if value < 0:
                raise DomainValidationException(f"{name} split ratio cannot be negative")
        total = self.train + self.valid + self.test
        if abs(total - 1.0) > 1e-9:
            raise DomainValidationException("split ratios must sum to 1.0")
