import pytest

from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.bounding_box import BoundingBox


class TestBoundingBoxInvariant:
    def test_creates_box_with_normalized_coordinates(self) -> None:
        box = BoundingBox(
            x_center=0.5,
            y_center=0.4,
            width=0.2,
            height=0.1,
        )

        assert box.x_center == 0.5
        assert box.y_center == 0.4
        assert box.width == 0.2
        assert box.height == 0.1

    def test_allows_full_frame_box(self) -> None:
        box = BoundingBox(x_center=0.5, y_center=0.5, width=1.0, height=1.0)

        assert box.width == 1.0
        assert box.height == 1.0

    def test_rejects_box_that_extends_outside_the_frame(self) -> None:
        with pytest.raises(DomainValidationException, match="outside"):
            BoundingBox(x_center=0.95, y_center=0.5, width=0.2, height=0.1)

    def test_allows_six_decimal_edge_rounding_noise(self) -> None:
        """Frontend round6 of center/size can leave ~1e-6 edge overshoot."""
        box = BoundingBox(
            x_center=0.000781,
            y_center=0.5,
            width=0.001563,
            height=0.1,
        )
        assert box.x_center == 0.000781
        assert box.width == 0.001563

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("x_center", -0.01),
            ("x_center", 1.01),
            ("y_center", -0.1),
            ("y_center", 1.5),
            ("width", 1.2),
            ("height", 2.0),
        ],
    )
    def test_rejects_coordinates_outside_unit_interval(
        self, field: str, value: float
    ) -> None:
        kwargs = {
            "x_center": 0.5,
            "y_center": 0.5,
            "width": 0.2,
            "height": 0.2,
            field: value,
        }

        with pytest.raises(DomainValidationException, match="[0, 1]"):
            BoundingBox(**kwargs)

    @pytest.mark.parametrize("width", [0.0, -0.1, -1.0])
    def test_rejects_non_positive_width(self, width: float) -> None:
        with pytest.raises(DomainValidationException, match="width"):
            BoundingBox(x_center=0.5, y_center=0.5, width=width, height=0.2)

    @pytest.mark.parametrize("height", [0.0, -0.1, -1.0])
    def test_rejects_non_positive_height(self, height: float) -> None:
        with pytest.raises(DomainValidationException, match="height"):
            BoundingBox(x_center=0.5, y_center=0.5, width=0.2, height=height)

    def test_yolo_line_uses_six_decimal_places(self) -> None:
        box = BoundingBox(x_center=0.5, y_center=0.25, width=0.2, height=0.1)

        assert box.to_yolo_coords() == "0.500000 0.250000 0.200000 0.100000"

    def test_pixel_slice_maps_normalized_box(self) -> None:
        box = BoundingBox(x_center=0.4, y_center=0.6, width=0.1, height=0.2)

        assert box.pixel_slice(100, 80) == (35, 40, 45, 56)

    def test_pixel_slice_covers_full_frame(self) -> None:
        box = BoundingBox(x_center=0.5, y_center=0.5, width=1.0, height=1.0)

        assert box.pixel_slice(100, 80) == (0, 0, 100, 80)
