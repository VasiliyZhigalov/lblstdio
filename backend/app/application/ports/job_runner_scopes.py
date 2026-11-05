from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TypeAlias

from app.application.ports.repositories.annotation_audit_job_repository import (
    IAnnotationAuditJobRepository,
)
from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.auto_label_job_repository import (
    IAutoLabelJobRepository,
)
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.dataset_version_repository import (
    IDatasetVersionRepository,
)
from app.application.ports.repositories.image_label_repository import IImageLabelRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.repositories.training_job_repository import (
    ITrainingJobRepository,
)
from app.application.ports.unit_of_work import IUnitOfWork


@dataclass
class TrainingRunnerScope:
    jobs: ITrainingJobRepository
    datasets: IDatasetVersionRepository
    models: IModelVersionRepository
    projects: IProjectRepository
    uow: IUnitOfWork


@dataclass
class AutoLabelRunnerScope:
    models: IModelVersionRepository
    images: IImageRepository
    annotations: IAnnotationRepository
    classes: IClassRepository
    jobs: IAutoLabelJobRepository
    projects: IProjectRepository
    labels: IImageLabelRepository
    uow: IUnitOfWork


@dataclass
class AuditRunnerScope:
    jobs: IAnnotationAuditJobRepository
    projects: IProjectRepository
    images: IImageRepository
    annotations: IAnnotationRepository
    classes: IClassRepository
    models: IModelVersionRepository
    uow: IUnitOfWork


TrainingScopeFactory: TypeAlias = Callable[
    [], AbstractAsyncContextManager[TrainingRunnerScope]
]
AutoLabelScopeFactory: TypeAlias = Callable[
    [], AbstractAsyncContextManager[AutoLabelRunnerScope]
]
AuditScopeFactory: TypeAlias = Callable[[], AbstractAsyncContextManager[AuditRunnerScope]]
