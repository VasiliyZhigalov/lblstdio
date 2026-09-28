import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.main import create_app


def _png() -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (32, 24), (10, 20, 30)).save(buffer, format="PNG")
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


class TestImagesSummaryApi:
    def test_summary_aggregates_annotations_for_project(self, client: TestClient) -> None:
        project_id = client.post("/api/v1/projects", json={"name": "Sum"}).json()["id"]
        defect_id = client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={"name": "defect", "color_hex": "#EF4444"},
        ).json()["id"]
        uploaded = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[
                ("files", ("a.png", _png(), "image/png")),
                ("files", ("b.png", _png(), "image/png")),
            ],
        )
        assert uploaded.status_code == 201, uploaded.text
        first, second = uploaded.json()
        saved = client.put(
            f"/api/v1/images/{first['id']}/annotations",
            json={
                "boxes": [
                    {
                        "class_id": defect_id,
                        "x_center": 0.4,
                        "y_center": 0.5,
                        "width": 0.2,
                        "height": 0.1,
                    },
                    {
                        "class_id": defect_id,
                        "x_center": 0.7,
                        "y_center": 0.3,
                        "width": 0.2,
                        "height": 0.1,
                    },
                ]
            },
        )
        assert saved.status_code == 200, saved.text

        summary = client.get(f"/api/v1/projects/{project_id}/images/summary")
        assert summary.status_code == 200, summary.text
        body = summary.json()
        assert body["class_counts"][defect_id] == 2
        assert [item["image_id"] for item in body["images"]] == [first["id"]]
        assert body["images"][0]["box_count"] == 2
        assert body["images"][0]["class_ids"] == [defect_id]
        assert len(body["images"][0]["annotations"]) == 2
        assert second["id"] not in {item["image_id"] for item in body["images"]}
