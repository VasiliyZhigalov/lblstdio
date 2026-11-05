from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.annotation_audit_job_repository import (
    IAnnotationAuditJobRepository,
)
from app.domain.entities.annotation_audit_job import AnnotationAuditJob
from app.domain.enums import AnnotationAuditJobStatus
from app.infrastructure.db.mappers import ensure_utc
from app.infrastructure.db.tables import AnnotationAuditJobRow


def _to_row(job: AnnotationAuditJob) -> AnnotationAuditJobRow:
    return AnnotationAuditJobRow(
        id=str(job.id),
        project_id=str(job.project_id),
        model_version_id=str(job.model_version_id),
        image_ids_json=[str(item) for item in job.image_ids],
        confidence_threshold=job.confidence_threshold,
        iou_threshold=job.iou_threshold,
        status=job.status.value,
        total_images=job.total_images,
        processed_images=job.processed_images,
        suspicious_images=job.suspicious_images,
        error_message=job.error_message,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def _from_row(row: AnnotationAuditJobRow) -> AnnotationAuditJob:
    return AnnotationAuditJob(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        model_version_id=UUID(row.model_version_id),
        image_ids=[UUID(item) for item in (row.image_ids_json or [])],
        confidence_threshold=row.confidence_threshold,
        iou_threshold=row.iou_threshold,
        status=AnnotationAuditJobStatus(row.status),
        total_images=row.total_images,
        processed_images=row.processed_images,
        suspicious_images=row.suspicious_images,
        error_message=row.error_message,
        created_at=ensure_utc(row.created_at),
        finished_at=ensure_utc(row.finished_at),
    )


class SqliteAnnotationAuditJobRepository(IAnnotationAuditJobRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: AnnotationAuditJob) -> None:
        self._session.add(_to_row(job))
        await self._session.flush()

    async def update(self, job: AnnotationAuditJob) -> None:
        row = await self._session.get(AnnotationAuditJobRow, str(job.id))
        if row is None:
            return
        row.status = job.status.value
        row.total_images = job.total_images
        row.processed_images = job.processed_images
        row.suspicious_images = job.suspicious_images
        row.error_message = job.error_message
        row.finished_at = job.finished_at
        await self._session.flush()

    async def get_by_id(self, job_id: UUID) -> AnnotationAuditJob | None:
        row = await self._session.get(AnnotationAuditJobRow, str(job_id))
        return _from_row(row) if row else None

    async def find_active(
        self, project_id: UUID, model_version_id: UUID
    ) -> AnnotationAuditJob | None:
        row = await self._session.scalar(
            select(AnnotationAuditJobRow)
            .where(
                AnnotationAuditJobRow.project_id == str(project_id),
                AnnotationAuditJobRow.model_version_id == str(model_version_id),
                AnnotationAuditJobRow.status.in_(
                    [
                        AnnotationAuditJobStatus.PENDING.value,
                        AnnotationAuditJobStatus.RUNNING.value,
                    ]
                ),
            )
            .order_by(AnnotationAuditJobRow.created_at.desc())
        )
        return _from_row(row) if row else None

    async def list_by_statuses(
        self, statuses: Sequence[AnnotationAuditJobStatus]
    ) -> list[AnnotationAuditJob]:
        if not statuses:
            return []
        rows = await self._session.scalars(
            select(AnnotationAuditJobRow).where(
                AnnotationAuditJobRow.status.in_([item.value for item in statuses])
            )
        )
        return [_from_row(row) for row in rows]

    async def list_by_project(self, project_id: UUID) -> list[AnnotationAuditJob]:
        rows = await self._session.scalars(
            select(AnnotationAuditJobRow).where(
                AnnotationAuditJobRow.project_id == str(project_id)
            )
        )
        return [_from_row(row) for row in rows]
