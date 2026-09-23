from uuid import uuid4

import pytest

from app.application.ports.services.stream_runner import StreamStatus
from app.application.use_cases.streaming.control_stream import StartStreamUseCase
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.model_version import ModelVersion
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig


class _Streams:
    def __init__(self, *items: StreamSource) -> None:
        self.by_id = {s.id: s for s in items}

    async def get_by_id(self, stream_id):
        return self.by_id.get(stream_id)

    async def get_active_for_project(self, project_id):
        for s in self.by_id.values():
            if s.project_id == project_id and s.is_active:
                return s
        return None

    async def update(self, stream) -> None:
        self.by_id[stream.id] = stream


class _Models:
    def __init__(self, model: ModelVersion) -> None:
        self.model = model

    async def get_by_id(self, version_id):
        return self.model if self.model.id == version_id else None


class _NoModels:
    async def get_by_id(self, version_id):
        return None


class _Classes:
    async def list_by_project(self, project_id):
        return [AnnotationClass.create(project_id, "obj", "#ffffff", 0)]


class _Storage:
    def get_absolute_path(self, relative: str) -> str:
        return f"/abs/{relative}"


class _Runner:
    def __init__(self) -> None:
        self.stopped: list[tuple] = []
        self.started: list = []
        self.weights: list[str | None] = []

    def stop(self, stream_id) -> None:
        self.stopped.append(("stop", stream_id))

    def stop_project(self, project_id) -> None:
        self.stopped.append(("stop_project", project_id))

    def start(self, stream, weights, *, allowed_class_indices=None) -> None:
        self.started.append(stream.id)
        self.weights.append(weights)

    def wait_until_ready(self, stream_id, timeout: float = 30.0) -> StreamStatus:
        return StreamStatus(is_running=True, state="running")


class _Uow:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_start_deactivates_other_active_stream_in_project() -> None:
    project_id = uuid4()
    model = ModelVersion.create_uploaded(project_id, 1, "w.pt", name="m")
    a = StreamSource.create(
        project_id, "A", StreamSourceType.DEVICE, "0", model_version_id=model.id
    )
    a.activate()
    b = StreamSource.create(
        project_id, "B", StreamSourceType.DEVICE, "1", model_version_id=model.id
    )
    streams = _Streams(a, b)
    runner = _Runner()

    await StartStreamUseCase(
        streams, _Models(model), _Classes(), _Storage(), runner, _Uow()
    ).execute(b.id)

    assert streams.by_id[a.id].is_active is False
    assert streams.by_id[b.id].is_active is True
    assert ("stop", a.id) in runner.stopped
    assert b.id in runner.started


@pytest.mark.asyncio
async def test_timer_stream_can_start_without_model() -> None:
    project_id = uuid4()
    stream = StreamSource.create(
        project_id,
        "Timer",
        StreamSourceType.DEVICE,
        "0",
        config=StreamTriggerConfig(timer_enabled=True),
    )
    streams = _Streams(stream)
    runner = _Runner()

    await StartStreamUseCase(
        streams, _NoModels(), _Classes(), _Storage(), runner, _Uow()
    ).execute(stream.id)

    assert stream.is_active is True
    assert stream.id in runner.started
    assert runner.weights == [None]


class _SwapRunner:
    """Stops the running source on start, matching a runner that preempts the project."""

    def __init__(self, fail_id) -> None:
        self.fail_id = fail_id
        self.running: dict = {}
        self.started: list = []
        self.stopped: list = []

    def stop(self, stream_id) -> None:
        self.stopped.append(("stop", stream_id))
        self.running[stream_id] = False

    def stop_project(self, project_id) -> None:
        self.stopped.append(("stop_project", project_id))

    def start(self, stream, weights, *, allowed_class_indices=None) -> None:
        for sid, is_on in list(self.running.items()):
            if is_on and sid != stream.id:
                self.stop(sid)
        self.started.append(stream.id)
        self.running[stream.id] = stream.id != self.fail_id

    def wait_until_ready(self, stream_id, timeout: float = 30.0) -> StreamStatus:
        if self.running.get(stream_id):
            return StreamStatus(is_running=True, state="running")
        return StreamStatus(
            is_running=False,
            state="error",
            error_message="failed to open camera",
        )

    def get_status(self, stream_id) -> StreamStatus:
        if self.running.get(stream_id):
            return StreamStatus(is_running=True, state="running")
        return StreamStatus(is_running=False, state="stopped")


class _CountingUow:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_failed_replacement_keeps_previous_stream_active() -> None:
    project_id = uuid4()
    model = ModelVersion.create_uploaded(project_id, 1, "w.pt", name="m")
    current = StreamSource.create(
        project_id, "A", StreamSourceType.DEVICE, "0", model_version_id=model.id
    )
    current.activate()
    replacement = StreamSource.create(
        project_id, "B", StreamSourceType.DEVICE, "1", model_version_id=model.id
    )
    streams = _Streams(current, replacement)
    runner = _SwapRunner(fail_id=replacement.id)
    runner.running[current.id] = True
    uow = _CountingUow()

    with pytest.raises(DomainValidationException, match="failed to open camera"):
        await StartStreamUseCase(
            streams, _Models(model), _Classes(), _Storage(), runner, uow
        ).execute(replacement.id)

    assert streams.by_id[current.id].is_active is True
    assert streams.by_id[replacement.id].is_active is False
    assert runner.running[current.id] is True
    assert uow.commits == 0
