import io
import zipfile
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


class TestLabeledUploadApi:
    def test_upload_yolo_pair_and_roboflow_zip(self, client: TestClient) -> None:
        project_id = client.post("/api/v1/projects", json={"name": "Import"}).json()["id"]

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as archive:
            archive.writestr("train/images/a.png", _png((10, 20, 30)))
            archive.writestr("train/labels/a.txt", "0 0.5 0.5 0.2 0.2\n")
            archive.writestr("valid/images/bg.png", _png((40, 50, 60)))
            archive.writestr("valid/labels/bg.txt", "\n")
            archive.writestr("data.yaml", "names: [crack]\n")

        response = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[
                ("files", ("bundle.zip", zip_buf.getvalue(), "application/zip")),
                ("files", ("loose.png", _png((1, 2, 3)), "image/png")),
            ],
            data={"relative_paths": ["bundle.zip", "raw/images/loose.png"]},
        )
        assert response.status_code == 201, response.text
        images = {item["file_name"]: item for item in response.json()}
        assert images["a.png"]["status"] == "VERIFIED"
        assert images["a.png"]["split"] == "train"
        assert images["bg.png"]["status"] == "VERIFIED"
        assert images["bg.png"]["is_background"] is True
        assert images["loose.png"]["status"] == "UNANNOTATED"

        detail = client.get(f"/api/v1/images/{images['a.png']['id']}")
        assert detail.status_code == 200
        assert len(detail.json()["annotations"]) == 1
        assert detail.json()["annotations"][0]["verification_status"] == "VERIFIED"

        classes = client.get(f"/api/v1/projects/{project_id}/classes").json()
        assert any(item["name"] == "crack" for item in classes)

    def test_folder_upload_uses_relative_paths_when_filename_is_basename(
        self, client: TestClient
    ) -> None:
        """Browsers often strip directories from multipart filename=; paths come separately."""
        project_id = client.post("/api/v1/projects", json={"name": "Folder"}).json()["id"]
        response = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=[
                ("files", ("x.png", _png((10, 20, 30)), "image/png")),
                ("files", ("x.txt", b"0 0.5 0.5 0.2 0.2\n", "text/plain")),
                ("files", ("x.png", _png((40, 50, 60)), "image/png")),
                ("files", ("x.txt", b"\n", "text/plain")),
                ("files", ("classes.txt", b"obj\n", "text/plain")),
            ],
            data={
                "relative_paths": [
                    "train/images/x.png",
                    "train/labels/x.txt",
                    "valid/images/x.png",
                    "valid/labels/x.txt",
                    "classes.txt",
                ]
            },
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert len(payload) == 2
        assert all(item["status"] == "VERIFIED" for item in payload)
        assert sum(1 for item in payload if item["is_background"]) == 1

    def test_dataset_version_split_ratios_ignore_upload_stub(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.application.use_cases.dataset import create_dataset_version as mod

        real_init = mod.CreateDatasetVersionUseCase.__init__

        def patched_init(self, *args, **kwargs):
            real_init(self, *args, **kwargs)
            self._min_verified = 10

        monkeypatch.setattr(mod.CreateDatasetVersionUseCase, "__init__", patched_init)

        project_id = client.post("/api/v1/projects", json={"name": "Split"}).json()["id"]
        files = []
        for index in range(10):
            files.append(
                (
                    "files",
                    (
                        f"img_{index}.png",
                        _png((index * 10, 20, 30)),
                        "image/png",
                    ),
                )
            )
            files.append(
                (
                    "files",
                    (f"img_{index}.txt", b"0 0.5 0.5 0.1 0.1\n", "text/plain"),
                )
            )
        files.append(("files", ("classes.txt", b"obj\n", "text/plain")))
        upload = client.post(
            f"/api/v1/projects/{project_id}/images/upload",
            files=files,
        )
        assert upload.status_code == 201, upload.text
        assert all(item["status"] == "VERIFIED" for item in upload.json())
        assert all(item["split"] == "train" for item in upload.json())

        version = client.post(
            f"/api/v1/projects/{project_id}/dataset-versions",
            json={
                "name": "v1",
                "train": 0.7,
                "valid": 0.2,
                "test": 0.1,
                "augmentation": {"multiplier": 1},
            },
        )
        assert version.status_code == 201, version.text
        payload = version.json()
        assert payload["train_count"] == 7
        assert payload["valid_count"] == 2
        assert payload["test_count"] == 1
