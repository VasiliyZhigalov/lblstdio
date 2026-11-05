from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, SplitType
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.session import create_session_factory, dispose_engine


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine, factory = await create_session_factory("sqlite+aiosqlite:///:memory:")
    async with factory() as db_session:
        yield db_session
    await dispose_engine(engine)


@pytest.mark.asyncio
async def test_list_page_filters_and_limits_in_sql(session: AsyncSession) -> None:
    projects = SqliteProjectRepository(session)
    images = SqliteImageRepository(session)
    project = Project.create("Paged")
    other = Project.create("Other")
    await projects.add(project)
    await projects.add(other)

    base = datetime.now(UTC)
    seeded: list[Image] = []
    for index, (split, status, name) in enumerate(
        [
            (SplitType.TRAIN, ImageStatus.UNANNOTATED, "t0.png"),
            (SplitType.TRAIN, ImageStatus.VERIFIED, "t1.png"),
            (SplitType.TRAIN, ImageStatus.VERIFIED, "t2.png"),
            (SplitType.TEST, ImageStatus.VERIFIED, "test.png"),
        ]
    ):
        image = Image.create(
            project_id=project.id,
            file_path=name,
            file_name=name,
            width=8,
            height=8,
            split=split,
        )
        image.status = status
        image.created_at = base + timedelta(seconds=index)
        seeded.append(image)
    outsider = Image.create(
        project_id=other.id,
        file_path="out.png",
        file_name="out.png",
        width=8,
        height=8,
        split=SplitType.TRAIN,
    )
    outsider.status = ImageStatus.VERIFIED
    await images.add_many([*seeded, outsider])
    await session.commit()

    page = await images.list_page(
        project.id,
        split=SplitType.TRAIN,
        status=ImageStatus.VERIFIED,
        offset=1,
        limit=1,
    )

    assert [item.file_name for item in page] == ["t2.png"]
    assert not hasattr(images, "_last_python_slice")
