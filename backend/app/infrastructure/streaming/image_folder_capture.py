from pathlib import Path

import cv2
import numpy as np

from app.domain.services.image_folder import list_image_files


def _imread_unicode(path: Path):
    """cv2.imread fails on Windows paths that contain non-ASCII characters."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


class ImageFolderCapture:
    """Still-image sequence with the VideoCapture read/release surface."""

    def __init__(self, folder: str) -> None:
        self._paths = list_image_files(Path(folder))
        self._index = 0

    def isOpened(self) -> bool:
        return bool(self._paths)

    def read(self):
        if not self._paths:
            return False, None
        for _ in range(len(self._paths)):
            path = self._paths[self._index]
            self._index = (self._index + 1) % len(self._paths)
            frame = _imread_unicode(path)
            if frame is not None:
                return True, frame
        return False, None

    def release(self) -> None:
        self._paths = []
        self._index = 0
