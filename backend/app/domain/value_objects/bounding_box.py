from dataclasses import dataclass

from app.domain.exceptions import DomainValidationException


@dataclass(frozen=True)
class BoundingBox:
    x_center: float
    y_center: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise DomainValidationException("width must be a positive value in (0, 1]")
        if self.height <= 0:
            raise DomainValidationException("height must be a positive value in (0, 1]")

        for name, value in (
            ("x_center", self.x_center),
            ("y_center", self.y_center),
            ("width", self.width),
            ("height", self.height),
        ):
            if not 0.0 <= value <= 1.0:
                raise DomainValidationException(
                    f"{name} must be in [0, 1], got {value}"
                )

        # Match YOLO 6-decimal export: independent rounding of center/size
        # can overshoot edges by ~1e-6 without leaving the image.
        eps = 1e-6
        left = self.x_center - self.width / 2
        right = self.x_center + self.width / 2
        top = self.y_center - self.height / 2
        bottom = self.y_center + self.height / 2
        if left < -eps or top < -eps or right > 1.0 + eps or bottom > 1.0 + eps:
            raise DomainValidationException(
                "bounding box extends outside the normalized [0, 1] frame"
            )

    def to_yolo_coords(self) -> str:
        return (
            f"{self.x_center:.6f} {self.y_center:.6f} "
            f"{self.width:.6f} {self.height:.6f}"
        )
