import io

from PIL import Image, UnidentifiedImageError

from app.application.ports.services.image_metadata import IImageMetadataReader
from app.domain.exceptions import DomainValidationException


class PillowMetadataReader(IImageMetadataReader):
    def read_size(self, data: bytes) -> tuple[int, int]:
        try:
            with Image.open(io.BytesIO(data)) as image:
                return image.size
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ) as exc:
            raise DomainValidationException("file is not a valid image") from exc

    def perceptual_hash(self, data: bytes) -> int:
        try:
            with Image.open(io.BytesIO(data)) as image:
                gray = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
                pixels = (
                    list(gray.get_flattened_data())
                    if hasattr(gray, "get_flattened_data")
                    else list(gray.getdata())
                )
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ) as exc:
            raise DomainValidationException("file is not a valid image") from exc
        average = sum(pixels) / len(pixels)
        bits = 0
        for pixel in pixels:
            bits = (bits << 1) | (1 if pixel >= average else 0)
        return bits
