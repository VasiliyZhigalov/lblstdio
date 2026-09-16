import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.main import create_app


def _png(color: tuple[int, int, int] = (80, 120, 160)) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (64, 48), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    db_path = (tmp_path / "app.db").as_posix()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        storage_root=tmp_path / "storage",
    )
    with TestClient(app) as test_client:
        yield test_client


class TestDeleteImageApi:
    def test_delete_image_removes_detail_and_file(self, client: TestClient, tmp_path: Path) -> None:
        project_id = client.post("/api/v1/projects", json={"name": "Del"}).json()["id"]
        uploaded = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[("files", ("shot.png", _png(), "image/png"))],
        )
        assert uploaded.status_code == 201, uploaded.text
        image = uploaded.json()[0]
        image_id = image["id"]

        file_before = client.get(f"/api/v1/images/{image_id}/file")
        assert file_before.status_code == 200

        deleted = client.delete(f"/api/v1/images/{image_id}")
        assert deleted.status_code == 204, deleted.text

        assert client.get(f"/api/v1/images/{image_id}").status_code == 404
        listed = client.get(f"/api/v1/projects/{project_id}/images").json()
        assert listed == []
        assert client.get(f"/api/v1/images/{image_id}/file").status_code == 404

    def test_delete_missing_image_returns_404(self, client: TestClient) -> None:
        response = client.delete("/api/v1/images/00000000-0000-4000-8000-000000000001")
        assert response.status_code == 404
