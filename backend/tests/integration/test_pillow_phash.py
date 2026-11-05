import io

from PIL import Image as PILImage

from app.domain.services.perceptual_hash import hamming_distance
from app.infrastructure.storage.pillow_metadata import PillowMetadataReader


def _png(color: tuple[int, int, int], size: tuple[int, int] = (64, 48)) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _striped(colors: tuple[tuple[int, int, int], tuple[int, int, int]]) -> bytes:
    image = PILImage.new("RGB", (64, 48))
    pixels = image.load()
    for y in range(48):
        for x in range(64):
            pixels[x, y] = colors[0] if (x // 8 + y // 8) % 2 == 0 else colors[1]
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_identical_frames_share_a_hash() -> None:
    reader = PillowMetadataReader()
    payload = _png((10, 20, 30))
    assert reader.perceptual_hash(payload) == reader.perceptual_hash(payload)


def test_visually_different_frames_are_far_apart() -> None:
    reader = PillowMetadataReader()
    checker = reader.perceptual_hash(_striped(((0, 0, 0), (255, 255, 255))))
    gradient = reader.perceptual_hash(_striped(((255, 0, 0), (0, 0, 255))))
    assert hamming_distance(checker, gradient) > 16
