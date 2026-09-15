from uuid import uuid4

import pytest

from app.application.use_cases.images.get_image import GetImageUseCase, ListImagesUseCase
from app.application.use_cases.projects.create_project import (
    CreateProjectUseCase,
    GetProjectUseCase,
    ListProjectsUseCase,
    UpdateProjectUseCase,
)
from app.application.use_cases.projects.delete_project import DeleteProjectUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, SplitType
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.services.split import assign_splits
from app.domain.value_objects.bounding_box import BoundingBox
from app.domain.value_objects.split_ratios import SplitRatios


class _FakeProjects:
    def __init__(self) -> None:
        self.items: list[Project] = []
        self.ops: list[str] = []

    async def add(self, project: Project) -> None:
        self.items.append(project)

    async def get_by_id(self, project_id):
        return next((item for item in self.items if item.id == project_id), None)

    async def list_all(self):
        return list(self.items)

    async def update(self, project: Project) -> None:
        self.items = [project if item.id == project.id else item for item in self.items]

    async def delete(self, project_id) -> None:
        self.ops.append("db")
        self.items = [item for item in self.items if item.id != project_id]


class _FakeStorage:
    def __init__(self, projects: _FakeProjects | None = None) -> None:
        self.deleted: list[str] = []
        self._projects = projects

    async def delete_directory(self, relative_dir: str) -> None:
        if self._projects is not None:
            self._projects.ops.append("fs")
        self.deleted.append(relative_dir)


class _FakeUow:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeImages:
    def __init__(self, images: list[Image]) -> None:
        self.images = images

    async def get_by_id(self, image_id):
        return next((item for item in self.images if item.id == image_id), None)

    async def list_by_project(self, project_id):
        return [item for item in self.images if item.project_id == project_id]


class _FakeAnnotations:
    def __init__(self, items: list[Annotation] | None = None) -> None:
        self.items = items or []

    async def list_by_image(self, image_id):
        return [item for item in self.items if item.image_id == image_id]


@pytest.mark.asyncio
async def test_create_list_and_get_project() -> None:
    projects = _FakeProjects()
    created = await CreateProjectUseCase(projects, _FakeUow()).execute("Alpha", "desc")
    listed = await ListProjectsUseCase(projects).execute()
    fetched = await GetProjectUseCase(projects).execute(created.id)

    assert listed == [created]
    assert fetched.name == "Alpha"
    assert fetched.description == "desc"


@pytest.mark.asyncio
async def test_update_project_name_and_description() -> None:
    projects = _FakeProjects()
    created = await CreateProjectUseCase(projects, _FakeUow()).execute("Alpha", "desc")
    updated = await UpdateProjectUseCase(projects, _FakeUow()).execute(
        created.id, "Beta", "new desc"
    )
    assert updated.name == "Beta"
    assert updated.description == "new desc"
    assert updated.updated_at >= created.updated_at

    cleared = await UpdateProjectUseCase(projects, _FakeUow()).execute(
        created.id, "Beta", None
    )
    assert cleared.description is None


@pytest.mark.asyncio
async def test_update_missing_project() -> None:
    with pytest.raises(ResourceNotFoundException):
        await UpdateProjectUseCase(_FakeProjects(), _FakeUow()).execute(
            uuid4(), "Nope", None
        )


@pytest.mark.asyncio
async def test_get_project_missing() -> None:
    with pytest.raises(ResourceNotFoundException):
        await GetProjectUseCase(_FakeProjects()).execute(uuid4())


@pytest.mark.asyncio
async def test_delete_project_removes_files_and_record() -> None:
    projects = _FakeProjects()
    storage = _FakeStorage(projects)
    project = await CreateProjectUseCase(projects, _FakeUow()).execute("Gone")

    await DeleteProjectUseCase(projects, storage, _FakeUow()).execute(project.id)

    assert projects.items == []
    assert storage.deleted == [f"projects/{project.id}"]
    assert projects.ops == ["db", "fs"]


@pytest.mark.asyncio
async def test_delete_missing_project() -> None:
    with pytest.raises(ResourceNotFoundException):
        await DeleteProjectUseCase(_FakeProjects(), _FakeStorage(), _FakeUow()).execute(
            uuid4()
        )


@pytest.mark.asyncio
async def test_get_and_list_images() -> None:
    project_id = uuid4()
    image = Image.create(
        project_id=project_id,
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    box = Annotation.create_manual(
        image.id, uuid4(), BoundingBox(0.5, 0.5, 0.1, 0.1)
    )
    images = _FakeImages([image])
    listed = await ListImagesUseCase(images).execute(project_id)
    train_only = await ListImagesUseCase(images).execute(
        project_id, split=SplitType.TRAIN
    )
    paged = await ListImagesUseCase(images).execute(project_id, offset=0, limit=1)
    unannotated = await ListImagesUseCase(images).execute(
        project_id, status=ImageStatus.UNANNOTATED
    )
    fetched, annotations = await GetImageUseCase(images, _FakeAnnotations([box])).execute(
        image.id
    )

    assert listed == [image]
    assert train_only == [image]
    assert paged == [image]
    assert unannotated == [image]
    assert fetched.id == image.id
    assert annotations == [box]


@pytest.mark.asyncio
async def test_get_image_missing() -> None:
    with pytest.raises(ResourceNotFoundException):
        await GetImageUseCase(_FakeImages([]), _FakeAnnotations()).execute(uuid4())


def test_split_ratios_must_sum_to_one() -> None:
    with pytest.raises(DomainValidationException, match="sum"):
        SplitRatios(train=0.5, valid=0.5, test=0.5)


def test_assign_splits_uses_hamilton_and_keeps_ten_image_ratio() -> None:
    splits = assign_splits(10, SplitRatios())
    values = [item.value for item in splits]
    assert values.count("train") == 7
    assert values.count("valid") == 2
    assert values.count("test") == 1


def test_assign_splits_gives_all_three_buckets_for_three_images() -> None:
    splits = assign_splits(3, SplitRatios())
    values = [item.value for item in splits]
    assert sorted(values) == ["test", "train", "valid"]


def test_project_rejects_blank_name() -> None:
    with pytest.raises(DomainValidationException, match="name"):
        Project.create("   ")
