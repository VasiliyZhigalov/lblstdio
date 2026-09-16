from uuid import UUID, uuid4

import pytest

from app.application.use_cases.streaming.manage_stream_source import ManageStreamSourceUseCase
from app.domain.entities.project import Project
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig


class _FakeProjects:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get_by_id(self, project_id: UUID):
        return self.project if self.project.id == project_id else None


class _FakeStreams:
    def __init__(self) -> None:
        self.by_id: dict[UUID, StreamSource] = {}

    async def add(self, stream: StreamSource) -> None:
        self.by_id[stream.id] = stream

    async def get_by_id(self, stream_id: UUID):
        return self.by_id.get(stream_id)

    async def list_by_project(self, project_id: UUID):
        return [s for s in self.by_id.values() if s.project_id == project_id]

    async def update(self, stream: StreamSource) -> None:
        self.by_id[stream.id] = stream

    async def delete(self, stream_id: UUID) -> None:
        self.by_id.pop(stream_id, None)


class _FakeModels:
    async def get_by_id(self, version_id: UUID):
        return None


class _FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, relative_dir: str, filename: str, data: bytes) -> str:
        path = f"{relative_dir}/{filename}"
        self.files[path] = data
        return path

    async def delete(self, relative_path: str) -> None:
        self.files.pop(relative_path, None)


class _FakeUow:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _uc():
    project = Project.create("P")
    streams = _FakeStreams()
    storage = _FakeStorage()
    return (
        ManageStreamSourceUseCase(
            _FakeProjects(project), streams, _FakeModels(), storage, _FakeUow()
        ),
        project,
        streams,
        storage,
    )


@pytest.mark.asyncio
async def test_create_rtsp_and_configure() -> None:
    uc, project, streams, _ = _uc()
    src = await uc.create_rtsp(project.id, "Gate", "rtsp://127.0.0.1/stream")
    assert src.source_type == StreamSourceType.RTSP
    cfg = StreamTriggerConfig(track_stable_enabled=True, track_stable_interval_seconds=2.0)
    updated = await uc.configure_triggers(src.id, cfg)
    assert updated.config.track_stable_enabled is True
    assert streams.by_id[src.id].config.track_stable_interval_seconds == 2.0


@pytest.mark.asyncio
async def test_upload_video_rejects_bad_extension() -> None:
    uc, project, _, _ = _uc()
    with pytest.raises(DomainValidationException):
        await uc.upload_video(project.id, "bad", "clip.txt", b"data")


@pytest.mark.asyncio
async def test_delete_video_removes_file() -> None:
    uc, project, streams, storage = _uc()
    src = await uc.upload_video(project.id, "clip", "a.mp4", b"video-bytes")
    assert src.source_uri in storage.files
    await uc.delete(src.id)
    assert src.id not in streams.by_id
    assert src.source_uri not in storage.files


@pytest.mark.asyncio
async def test_upload_video_rejects_oversized(monkeypatch) -> None:
    import app.application.use_cases.streaming.manage_stream_source as mod

    monkeypatch.setattr(mod, "_MAX_VIDEO_BYTES", 10)
    uc, project, _, _ = _uc()
    with pytest.raises(DomainValidationException):
        await uc.upload_video(project.id, "big", "a.mp4", b"x" * 11)


@pytest.mark.asyncio
async def test_create_rtsp_rejects_metadata_host() -> None:
    uc, project, _, _ = _uc()
    with pytest.raises(DomainValidationException):
        await uc.create_rtsp(project.id, "bad", "rtsp://169.254.169.254/latest")


@pytest.mark.asyncio
async def test_cannot_delete_active_stream() -> None:
    uc, project, streams, _ = _uc()
    src = await uc.create_device(project.id, "Webcam", 0)
    streams.by_id[src.id].activate()
    with pytest.raises(DomainValidationException):
        await uc.delete(src.id)
