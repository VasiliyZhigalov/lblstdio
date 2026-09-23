from uuid import UUID

from app.application.ports.repositories.annotation_audit_job_repository import (
    IAnnotationAuditJobRepository,
)
from app.application.ports.repositories.auto_label_job_repository import (
    IAutoLabelJobRepository,
)
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.repositories.training_job_repository import (
    ITrainingJobRepository,
)
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.enums import (
    AnnotationAuditJobStatus,
    AutoLabelJobStatus,
    TrainingJobStatus,
)
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException

_ACTIVE_TRAINING = {TrainingJobStatus.QUEUED, TrainingJobStatus.RUNNING}
_ACTIVE_AUTO_LABEL = {AutoLabelJobStatus.PENDING, AutoLabelJobStatus.RUNNING}
_ACTIVE_AUDIT = {AnnotationAuditJobStatus.PENDING, AnnotationAuditJobStatus.RUNNING}


class DeleteProjectUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        storage: IFileStorage,
        uow: IUnitOfWork,
        *,
        training_jobs: ITrainingJobRepository | None = None,
        auto_label_jobs: IAutoLabelJobRepository | None = None,
        audit_jobs: IAnnotationAuditJobRepository | None = None,
    ) -> None:
        self._projects = projects
        self._storage = storage
        self._uow = uow
        self._training_jobs = training_jobs
        self._auto_label_jobs = auto_label_jobs
        self._audit_jobs = audit_jobs

    async def execute(self, project_id: UUID) -> None:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")
        if await self._has_active_job(project_id):
            raise DomainValidationException(
                "cannot delete project while a job is queued or running"
            )
        await self._projects.delete(project_id)
        await self._uow.commit()
        await self._storage.delete_directory(f"projects/{project_id}")

    async def _has_active_job(self, project_id: UUID) -> bool:
        if self._training_jobs is not None:
            training = await self._training_jobs.list_by_project(project_id)
            if any(job.status in _ACTIVE_TRAINING for job in training):
                return True
        if self._auto_label_jobs is not None:
            auto_label = await self._auto_label_jobs.list_by_project(project_id)
            if any(job.status in _ACTIVE_AUTO_LABEL for job in auto_label):
                return True
        if self._audit_jobs is not None:
            audits = await self._audit_jobs.list_by_project(project_id)
            if any(job.status in _ACTIVE_AUDIT for job in audits):
                return True
        return False
