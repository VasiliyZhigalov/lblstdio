"""Concurrent version publication must not share or wipe a vN directory."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path

import pytest

from app.application.ports.services.augmentation import AugmentedSample, LabeledBox
from app.application.ports.services.model_trainer import TrainingConfig, TrainingResult
from app.application.use_cases.dataset.create_dataset_version import (
    CreateDatasetVersionUseCase,
)
from app.application.use_cases.ml.manage_model_version import UploadModelVersionUseCase
from app.application.use_cases.ml.train_model import TrainingJobRunner
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.dataset_version import AugmentationConfig, DatasetVersion
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.entities.training_job import TrainingJob
from app.domain.enums import ImageStatus, SplitType
from app.domain.value_objects.bounding_box import BoundingBox
from app.infrastructure.db.repositories.annotation_repository import (
    SqliteAnnotationRepository,
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
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.storage.local_storage import LocalFileStorage


class _Gate:
    """Release the first `parties` waiters together. Later callers pass through."""

    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._arrived = 0
        self._event = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived >= self._parties:
            self._event.set()
        await self._event.wait()


def _race_allocator(monkeypatch: pytest.MonkeyPatch, repository_cls: type) -> None:
    """Both callers observe MAX+1 before either one inserts a version row."""
    original = repository_cls.next_version_number
    gate = _Gate(2)
    seen = {"n": 0}

    async def racing(self, project_id):
        number = await original(self, project_id)
        seen["n"] += 1
        if seen["n"] <= 2:
            await gate.wait()
        return number

    monkeypatch.setattr(repository_cls, "next_version_number", racing)


class _IdentityAugmentation:
    def generate_samples(
        self,
        image_bytes: bytes,
        boxes: list[LabeledBox],
        config: AugmentationConfig,
        *,
        apply_augmentation: bool,
    ) -> list[AugmentedSample]:
        return [AugmentedSample(image_bytes=image_bytes, boxes=list(boxes), suffix="")]


class _ScriptedTrainer:
    def train(
        self,
        config: TrainingConfig,
        on_epoch_end=None,
    ) -> TrainingResult:
        out = Path(config.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        payload = out.name.encode()
        weights = out / "best.pt"
        weights.write_bytes(payload)
        return TrainingResult(
            best_weights_path=str(weights),
            map50=0.5,
            epochs_trained=1,
        )


def _version_dir(relative_path: str) -> str:
    path = Path(relative_path)
    if path.name in {"data.yaml", "best.pt"}:
        return path.parent.as_posix()
    return path.as_posix()


async def _factory(tmp_path: Path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}"
    engine, factory = await create_session_factory(url)
    return engine, factory


@pytest.mark.asyncio
async def test_concurrent_dataset_creates_keep_distinct_readable_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory = await _factory(tmp_path)
    storage = LocalFileStorage(tmp_path / "files")
    try:
        async with factory() as session:
            projects = SqliteProjectRepository(session)
            images = SqliteImageRepository(session)
            classes = SqliteClassRepository(session)
            annotations = SqliteAnnotationRepository(session)
            project = Project.create("Race")
            annotation_class = AnnotationClass.create(project.id, "crack", "#FF0000", 0)
            image = Image.create(
                project_id=project.id,
                file_path=f"projects/{project.id}/images/frame.png",
                file_name="frame.png",
                width=32,
                height=32,
                split=SplitType.TRAIN,
            )
            image.status = ImageStatus.VERIFIED
            await storage.save(
                f"projects/{project.id}/images", "frame.png", b"frame-bytes"
            )
            box = Annotation.create_manual(
                image.id, annotation_class.id, BoundingBox(0.5, 0.5, 0.2, 0.2)
            )
            await projects.add(project)
            await classes.add(annotation_class)
            await images.add_many([image])
            await annotations.replace_for_image(image.id, [box])
            await session.commit()
            project_id = project.id

        _race_allocator(monkeypatch, SqliteDatasetVersionRepository)

        async def create_one() -> DatasetVersion:
            async with factory() as session:
                use_case = CreateDatasetVersionUseCase(
                    SqliteProjectRepository(session),
                    SqliteImageRepository(session),
                    SqliteAnnotationRepository(session),
                    SqliteClassRepository(session),
                    SqliteDatasetVersionRepository(session),
                    storage,
                    _IdentityAugmentation(),
                    SqlAlchemyUnitOfWork(session),
                    min_verified_images=1,
                )
                return await use_case.execute(project_id, AugmentationConfig(multiplier=1))

        first, second = await asyncio.wait_for(
            asyncio.gather(create_one(), create_one()),
            timeout=15,
        )
        directories = {_version_dir(first.yaml_path), _version_dir(second.yaml_path)}
        assert len(directories) == 2
        assert await storage.read(first.yaml_path)
        assert await storage.read(second.yaml_path)
        for version in (first, second):
            root = _version_dir(version.yaml_path)
            files = await storage.list_files(root)
            assert any(name.endswith(".jpg") for name in files)
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_concurrent_model_uploads_keep_distinct_readable_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory = await _factory(tmp_path)
    storage = LocalFileStorage(tmp_path / "files")
    try:
        async with factory() as session:
            projects = SqliteProjectRepository(session)
            project = Project.create("Upload")
            await projects.add(project)
            await session.commit()
            project_id = project.id

        _race_allocator(monkeypatch, SqliteModelVersionRepository)

        async def upload(payload: bytes):
            async with factory() as session:
                use_case = UploadModelVersionUseCase(
                    SqliteProjectRepository(session),
                    SqliteModelVersionRepository(session),
                    storage,
                    SqlAlchemyUnitOfWork(session),
                )
                return await use_case.execute(
                    project_id, filename="weights.pt", data=payload
                )

        first, second = await asyncio.wait_for(
            asyncio.gather(upload(b"weights-a"), upload(b"weights-b")),
            timeout=15,
        )
        assert _version_dir(first.weights_path) != _version_dir(second.weights_path)
        assert await storage.read(first.weights_path) == b"weights-a"
        assert await storage.read(second.weights_path) == b"weights-b"
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_concurrent_training_completion_keeps_distinct_readable_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory = await _factory(tmp_path)
    storage = LocalFileStorage(tmp_path / "files")
    published_writes: dict[str, set[bytes]] = defaultdict(set)
    try:
        async with factory() as session:
            projects = SqliteProjectRepository(session)
            versions = SqliteDatasetVersionRepository(session)
            jobs = SqliteTrainingJobRepository(session)
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
            await storage.save(
                f"projects/{project.id}/datasets/v1", "data.yaml", b"path: .\n"
            )
            left = TrainingJob.create(
                project_id=project.id,
                dataset_version_id=version.id,
                epochs=1,
                batch_size=1,
                imgsz=32,
                device="cpu",
            )
            right = TrainingJob.create(
                project_id=project.id,
                dataset_version_id=version.id,
                epochs=1,
                batch_size=1,
                imgsz=32,
                device="cpu",
            )
            await projects.add(project)
            await versions.add(version)
            await jobs.add(left)
            await jobs.add(right)
            await session.commit()
            project_id = project.id
            job_ids = (left.id, right.id)

        import app.application.use_cases.ml.train_model as train_module

        real_copy2 = train_module.shutil.copy2

        def _tracking_copy2(src, dst, *args, **kwargs):
            real_copy2(src, dst, *args, **kwargs)
            parent = Path(dst).as_posix()
            if "/models/v" in parent:
                published_writes[str(Path(dst).parent)].add(Path(dst).read_bytes())

        monkeypatch.setattr(train_module.shutil, "copy2", _tracking_copy2)
        _race_allocator(monkeypatch, SqliteModelVersionRepository)

        runner = TrainingJobRunner(
            factory,
            storage,
            _ScriptedTrainer(),
            max_concurrent=2,
        )
        await asyncio.wait_for(
            asyncio.gather(*(runner.run_inline(job_id) for job_id in job_ids)),
            timeout=20,
        )

        async with factory() as session:
            models = SqliteModelVersionRepository(session)
            stored = await models.list_by_project(project_id)
        assert len(stored) == 2
        directories = {_version_dir(item.weights_path) for item in stored}
        assert len(directories) == 2
        assert all(len(payloads) == 1 for payloads in published_writes.values())
        for item in stored:
            assert item.training_job_id is not None
            assert await storage.read(item.weights_path) == (
                f"_train_{item.training_job_id}".encode()
            )
    finally:
        await dispose_engine(engine)
