"""Deleting a project must not leave active jobs, orphan rows, or files."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.application.use_cases.projects.delete_project import DeleteProjectUseCase
from app.domain.entities.annotation_audit_job import AnnotationAuditJob
from app.domain.entities.auto_label_job import AutoLabelJob
from app.domain.entities.model_version import ModelVersion
from app.domain.entities.project import Project
from app.domain.entities.training_job import TrainingJob
from app.domain.exceptions import DomainValidationException
from app.infrastructure.db.repositories.annotation_audit_job_repository import (
    SqliteAnnotationAuditJobRepository,
)
from app.infrastructure.db.repositories.auto_label_job_repository import (
    SqliteAutoLabelJobRepository,
)
from app.infrastructure.db.repositories.model_version_repository import (
    SqliteModelVersionRepository,
)
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.repositories.training_job_repository import (
    SqliteTrainingJobRepository,
)
from app.infrastructure.db.session import create_session_factory, dispose_engine
from app.infrastructure.db.tables import (
    AnnotationAuditJobRow,
    AutoLabelJobRow,
    ModelVersionRow,
    TrainingJobRow,
    VersionSequenceRow,
)
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.storage.local_storage import LocalFileStorage


async def _engine(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}"
    return await create_session_factory(url)


async def _seed_active(session, kind: str, status: str):
    project = Project.create("Busy")
    await SqliteProjectRepository(session).add(project)
    if kind == "training":
        job = TrainingJob.create(
            project.id,
            uuid4(),
            epochs=1,
            batch_size=1,
            imgsz=32,
        )
        if status == "RUNNING":
            job.mark_running()
        await SqliteTrainingJobRepository(session).add(job)
    elif kind == "auto_label":
        job = AutoLabelJob.create(project.id, uuid4(), [])
        if status == "RUNNING":
            job.mark_running()
        await SqliteAutoLabelJobRepository(session).add(job)
    else:
        job = AnnotationAuditJob.create(project.id, uuid4(), [], 0.5, 0.5)
        if status == "RUNNING":
            job.mark_running()
        await SqliteAnnotationAuditJobRepository(session).add(job)
    await session.commit()
    return project


def _use_case(session, storage) -> DeleteProjectUseCase:
    return DeleteProjectUseCase(
        SqliteProjectRepository(session),
        storage,
        SqlAlchemyUnitOfWork(session),
        training_jobs=SqliteTrainingJobRepository(session),
        auto_label_jobs=SqliteAutoLabelJobRepository(session),
        audit_jobs=SqliteAnnotationAuditJobRepository(session),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("training", "QUEUED"),
        ("training", "RUNNING"),
        ("auto_label", "PENDING"),
        ("auto_label", "RUNNING"),
        ("audit", "PENDING"),
        ("audit", "RUNNING"),
    ],
)
async def test_delete_project_rejects_queued_or_running_jobs(
    tmp_path, kind: str, status: str
) -> None:
    engine, factory = await _engine(tmp_path)
    storage = LocalFileStorage(tmp_path / "files")
    try:
        async with factory() as session:
            project = await _seed_active(session, kind, status)
            relative = await storage.save(
                f"projects/{project.id}/images", "keep.txt", b"keep"
            )
            with pytest.raises(DomainValidationException, match="queued or running"):
                await _use_case(session, storage).execute(project.id)

            assert await SqliteProjectRepository(session).get_by_id(project.id) is not None
            assert await storage.read(relative) == b"keep"
            table = {
                "training": TrainingJobRow,
                "auto_label": AutoLabelJobRow,
                "audit": AnnotationAuditJobRow,
            }[kind]
            stored_status = await session.scalar(
                select(table.status).where(table.project_id == str(project.id))
            )
            assert stored_status == status
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_delete_project_removes_terminal_jobs_models_and_files(tmp_path) -> None:
    engine, factory = await _engine(tmp_path)
    storage = LocalFileStorage(tmp_path / "files")
    try:
        async with factory() as session:
            project = Project.create("Done")
            await SqliteProjectRepository(session).add(project)
            training = TrainingJob.create(
                project.id, uuid4(), epochs=1, batch_size=1, imgsz=32
            )
            training.mark_failed("finished earlier")
            await SqliteTrainingJobRepository(session).add(training)
            model = ModelVersion.create(
                project_id=project.id,
                dataset_version_id=None,
                training_job_id=training.id,
                version_number=1,
                weights_path=f"projects/{project.id}/models/v1/best.pt",
                map50=0.1,
            )
            await SqliteModelVersionRepository(session).add(model)
            auto = AutoLabelJob.create(project.id, model.id, [])
            auto.mark_failed("done")
            await SqliteAutoLabelJobRepository(session).add(auto)
            audit = AnnotationAuditJob.create(project.id, model.id, [], 0.5, 0.5)
            audit.mark_failed("done")
            await SqliteAnnotationAuditJobRepository(session).add(audit)
            session.add(
                VersionSequenceRow(
                    project_id=str(project.id), kind="models", last_number=1
                )
            )
            await session.commit()
            weights = await storage.save(
                f"projects/{project.id}/models/v1", "best.pt", b"weights"
            )

            await _use_case(session, storage).execute(project.id)

            project_id = str(project.id)
            assert await SqliteProjectRepository(session).get_by_id(project.id) is None
            for table in (
                TrainingJobRow,
                AutoLabelJobRow,
                AnnotationAuditJobRow,
                ModelVersionRow,
            ):
                leftover = await session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(table.project_id == project_id)
                )
                assert leftover == 0
            remaining = await session.scalar(
                select(func.count())
                .select_from(VersionSequenceRow)
                .where(VersionSequenceRow.project_id == project_id)
            )
            assert remaining == 0
            with pytest.raises(FileNotFoundError):
                await storage.read(weights)
    finally:
        await dispose_engine(engine)
