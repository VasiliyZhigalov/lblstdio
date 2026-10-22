import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.main import create_app


def png():
    data = io.BytesIO()
    Image.new("RGB", (64, 48), (60, 120, 180)).save(data, "PNG")
    return data.getvalue()


@pytest.fixture
def client(tmp_path):
    app = create_app(database_url=f"sqlite+aiosqlite:///{(tmp_path/'app.db').as_posix()}", storage_root=tmp_path/"storage")
    with TestClient(app) as client: yield client


def project(client, task="DETECTION"):
    return client.post("/api/v1/projects", json={"name": "Data", "task_type": task}).json()["id"]


def preview(client, pid, members, kind="dataset"):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in members.items(): z.writestr(name, data)
    return client.post(f"/api/v1/projects/{pid}/data/imports/preview", data={"kind": kind}, files=[("files", ("dataset.zip", archive.getvalue(), "application/zip"))])


def finish(client, pid, job_id, mapping=None):
    started = client.post(f"/api/v1/projects/{pid}/data/imports/{job_id}/start", json={"mapping": mapping or {}})
    assert started.status_code == 200, started.text
    for _ in range(300):
        job = next(j for j in client.get(f"/api/v1/projects/{pid}/data/imports").json() if j["id"] == job_id)
        if job["status"] not in {"QUEUED", "RUNNING"}: break
        time.sleep(.01)
    assert job["status"] == "COMPLETED", job
    return job


def query(client, pid, **filters):
    response = client.post(f"/api/v1/projects/{pid}/data/query", json=filters)
    assert response.status_code == 200, response.text
    return response.json()


def test_yolo_mapping_splits_background_pagination_thumbnail_trash(client):
    pid = project(client)
    existing = client.post(f"/api/v1/projects/{pid}/classes", json={"name": "Project class", "color_hex": "#123456"}).json()
    response = preview(client, pid, {"data.yaml": "names: [source-name]\n", "train/images/a.png": png(), "train/labels/a.txt": "0 .5 .5 .2 .2", "test/images/bg.png": png(), "test/labels/bg.txt": ""})
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["summary"]["names"] == ["source-name"]
    assert query(client, pid)["total"] == 0  # preview has no project side effects
    finish(client, pid, job["id"], {"0": existing["id"]})
    result = query(client, pid, limit=1)
    assert len(result["items"]) == 1 and result["total"] == 2
    assert query(client, pid, class_id=existing["id"])["total"] == 1
    assert query(client, pid, background=True, split="test")["items"][0]["is_background"]
    assert query(client, pid, min_conf=.1)["total"] == 0  # manual labels do not have model confidence
    assert client.get(f"/api/v1/projects/{pid}/classes").json()[0]["name"] == "Project class"
    image = query(client, pid, class_id=existing["id"])["items"][0]
    thumb = client.get(f"/api/v1/images/{image['id']}/thumbnail")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(thumb.content)) as im: assert im.width <= 480
    base = f"/api/v1/projects/{pid}/data/actions"
    assert client.post(base, json={"action": "tag", "ids": [image["id"]], "tag": "ночь"}).json()["updated"] == 1
    assert query(client, pid, tag="ночь")["total"] == 1
    assert client.post(base, json={"action": "trash", "all_matching": True, "filters": {"tag": "ночь"}}).json()["updated"] == 1
    assert query(client, pid)["total"] == 1
    assert len(client.get(f"/api/v1/projects/{pid}/images").json()) == 1
    assert query(client, pid, trash=True)["total"] == 1
    client.post(base, json={"action": "restore", "filters": {"trash": True}, "ids": [image["id"]]})
    assert query(client, pid)["total"] == 2
    stats = client.get(f"/api/v1/projects/{pid}/data/statistics").json()
    assert stats["total"] == 2 and stats["classes"][0]["objects"] == 1
    assert client.post(f"/api/v1/projects/{pid}/data/imports/{job['id']}/rollback").status_code == 200
    assert query(client, pid)["total"] == 0 and query(client, pid, trash=True)["total"] == 2


def test_coco_non_contiguous_categories_and_classification_folders(client):
    pid = project(client)
    coco = {"categories": [{"id": 42, "name": "car"}], "images": [{"id": 6, "file_name": "a.png", "width": 64, "height": 48}], "annotations": [{"image_id": 6, "category_id": 42, "bbox": [16, 12, 32, 24]}]}
    response = preview(client, pid, {"a.png": png(), "annotations.json": json.dumps(coco)})
    assert response.status_code == 200, response.text
    finish(client, pid, response.json()["id"])
    box = query(client, pid)["items"][0]["annotations"][0]
    assert (box["x_center"], box["y_center"], box["width"], box["height"]) == (.5, .5, .5, .5)
    pid2 = project(client, "CLASSIFICATION")
    response = preview(client, pid2, {"train/on/a.png": png(), "val/off/b.png": png()})
    assert response.status_code == 200, response.text
    finish(client, pid2, response.json()["id"])
    images = query(client, pid2)["items"]
    assert all(i["label"] and i["status"] == "VERIFIED" for i in images)
    assert {i["split"] for i in images} == {"train", "valid"}


