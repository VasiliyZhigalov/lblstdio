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
