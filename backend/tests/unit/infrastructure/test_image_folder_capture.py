from pathlib import Path
from uuid import uuid4

from PIL import Image as PILImage

from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig
from app.infrastructure.streaming.image_folder_capture import ImageFolderCapture
from app.infrastructure.streaming.opencv_stream_runner import OpenCVStreamRunner


def _png(path: Path, color: tuple[int, int, int]) -> None:
    PILImage.new("RGB", (32, 24), color).save(path, format="PNG")


def test_image_folder_capture_loops_in_name_order(tmp_path: Path) -> None:
    _png(tmp_path / "b.png", (0, 0, 255))
    _png(tmp_path / "a.png", (255, 0, 0))
    (tmp_path / "skip.txt").write_text("no", encoding="utf-8")

    cap = ImageFolderCapture(str(tmp_path))
    assert cap.isOpened()
    ok1, first = cap.read()
    ok2, second = cap.read()
    ok3, third = cap.read()
    cap.release()

    assert ok1 and ok2 and ok3
    assert first.shape[:2] == (24, 32)
    assert int(first[0, 0, 2]) > int(first[0, 0, 0])
    assert int(second[0, 0, 0]) > int(second[0, 0, 2])
    assert int(third[0, 0, 2]) > int(third[0, 0, 0])


def test_image_folder_runner_publishes_preview(tmp_path: Path) -> None:
    _png(tmp_path / "frame.png", (10, 20, 30))
    stream = StreamSource.create(
        project_id=uuid4(),
        name="Stills",
        source_type=StreamSourceType.IMAGE_FOLDER,
        source_uri=str(tmp_path),
        config=StreamTriggerConfig(timer_enabled=True, track_stable_enabled=False),
    )
    runner = OpenCVStreamRunner()
    try:
        runner.start(stream, None)
        status = runner.wait_until_ready(stream.id, timeout=5.0)
        assert status.state == "running", status.error_message
        jpeg = runner.latest_jpeg(stream.id)
        assert jpeg is not None and len(jpeg) > 0
    finally:
        runner.stop(stream.id)
