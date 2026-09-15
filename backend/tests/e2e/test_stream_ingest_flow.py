from pathlib import Path
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.application.ports.services.model_predictor import Detection
from app.application.ports.services.stream_runner import IngestJob
from app.infrastructure.streaming.opencv_stream_runner import FakeStreamRunner
from app.main import create_app


def _jpeg_bytes(size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, color=(40, 80, 120)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    runner = FakeStreamRunner()
    db_path = (tmp_path / "app.db").as_posix()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        storage_root=tmp_path / "storage",
        stream_runner=runner,
    )
    with TestClient(app) as test_client:
        test_client.fake_runner = runner  # type: ignore[attr-defined]
        yield test_client


def test_stream_ingest_flow_creates_requires_review(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Ingest"}).json()["id"]
    class_id = client.post(
        f"/api/v1/projects/{project_id}/classes",
        json={"name": "car", "color_hex": "#22C55E"},
    ).json()["id"]
    model = client.post(
        f"/api/v1/projects/{project_id}/models/upload",
        files={"file": ("m.pt", b"weights", "application/octet-stream")},
        data={"name": "M1"},
    ).json()
    stream = client.post(
        f"/api/v1/projects/{project_id}/streams/rtsp",
        json={"name": "Cam", "rtsp_url": "rtsp://127.0.0.1/x"},
    ).json()
    client.put(
        f"/api/v1/streams/{stream['id']}/triggers",
        json={"config": {"timer_enabled": True}, "model_version_id": model["id"]},
    )
    assert client.post(f"/api/v1/streams/{stream['id']}/start").status_code == 200

    runner: FakeStreamRunner = client.app.state.stream_runner
    runner.push_ingest_for_tests(
        IngestJob(
            stream_id=__import__("uuid").UUID(stream["id"]),
            jpeg_bytes=_jpeg_bytes(),
            detections=[
                Detection(
                    class_index=0,
                    confidence=0.77,
                    x_center=0.5,
                    y_center=0.5,
                    width=0.2,
                    height=0.2,
                )
            ],
            reason="timer",
            captured_at=time.time(),
        )
    )

    images = None
    for _ in range(40):
        images = client.get(f"/api/v1/projects/{project_id}/images").json()
        if images:
            break
        time.sleep(0.1)
    assert images, "ingest consumer did not create an image"
    item = images[0]
    assert item["source_type"] == "STREAM_INGEST"
    assert item["status"] == "REQUIRES_REVIEW"

    detail = client.get(f"/api/v1/images/{item['id']}").json()
    assert detail["annotations"]
    assert detail["annotations"][0]["source"] == "MODEL_PREDICTION"
    assert detail["annotations"][0]["verification_status"] == "PENDING_REVIEW"
    assert detail["annotations"][0]["class_id"] == class_id
