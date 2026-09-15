from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.auto_label_job_repository import (
    IAutoLabelJobRepository,
)
from app.domain.entities.auto_label_job import AutoLabelJob
from app.domain.enums import AutoLabelJobStatus
from app.infrastructure.db.mappers import ensure_utc
from app.infrastructure.db.tables import AutoLabelJobRow


def _to_row(job: AutoLabelJob) -> AutoLabelJobRow:
    return AutoLabelJobRow(
        id=str(job.id),
        project_id=str(job.project_id),
        model_version_id=str(job.model_version_id),
        confidence_threshold=job.confidence_threshold,
        status=job.status.value,
        image_ids_json=[str(item) for item in job.image_ids],
        total_images_processed=job.total_images_processed,
        total_predictions_generated=job.total_predictions_generated,
        error_message=job.error_message,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def _from_row(row: AutoLabelJobRow) -> AutoLabelJob:
    return AutoLabelJob(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        model_version_id=UUID(row.model_version_id),
        confidence_threshold=row.confidence_threshold,
        status=AutoLabelJobStatus(row.status),
        image_ids=[UUID(item) for item in (row.image_ids_json or [])],
        total_images_processed=row.total_images_processed,
        total_predictions_generated=row.total_predictions_generated,
        error_message=row.error_message,
        created_at=ensure_utc(row.created_at),
        finished_at=ensure_utc(row.finished_at),
    )


class SqliteAutoLabelJobRepository(IAutoLabelJobRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: AutoLabelJob) -> None:
        self._session.add(_to_row(job))
        await self._session.flush()

    async def update(self, job: AutoLabelJob) -> None:
        row = await self._session.get(AutoLabelJobRow, str(job.id))
        if row is None:
            return
        row.status = job.status.value
        row.total_images_processed = job.total_images_processed
        row.total_predictions_generated = job.total_predictions_generated
        row.error_message = job.error_message
        row.finished_at = job.finished_at
        await self._session.flush()

    async def get_by_id(self, job_id: UUID) -> AutoLabelJob | None:
        row = await self._session.get(AutoLabelJobRow, str(job_id))
        return _from_row(row) if row else None

    async def list_by_statuses(
        self, statuses: Sequence[AutoLabelJobStatus]
    ) -> list[AutoLabelJob]:
        if not statuses:
            return []
        result = await self._session.scalars(
            select(AutoLabelJobRow).where(
                AutoLabelJobRow.status.in_([item.value for item in statuses])
            )
        )
        return [_from_row(row) for row in result]

    async def delete_by_model_version(self, model_version_id: UUID) -> None:
        await self._session.execute(
            delete(AutoLabelJobRow).where(
                AutoLabelJobRow.model_version_id == str(model_version_id)
            )
        )
        await self._session.flush()

    async def delete_by_model_versions(
        self, model_version_ids: Sequence[UUID]
    ) -> None:
        if not model_version_ids:
            return
        await self._session.execute(
            delete(AutoLabelJobRow).where(
                AutoLabelJobRow.model_version_id.in_(
                    [str(item) for item in model_version_ids]
                )
            )
        )
        await self._session.flush()
