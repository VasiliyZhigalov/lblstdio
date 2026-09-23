from uuid import uuid4

import pytest

from app.application.use_cases.ml.manage_model_version import UploadModelVersionUseCase
from app.domain.entities.project import Project
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException


class _FakeUow:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeProjects:
    def __init__(self, project: Project | None = None) -> None:
        self.project = project

    async def get_by_id(self, project_id):
        if self.project and self.project.id == project_id:
            return self.project
        return None


class _FakeModels:
    def __init__(self) -> None:
        self.items = []
        self.next_number = 1

    async def next_version_number(self, project_id):
        return self.next_number

    async def deactivate_stream_models(self, project_id) -> None:
        for item in self.items:
            if item.project_id == project_id:
                item.is_active_for_stream = False

    async def add(self, version) -> None:
        self.items.append(version)
        self.next_number = max(self.next_number, version.version_number + 1)


class _FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def save(self, relative_dir: str, filename: str, data: bytes) -> str:
        path = f"{relative_dir.rstrip('/')}/{filename}"
        self.files[path] = data
        return path

    async def delete_directory(self, relative_dir: str) -> None:
        self.deleted.append(relative_dir)
        prefix = relative_dir.rstrip("/") + "/"
        for path in list(self.files):
            if path.startswith(prefix) or path == relative_dir:
                del self.files[path]

    async def move_directory(self, source_rel: str, dest_rel: str) -> None:
        source = source_rel.rstrip("/")
        dest = dest_rel.rstrip("/")
        prefix = source + "/"
        if any(path == dest or path.startswith(dest + "/") for path in self.files):
            raise FileExistsError(dest_rel)
        found = False
        for path in list(self.files):
            if path == source or path.startswith(prefix):
                suffix = path[len(source) :]
                self.files[dest + suffix] = self.files.pop(path)
                found = True
        if not found:
            raise FileNotFoundError(source_rel)


@pytest.mark.asyncio
async def test_upload_model_creates_version_without_training_link() -> None:
    project = Project.create("P")
    models = _FakeModels()
    storage = _FakeStorage()
    use_case = UploadModelVersionUseCase(
        _FakeProjects(project), models, storage, _FakeUow()
    )

    model = await use_case.execute(
        project.id,
        filename="custom-yolo.pt",
        data=b"fake-weights",
        name="Imported",
    )

    assert model.name == "Imported"
    assert model.dataset_version_id is None
    assert model.training_job_id is None
    assert model.version_number == 1
    assert model.weights_path.endswith("/best.pt")
    assert storage.files[model.weights_path] == b"fake-weights"
    assert model.is_active_for_stream is True


@pytest.mark.asyncio
async def test_upload_model_rejects_non_pt() -> None:
    project = Project.create("P")
    use_case = UploadModelVersionUseCase(
        _FakeProjects(project), _FakeModels(), _FakeStorage(), _FakeUow()
    )
    with pytest.raises(DomainValidationException, match="\\.pt"):
        await use_case.execute(project.id, filename="model.onnx", data=b"x")


@pytest.mark.asyncio
async def test_upload_model_missing_project() -> None:
    use_case = UploadModelVersionUseCase(
        _FakeProjects(), _FakeModels(), _FakeStorage(), _FakeUow()
    )
    with pytest.raises(ResourceNotFoundException):
        await use_case.execute(uuid4(), filename="a.pt", data=b"x")
