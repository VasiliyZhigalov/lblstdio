from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    db_path = (tmp_path / "app.db").as_posix()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        storage_root=tmp_path / "storage",
    )
    with TestClient(app) as test_client:
        yield test_client


def test_stream_crud_api(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "StreamProj"}).json()["id"]

    created = client.post(
        f"/api/v1/projects/{project_id}/streams/rtsp",
        json={"name": "Gate", "rtsp_url": "rtsp://127.0.0.1/cam"},
    )
    assert created.status_code == 201, created.text
    stream_id = created.json()["id"]

    listed = client.get(f"/api/v1/projects/{project_id}/streams")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.put(
        f"/api/v1/streams/{stream_id}/triggers",
        json={
            "config": {
                "timer_enabled": True,
                "timer_interval_seconds": 4.0,
                "uncertainty_range": [0.6, 0.85],
            }
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["config"]["timer_enabled"] is True
    assert updated.json()["config"]["timer_interval_seconds"] == 4.0

    deleted = client.delete(f"/api/v1/streams/{stream_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/projects/{project_id}/streams").json() == []
