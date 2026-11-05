from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.domain.exceptions import DomainValidationException
from app.presentation.api.v1.stream_router import upload_video_stream
from app.presentation.api.v1.training_router import upload_model
from app.presentation.streaming_io import UploadTooLarge, spool_upload


class _ChunkUpload:
    def __init__(self, chunks: list[bytes], filename: str) -> None:
        self._chunks = list(chunks)
        self.filename = filename
        self.reads = 0
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_over_limit_stops_reading_and_discards_partial() -> None:
    upload = _ChunkUpload([b"a" * 10, b"b" * 10, b"c" * 10, b"d" * 10], "clip.mp4")

    with pytest.raises(UploadTooLarge):
        await spool_upload(upload, max_bytes=25, chunk_size=10)

    assert upload.reads == 3
    assert upload._chunks == [b"d" * 10]


@pytest.mark.asyncio
async def test_spool_writes_chunks_under_the_limit() -> None:
    upload = _ChunkUpload([b"abc", b"def"], "best.pt")

    path = await spool_upload(upload, max_bytes=10, chunk_size=3)
    try:
        assert path.read_bytes() == b"abcdef"
        assert upload.reads == 3
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_video_upload_stops_before_use_case(monkeypatch) -> None:
    import app.presentation.api.v1.stream_router as stream_router

    monkeypatch.setattr(stream_router, "_MAX_VIDEO_UPLOAD_BYTES", 10)
    upload = _ChunkUpload([b"x" * 8, b"y" * 8, b"z" * 8], "clip.mp4")
    called = False

    class _UseCase:
        async def upload_video(self, *args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("over-limit upload must not be stored")

    with pytest.raises(HTTPException) as exc_info:
        await upload_video_stream(
            uuid4(),
            request=None,  # type: ignore[arg-type]
            file=upload,  # type: ignore[arg-type]
            name="clip",
            use_case=_UseCase(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 413
    assert called is False
    assert upload.reads == 2
    assert upload.closed is True
    assert upload._chunks == [b"z" * 8]


@pytest.mark.asyncio
async def test_model_upload_stops_before_use_case(monkeypatch) -> None:
    import app.presentation.api.v1.training_router as training_router

    monkeypatch.setattr(training_router, "MAX_MODEL_UPLOAD_BYTES", 10)
    upload = _ChunkUpload([b"x" * 8, b"y" * 8, b"z" * 8], "best.pt")
    called = False

    class _UseCase:
        async def execute(self, *args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("over-limit upload must not be stored")

    with pytest.raises(DomainValidationException):
        await upload_model(
            uuid4(),
            file=upload,  # type: ignore[arg-type]
            name=None,
            use_case=_UseCase(),  # type: ignore[arg-type]
        )

    assert called is False
    assert upload.reads == 2
    assert upload.closed is True
    assert upload._chunks == [b"z" * 8]
