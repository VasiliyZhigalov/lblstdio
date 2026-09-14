import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.main import create_app


def _png_from_bgr(image: np.ndarray) -> bytes:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    buffer = io.BytesIO()
    PILImage.fromarray(rgb).save(buffer, format="PNG")
    return buffer.getvalue()


def _textured_pair() -> tuple[bytes, bytes]:
    rng = np.random.default_rng(7)
    source = rng.integers(20, 80, (320, 400, 3), dtype=np.uint8)
    patch = rng.integers(40, 220, (90, 110, 3), dtype=np.uint8)
    patch[::4, :] = 255
    patch[:, ::5] = 12
    cv2.putText(patch, "OBJ", (8, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (240, 240, 10), 3)
    source[70:160, 90:200] = patch
    matrix = cv2.getRotationMatrix2D((200.0, 160.0), 5.0, 1.0)
    matrix[0, 2] += 50
    target = cv2.warpAffine(source, matrix, (400, 320), borderValue=(8, 8, 8))
    return _png_from_bgr(source), _png_from_bgr(target)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    db_path = (tmp_path / "app.db").as_posix()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        storage_root=tmp_path / "storage",
    )
    with TestClient(app) as test_client:
        yield test_client


def _seed_project(client: TestClient, files: list[tuple[str, bytes]]) -> tuple[str, str, list[dict]]:
    project_id = client.post("/api/v1/projects", json={"name": "Match"}).json()["id"]
    class_id = client.post(
        f"/api/v1/projects/{project_id}/classes",
        json={"name": "crack", "color_hex": "#EF4444"},
    ).json()["id"]
    upload = client.post(
        f"/api/v1/projects/{project_id}/images/upload",
        files=[("files", (name, data, "image/png")) for name, data in files],
    )
    assert upload.status_code == 201, upload.text
    return project_id, class_id, upload.json()


class TestPropagateBoxApi:
    def test_propagate_returns_pending_review_and_marks_image(self, client: TestClient) -> None:
        source_bytes, target_bytes = _textured_pair()
        _, class_id, images = _seed_project(
            client, [("a.png", source_bytes), ("b.png", target_bytes)]
        )
        source, target = images[0], images[1]
        saved = client.put(
            f"/api/v1/images/{source['id']}/annotations",
            json={
                "boxes": [
                    {
                        "class_id": class_id,
                        "x_center": 0.3625,
                        "y_center": 0.359375,
                        "width": 0.275,
                        "height": 0.28125,
                    }
                ]
            },
        )
        assert saved.status_code == 200, saved.text
        donor = saved.json()[0]

        response = client.post(
            "/api/v1/matching/propagate-box",
            json={
                "source_image_id": source["id"],
                "target_image_id": target["id"],
                "source_box": {
                    "id": donor["id"],
                    "class_id": class_id,
                    "x_center": donor["x_center"],
                    "y_center": donor["y_center"],
                    "width": donor["width"],
                    "height": donor["height"],
                },
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["source"] == "KEYPOINT_PROPAGATION"
        assert payload["verification_status"] == "PENDING_REVIEW"
        assert payload["verified_at"] is None
        assert payload["source_annotation_id"] == donor["id"]
        assert 0.0 < payload["confidence"] <= 1.0

        detail = client.get(f"/api/v1/images/{target['id']}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "REQUIRES_REVIEW"
        assert detail.json()["annotations"][0]["verification_status"] == "PENDING_REVIEW"

        verified = client.post(
            f"/api/v1/images/{target['id']}/annotations/{payload['id']}/verify"
        )
        assert verified.status_code == 200
        assert verified.json()["verification_status"] == "VERIFIED"
        after = client.get(f"/api/v1/images/{target['id']}")
        assert after.json()["status"] == "VERIFIED"

    def test_unrelated_images_return_422(self, client: TestClient) -> None:
        rng = np.random.default_rng(3)
        part = np.zeros((160, 200, 3), dtype=np.uint8)
        part[40:100, 50:130] = rng.integers(30, 220, (60, 80, 3), dtype=np.uint8)
        street = rng.integers(0, 255, (160, 200, 3), dtype=np.uint8)
        _, class_id, images = _seed_project(
            client,
            [("part.png", _png_from_bgr(part)), ("street.png", _png_from_bgr(street))],
        )
        source, target = images[0], images[1]
        donor = client.put(
            f"/api/v1/images/{source['id']}/annotations",
            json={
                "boxes": [
                    {
                        "class_id": class_id,
                        "x_center": 0.45,
                        "y_center": 0.44,
                        "width": 0.40,
                        "height": 0.38,
                    }
                ]
            },
        ).json()[0]

        response = client.post(
            "/api/v1/matching/propagate-box",
            json={
                "source_image_id": source["id"],
                "target_image_id": target["id"],
                "source_box": {
                    "id": donor["id"],
                    "class_id": class_id,
                    "x_center": donor["x_center"],
                    "y_center": donor["y_center"],
                    "width": donor["width"],
                    "height": donor["height"],
                },
            },
        )
        assert response.status_code == 422
        assert "Разметьте вручную" in response.json()["detail"]
        detail = client.get(f"/api/v1/images/{target['id']}")
        assert detail.json()["status"] == "UNANNOTATED"
        assert detail.json()["annotations"] == []
