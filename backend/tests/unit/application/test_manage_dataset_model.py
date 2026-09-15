import io
import json
import zipfile
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.use_cases.dataset.manage_dataset_version import (
    DeleteDatasetVersionUseCase,
    ExportDatasetVersionUseCase,
    RenameDatasetVersionUseCase,
)
from app.application.use_cases.ml.manage_model_version import (
    DeleteModelVersionUseCase,
    ExportModelVersionUseCase,
    RenameModelVersionUseCase,
)
from app.domain.entities.dataset_version import AugmentationConfig, DatasetVersion
from app.domain.entities.model_version import ModelVersion
from app.domain.entities.training_job import TrainingJob
from app.domain.enums import DatasetVersionStatus, TrainingJobStatus
from app.domain.exceptions import DomainValidationException
from app.infrastructure.storage.zip_packer import ZipArchivePacker


class _FakeUow:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeVersions:
    def __init__(self, version: DatasetVersion) -> None:
        self.store = {version.id: version}

    async def get_by_id(self, version_id):
        return self.store.get(version_id)

    async def update(self, version) -> None:
        self.store[version.id] = version

    async def delete(self, version_id) -> None:
        self.store.pop(version_id, None)


class _FakeModels:
    def __init__(self, items=None) -> None:
        self.store = {item.id: item for item in (items or [])}

    async def get_by_id(self, model_id):
        return self.store.get(model_id)

    async def list_by_dataset_version(self, dataset_version_id):
        return [
            item
            for item in self.store.values()
            if item.dataset_version_id == dataset_version_id
        ]

    async def update(self, model) -> None:
        self.store[model.id] = model

    async def delete(self, model_id) -> None:
        self.store.pop(model_id, None)


class _FakeJobs:
    def __init__(self, items=None) -> None:
        self.items = list(items or [])

    async def get_by_id(self, job_id):
        return next((item for item in self.items if item.id == job_id), None)

    async def list_by_dataset_version(self, dataset_version_id):
        return [
            item
            for item in self.items
            if item.dataset_version_id == dataset_version_id
        ]

    async def update(self, job) -> None:
        self.items = [job if item.id == job.id else item for item in self.items]

    async def delete_by_dataset_version(self, dataset_version_id) -> None:
        self.items = [
            item
            for item in self.items
            if item.dataset_version_id != dataset_version_id
        ]

    async def delete(self, job_id) -> None:
        self.items = [item for item in self.items if item.id != job_id]


class _FakeAutoJobs:
    def __init__(self) -> None:
        self.deleted: list = []

    async def delete_by_model_version(self, model_version_id) -> None:
        self.deleted.append(model_version_id)

    async def delete_by_model_versions(self, model_version_ids) -> None:
        self.deleted.extend(list(model_version_ids))


class _FakeAnnotations:
    def __init__(self) -> None:
        self.cleared: list = []

    async def clear_model_version_refs(self, model_version_id) -> None:
        self.cleared.append(model_version_id)


class _FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.deleted_dirs: list[str] = []

    async def read(self, relative_path: str) -> bytes:
        return self.files[relative_path]

    async def list_files(self, relative_dir: str) -> dict[str, bytes]:
        prefix = relative_dir.rstrip("/") + "/"
        return {
            path[len(prefix) :]: data
            for path, data in self.files.items()
            if path.startswith(prefix)
        }

    async def delete_directory(self, relative_dir: str) -> None:
        self.deleted_dirs.append(relative_dir)


def _ready_dataset(**kwargs) -> DatasetVersion:
    project_id = kwargs.get("project_id", uuid4())
    version = DatasetVersion.create(project_id, 1, name="v1")
    version.mark_ready(
        train_count=1,
        valid_count=1,
        test_count=0,
        train_file_count=1,
        valid_file_count=1,
        test_file_count=0,
        yaml_path=kwargs.get(
            "yaml_path", f"projects/{project_id}/datasets/v1/data.yaml"
        ),
        items=[],
    )
    return version


def _model(dataset_version_id, **kwargs) -> ModelVersion:
    return ModelVersion.create(
        project_id=kwargs.get("project_id", uuid4()),
        dataset_version_id=dataset_version_id,
        training_job_id=kwargs.get("training_job_id", uuid4()),
        version_number=1,
        weights_path=kwargs.get(
            "weights_path", f"projects/{uuid4()}/models/v1/best.pt"
        ),
        map50=0.8,
        name=kwargs.get("name"),
    )


def _job(dataset_version_id, status=TrainingJobStatus.COMPLETED, **kwargs) -> TrainingJob:
    return TrainingJob(
        id=kwargs.get("id", uuid4()),
        project_id=kwargs.get("project_id", uuid4()),
        dataset_version_id=dataset_version_id,
        status=status,
        epochs=10,
        batch_size=8,
        imgsz=640,
        device="cpu",
        base_weights="yolov8n.pt",
        patience=20,
        metrics_history=[],
        current_epoch=0,
        stopped_early=False,
        model_version_id=None,
        error_message=None,
        created_at=datetime.now(UTC),
        started_at=None,
        finished_at=None,
    )


