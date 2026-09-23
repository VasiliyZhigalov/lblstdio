from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.image_label_repository import (
    IImageLabelRepository,
)
from app.domain.entities.image_label import ImageLabel
from app.infrastructure.db.mappers import label_to_row, row_to_label
from app.infrastructure.db.tables import ImageLabelRow


class SqliteImageLabelRepository(IImageLabelRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_image_id(self, image_id: UUID) -> ImageLabel | None:
        result = await self._session.scalars(
            select(ImageLabelRow).where(ImageLabelRow.image_id == str(image_id))
        )
        row = result.first()
        return row_to_label(row) if row else None

    async def list_by_image_ids(self, image_ids: Sequence[UUID]) -> list[ImageLabel]:
        if not image_ids:
            return []
        result = await self._session.scalars(
            select(ImageLabelRow).where(
                ImageLabelRow.image_id.in_([str(item) for item in image_ids])
            )
        )
        return [row_to_label(row) for row in result]

    async def upsert(self, label: ImageLabel) -> None:
        await self._session.execute(
            delete(ImageLabelRow).where(ImageLabelRow.image_id == str(label.image_id))
        )
        self._session.add(label_to_row(label))
        await self._session.flush()

    async def delete_by_image_id(self, image_id: UUID) -> None:
        await self._session.execute(
            delete(ImageLabelRow).where(ImageLabelRow.image_id == str(image_id))
        )
        await self._session.flush()
