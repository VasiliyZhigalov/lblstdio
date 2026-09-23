from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import UploadFile


class UploadTooLarge(Exception):
    def __init__(self, limit_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        super().__init__(f"upload exceeds {limit_bytes} bytes")


async def spool_upload(
    upload: UploadFile,
    *,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Copy an upload to a temp file. Stop reading as soon as the limit is crossed."""
    handle = tempfile.NamedTemporaryFile(delete=False)
    path = Path(handle.name)
    total = 0
    try:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise UploadTooLarge(max_bytes)
            handle.write(chunk)
    except BaseException:
        handle.close()
        path.unlink(missing_ok=True)
        raise
    handle.close()
    return path


def discard_file(path: str) -> None:
    Path(path).unlink(missing_ok=True)
