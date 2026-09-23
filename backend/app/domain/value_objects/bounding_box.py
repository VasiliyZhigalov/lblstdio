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

    def pixel_slice(self, image_width: int, image_height: int) -> tuple[int, int, int, int]:
        """Exclusive pixel box (left, top, right, bottom) for PIL crop."""
        if image_width <= 0 or image_height <= 0:
            raise DomainValidationException("image dimensions must be positive")
        x1 = int(round((self.x_center - self.width / 2) * image_width))
        y1 = int(round((self.y_center - self.height / 2) * image_height))
        x2 = int(round((self.x_center + self.width / 2) * image_width))
        y2 = int(round((self.y_center + self.height / 2) * image_height))
        x1 = min(max(x1, 0), image_width - 1)
        y1 = min(max(y1, 0), image_height - 1)
        x2 = min(max(x2, x1 + 1), image_width)
        y2 = min(max(y2, y1 + 1), image_height)
        return x1, y1, x2, y2
