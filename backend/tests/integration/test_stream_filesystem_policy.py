"""Filesystem sources are allowlisted and closed outside trusted-local mode."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.streaming.opencv_stream_runner import FakeStreamRunner
from app.main import create_app


def _client(
    tmp_path: Path,
    *,
    trusted_local: bool,
    allowed_roots: list[Path] | None = None,
) -> TestClient:
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        storage_root=tmp_path / "storage",
        trusted_local=trusted_local,
        allowed_roots=allowed_roots,
        stream_runner=FakeStreamRunner(),
    )
    return TestClient(app)


def _project_id(client: TestClient) -> str:
    created = client.post("/api/v1/projects", json={"name": "Policy"})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _image_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "frame.png").write_bytes(b"png")


def test_rejects_folder_outside_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    _image_folder(allowed)
    _image_folder(outside)
    with _client(tmp_path, trusted_local=True, allowed_roots=[allowed]) as client:
        project_id = _project_id(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/streams/image-folder",
            json={"name": "Outside", "folder_path": str(outside)},
        )
    assert response.status_code == 422, response.text


def test_invalid_tripwire_direction_returns_422(tmp_path: Path) -> None:
    with _client(tmp_path, trusted_local=True) as client:
        project_id = _project_id(client)
        stream = client.post(
            f"/api/v1/projects/{project_id}/streams/rtsp",
            json={"name": "Cam", "rtsp_url": "rtsp://127.0.0.1/cam"},
        )
        assert stream.status_code == 201, stream.text
        updated = client.put(
            f"/api/v1/streams/{stream.json()['id']}/triggers",
            json={"config": {"tripwire_direction": "SIDEWAYS"}},
        )
    assert updated.status_code == 422, updated.text


def test_trusted_local_accepts_folder_inside_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    folder = allowed / "stills"
    _image_folder(folder)
    with _client(tmp_path, trusted_local=True, allowed_roots=[allowed]) as client:
        project_id = _project_id(client)
        created = client.post(
            f"/api/v1/projects/{project_id}/streams/image-folder",
            json={"name": "Stills", "folder_path": str(folder)},
        )
        assert created.status_code == 201, created.text
        assert Path(created.json()["source_uri"]) == folder.resolve()


def test_trusted_local_without_allowlist_keeps_any_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "anywhere"
    _image_folder(folder)
    monkeypatch.setattr(
        "app.infrastructure.system.folder_dialog.ask_image_folder",
        lambda: str(folder),
    )
    with _client(tmp_path, trusted_local=True, allowed_roots=[]) as client:
        project_id = _project_id(client)
        created = client.post(
            f"/api/v1/projects/{project_id}/streams/image-folder",
            json={"name": "Anywhere", "folder_path": str(folder)},
        )
        assert created.status_code == 201, created.text
        assert Path(created.json()["source_uri"]) == folder.resolve()
        picked = client.post(f"/api/v1/projects/{project_id}/streams/image-folder/pick")
        assert picked.status_code == 201, picked.text


def test_filesystem_endpoints_closed_outside_trusted_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "local"
    _image_folder(folder)
    called = {"n": 0}

    def _forbidden_dialog() -> str:
        called["n"] += 1
        return str(folder)

    monkeypatch.setattr(
        "app.infrastructure.system.folder_dialog.ask_image_folder",
        _forbidden_dialog,
    )
    with _client(tmp_path, trusted_local=False, allowed_roots=[folder]) as client:
        project_id = _project_id(client)
        created = client.post(
            f"/api/v1/projects/{project_id}/streams/image-folder",
            json={"name": "Local", "folder_path": str(folder)},
        )
        picked = client.post(f"/api/v1/projects/{project_id}/streams/image-folder/pick")
        video = client.post(
            f"/api/v1/projects/{project_id}/streams/upload-video",
            files={"file": ("clip.mp4", b"video", "video/mp4")},
            data={"name": "Clip"},
        )
    assert created.status_code == 404, created.text
    assert picked.status_code == 404, picked.text
    assert called["n"] == 0
    assert video.status_code == 201, video.text
