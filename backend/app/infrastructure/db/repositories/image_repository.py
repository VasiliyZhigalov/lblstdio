from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.image_repository import IImageRepository
from app.domain.entities.image import Image
from app.infrastructure.db.mappers import image_to_row, row_to_image
from app.infrastructure.db.tables import DatasetItemRow, ImageRow


class SqliteImageRepository(IImageRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, images: Sequence[Image]) -> None:
        self._session.add_all([image_to_row(item) for item in images])
        await self._session.flush()

    async def get_by_id(self, image_id: UUID) -> Image | None:
        row = await self._session.get(ImageRow, str(image_id))
        return row_to_image(row) if row else None

    async def list_by_project(self, project_id: UUID) -> list[Image]:
        result = await self._session.scalars(
            select(ImageRow)
            .where(ImageRow.project_id == str(project_id))
            .order_by(ImageRow.created_at)
        )
        return [row_to_image(row) for row in result]

    async def update(self, image: Image) -> None:
        row = await self._session.get(ImageRow, str(image.id))
        if row is None:
            return
        row.file_path = image.file_path
        row.file_name = image.file_name
        row.width = image.width
        row.height = image.height
        row.source_type = image.source_type.value
        row.split = image.split.value
        row.status = image.status.value
        row.is_background = 1 if image.is_background else 0
        row.stream_source_id = (
            str(image.stream_source_id) if image.stream_source_id else None
        )
        await self._session.flush()

    async def delete(self, image_id: UUID) -> None:
        await self._session.execute(
            delete(DatasetItemRow).where(DatasetItemRow.image_id == str(image_id))
        )
        row = await self._session.get(ImageRow, str(image_id))
        if row is None:
            return
        await self._session.delete(row)
        await self._session.flush()
