from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.project_repository import IProjectRepository
from app.domain.entities.project import Project
from app.infrastructure.db.mappers import project_to_row, row_to_project
from app.infrastructure.db.tables import (
    AnnotationAuditJobRow,
    AutoLabelJobRow,
    ModelVersionRow,
    ProjectRow,
    TrainingJobRow,
    VersionSequenceRow,
)


class SqliteProjectRepository(IProjectRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, project: Project) -> None:
        self._session.add(project_to_row(project))
        await self._session.flush()

    async def get_by_id(self, project_id: UUID) -> Project | None:
        row = await self._session.get(ProjectRow, str(project_id))
        return row_to_project(row) if row else None

    async def list_all(self) -> list[Project]:
        result = await self._session.scalars(
            select(ProjectRow).order_by(ProjectRow.created_at.desc())
        )
        return [row_to_project(row) for row in result]

    async def update(self, project: Project) -> None:
        row = await self._session.get(ProjectRow, str(project.id))
        if row is None:
            return
        row.name = project.name
        row.description = project.description
        row.updated_at = project.updated_at
        row.task_type = project.task_type.value
        await self._session.flush()

    async def delete(self, project_id: UUID) -> None:
        project_key = str(project_id)
        for table in (
            TrainingJobRow,
            AutoLabelJobRow,
            AnnotationAuditJobRow,
            ModelVersionRow,
            VersionSequenceRow,
        ):
            await self._session.execute(
                delete(table).where(table.project_id == project_key)
            )
        row = await self._session.get(ProjectRow, project_key)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
