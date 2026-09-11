from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import SplitType
from app.domain.value_objects.bounding_box import BoundingBox
from app.infrastructure.db.repositories.annotation_repository import (
    SqliteAnnotationRepository,
)
from app.infrastructure.db.repositories.class_repository import SqliteClassRepository
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.session import create_session_factory, dispose_engine


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine, factory = await create_session_factory("sqlite+aiosqlite:///:memory:")
    async with factory() as db_session:
        yield db_session
    await dispose_engine(engine)


def _box() -> BoundingBox:
    return BoundingBox(x_center=0.5, y_center=0.5, width=0.2, height=0.1)


async def _seed(session: AsyncSession) -> tuple[Project, AnnotationClass, Image, Annotation]:
    projects = SqliteProjectRepository(session)
    classes = SqliteClassRepository(session)
    images = SqliteImageRepository(session)
    annotations = SqliteAnnotationRepository(session)

    project = Project.create("Cascade")
    annotation_class = AnnotationClass.create(project.id, "defect", "#FF0000", 0)
    image = Image.create(
        project_id=project.id,
        file_path="projects/p/images/a.png",
        file_name="a.png",
        width=64,
        height=48,
        split=SplitType.TRAIN,
    )
    annotation = Annotation.create_manual(image.id, annotation_class.id, _box())

    await projects.add(project)
    await classes.add(annotation_class)
    await images.add_many([image])
    await annotations.replace_for_image(image.id, [annotation])
    await session.commit()
    return project, annotation_class, image, annotation


class TestSqliteRepositories:
    @pytest.mark.asyncio
    async def test_class_delete_cascades_annotations(self, session: AsyncSession) -> None:
        _, annotation_class, image, _ = await _seed(session)
        classes = SqliteClassRepository(session)
        annotations = SqliteAnnotationRepository(session)

        await classes.delete(annotation_class.id)
        await session.commit()

        assert await annotations.list_by_image(image.id) == []
        assert await classes.get_by_id(annotation_class.id) is None

    @pytest.mark.asyncio
    async def test_project_delete_cascades_classes_and_images(
        self, session: AsyncSession
    ) -> None:
        project, _, image, _ = await _seed(session)
        projects = SqliteProjectRepository(session)
        classes = SqliteClassRepository(session)
        images = SqliteImageRepository(session)
        annotations = SqliteAnnotationRepository(session)

        await projects.delete(project.id)
        await session.commit()

        assert await projects.get_by_id(project.id) is None
        assert await classes.list_by_project(project.id) == []
        assert await images.list_by_project(project.id) == []
        assert await annotations.list_by_image(image.id) == []

    @pytest.mark.asyncio
    async def test_replace_annotations_rolls_back_with_session(
        self, session: AsyncSession
    ) -> None:
        _, annotation_class, image, original = await _seed(session)
        annotations = SqliteAnnotationRepository(session)
        replacement = Annotation.create_manual(
            image.id,
            annotation_class.id,
            BoundingBox(x_center=0.1, y_center=0.1, width=0.1, height=0.1),
        )

        await annotations.replace_for_image(image.id, [replacement])
        await session.rollback()

        stored = await annotations.list_by_image(image.id)
        assert len(stored) == 1
        assert stored[0].id == original.id
        assert stored[0].bbox.x_center == 0.5

    @pytest.mark.asyncio
    async def test_unique_class_name_per_project(self, session: AsyncSession) -> None:
        project, _, _, _ = await _seed(session)
        classes = SqliteClassRepository(session)
        duplicate = AnnotationClass.create(project.id, "defect", "#00FF00", 1)

        with pytest.raises(Exception):
            await classes.add(duplicate)
            await session.commit()

    @pytest.mark.asyncio
    async def test_get_missing_entities_return_none(self, session: AsyncSession) -> None:
        projects = SqliteProjectRepository(session)
        images = SqliteImageRepository(session)
        classes = SqliteClassRepository(session)

        assert await projects.get_by_id(uuid4()) is None
        assert await images.get_by_id(uuid4()) is None
        assert await classes.get_by_id(uuid4()) is None

    @pytest.mark.asyncio
    async def test_compacting_indices_after_delete_does_not_hit_unique_constraint(
        self, session: AsyncSession
    ) -> None:
        from app.domain.services.class_index import compact_indices

        projects = SqliteProjectRepository(session)
        classes = SqliteClassRepository(session)
        project = Project.create("Reindex")
        await projects.add(project)
        created = [
            AnnotationClass.create(project.id, name, color, index)
            for index, (name, color) in enumerate(
                (("a", "#111111"), ("b", "#222222"), ("c", "#333333"))
            )
        ]
        for item in created:
            await classes.add(item)
        await session.commit()

        await classes.delete(created[0].id)
        remaining = await classes.list_by_project(project.id)
        await classes.update_many(compact_indices(remaining))
        await session.commit()

        stored = await classes.list_by_project(project.id)
        assert sorted(item.index_id for item in stored) == [0, 1]
        assert {item.name for item in stored} == {"b", "c"}
