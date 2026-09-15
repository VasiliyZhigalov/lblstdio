import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.application.ports.services.model_predictor import Detection
from app.application.ports.services.model_trainer import TrainingConfig, TrainingResult
from app.main import create_app


def _png(color=(80, 120, 160)) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (200, 160), color).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeTrainer:
    def train(self, config: TrainingConfig, on_epoch_end=None) -> TrainingResult:
        history = []
        planned = config.epochs
        # Simulate early stop when patience is small relative to epochs
        run_epochs = planned
        if config.patience > 0 and config.patience < planned:
            run_epochs = max(config.patience + 1, min(planned, config.patience + 2))
        for epoch in range(1, run_epochs + 1):
            metrics = {
                "epoch": epoch,
                "train_loss": max(0.1, 1.0 / epoch),
                "map50": min(0.9, 0.4 + epoch * 0.05),
                "map50_95": 0.3,
                "precision": 0.7,
                "recall": 0.6,
            }
            history.append(metrics)
            if on_epoch_end:
                on_epoch_end(metrics)
        best = Path(config.output_dir) / "run" / "weights" / "best.pt"
        best.parent.mkdir(parents=True, exist_ok=True)
        best.write_bytes(b"fake-weights")
        return TrainingResult(
            best_weights_path=str(best),
            metrics_history=history,
            map50=history[-1]["map50"],
            map50_95=0.3,
            precision=0.7,
            recall=0.6,
            stopped_early=run_epochs < planned,
            epochs_trained=run_epochs,
        )


class _FakePredictor:
    def predict(self, weights_path, image_paths, confidence_threshold):
        out = {}
        for path in image_paths:
            out[path] = [
                Detection(
                    class_index=0,
                    confidence=max(confidence_threshold, 0.77),
                    x_center=0.5,
                    y_center=0.5,
                    width=0.2,
                    height=0.2,
                )
            ]
        return out


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.application.use_cases.dataset import create_dataset_version as mod
    from app.presentation import dependencies as deps

    real_init = mod.CreateDatasetVersionUseCase.__init__

    def patched_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self._min_verified = 3

    monkeypatch.setattr(mod.CreateDatasetVersionUseCase, "__init__", patched_init)

    db_path = (tmp_path / "app.db").as_posix()
    fake_predictor = _FakePredictor()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        storage_root=tmp_path / "storage",
        training_trainer=_FakeTrainer(),
        predictor=fake_predictor,
    )
    app.dependency_overrides[deps.get_predictor] = lambda: fake_predictor
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _seed_ready_dataset(client: TestClient) -> tuple[str, str, str]:
    project_id = client.post("/api/v1/projects", json={"name": "AL"}).json()["id"]
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
            ("files", ("raw.png", _png((1, 2, 3)), "image/png")),
        ],
    )
    assert upload.status_code == 201, upload.text
    images = upload.json()
    for image in images[:3]:
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
    version = client.post(
        f"/api/v1/projects/{project_id}/dataset-versions",
        json={"name": "v1", "augmentation": {"multiplier": 1}},
    )
    assert version.status_code == 201, version.text
    raw_id = images[3]["id"]
    return project_id, version.json()["id"], raw_id


class TestTrainingAndAutoLabelApi:
    def test_train_job_completes_and_auto_label_is_pending(self, client: TestClient) -> None:
        project_id, version_id, raw_id = _seed_ready_dataset(client)
        start = client.post(
            f"/api/v1/projects/{project_id}/train",
            json={"dataset_version_id": version_id, "epochs": 10},
        )
        assert start.status_code == 202, start.text
        job_id = start.json()["id"]

        deadline = time.time() + 15
        payload = None
        while time.time() < deadline:
            response = client.get(f"/api/v1/training-jobs/{job_id}")
            assert response.status_code == 200, response.text
            payload = response.json()
            if payload["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(0.2)

        assert payload is not None
        assert payload["status"] == "COMPLETED", payload
        assert payload["progress_percent"] == 100
        assert payload["metrics_history"]
        assert payload["model_version_id"]

        models = client.get(f"/api/v1/projects/{project_id}/models")
        assert models.status_code == 200
        assert len(models.json()) == 1
        model_id = models.json()[0]["id"]
        weights = Path(client.app.state.storage.get_absolute_path(models.json()[0]["weights_path"]))
        assert weights.is_file()

        labeled = client.post(
            f"/api/v1/projects/{project_id}/models/{model_id}/auto-label",
            json={"image_ids": [raw_id], "confidence_threshold": 0.5},
        )
        assert labeled.status_code == 202, labeled.text
        auto_job_id = labeled.json()["id"]

        deadline = time.time() + 15
        auto_payload = None
        while time.time() < deadline:
            response = client.get(f"/api/v1/auto-label-jobs/{auto_job_id}")
            assert response.status_code == 200, response.text
            auto_payload = response.json()
            if auto_payload["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(0.2)

        assert auto_payload is not None
        assert auto_payload["status"] == "COMPLETED", auto_payload
        assert auto_payload["total_predictions_generated"] == 1

        detail = client.get(f"/api/v1/images/{raw_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "REQUIRES_REVIEW"
        assert body["annotations"][0]["verification_status"] == "PENDING_REVIEW"
        assert body["annotations"][0]["source"] == "MODEL_PREDICTION"

        verified = client.post(f"/api/v1/images/{raw_id}/verify-all")
        assert verified.status_code == 200
        assert all(item["verification_status"] == "VERIFIED" for item in verified.json())
        after = client.get(f"/api/v1/images/{raw_id}")
        assert after.json()["status"] == "VERIFIED"