@pytest.mark.asyncio
async def test_rename_dataset_version() -> None:
    version = _ready_dataset()
    use_case = RenameDatasetVersionUseCase(_FakeVersions(version), _FakeUow())
    result = await use_case.execute(version.id, "  my-ds  ")
    assert result.name == "my-ds"


@pytest.mark.asyncio
async def test_export_dataset_version_zip() -> None:
    version = _ready_dataset()
    storage = _FakeStorage()
    root = version.yaml_path.rsplit("/", 1)[0]
    storage.files[f"{root}/data.yaml"] = b"names: []\n"
    storage.files[f"{root}/train/images/a.jpg"] = b"img"
    use_case = ExportDatasetVersionUseCase(version, storage, ZipArchivePacker())
    # fix: ExportDatasetVersionUseCase expects versions repo
    use_case = ExportDatasetVersionUseCase(
        _FakeVersions(version), storage, ZipArchivePacker()
    )
    archive, filename = await use_case.execute(version.id)
    assert filename.startswith("dataset-")
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = set(zf.namelist())
    assert "data.yaml" in names
    assert "train/images/a.jpg" in names


@pytest.mark.asyncio
async def test_delete_dataset_cascades_models() -> None:
    version = _ready_dataset()
    job = _job(version.id, project_id=version.project_id)
    model = _model(
        version.id,
        project_id=version.project_id,
        training_job_id=job.id,
        weights_path=f"projects/{version.project_id}/models/v1/best.pt",
    )
    models = _FakeModels([model])
    jobs = _FakeJobs([job])
    auto = _FakeAutoJobs()
    annotations = _FakeAnnotations()
    storage = _FakeStorage()
    versions = _FakeVersions(version)

    use_case = DeleteDatasetVersionUseCase(
        versions, models, jobs, auto, annotations, storage, _FakeUow()
    )
    await use_case.execute(version.id)

    assert version.id not in versions.store
    assert model.id not in models.store
    assert model.id in auto.deleted
    assert model.id in annotations.cleared
    assert f"projects/{version.project_id}/models/v1" in storage.deleted_dirs
    assert f"projects/{version.project_id}/models/_train_{job.id}" in storage.deleted_dirs
    assert version.yaml_path.rsplit("/", 1)[0] in storage.deleted_dirs


@pytest.mark.asyncio
async def test_delete_dataset_blocked_while_training() -> None:
    version = _ready_dataset()
    jobs = _FakeJobs([_job(version.id, status=TrainingJobStatus.RUNNING)])
    use_case = DeleteDatasetVersionUseCase(
        _FakeVersions(version),
        _FakeModels(),
        jobs,
        _FakeAutoJobs(),
        _FakeAnnotations(),
        _FakeStorage(),
        _FakeUow(),
    )
    with pytest.raises(DomainValidationException, match="training"):
        await use_case.execute(version.id)


@pytest.mark.asyncio
async def test_rename_and_export_model() -> None:
    model = _model(uuid4(), name="Model v1", weights_path="projects/p/models/v1/best.pt")
    models = _FakeModels([model])
    renamed = await RenameModelVersionUseCase(models, _FakeUow()).execute(
        model.project_id, model.id, "best-detector"
    )
    assert renamed.name == "best-detector"
    assert "best-detector" in renamed.display_name

    storage = _FakeStorage()
    storage.files[model.weights_path] = b"weights-bytes"
    archive, filename = await ExportModelVersionUseCase(
        models, storage, ZipArchivePacker()
    ).execute(model.project_id, model.id)
    assert filename.startswith("model-")
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert "best.pt" in zf.namelist()
        assert "metadata.json" in zf.namelist()
        meta = json.loads(zf.read("metadata.json"))
    assert meta["name"] == "best-detector"
    assert meta["map50"] == 0.8


@pytest.mark.asyncio
async def test_delete_model_removes_weights_and_train_dir() -> None:
    job = _job(uuid4(), status=TrainingJobStatus.COMPLETED)
    model = _model(
        job.dataset_version_id,
        project_id=job.project_id,
        training_job_id=job.id,
        weights_path=f"projects/{job.project_id}/models/v1/best.pt",
    )
    job.model_version_id = model.id
    storage = _FakeStorage()
    use_case = DeleteModelVersionUseCase(
        _FakeModels([model]),
        _FakeJobs([job]),
        _FakeAutoJobs(),
        _FakeAnnotations(),
        storage,
        _FakeUow(),
    )
    await use_case.execute(model.project_id, model.id)
    assert f"projects/{job.project_id}/models/v1" in storage.deleted_dirs
    assert f"projects/{job.project_id}/models/_train_{job.id}" in storage.deleted_dirs


@pytest.mark.asyncio
async def test_delete_model_blocked_while_training() -> None:
    job = _job(uuid4(), status=TrainingJobStatus.QUEUED)
    model = _model(
        job.dataset_version_id,
        project_id=job.project_id,
        training_job_id=job.id,
    )
    use_case = DeleteModelVersionUseCase(
        _FakeModels([model]),
        _FakeJobs([job]),
        _FakeAutoJobs(),
        _FakeAnnotations(),
        _FakeStorage(),
        _FakeUow(),
    )
    with pytest.raises(DomainValidationException, match="training"):
        await use_case.execute(model.project_id, model.id)
