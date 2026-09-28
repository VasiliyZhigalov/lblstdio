from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.entities.project import Project
from app.domain.enums import ImageListSort, SplitType
from app.domain.value_objects.bounding_box import BoundingBox
from app.infrastructure.db.repositories.annotation_repository import SqliteAnnotationRepository
from app.infrastructure.db.repositories.class_repository import SqliteClassRepository
from app.infrastructure.db.repositories.image_label_repository import SqliteImageLabelRepository
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.session import create_session_factory, dispose_engine


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine, factory = await create_session_factory("sqlite+aiosqlite:///:memory:")
    async with factory() as db_session:
        yield db_session
    await dispose_engine(engine)


def _image(project_id, name: str, *, created_offset: int) -> Image:
    image = Image.create(
        project_id=project_id,
        file_path=name,
        file_name=name,
        width=8,
        height=8,
        split=SplitType.TRAIN,
    )
    image.created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=created_offset)
    return image


@pytest.mark.asyncio
async def test_uncertainty_sort_uses_the_lowest_model_confidence(session: AsyncSession) -> None:
    projects = SqliteProjectRepository(session)
    images = SqliteImageRepository(session)
    classes = SqliteClassRepository(session)
    annotations = SqliteAnnotationRepository(session)
    labels = SqliteImageLabelRepository(session)
    project = Project.create("Queue")
    await projects.add(project)
    annotation_class = AnnotationClass.create(project.id, "defect", "#EF4444", 0)
    await classes.add(annotation_class)

    sure = _image(project.id, "sure.png", created_offset=0)
    unsure = _image(project.id, "unsure.png", created_offset=1)
    manual = _image(project.id, "manual.png", created_offset=2)
    labeled = _image(project.id, "labeled.png", created_offset=3)
    await images.add_many([sure, unsure, manual, labeled])

    box = BoundingBox(x_center=0.5, y_center=0.5, width=0.2, height=0.2)
    await annotations.replace_for_image(
        sure.id,
        [
            Annotation.create_prediction(sure.id, annotation_class.id, box, 0.91),
            Annotation.create_prediction(sure.id, annotation_class.id, box, 0.4),
        ],
    )
    await annotations.replace_for_image(
        unsure.id,
        [Annotation.create_prediction(unsure.id, annotation_class.id, box, 0.22)],
    )
    await annotations.replace_for_image(
        manual.id,
        [Annotation.create_manual(manual.id, annotation_class.id, box)],
    )
    await labels.upsert(
        ImageLabel.create_prediction(labeled.id, annotation_class.id, confidence=0.55)
    )
    await session.commit()

    ordered = await images.list_page(project.id, sort=ImageListSort.UNCERTAINTY)
    assert [item.file_name for item in ordered] == [
        "unsure.png",
        "sure.png",
        "labeled.png",
        "manual.png",
    ]

    scores = await images.min_model_confidence([item.id for item in ordered])
    assert scores[unsure.id] == pytest.approx(0.22)
    assert scores[sure.id] == pytest.approx(0.4)
    assert scores[labeled.id] == pytest.approx(0.55)
    assert manual.id not in scores

    created_order = await images.list_page(project.id)
    assert [item.file_name for item in created_order] == [
        "sure.png",
        "unsure.png",
        "manual.png",
        "labeled.png",
    ]
