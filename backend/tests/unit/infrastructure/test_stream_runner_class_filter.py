from uuid import uuid4

from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType
from app.domain.services.stream_capture_rules import class_is_allowed
from app.infrastructure.streaming.opencv_stream_runner import FakeStreamRunner


def test_runner_keeps_none_all_and_empty_none_filter() -> None:
    stream = StreamSource.create(uuid4(), "Cam", StreamSourceType.DEVICE, "0")
    runner = FakeStreamRunner()
    runner.start(stream, None, allowed_class_indices=None)
    assert runner._allowed[stream.id] is None
    assert class_is_allowed(0, runner._allowed[stream.id]) is True

    runner.update_triggers(stream.id, stream.config, allowed_class_indices=frozenset())
    assert runner._allowed[stream.id] == frozenset()
    assert class_is_allowed(0, runner._allowed[stream.id]) is False

    runner.update_triggers(
        stream.id, stream.config, allowed_class_indices=frozenset({1})
    )
    assert class_is_allowed(1, runner._allowed[stream.id]) is True
    assert class_is_allowed(0, runner._allowed[stream.id]) is False
