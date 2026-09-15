from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.stream_source_repository import (
    IStreamSourceRepository,
)
from app.domain.entities.stream_source import StreamSource
from app.infrastructure.db.mappers import row_to_stream_source, stream_source_to_row
from app.infrastructure.db.tables import StreamSourceRow


class SqliteStreamSourceRepository(IStreamSourceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, stream: StreamSource) -> None:
        self._session.add(stream_source_to_row(stream))
        await self._session.flush()

    async def get_by_id(self, stream_id: UUID) -> StreamSource | None:
        row = await self._session.get(StreamSourceRow, str(stream_id))
        return row_to_stream_source(row) if row else None

    async def list_by_project(self, project_id: UUID) -> list[StreamSource]:
        result = await self._session.scalars(
            select(StreamSourceRow)
            .where(StreamSourceRow.project_id == str(project_id))
            .order_by(StreamSourceRow.created_at.desc())
        )
        return [row_to_stream_source(row) for row in result]

    async def update(self, stream: StreamSource) -> None:
        row = await self._session.get(StreamSourceRow, str(stream.id))
        if row is None:
            return
        row.name = stream.name
        row.source_type = stream.source_type.value
        row.source_uri = stream.source_uri
        row.is_active = 1 if stream.is_active else 0
        row.model_version_id = (
            str(stream.model_version_id) if stream.model_version_id else None
        )
        row.config_json = stream_source_to_row(stream).config_json
        row.captured_frames_count = stream.captured_frames_count
        await self._session.flush()

    async def delete(self, stream_id: UUID) -> None:
        row = await self._session.get(StreamSourceRow, str(stream_id))
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()

    async def get_active_for_project(self, project_id: UUID) -> StreamSource | None:
        result = await self._session.scalars(
            select(StreamSourceRow).where(
                StreamSourceRow.project_id == str(project_id),
                StreamSourceRow.is_active == 1,
            )
        )
        row = result.first()
        return row_to_stream_source(row) if row else None
