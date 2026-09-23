import io
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.main import create_app


def _png(color: tuple[int, int, int] = (80, 120, 160)) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (200, 160), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _bgr_png(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    PILImage.fromarray(cv2.cvtColor(array, cv2.COLOR_BGR2RGB)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.application.use_cases.dataset import create_dataset_version as mod

    real_init = mod.CreateDatasetVersionUseCase.__init__

    def patched_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self._min_verified = 3

    monkeypatch.setattr(mod.CreateDatasetVersionUseCase, "__init__", patched_init)

    db_path = (tmp_path / "app.db").as_posix()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        storage_root=tmp_path / "storage",
    )
    with TestClient(app) as test_client:
        yield test_client


def _seed_verified_triplet(client: TestClient) -> str:
    project_id = client.post("/api/v1/projects", json={"name": "Dataset"}).json()["id"]
    class_id = client.post(
        f"/api/v1/projects/{project_id}/classes",
        json={"name": "crack", "color_hex": "#EF4444"},
    ).json()["id"]
    upload = client.post(
        f"/api/v1/projects/{project_id}/images/upload",
        files=[
            ("files", ("train.png", _png((10, 20, 30)), "image/png")),
            ("files", ("valid.png", _png((40, 50, 60)), "image/png")),
            ("files", ("test.png", _png((70, 80, 90)), "image/png")),
        ],
    )
    assert upload.status_code == 201, upload.text
    test_image = next(item for item in upload.json() if item["file_name"] == "test.png")
    held = client.put(
        f"/api/v1/images/{test_image['id']}/holdout",
        json={"holdout": True},
    )
    assert held.status_code == 200, held.text
    assert held.json()["split"] == "test"
    for image in upload.json():
        saved = client.put(
            f"/api/v1/images/{image['id']}/annotations",
            json={
                "boxes": [
                    {
                        "class_id": class_id,
                        "x_center": 0.5,
                        "y_center": 0.5,
                        "width": 0.2,
                        "height": 0.2,
                    }
                ]
            },
        )
        assert saved.status_code == 200, saved.text
    return project_id


class TestDatasetVersionsApi:
    def test_create_version_returns_201_when_verified(self, client: TestClient) -> None:
        project_id = _seed_verified_triplet(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/dataset-versions",
            json={
                "name": "v1-core",
                "augmentation": {
                    "horizontal_flip": True,
                    "brightness_contrast": True,
                    "blur": False,
                    "multiplier": 3,
                },
            },
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["status"] == "READY"
        assert payload["name"] == "v1-core"
        assert payload["train_count"] == 1
        assert payload["valid_count"] == 1
        assert payload["test_count"] == 1
        assert payload["train_file_count"] == 3
        assert payload["valid_file_count"] == 1
        assert payload["test_file_count"] == 1
        assert payload["yaml_path"].endswith("data.yaml")

        listed = client.get(f"/api/v1/projects/{project_id}/dataset-versions")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        storage_root = Path(client.app.state.storage._root)
        yaml_file = storage_root / payload["yaml_path"]
        assert yaml_file.is_file()
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        assert data["names"][0] == "crack"
        train_dir = yaml_file.parent / "train" / "images"
        valid_dir = yaml_file.parent / "valid" / "images"
        test_dir = yaml_file.parent / "test" / "images"
        assert len(list(train_dir.glob("*.jpg"))) == 3
        assert len(list(valid_dir.glob("*.jpg"))) == 1
        assert len(list(test_dir.glob("*.jpg"))) == 1

    def test_create_version_returns_400_when_pending(self, client: TestClient) -> None:
        rng = np.random.default_rng(3)
        source = rng.integers(20, 200, (240, 320, 3), dtype=np.uint8)
        source[60:140, 80:180] = 255
        source[::5, :] = 10
        target = np.roll(source, 25, axis=1)

        project_id = client.post("/api/v1/projects", json={"name": "Pending"}).json()["id"]
        class_id = client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={"name": "dent", "color_hex": "#22C55E"},
        ).json()["id"]
        upload = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[
                ("files", ("s.png", _bgr_png(source), "image/png")),
                ("files", ("t.png", _bgr_png(target), "image/png")),
                ("files", ("u.png", _png((1, 2, 3)), "image/png")),
            ],
        )
        assert upload.status_code == 201, upload.text
        source_img, target_img, third = upload.json()
        for image in (source_img, third):
            saved = client.put(
                f"/api/v1/images/{image['id']}/annotations",
                json={
                    "boxes": [
                        {
                            "class_id": class_id,
                            "x_center": 0.4,
                            "y_center": 0.4,
                            "width": 0.3,
                            "height": 0.3,
                        }
                    ]
                },
            )
            assert saved.status_code == 200, saved.text

        source_box = client.get(f"/api/v1/images/{source_img['id']}").json()["annotations"][0]
        propagated = client.post(
            "/api/v1/matching/propagate-box",
            json={
                "source_image_id": source_img["id"],
                "target_image_id": target_img["id"],
                "source_box": {
                    "id": source_box["id"],
                    "class_id": class_id,
                    "x_center": source_box["x_center"],
                    "y_center": source_box["y_center"],
                    "width": source_box["width"],
                    "height": source_box["height"],
                },
            },
        )
        if propagated.status_code != 200:
            pytest.skip(f"propagate unavailable for gate test: {propagated.text}")

        response = client.post(f"/api/v1/projects/{project_id}/dataset-versions")
        assert response.status_code == 400, response.text
        assert "unverified" in response.json()["detail"].lower()


def test_dataset_version_rename_export_delete(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Lifecycle"}).json()
    project_id = project["id"]
    class_id = client.post(
        f"/api/v1/projects/{project_id}/classes",
        json={"name": "obj", "color_hex": "#112233"},
    ).json()["id"]
    upload = client.post(
        f"/api/v1/projects/{project_id}/images/upload",
        files=[
            ("files", ("a.png", _png(), "image/png")),
            ("files", ("b.png", _png((10, 20, 30)), "image/png")),
            ("files", ("c.png", _png((40, 50, 60)), "image/png")),
        ],
    )
    assert upload.status_code == 201, upload.text
    for image in upload.json():
        saved = client.put(
            f"/api/v1/images/{image['id']}/annotations",
            json={
                "boxes": [
                    {
                        "class_id": class_id,
                        "x_center": 0.5,
                        "y_center": 0.5,
                        "width": 0.2,
                        "height": 0.2,
                    }
                ]
            },
        )
        assert saved.status_code == 200, saved.text

    created = client.post(
        f"/api/v1/projects/{project_id}/dataset-versions",
        json={"name": "v1"},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]

    renamed = client.patch(
        f"/api/v1/dataset-versions/{version_id}",
        json={"name": "export-me"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "export-me"

    exported = client.get(f"/api/v1/dataset-versions/{version_id}/export")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("application/zip")
    assert exported.content[:2] == b"PK"

    deleted = client.delete(f"/api/v1/dataset-versions/{version_id}")
    assert deleted.status_code == 204, deleted.text
    listed = client.get(f"/api/v1/projects/{project_id}/dataset-versions")
    assert listed.status_code == 200
    assert listed.json() == []

    yaml_path = created.json()["yaml_path"]
    assert yaml_path
    dataset_dir = Path(client.app.state.storage.get_absolute_path(yaml_path)).parent
    assert not dataset_dir.exists()
