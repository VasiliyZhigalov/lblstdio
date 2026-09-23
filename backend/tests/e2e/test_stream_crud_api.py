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


def test_pick_image_folder_stream(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "picked"
    folder.mkdir()
    (folder / "frame.png").write_bytes(b"png")
    monkeypatch.setattr(
        "app.infrastructure.system.folder_dialog.ask_image_folder",
        lambda: str(folder),
    )
    project_id = client.post("/api/v1/projects", json={"name": "Pick"}).json()["id"]
    created = client.post(f"/api/v1/projects/{project_id}/streams/image-folder/pick")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source_type"] == "IMAGE_FOLDER"
    assert Path(body["source_uri"]) == folder.resolve()
    assert body["name"] == "picked"


def test_pick_image_folder_cancel(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.infrastructure.system.folder_dialog.ask_image_folder",
        lambda: None,
    )
    project_id = client.post("/api/v1/projects", json={"name": "PickCancel"}).json()["id"]
    created = client.post(f"/api/v1/projects/{project_id}/streams/image-folder/pick")
    assert created.status_code == 204
    assert client.get(f"/api/v1/projects/{project_id}/streams").json() == []


def test_create_image_folder_stream(client: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "stills"
    folder.mkdir()
    (folder / "frame.png").write_bytes(b"png")
    project_id = client.post("/api/v1/projects", json={"name": "Folder"}).json()["id"]
    created = client.post(
        f"/api/v1/projects/{project_id}/streams/image-folder",
        json={"name": "Stills", "folder_path": str(folder)},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source_type"] == "IMAGE_FOLDER"
    assert Path(body["source_uri"]) == folder.resolve()


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
                "track_stable_enabled": True,
                "track_stable_min_frames": 10,
                "track_stable_max_size_variation": 0.25,
                "track_stable_interval_seconds": 4.0,
            }
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["config"]["track_stable_enabled"] is True
    assert updated.json()["config"]["track_stable_min_frames"] == 10
    assert updated.json()["config"]["track_stable_interval_seconds"] == 4.0

    deleted = client.delete(f"/api/v1/streams/{stream_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/projects/{project_id}/streams").json() == []
