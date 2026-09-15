from uuid import uuid4

import pytest

from app.application.ports.services.model_trainer import TrainingConfig, TrainingResult
from app.application.use_cases.ml.train_model import TrainModelUseCase
from app.domain.entities.dataset_version import AugmentationConfig, DatasetVersion
from app.domain.entities.project import Project
from app.domain.enums import DatasetVersionStatus, TrainingJobStatus
from app.domain.exceptions import DatasetNotReadyException


class _FakeProjects:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get_by_id(self, project_id):
        return self.project if self.project.id == project_id else None


class _FakeVersions:
    def __init__(self, version: DatasetVersion) -> None:
        self.version = version

    async def get_by_id(self, version_id):
        return self.version if self.version.id == version_id else None


class _FakeJobs:
    def __init__(self) -> None:
        self.store = {}

    async def add(self, job) -> None:
        self.store[job.id] = job

    async def update(self, job) -> None:
        self.store[job.id] = job

    async def get_by_id(self, job_id):
        return self.store.get(job_id)


class _FakeStorage:
    def __init__(self) -> None:
        self.paths = set()

    def get_absolute_path(self, relative_path: str) -> str:
        self.paths.add(relative_path)
        return f"/abs/{relative_path}"


class _FakeUow:
    async def commit(self) -> None:
        return None


class _FakeRunner:
    def __init__(self) -> None:
        self.scheduled = []

    def schedule(self, job_id) -> None:
        self.scheduled.append(job_id)


@pytest.mark.asyncio
async def test_train_model_creates_queued_job_and_schedules() -> None:
    project = Project.create("Train")
    version = DatasetVersion.create(project.id, 1, "v1")
    version.mark_ready(
        train_count=1,
        valid_count=1,
        test_count=1,
        train_file_count=1,
        valid_file_count=1,
        test_file_count=1,
        yaml_path="projects/p/datasets/v1/data.yaml",
        items=[],
    )
    jobs = _FakeJobs()
    runner = _FakeRunner()
    use_case = TrainModelUseCase(
        _FakeProjects(project),
        _FakeVersions(version),
        jobs,
        _FakeStorage(),
        _FakeUow(),
        runner=runner,
        device_resolver=lambda _: "cpu",
    )
    job = await use_case.execute(project.id, version.id, epochs=30)
    assert job.status == TrainingJobStatus.QUEUED
    assert job.epochs == 30
    assert job.base_weights == "yolov8n.pt"
    assert job.device == "cpu"
    assert runner.scheduled == [job.id]
    assert job.id in jobs.store


@pytest.mark.asyncio
async def test_train_model_rejects_invalid_device() -> None:
    project = Project.create("Train")
    version = DatasetVersion.create(project.id, 1, "v1")
    version.mark_ready(
        train_count=1,
        valid_count=1,
        test_count=1,
        train_file_count=1,
        valid_file_count=1,
        test_file_count=1,
        yaml_path="projects/p/datasets/v1/data.yaml",
        items=[],
    )
    use_case = TrainModelUseCase(
        _FakeProjects(project),
        _FakeVersions(version),
        _FakeJobs(),
        _FakeStorage(),
        _FakeUow(),
        device_resolver=lambda d: d,
    )
    from app.domain.exceptions import DomainValidationException

    with pytest.raises(DomainValidationException, match="device"):
        await use_case.execute(project.id, version.id, device="mps")

    project = Project.create("Train")
    version = DatasetVersion.create(project.id, 1, "v1")
    assert version.status == DatasetVersionStatus.PREPARING
    use_case = TrainModelUseCase(
        _FakeProjects(project),
        _FakeVersions(version),
        _FakeJobs(),
        _FakeStorage(),
        _FakeUow(),
    )
    with pytest.raises(DatasetNotReadyException):
        await use_case.execute(project.id, version.id)


@pytest.mark.asyncio
async def test_train_model_uses_project_model_weights(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from app.domain.entities.model_version import ModelVersion

    project = Project.create("Train")
    version = DatasetVersion.create(project.id, 1, "v1")
    version.mark_ready(
        train_count=1,
        valid_count=1,
        test_count=1,
        train_file_count=1,
        valid_file_count=1,
        test_file_count=1,
        yaml_path="projects/p/datasets/v1/data.yaml",
        items=[],
    )
    model = ModelVersion.create(
        project_id=project.id,
        dataset_version_id=version.id,
        training_job_id=uuid4(),
        version_number=1,
        weights_path="projects/p/models/v1/best.pt",
        map50=0.8,
    )
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"w")

    class _Models:
        async def get_by_id(self, model_id):
            return model if model.id == model_id else None

    class _Storage(_FakeStorage):
        def get_absolute_path(self, relative_path: str) -> str:
            if relative_path.endswith("best.pt"):
                return str(weights)
            return super().get_absolute_path(relative_path)

    jobs = _FakeJobs()
    use_case = TrainModelUseCase(
        _FakeProjects(project),
        _FakeVersions(version),
        jobs,
        _Storage(),
        _FakeUow(),
        models=_Models(),
    )
    job = await use_case.execute(
        project.id,
        version.id,
        base_model_version_id=model.id,
        base_weights=None,
    )
    assert Path(job.base_weights) == weights
