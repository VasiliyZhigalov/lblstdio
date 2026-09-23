from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.entities.project import Project
from app.domain.enums import ProjectTaskType, SplitType, SourceType, VerificationStatus
from app.infrastructure.db.mappers import row_to_project
from app.infrastructure.db.repositories.class_repository import SqliteClassRepository
from app.infrastructure.db.repositories.image_label_repository import (
    SqliteImageLabelRepository,
)
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.session import create_session_factory, dispose_engine


@pytest.mark.asyncio
async def test_project_task_type_roundtrip(tmp_path) -> None:
    engine, factory = await create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with factory() as session:
        repo = SqliteProjectRepository(session)
        project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
        await repo.add(project)
        await session.commit()
        loaded = await repo.get_by_id(project.id)
        assert loaded is not None
        assert loaded.task_type == ProjectTaskType.CLASSIFICATION
    await dispose_engine(engine)


def test_row_to_project_defaults_detection_when_column_missing() -> None:
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=str(uuid4()),
        name="Legacy",
        description=None,
        created_at=now,
        updated_at=now,
    )
    restored = row_to_project(row)
    assert restored.task_type == ProjectTaskType.DETECTION


@pytest.mark.asyncio
async def test_image_label_upsert_replaces_same_image(tmp_path) -> None:
    engine, factory = await create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with factory() as session:
        projects = SqliteProjectRepository(session)
        classes = SqliteClassRepository(session)
        images = SqliteImageRepository(session)
        labels = SqliteImageLabelRepository(session)

        project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
        cls_a = AnnotationClass.create(project.id, "good", "#00FF00", 0)
        cls_b = AnnotationClass.create(project.id, "bad", "#FF0000", 1)
        image = Image.create(
            project_id=project.id,
            file_path="a.png",
            file_name="a.png",
            width=10,
            height=10,
            split=SplitType.TRAIN,
        )
        await projects.add(project)
        await classes.add(cls_a)
        await classes.add(cls_b)
        await images.add_many([image])

        first = ImageLabel.create_manual(image.id, cls_a.id)
        await labels.upsert(first)
        await session.commit()

        second = ImageLabel.create_prediction(image.id, cls_b.id, 0.8)
        await labels.upsert(second)
        await session.commit()

        stored = await labels.get_by_image_id(image.id)
        listed = await labels.list_by_image_ids([image.id])
        assert stored is not None
        assert stored.class_id == cls_b.id
        assert stored.source == SourceType.MODEL_PREDICTION
        assert stored.verification_status == VerificationStatus.PENDING_REVIEW
        assert listed == [stored]

        await labels.delete_by_image_id(image.id)
        await session.commit()
        assert await labels.get_by_image_id(image.id) is None
    await dispose_engine(engine)