def test_preview_rejects_bad_labels_missing_classes_and_unsafe_archives(client):
    pid = project(client)
    for members in ({"a.png": png(), "a.txt": "0 .5 .5 .2 .2"}, {"a.png": png(), "data.yaml": "names: [car]", "a.txt": "0 .5 .5 2 .2"}, {"../a.png": png()}):
        response = preview(client, pid, members)
        assert response.status_code == 422, response.text
    assert query(client, pid)["total"] == 0
    assert client.get(f"/api/v1/projects/{pid}/classes").json() == []


def test_project_camera_link_is_shared_not_copied(client):
    first, second = project(client), project(client)
    camera = client.post(f"/api/v1/projects/{first}/streams/rtsp", json={"name": "Shared", "rtsp_url": "rtsp://user:password@example.org/live"}).json()
    route = f"/api/v1/projects/{second}/data/cameras"
    assert client.put(f"{route}/{camera['id']}", json={"linked": True}).status_code == 200
    cameras = client.get(route).json()
    assert len(cameras) == 1 and cameras[0]["id"] == camera["id"] and not cameras[0]["owned"]
    assert "password" not in json.dumps(cameras)
    assert len(client.get(f"/api/v1/projects/{second}/streams").json()) == 0
    client.put(f"{route}/{camera['id']}", json={"linked": False})
    assert client.get(route).json() == []


def test_page_limit_is_bounded_and_foreign_ids_not_mutated(client):
    pid, other = project(client), project(client)
    response = preview(client, pid, {f"a{i}.png": png() for i in range(101)}, "images")
    assert response.status_code == 200, response.text
    finish(client, pid, response.json()["id"])
    result = query(client, pid, limit=10000)
    assert result["total"] == 101 and len(result["items"]) == 96
    assert len(query(client, pid, offset=96, limit=96)["items"]) == 5
    foreign = result["items"][0]["id"]
    response = client.post(f"/api/v1/projects/{other}/data/actions", json={"action": "trash", "ids": [foreign]})
    assert response.json()["updated"] == 0
    assert query(client, pid)["total"] == 101


def test_model_import_preserves_head_mapping_and_current_active_model(client, monkeypatch):
    pid = project(client)
    old = client.post(f"/api/v1/projects/{pid}/models/upload", files={"file": ("old.pt", b"old weights")})
    assert old.status_code == 201, old.text
    a = client.post(f"/api/v1/projects/{pid}/classes", json={"name": "A", "color_hex": "#123456"}).json()
    b = client.post(f"/api/v1/projects/{pid}/classes", json={"name": "B", "color_hex": "#654321"}).json()
    def inspect(path, task):
        return {"format": "YOLO .pt", "names": ["source-B", "source-A"], "records": [], "model_path": str(path), "task": task}
    monkeypatch.setattr("app.infrastructure.db.data_imports.inspect_model", inspect)
    response = client.post(f"/api/v1/projects/{pid}/data/imports/preview", data={"kind": "model"}, files=[("files", ("new.pt", b"new weights"))])
    assert response.status_code == 200, response.text
    finish(client, pid, response.json()["id"], {"0": b["id"], "1": a["id"]})
    models = client.get(f"/api/v1/projects/{pid}/models").json()
    assert models[0]["class_metadata"] == {"class_names": ["source-B", "source-A"], "class_mapping": {"0": b["id"], "1": a["id"]}}
    assert not models[0]["is_active_for_stream"] and models[1]["is_active_for_stream"]
    assert client.delete(f"/api/v1/projects/{pid}/data/classes/{a['id']}").status_code == 422


def test_quality_job_and_filter_validation(client):
    pid = project(client)
    response = preview(client, pid, {"a.png": png()}, "images")
    finish(client, pid, response.json()["id"])
    assert client.post(f"/api/v1/projects/{pid}/data/analyze").status_code == 200
    for _ in range(300):
        jobs = client.get(f"/api/v1/projects/{pid}/data/imports").json()
        job = next(j for j in jobs if j["kind"] == "quality")
        if job["status"] not in {"RUNNING", "QUEUED"}: break
        time.sleep(.01)
    assert job["status"] == "COMPLETED", job
    assert client.get(f"/api/v1/projects/{pid}/data/statistics").json()["analyzed"] == 1
    assert query(client, pid, quality="blur", orientation="landscape", format="png")["total"] == 1
    for filters in ({"min_conf": 2}, {"after": "invalid"}, {"min_objects": -1}, {"min_conf": .8, "max_conf": .2}):
        assert client.post(f"/api/v1/projects/{pid}/data/query", json=filters).status_code == 422


def test_model_inspection_reads_real_checkpoint_names_without_download(tmp_path):
    from ultralytics import YOLO
    from ultralytics.nn.tasks import DetectionModel
    from app.infrastructure.storage.dataset_manifest import inspect_model
    model = YOLO("yolo11n.yaml")
    model.model = DetectionModel("yolo11n.yaml", nc=2, verbose=False)
    model.model.names = {0: "car", 1: "person"}
    target = tmp_path / "sample.pt"
    model.save(target)
    manifest = inspect_model(target, "DETECTION")
    assert manifest["names"] == ["car", "person"]
    from app.domain.exceptions import DomainValidationException
    with pytest.raises(DomainValidationException): inspect_model(target, "CLASSIFICATION")
