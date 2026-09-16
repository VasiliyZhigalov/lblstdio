from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.domain.entities.model_version import ModelVersion
from app.infrastructure.db.mappers import ensure_utc
from app.infrastructure.db.tables import ModelVersionRow


def _to_row(version: ModelVersion) -> ModelVersionRow:
    return ModelVersionRow(
        id=str(version.id),
        project_id=str(version.project_id),
        dataset_version_id=(
            str(version.dataset_version_id) if version.dataset_version_id else None
        ),
        training_job_id=(
            str(version.training_job_id) if version.training_job_id else None
        ),
        version_number=version.version_number,
        name=version.name or f"Model v{version.version_number}",
        weights_path=version.weights_path,
        map50=version.map50,
        map50_95=version.map50_95,
        precision=version.precision,
        recall=version.recall,
        is_active_for_stream=1 if version.is_active_for_stream else 0,
        created_at=version.created_at,
    )


def _from_row(row: ModelVersionRow) -> ModelVersion:
    return ModelVersion(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        dataset_version_id=(
            UUID(row.dataset_version_id) if row.dataset_version_id else None
        ),
        training_job_id=UUID(row.training_job_id) if row.training_job_id else None,
        version_number=row.version_number,
        name=getattr(row, "name", None) or f"Model v{row.version_number}",
        weights_path=row.weights_path,
        map50=row.map50,
        map50_95=row.map50_95,
        precision=row.precision,
        recall=row.recall,
        is_active_for_stream=bool(row.is_active_for_stream),
        created_at=ensure_utc(row.created_at),
    )


class SqliteModelVersionRepository(IModelVersionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, version: ModelVersion) -> None:
        self._session.add(_to_row(version))
        await self._session.flush()

    async def get_by_id(self, version_id: UUID) -> ModelVersion | None:
        row = await self._session.get(ModelVersionRow, str(version_id))
        return _from_row(row) if row else None

    async def list_by_project(self, project_id: UUID) -> list[ModelVersion]:
        result = await self._session.scalars(
            select(ModelVersionRow)
            .where(ModelVersionRow.project_id == str(project_id))
            .order_by(ModelVersionRow.version_number.desc())
        )
        return [_from_row(row) for row in result]

    async def next_version_number(self, project_id: UUID) -> int:
        current = await self._session.scalar(
            select(func.max(ModelVersionRow.version_number)).where(
                ModelVersionRow.project_id == str(project_id)
            )
        )
        return int(current or 0) + 1

    async def deactivate_stream_models(self, project_id: UUID) -> None:
        await self._session.execute(
            update(ModelVersionRow)
            .where(ModelVersionRow.project_id == str(project_id))
            .values(is_active_for_stream=0)
        )
        await self._session.flush()

    async def list_by_dataset_version(
        self, dataset_version_id: UUID
    ) -> list[ModelVersion]:
        result = await self._session.scalars(
            select(ModelVersionRow)
            .where(ModelVersionRow.dataset_version_id == str(dataset_version_id))
            .order_by(ModelVersionRow.version_number.desc())
        )
        return [_from_row(row) for row in result]

    async def update(self, version: ModelVersion) -> None:
        row = await self._session.get(ModelVersionRow, str(version.id))
        if row is None:
            return
        row.name = version.name
        row.dataset_version_id = (
            str(version.dataset_version_id) if version.dataset_version_id else None
        )
        row.training_job_id = (
            str(version.training_job_id) if version.training_job_id else None
        )
        row.weights_path = version.weights_path
        row.map50 = version.map50
        row.map50_95 = version.map50_95
        row.precision = version.precision
        row.recall = version.recall
        row.is_active_for_stream = 1 if version.is_active_for_stream else 0
        await self._session.flush()

    async def delete(self, version_id: UUID) -> None:
        row = await self._session.get(ModelVersionRow, str(version_id))
        if row is None:
            return
        await self._session.delete(row)
        await self._session.flush()
