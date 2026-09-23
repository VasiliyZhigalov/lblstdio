from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.annotation_audit_job import AnnotationAuditJob
from app.domain.enums import AnnotationAuditJobStatus


class IAnnotationAuditJobRepository(ABC):
    @abstractmethod
    async def add(self, job: AnnotationAuditJob) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update(self, job: AnnotationAuditJob) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, job_id: UUID) -> AnnotationAuditJob | None:
        raise NotImplementedError

    @abstractmethod
    async def find_active(
        self, project_id: UUID, model_version_id: UUID
    ) -> AnnotationAuditJob | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_statuses(
        self, statuses: Sequence[AnnotationAuditJobStatus]
    ) -> list[AnnotationAuditJob]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> list[AnnotationAuditJob]:
        raise NotImplementedError
