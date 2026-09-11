import io
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.main import create_app


def _png(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (width, height), color=(200, 10, 10)).save(buffer, format="PNG")
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


class TestLabelingCycleE2E:
    def test_project_classes_upload_annotate_export_yolo(self, client: TestClient) -> None:
        created = client.post("/api/v1/projects", json={"name": "Test Project"})
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        assert created.json()["name"] == "Test Project"

        defect = client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={"name": "defect", "color_hex": "#EF4444"},
        )
        scratch = client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={"name": "scratch", "color_hex": "#22C55E"},
        )
        assert defect.status_code == 201
        assert scratch.status_code == 201
        assert defect.json()["index_id"] == 0
        assert scratch.json()["index_id"] == 1
        defect_id = defect.json()["id"]
        scratch_id = scratch.json()["id"]

        upload = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[
                ("files", ("frame_a.png", _png(), "image/png")),
                ("files", ("frame_b.png", _png(50, 40), "image/png")),
                ("files", ("frame_c.png", _png(20, 20), "image/png")),
            ],
        )
        assert upload.status_code == 201, upload.text
        images = upload.json()
        assert len(images) == 3
        assert images[0]["width"] == 40 and images[0]["height"] == 30
        first = images[0]

        save = client.put(
            f"/api/v1/images/{first['id']}/annotations",
            json={
                "boxes": [
                    {
                        "class_id": defect_id,
                        "x_center": 0.40,
                        "y_center": 0.50,
                        "width": 0.20,
                        "height": 0.10,
                    },
                    {
                        "class_id": scratch_id,
                        "x_center": 0.70,
                        "y_center": 0.30,
                        "width": 0.15,
                        "height": 0.25,
                    },
                ]
            },
        )
        assert save.status_code == 200, save.text
        boxes = save.json()
        assert len(boxes) == 2
        assert all(item["source"] == "MANUAL" for item in boxes)
        assert all(item["verification_status"] == "VERIFIED" for item in boxes)

        exported = client.get(f"/api/v1/projects/{project_id}/export-yolo")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("application/zip")

        archive = zipfile.ZipFile(io.BytesIO(exported.content))
        names = archive.namelist()
        assert "data.yaml" in names

        data = yaml.safe_load(archive.read("data.yaml"))
        assert data["names"][0] == "defect"
        assert data["names"][1] == "scratch"

        split = first["split"]
        label_name = f"{split}/labels/{first['id']}.txt"
        image_name = f"{split}/images/{first['id']}.png"
        assert label_name in names
        assert image_name in names
        lines = archive.read(label_name).decode("utf-8").strip().splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("0 ")
        assert lines[1].startswith("1 ")
        assert "0.400000" in lines[0]
        assert "0.700000" in lines[1]

    def test_swagger_docs_are_available(self, client: TestClient) -> None:
        docs = client.get("/docs")
        schema = client.get("/openapi.json")
        assert docs.status_code == 200
        assert schema.status_code == 200
        paths = schema.json()["paths"]
        assert "/api/v1/projects" in paths
        assert "/api/v1/projects/{project_id}/export-yolo" in paths

    def test_frontend_index_is_served(self, client: TestClient) -> None:
        home = client.get("/")
        assert home.status_code == 200
        assert b"annotation-canvas" in home.content
        app_js = client.get("/js/app.js")
        assert app_js.status_code == 200

    def test_invalid_box_returns_422(self, client: TestClient) -> None:
        project_id = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
        class_id = client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={"name": "defect", "color_hex": "#EF4444"},
        ).json()["id"]
        image_id = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[("files", ("a.png", _png(), "image/png"))],
        ).json()[0]["id"]

        response = client.put(
            f"/api/v1/images/{image_id}/annotations",
            json={
                "boxes": [
                    {
                        "class_id": class_id,
                        "x_center": 1.5,
                        "y_center": 0.5,
                        "width": 0.2,
                        "height": 0.1,
                    }
                ]
            },
        )
        assert response.status_code == 422

    def test_delete_first_of_three_classes_reindexes(self, client: TestClient) -> None:
        project_id = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
        created = []
        for name, color in (("a", "#111111"), ("b", "#222222"), ("c", "#333333")):
            created.append(
                client.post(
                    f"/api/v1/projects/{project_id}/classes",
                    json={"name": name, "color_hex": color},
                ).json()
            )
        deleted = client.delete(
            f"/api/v1/projects/{project_id}/classes/{created[0]['id']}"
        )
        assert deleted.status_code == 204
        remaining = client.get(f"/api/v1/projects/{project_id}/classes").json()
        assert sorted(item["index_id"] for item in remaining) == [0, 1]
        assert {item["name"] for item in remaining} == {"b", "c"}

    def test_delete_class_under_wrong_project_is_404(self, client: TestClient) -> None:
        first = client.post("/api/v1/projects", json={"name": "A"}).json()["id"]
        second = client.post("/api/v1/projects", json={"name": "B"}).json()["id"]
        class_id = client.post(
            f"/api/v1/projects/{first}/classes",
            json={"name": "a", "color_hex": "#111111"},
        ).json()["id"]
        response = client.delete(f"/api/v1/projects/{second}/classes/{class_id}")
        assert response.status_code == 404

    def test_jpg_upload_and_image_filters(self, client: TestClient) -> None:
        buffer = io.BytesIO()
        PILImage.new("RGB", (12, 8), (0, 128, 255)).save(buffer, format="JPEG")
        project_id = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
        uploaded = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[("files", ("shot.jpg", buffer.getvalue(), "image/jpeg"))],
        )
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.json()[0]["width"] == 12
        listing = client.get(
            f"/api/v1/projects/{project_id}/images",
            params={"split": uploaded.json()[0]["split"]},
        )
        assert listing.status_code == 200
        assert len(listing.json()) == 1


def test_delete_project_removes_files(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        storage_root=storage,
    )
    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"name": "Gone"}).json()["id"]
        client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[("files", ("a.png", _png(), "image/png"))],
        )
        assert any(storage.rglob("*.png"))
        deleted = client.delete(f"/api/v1/projects/{project_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/projects/{project_id}").status_code == 404
        assert list(storage.rglob("*.png")) == []
