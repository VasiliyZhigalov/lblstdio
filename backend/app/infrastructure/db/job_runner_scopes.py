from __future__ import annotations

from contextlib import asynccontextmanager

from app.application.ports.job_runner_scopes import (
    AuditRunnerScope,
    AuditScopeFactory,
    AutoLabelRunnerScope,
    AutoLabelScopeFactory,
    TrainingRunnerScope,
    TrainingScopeFactory,
)
from app.infrastructure.db.repositories.annotation_audit_job_repository import (
    SqliteAnnotationAuditJobRepository,
)
from app.infrastructure.db.repositories.annotation_repository import (
    SqliteAnnotationRepository,
)
from app.infrastructure.db.repositories.auto_label_job_repository import (
    SqliteAutoLabelJobRepository,
)
from app.infrastructure.db.repositories.class_repository import SqliteClassRepository
from app.infrastructure.db.repositories.dataset_version_repository import (
    SqliteDatasetVersionRepository,
)
from app.infrastructure.db.repositories.image_label_repository import (
    SqliteImageLabelRepository,
)
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.model_version_repository import (
    SqliteModelVersionRepository,
)
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.repositories.training_job_repository import (
    SqliteTrainingJobRepository,
)
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


def training_runner_scope(session_factory) -> TrainingScopeFactory:
    @asynccontextmanager
    async def open_scope():
        async with session_factory() as session:
            yield TrainingRunnerScope(
                jobs=SqliteTrainingJobRepository(session),
                datasets=SqliteDatasetVersionRepository(session),
                models=SqliteModelVersionRepository(session),
                projects=SqliteProjectRepository(session),
                uow=SqlAlchemyUnitOfWork(session),
            )

    return open_scope


def auto_label_runner_scope(session_factory) -> AutoLabelScopeFactory:
    @asynccontextmanager
    async def open_scope():
        async with session_factory() as session:
            yield AutoLabelRunnerScope(
                models=SqliteModelVersionRepository(session),
                images=SqliteImageRepository(session),
                annotations=SqliteAnnotationRepository(session),
                classes=SqliteClassRepository(session),
                jobs=SqliteAutoLabelJobRepository(session),
                projects=SqliteProjectRepository(session),
                labels=SqliteImageLabelRepository(session),
                uow=SqlAlchemyUnitOfWork(session),
            )

    return open_scope


def audit_runner_scope(session_factory) -> AuditScopeFactory:
    @asynccontextmanager
    async def open_scope():
        async with session_factory() as session:
            yield AuditRunnerScope(
                jobs=SqliteAnnotationAuditJobRepository(session),
                projects=SqliteProjectRepository(session),
                images=SqliteImageRepository(session),
                annotations=SqliteAnnotationRepository(session),
                classes=SqliteClassRepository(session),
                models=SqliteModelVersionRepository(session),
                uow=SqlAlchemyUnitOfWork(session),
            )

    return open_scope
