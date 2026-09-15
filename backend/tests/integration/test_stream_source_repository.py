from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.project import Project
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType, TripwireDirection
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.repositories.stream_source_repository import (
    SqliteStreamSourceRepository,
)
from app.infrastructure.db.session import create_session_factory, dispose_engine


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine, factory = await create_session_factory("sqlite+aiosqlite:///:memory:")
    async with factory() as db_session:
        yield db_session
    await dispose_engine(engine)


@pytest.mark.asyncio
async def test_stream_source_crud_and_active_lookup(session: AsyncSession) -> None:
    projects = SqliteProjectRepository(session)
    streams = SqliteStreamSourceRepository(session)

    project = Project.create("Streams")
    await projects.add(project)

    src = StreamSource.create(
        project_id=project.id,
        name="Gate",
        source_type=StreamSourceType.RTSP,
        source_uri="rtsp://127.0.0.1/cam",
    )
    await streams.add(src)
    await session.commit()

    listed = await streams.list_by_project(project.id)
    assert len(listed) == 1
    assert listed[0].name == "Gate"
    assert await streams.get_active_for_project(project.id) is None

    cfg = StreamTriggerConfig(
        timer_enabled=True,
        tripwire_line=(0.1, 0.2, 0.9, 0.2),
        tripwire_direction=TripwireDirection.FORWARD,
    )
    src.update_config(cfg)
    src.activate()
    await streams.update(src)
    await session.commit()

    active = await streams.get_active_for_project(project.id)
    assert active is not None
    assert active.is_active is True
    assert active.config.tripwire_line == (0.1, 0.2, 0.9, 0.2)
    assert active.config.tripwire_direction == TripwireDirection.FORWARD

    await streams.delete(src.id)
    await session.commit()
    assert await streams.get_by_id(src.id) is None
    assert await streams.list_by_project(project.id) == []
