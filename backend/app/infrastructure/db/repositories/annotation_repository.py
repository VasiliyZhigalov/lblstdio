from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.domain.entities.annotation import Annotation
from app.infrastructure.db.mappers import annotation_to_row, row_to_annotation
from app.infrastructure.db.tables import AnnotationRow


class SqliteAnnotationRepository(IAnnotationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_image(
        self, image_id: UUID, annotations: Sequence[Annotation]
    ) -> None:
        await self._session.execute(
            delete(AnnotationRow).where(AnnotationRow.image_id == str(image_id))
        )
        self._session.add_all([annotation_to_row(item) for item in annotations])
        await self._session.flush()

    async def list_by_image(self, image_id: UUID) -> list[Annotation]:
        result = await self._session.scalars(
            select(AnnotationRow).where(AnnotationRow.image_id == str(image_id))
        )
        return [row_to_annotation(row) for row in result]

    async def list_by_image_ids(self, image_ids: Sequence[UUID]) -> list[Annotation]:
        if not image_ids:
            return []
        result = await self._session.scalars(
            select(AnnotationRow).where(
                AnnotationRow.image_id.in_([str(item) for item in image_ids])
            )
        )
        return [row_to_annotation(row) for row in result]

    async def clear_model_version_refs(self, model_version_id: UUID) -> None:
        await self._session.execute(
            update(AnnotationRow)
            .where(AnnotationRow.model_version_id == str(model_version_id))
            .values(model_version_id=None)
        )
        await self._session.flush()
