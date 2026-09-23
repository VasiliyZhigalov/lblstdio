"""A failed success-commit must leave the job FAILED, not RUNNING."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image as PILImage

from app.application.ports.services.model_trainer import TrainingConfig, TrainingResult
from app.application.use_cases.ml.batch_auto_label import AutoLabelJobRunner
from app.application.use_cases.ml.train_model import TrainingJobRunner
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.auto_label_job import AutoLabelJob
from app.domain.entities.dataset_version import DatasetVersion
from app.domain.entities.image import Image
from app.domain.entities.model_version import ModelVersion
from app.domain.entities.project import Project
from app.domain.entities.training_job import TrainingJob
from app.domain.enums import AutoLabelJobStatus, SplitType, TrainingJobStatus
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
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.model_version_repository import (
    SqliteModelVersionRepository,
)
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.repositories.training_job_repository import (
    SqliteTrainingJobRepository,
)
from app.infrastructure.db.session import create_session_factory, dispose_engine
from app.infrastructure.db.tables import AutoLabelJobRow, TrainingJobRow
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.storage.local_storage import LocalFileStorage


class _ScriptedTrainer:
    def train(self, config: TrainingConfig, on_epoch_end=None) -> TrainingResult:
        out = Path(config.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        weights = out / "best.pt"
        weights.write_bytes(b"weights")
        return TrainingResult(best_weights_path=str(weights), map50=0.4, epochs_trained=1)


class _EmptyPredictor:
    def predict(self, weights_path, image_paths, confidence_threshold, iou_threshold=0.7):
        return {path: [] for path in image_paths}


def _poison_completed_commit(monkeypatch, row_type, status_value: str) -> None:
    """Fail the commit that would persist COMPLETED and invalidate that session."""
    original_commit = SqlAlchemyUnitOfWork.commit
    original_rollback = SqlAlchemyUnitOfWork.rollback

    async def commit(self):
        if self._session.info.get("dead"):
            raise RuntimeError("pending rollback")
        row = await self._session.get(row_type, self._session.info.get("watched_job_id"))
        if row is not None and row.status == status_value:
            self._session.info["dead"] = True
            raise RuntimeError("commit failed")
        await original_commit(self)

    async def rollback(self):
        self._session.info.pop("dead", None)
        await original_rollback(self)

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", commit)
    monkeypatch.setattr(SqlAlchemyUnitOfWork, "rollback", rollback)


async def _factory(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}"
    return await create_session_factory(url)


@pytest.mark.asyncio
async def test_training_commit_failure_marks_job_failed(tmp_path, monkeypatch) -> None:
    engine, factory = await _factory(tmp_path)
    storage = LocalFileStorage(tmp_path / "files")
    try:
        async with factory() as session:
            project = Project.create("Train")
            version = DatasetVersion.create(project.id, 1, "v1")
            version.mark_ready(
                train_count=1,
                valid_count=1,
                test_count=1,
                train_file_count=1,
                valid_file_count=1,
                test_file_count=1,
                yaml_path=f"projects/{project.id}/datasets/v1/data.yaml",
                items=[],
            )
            job = TrainingJob.create(
                project.id, version.id, epochs=1, batch_size=1, imgsz=32, device="cpu"
            )
            await SqliteProjectRepository(session).add(project)
            await SqliteDatasetVersionRepository(session).add(version)
            await SqliteTrainingJobRepository(session).add(job)
            await session.commit()
            await storage.save(
                f"projects/{project.id}/datasets/v1", "data.yaml", b"path: .\n"
            )
            session.info["watched_job_id"] = str(job.id)
            job_id = job.id
            project_id = project.id

        _poison_completed_commit(monkeypatch, TrainingJobRow, TrainingJobStatus.COMPLETED.value)
        # The runner opens new sessions; stamp the watched id via the factory wrapper.
        original_factory = factory

        def watching_factory():
            session_cm = original_factory()

            class _Wrap:
                async def __aenter__(self):
                    session = await session_cm.__aenter__()
                    session.info["watched_job_id"] = str(job_id)
                    return session

                async def __aexit__(self, exc_type, exc, tb):
                    return await session_cm.__aexit__(exc_type, exc, tb)

            return _Wrap()

        runner = TrainingJobRunner(watching_factory, storage, _ScriptedTrainer())
        await runner.run_inline(job_id)

        async with factory() as session:
            stored = await SqliteTrainingJobRepository(session).get_by_id(job_id)
            models = await SqliteModelVersionRepository(session).list_by_project(project_id)
        assert stored is not None
        assert stored.status == TrainingJobStatus.FAILED
        assert stored.error_message is not None
        assert "commit failed" in stored.error_message
        assert models == []
        assert list((tmp_path / "files").rglob("best.pt")) == []
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_auto_label_commit_failure_marks_job_failed(tmp_path, monkeypatch) -> None:
    engine, factory = await _factory(tmp_path)
    storage = LocalFileStorage(tmp_path / "files")
    try:
        async with factory() as session:
            project = Project.create("Label")
            await SqliteProjectRepository(session).add(project)
            annotation_class = AnnotationClass.create(project.id, "crack", "#FF0000", 0)
            await SqliteClassRepository(session).add(annotation_class)
            image = Image.create(
                project_id=project.id,
                file_path=f"projects/{project.id}/images/a.jpg",
                file_name="a.jpg",
                width=32,
                height=32,
                split=SplitType.TRAIN,
            )
            await SqliteImageRepository(session).add_many([image])
            model = ModelVersion.create(
                project_id=project.id,
                dataset_version_id=None,
                training_job_id=None,
                version_number=1,
                weights_path=f"projects/{project.id}/models/v1/best.pt",
                map50=0.2,
            )
            await SqliteModelVersionRepository(session).add(model)
            job = AutoLabelJob.create(project.id, model.id, [image.id])
            await SqliteAutoLabelJobRepository(session).add(job)
            await session.commit()
            buffer = BytesIO()
            PILImage.new("RGB", (32, 32), "white").save(buffer, format="JPEG")
            await storage.save(f"projects/{project.id}/images", "a.jpg", buffer.getvalue())
            await storage.save(
                f"projects/{project.id}/models/v1", "best.pt", b"weights"
            )
            job_id = job.id

        def watching_factory():
            session_cm = factory()

            class _Wrap:
                async def __aenter__(self):
                    session = await session_cm.__aenter__()
                    session.info["watched_job_id"] = str(job_id)
                    return session

                async def __aexit__(self, exc_type, exc, tb):
                    return await session_cm.__aexit__(exc_type, exc, tb)

            return _Wrap()

        _poison_completed_commit(
            monkeypatch, AutoLabelJobRow, AutoLabelJobStatus.COMPLETED.value
        )
        runner = AutoLabelJobRunner(
            watching_factory,
            storage,
            _EmptyPredictor(),
        )
        await runner.run_inline(job_id)

        async with factory() as session:
            stored = await SqliteAutoLabelJobRepository(session).get_by_id(job_id)
        assert stored is not None
        assert stored.status == AutoLabelJobStatus.FAILED
        assert stored.error_message is not None
        assert "commit failed" in stored.error_message
    finally:
        await dispose_engine(engine)
