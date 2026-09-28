"""Job runners depend on scope ports, not SQLAlchemy adapters."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from app.application.ports.job_runner_scopes import (
    AuditRunnerScope,
    AutoLabelRunnerScope,
    TrainingRunnerScope,
)
from app.application.use_cases.ml.audit_annotations import AuditAnnotationsRunner
from app.application.use_cases.ml.batch_auto_label import AutoLabelJobRunner
from app.application.use_cases.ml.train_model import TrainingJobRunner
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_audit_job import AnnotationAuditJob
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.auto_label_job import AutoLabelJob
from app.domain.entities.image import Image
from app.domain.entities.model_version import ModelVersion
from app.domain.entities.project import Project
from app.domain.entities.training_job import TrainingJob
from app.domain.enums import (
    AnnotationAuditJobStatus,
    AutoLabelJobStatus,
    ImageStatus,
    SplitType,
    TrainingJobStatus,
)
from app.domain.value_objects.bounding_box import BoundingBox


def test_job_runners_do_not_import_infrastructure() -> None:
    root = Path(__file__).resolve().parents[3] / "app" / "application" / "use_cases" / "ml"
    for name in ("audit_annotations.py", "train_model.py", "batch_auto_label.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "app.infrastructure" not in text, name


class _Uow:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class _TrainingJobs:
    def __init__(self, jobs: dict) -> None:
        self._jobs = jobs

    async def list_by_statuses(self, statuses):
        return [job for job in self._jobs.values() if job.status in statuses]

    async def update(self, job) -> None:
        self._jobs[job.id] = job

    async def get_by_id(self, job_id):
        return self._jobs.get(job_id)


class _AutoLabelJobs(_TrainingJobs):
    pass


class _AuditJobs:
    def __init__(self, jobs: dict) -> None:
        self._jobs = jobs

    async def add(self, job: AnnotationAuditJob) -> None:
        self._jobs[job.id] = job

    async def update(self, job: AnnotationAuditJob) -> None:
        self._jobs[job.id] = job

    async def get_by_id(self, job_id):
        return self._jobs.get(job_id)

    async def find_active(self, project_id, model_version_id):
        return None

    async def list_by_statuses(self, statuses):
        return [job for job in self._jobs.values() if job.status in statuses]


class _Projects:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get_by_id(self, project_id):
        return self.project if self.project.id == project_id else None


class _Images:
    def __init__(self, images: list[Image]) -> None:
        self.by_id = {item.id: item for item in images}

    async def list_by_project(self, project_id):
        return [item for item in self.by_id.values() if item.project_id == project_id]

    async def update(self, image: Image) -> None:
        self.by_id[image.id] = image


class _Annotations:
    def __init__(self, store: dict) -> None:
        self.store = store

    async def list_by_image_ids(self, image_ids):
        result = []
        for image_id in image_ids:
            result.extend(self.store.get(image_id, []))
        return result

    async def replace_for_image(self, image_id, annotations) -> None:
        self.store[image_id] = list(annotations)


class _Classes:
    def __init__(self, items) -> None:
        self.items = items

    async def list_by_project(self, project_id):
        return list(self.items)


class _Models:
    def __init__(self, model: ModelVersion) -> None:
        self.model = model

    async def get_by_id(self, version_id):
        return self.model if self.model.id == version_id else None


class _Storage:
    def get_absolute_path(self, relative_path: str) -> str:
        return f"/abs/{relative_path}"


class _Predictor:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def predict(self, weights_path, image_paths, confidence_threshold, iou_threshold=0.7):
        self.calls.append((confidence_threshold, iou_threshold))
        return {
            path: []
            for path in image_paths
        }


def _scope_factory(scope):
    @asynccontextmanager
    async def open_scope():
        yield scope

    return open_scope


@pytest.mark.asyncio
async def test_training_runner_fails_orphans_through_scope() -> None:
    job = TrainingJob.create(uuid4(), uuid4(), epochs=1, batch_size=1, imgsz=32)
    jobs = {job.id: job}
    scope = TrainingRunnerScope(
        jobs=_TrainingJobs(jobs),
        datasets=None,
        models=None,
        projects=None,
        uow=_Uow(),
    )
    runner = TrainingJobRunner(_scope_factory(scope), _Storage(), object())
    assert await runner.fail_orphaned_jobs() == 1
    assert job.status == TrainingJobStatus.FAILED
    assert job.error_message == "interrupted by server restart"


@pytest.mark.asyncio
async def test_auto_label_runner_fails_orphans_through_scope() -> None:
    job = AutoLabelJob.create(uuid4(), uuid4(), [uuid4()])
    jobs = {job.id: job}
    scope = AutoLabelRunnerScope(
        models=None,
        images=None,
        annotations=None,
        classes=None,
        jobs=_AutoLabelJobs(jobs),
        projects=None,
        labels=None,
        uow=_Uow(),
    )
    runner = AutoLabelJobRunner(_scope_factory(scope), _Storage(), _Predictor())
    assert await runner.fail_orphaned_jobs() == 1
    assert job.status == AutoLabelJobStatus.FAILED
    assert job.error_message == "interrupted by server restart"


@pytest.mark.asyncio
async def test_audit_runner_passes_threshold_through_scope() -> None:
    project = Project.create("Detect")
    image = Image.create(
        project_id=project.id,
        file_path="projects/p/images/a.jpg",
        file_name="a.jpg",
        width=64,
        height=64,
        split=SplitType.TRAIN,
    )
    image.status = ImageStatus.VERIFIED
    class_id = uuid4()
    annotation = Annotation.create_manual(
        image.id, class_id, BoundingBox(0.5, 0.5, 0.2, 0.2)
    )
    model = ModelVersion.create(
        project_id=project.id,
        dataset_version_id=uuid4(),
        training_job_id=uuid4(),
        version_number=1,
        weights_path="projects/p/models/v1/best.pt",
        map50=0.5,
    )
    stored_jobs: dict = {}
    scope = AuditRunnerScope(
        jobs=_AuditJobs(stored_jobs),
        projects=_Projects(project),
        images=_Images([image]),
        annotations=_Annotations({image.id: [annotation]}),
        classes=_Classes(
            [
                AnnotationClass(
                    id=class_id,
                    project_id=project.id,
                    name="crack",
                    color_hex="#FF0000",
                    index_id=0,
                )
            ]
        ),
        models=_Models(model),
        uow=_Uow(),
    )
    predictor = _Predictor()
    runner = AuditAnnotationsRunner(_scope_factory(scope), _Storage(), predictor)
    job = await runner.start(
        project.id,
        model.id,
        image_ids=[image.id],
        confidence_threshold=0.01,
        iou_threshold=0.01,
    )
    if runner._running:
        await asyncio.wait(set(runner._running))
    assert predictor.calls == [(0.01, 0.01)]
    assert stored_jobs[job.id].status == AnnotationAuditJobStatus.COMPLETED
