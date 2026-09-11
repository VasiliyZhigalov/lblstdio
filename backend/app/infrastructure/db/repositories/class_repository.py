from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.class_repository import IClassRepository
from app.domain.entities.annotation_class import AnnotationClass
from app.infrastructure.db.mappers import class_to_row, row_to_class
from app.infrastructure.db.tables import ClassRow


class SqliteClassRepository(IClassRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, annotation_class: AnnotationClass) -> None:
        self._session.add(class_to_row(annotation_class))
        await self._session.flush()

    async def get_by_id(self, class_id: UUID) -> AnnotationClass | None:
        row = await self._session.get(ClassRow, str(class_id))
        return row_to_class(row) if row else None

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        result = await self._session.scalars(
            select(ClassRow)
            .where(ClassRow.project_id == str(project_id))
            .order_by(ClassRow.index_id)
        )
        return [row_to_class(row) for row in result]

    async def delete(self, class_id: UUID) -> None:
        row = await self._session.get(ClassRow, str(class_id))
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()

    async def update_many(self, classes: Sequence[AnnotationClass]) -> None:
        offset = max((item.index_id for item in classes), default=0) + len(classes) + 1
        for item in classes:
            row = await self._session.get(ClassRow, str(item.id))
            if row is None:
                continue
            row.index_id = item.index_id + offset
        await self._session.flush()
        for item in classes:
            row = await self._session.get(ClassRow, str(item.id))
            if row is None:
                continue
            row.name = item.name
            row.color_hex = item.color_hex
            row.index_id = item.index_id
        await self._session.flush()
