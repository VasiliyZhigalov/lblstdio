from uuid import uuid4

from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType


def test_create_defaults_inactive_zero_captures():
    src = StreamSource.create(
        project_id=uuid4(),
        name="Gate cam",
        source_type=StreamSourceType.RTSP,
        source_uri="rtsp://127.0.0.1/stream",
    )
    assert src.is_active is False
    assert src.captured_frames_count == 0
    assert src.model_version_id is None
