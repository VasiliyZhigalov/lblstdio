from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.training_job_repository import (
    ITrainingJobRepository,
)
from app.domain.entities.training_job import TrainingJob
from app.domain.enums import TrainingJobStatus
from app.infrastructure.db.mappers import ensure_utc
from app.infrastructure.db.tables import TrainingJobRow


def _to_row(job: TrainingJob) -> TrainingJobRow:
    return TrainingJobRow(
        id=str(job.id),
        project_id=str(job.project_id),
        dataset_version_id=str(job.dataset_version_id),
        status=job.status.value,
        epochs=job.epochs,
        batch_size=job.batch_size,
        imgsz=job.imgsz,
        device=job.device,
        base_weights=job.base_weights,
        patience=job.patience,
        metrics_history=list(job.metrics_history),
        test_metrics=job.test_metrics,
        current_epoch=job.current_epoch,
        stopped_early=1 if job.stopped_early else 0,
        model_version_id=str(job.model_version_id) if job.model_version_id else None,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _from_row(row: TrainingJobRow) -> TrainingJob:
    return TrainingJob(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        dataset_version_id=UUID(row.dataset_version_id),
        status=TrainingJobStatus(row.status),
        epochs=row.epochs,
        batch_size=row.batch_size,
        imgsz=row.imgsz,
        device=row.device,
        base_weights=row.base_weights,
        patience=getattr(row, "patience", 20) or 20,
        metrics_history=list(row.metrics_history or []),
        test_metrics=getattr(row, "test_metrics", None),
        current_epoch=row.current_epoch,
        stopped_early=bool(getattr(row, "stopped_early", 0)),
        model_version_id=UUID(row.model_version_id) if row.model_version_id else None,
        error_message=row.error_message,
        created_at=ensure_utc(row.created_at),
        started_at=ensure_utc(row.started_at),
        finished_at=ensure_utc(row.finished_at),
    )


class SqliteTrainingJobRepository(ITrainingJobRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: TrainingJob) -> None:
        self._session.add(_to_row(job))
        await self._session.flush()

    async def update(self, job: TrainingJob) -> None:
        row = await self._session.get(TrainingJobRow, str(job.id))
        if row is None:
            return
        row.status = job.status.value
        row.metrics_history = list(job.metrics_history)
        row.test_metrics = job.test_metrics
        row.current_epoch = job.current_epoch
        row.stopped_early = 1 if job.stopped_early else 0
        row.model_version_id = str(job.model_version_id) if job.model_version_id else None
        row.error_message = job.error_message
        row.started_at = job.started_at
        row.finished_at = job.finished_at
        await self._session.flush()

    async def get_by_id(self, job_id: UUID) -> TrainingJob | None:
        row = await self._session.get(TrainingJobRow, str(job_id))
        return _from_row(row) if row else None

    async def list_by_dataset_version(
        self, dataset_version_id: UUID
    ) -> list[TrainingJob]:
        result = await self._session.scalars(
            select(TrainingJobRow).where(
                TrainingJobRow.dataset_version_id == str(dataset_version_id)
            )
        )
        return [_from_row(row) for row in result]

    async def list_by_statuses(
        self, statuses: Sequence[TrainingJobStatus]
    ) -> list[TrainingJob]:
        if not statuses:
            return []
        result = await self._session.scalars(
            select(TrainingJobRow).where(
                TrainingJobRow.status.in_([item.value for item in statuses])
            )
        )
        return [_from_row(row) for row in result]

    async def list_by_project(self, project_id: UUID) -> list[TrainingJob]:
        result = await self._session.scalars(
            select(TrainingJobRow).where(TrainingJobRow.project_id == str(project_id))
        )
        return [_from_row(row) for row in result]

    async def delete_by_dataset_version(self, dataset_version_id: UUID) -> None:
        await self._session.execute(
            delete(TrainingJobRow).where(
                TrainingJobRow.dataset_version_id == str(dataset_version_id)
            )
        )
        await self._session.flush()

    async def delete(self, job_id: UUID) -> None:
        row = await self._session.get(TrainingJobRow, str(job_id))
        if row is None:
            return
        await self._session.delete(row)
        await self._session.flush()
