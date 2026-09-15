from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.streaming.opencv_stream_runner import FakeStreamRunner
from app.main import create_app


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
        yield test_client


def test_stream_start_status_live_buffer_stop(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Live"}).json()["id"]
    model = client.post(
        f"/api/v1/projects/{project_id}/models/upload",
        files={"file": ("m.pt", b"weights", "application/octet-stream")},
        data={"name": "M1"},
    ).json()

    stream = client.post(
        f"/api/v1/projects/{project_id}/streams/rtsp",
        json={"name": "Cam", "rtsp_url": "rtsp://127.0.0.1/x"},
    ).json()
    stream_id = stream["id"]

    configured = client.put(
        f"/api/v1/streams/{stream_id}/triggers",
        json={"config": {"timer_enabled": True}, "model_version_id": model["id"]},
    )
    assert configured.status_code == 200, configured.text

    started = client.post(f"/api/v1/streams/{stream_id}/start")
    assert started.status_code == 200, started.text
    assert started.json()["is_active"] is True

    status = client.get(f"/api/v1/streams/{stream_id}/status")
    assert status.status_code == 200
    assert status.json()["is_running"] is True
    assert status.json()["state"] == "running"

    # Infinite MJPEG Response hangs Starlette TestClient; assert buffer instead.
    jpeg = client.app.state.stream_runner.latest_jpeg(UUID(stream_id))
    assert jpeg is not None and len(jpeg) > 0

    stopped = client.post(f"/api/v1/streams/{stream_id}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["is_active"] is False


def test_stream_start_failure_keeps_inactive(client: TestClient) -> None:
    runner: FakeStreamRunner = client.app.state.stream_runner
    runner.fail_start_message = "boom"
    project_id = client.post("/api/v1/projects", json={"name": "Fail"}).json()["id"]
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
        json={"config": {}, "model_version_id": model["id"]},
    )
    failed = client.post(f"/api/v1/streams/{stream['id']}/start")
    assert failed.status_code == 422
    listed = client.get(f"/api/v1/projects/{project_id}/streams").json()
    assert listed[0]["is_active"] is False


def test_stream_live_404_for_unknown(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000099"
    response = client.get(f"/api/v1/streams/{missing}/live")
    assert response.status_code == 404
