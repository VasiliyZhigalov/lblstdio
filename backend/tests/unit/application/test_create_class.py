from uuid import uuid4

import pytest

from app.application.use_cases.classes.create_class import CreateClassUseCase
from app.application.use_cases.classes.delete_class import DeleteClassUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, SplitType
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.value_objects.bounding_box import BoundingBox


class _FakeProjects:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get_by_id(self, project_id):
        return self.project if self.project.id == project_id else None


class _FakeClasses:
    def __init__(self) -> None:
        self.items: list[AnnotationClass] = []

    async def list_by_project(self, project_id):
        return [item for item in self.items if item.project_id == project_id]

    async def add(self, annotation_class: AnnotationClass) -> None:
        self.items.append(annotation_class)

    async def get_by_id(self, class_id):
        return next((item for item in self.items if item.id == class_id), None)

    async def delete(self, class_id) -> None:
        self.items = [item for item in self.items if item.id != class_id]

    async def update_many(self, classes: list[AnnotationClass]) -> None:
        by_id = {item.id: item for item in classes}
        self.items = [by_id.get(item.id, item) for item in self.items]


class _FakeUow:
    async def commit(self) -> None:
        return None


class _FakeImages:
    def __init__(self, images: list[Image] | None = None) -> None:
        self.images = images or []

    async def list_by_project(self, project_id):
        return [item for item in self.images if item.project_id == project_id]

    async def update(self, image: Image) -> None:
        for index, item in enumerate(self.images):
            if item.id == image.id:
                self.images[index] = image


class _FakeAnnotations:
    def __init__(
        self,
        items: list[Annotation] | None = None,
        classes: _FakeClasses | None = None,
    ) -> None:
        self.items = items or []
        self.classes = classes

    async def list_by_image(self, image_id):
        known = {item.id for item in self.classes.items} if self.classes is not None else None
        return [
            item
            for item in self.items
            if item.image_id == image_id
            and (known is None or item.class_id in known)
        ]


def _delete_use_case(project: Project, classes: _FakeClasses, **kwargs):
    return DeleteClassUseCase(
        _FakeProjects(project),
        classes,
        _FakeUow(),
        kwargs.get("images", _FakeImages()),
        kwargs.get("annotations", _FakeAnnotations()),
    )


@pytest.mark.asyncio
async def test_class_indices_increment_without_gaps() -> None:
    project = Project.create("P")
    classes = _FakeClasses()
    use_case = CreateClassUseCase(_FakeProjects(project), classes, _FakeUow())

    first = await use_case.execute(project.id, "defect", "#FF0000")
    second = await use_case.execute(project.id, "scratch", "#00FF00")
    third = await use_case.execute(project.id, "dent", "#0000FF")

    assert [first.index_id, second.index_id, third.index_id] == [0, 1, 2]


@pytest.mark.asyncio
async def test_duplicate_class_name_is_rejected() -> None:
    project = Project.create("P")
    classes = _FakeClasses()
    use_case = CreateClassUseCase(_FakeProjects(project), classes, _FakeUow())
    await use_case.execute(project.id, "defect", "#FF0000")

    with pytest.raises(DomainValidationException, match="name"):
        await use_case.execute(project.id, "defect", "#00FF00")


@pytest.mark.asyncio
async def test_delete_class_compacts_remaining_indices() -> None:
    project = Project.create("P")
    classes = _FakeClasses()
    create = CreateClassUseCase(_FakeProjects(project), classes, _FakeUow())
    first = await create.execute(project.id, "a", "#111111")
    await create.execute(project.id, "b", "#222222")
    await create.execute(project.id, "c", "#333333")

    delete = _delete_use_case(project, classes)
    await delete.execute(first.id, project.id)

    remaining = await classes.list_by_project(project.id)
    assert sorted(item.index_id for item in remaining) == [0, 1]
    assert {item.name for item in remaining} == {"b", "c"}


@pytest.mark.asyncio
async def test_create_class_requires_existing_project() -> None:
    use_case = CreateClassUseCase(_FakeProjects(Project.create("P")), _FakeClasses(), _FakeUow())
    with pytest.raises(ResourceNotFoundException):
        await use_case.execute(uuid4(), "x", "#FFFFFF")


@pytest.mark.asyncio
async def test_delete_class_rejects_unknown_project() -> None:
    project = Project.create("P")
    classes = _FakeClasses()
    created = await CreateClassUseCase(_FakeProjects(project), classes, _FakeUow()).execute(
        project.id, "a", "#111111"
    )
    with pytest.raises(ResourceNotFoundException):
        await _delete_use_case(project, classes).execute(created.id, uuid4())


@pytest.mark.asyncio
async def test_delete_class_rejects_project_mismatch() -> None:
    project = Project.create("P")
    other = Project.create("Q")
    classes = _FakeClasses()
    created = await CreateClassUseCase(_FakeProjects(project), classes, _FakeUow()).execute(
        project.id, "a", "#111111"
    )
    with pytest.raises(ResourceNotFoundException):
        await _delete_use_case(project, classes).execute(created.id, other.id)


@pytest.mark.asyncio
async def test_delete_class_recalculates_image_status() -> None:
    project = Project.create("P")
    classes = _FakeClasses()
    created = await CreateClassUseCase(_FakeProjects(project), classes, _FakeUow()).execute(
        project.id, "a", "#111111"
    )
    image = Image.create(
        project_id=project.id,
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    box = Annotation.create_manual(
        image.id, created.id, BoundingBox(0.5, 0.5, 0.1, 0.1)
    )
    image.recalculate_status([box])
    assert image.status == ImageStatus.VERIFIED

    annotations = _FakeAnnotations([box], classes=classes)
    images = _FakeImages([image])
    await _delete_use_case(project, classes, images=images, annotations=annotations).execute(
        created.id, project.id
    )

    assert images.images[0].status == ImageStatus.UNANNOTATED


@pytest.mark.asyncio
async def test_rename_class_updates_name() -> None:
    from app.application.use_cases.classes.rename_class import RenameClassUseCase

    project = Project.create("P")
    classes = _FakeClasses()
    created = await CreateClassUseCase(_FakeProjects(project), classes, _FakeUow()).execute(
        project.id, "car", "#FF0000"
    )
    renamed = await RenameClassUseCase(_FakeProjects(project), classes, _FakeUow()).execute(
        created.id, project.id, " vehicle "
    )
    assert renamed.name == "vehicle"
    assert classes.items[0].name == "vehicle"


@pytest.mark.asyncio
async def test_rename_class_rejects_duplicate_name() -> None:
    from app.application.use_cases.classes.rename_class import RenameClassUseCase

    project = Project.create("P")
    classes = _FakeClasses()
    create = CreateClassUseCase(_FakeProjects(project), classes, _FakeUow())
    await create.execute(project.id, "car", "#FF0000")
    second = await create.execute(project.id, "truck", "#00FF00")
    with pytest.raises(DomainValidationException, match="already exists"):
        await RenameClassUseCase(_FakeProjects(project), classes, _FakeUow()).execute(
            second.id, project.id, "car"
        )
