# Classification Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add single-label image classification projects beside existing detection, covering label → dataset → train `yolov8*-cls` → auto-label → verify.

**Architecture:** Same `Project` aggregate with immutable `task_type`. Classification stores one `ImageLabel` per image (never `Annotation` boxes). Dataset export is Ultralytics classify folders (`train|val|test/<class>/`). Training and auto-label reuse job runners but branch on task type.

**Tech Stack:** FastAPI, SQLAlchemy async + SQLite (`create_all` + `_ensure_table_columns`), Ultralytics classify, vanilla JS frontend.

**Spec:** `docs/superpowers/specs/2026-09-21-classification-projects-design.md`

## Global Constraints

- One class per image, or none. No multilabel.
- `task_type` set only on create; existing DB rows default to `DETECTION`.
- Classification never writes `annotations`; detection never writes `image_labels`.
- No stream, keypoints, box canvas, IoU audit, `is_background`, or Albumentations for classification.
- Classification on-disk valid split folder is `val/` (DB enum stays `valid`).
- `yaml_path` for classification is the dataset **root directory**, not a `data.yaml` file.
- Cross-task operations raise `TaskTypeMismatchException` → HTTP **409**.
- Follow Clean Architecture: domain has no Ultralytics/FastAPI imports.
- Commits: only when the user asks. Skip commit steps unless explicitly requested.
- Run tests from `backend/`: `python -m pytest <path> -v`

---

## File Structure

| Path | Responsibility |
| :--- | :--- |
| `backend/app/domain/enums.py` | `ProjectTaskType` |
| `backend/app/domain/entities/project.py` | Immutable `task_type` |
| `backend/app/domain/entities/image_label.py` | Single image-level label |
| `backend/app/domain/entities/image.py` | `recalculate_status_from_label` |
| `backend/app/domain/entities/dataset_version.py` | `SnapshotClassLabel` + union snapshots |
| `backend/app/domain/services/split.py` | `assign_splits_stratified` |
| `backend/app/domain/services/class_dir_name.py` | Safe folder name for a class |
| `backend/app/domain/exceptions.py` | `TaskTypeMismatchException` |
| `backend/app/application/services/task_policy.py` | `require_task(project, expected)` |
| `backend/app/application/ports/repositories/image_label_repository.py` | Label repo port |
| `backend/app/application/ports/services/model_predictor.py` | `Classification` DTO + `IClassificationPredictor` |
| `backend/app/application/ports/services/model_trainer.py` | `task` on `TrainingConfig`; `top1` on result |
| `backend/app/application/use_cases/projects/create_project.py` | Pass `task_type` |
| `backend/app/application/use_cases/labels/save_image_label.py` | Assign / clear / verify / reject |
| `backend/app/application/use_cases/dataset/create_dataset_version.py` | Classification folder layout |
| `backend/app/application/use_cases/dataset/export_yolo.py` | Classification zip |
| `backend/app/application/use_cases/ml/train_model.py` | Cls weights + dir check |
| `backend/app/application/use_cases/ml/batch_auto_label.py` | Classification branch |
| `backend/app/infrastructure/db/tables.py` | `task_type`, `ImageLabelRow`, `top1` |
| `backend/app/infrastructure/db/session.py` | Ensure `projects.task_type`, `model_versions.top1` |
| `backend/app/infrastructure/db/mappers.py` | Project/label/snapshot/model mapping |
| `backend/app/infrastructure/db/repositories/image_label_repository.py` | SQLite repo |
| `backend/app/infrastructure/ml/ultralytics_trainer.py` | Classify `model.train(data=dir)` |
| `backend/app/infrastructure/ml/` (existing predictor module) | Top-1 classify predict |
| `backend/app/presentation/schemas.py` | `task_type`, `ImageLabelRead`, `top1` |
| `backend/app/presentation/exception_handlers.py` | 409 handler |
| `backend/app/presentation/api/v1/images_router.py` / `projects_router.py` / label routes | CRUD + attach label on reads |
| `frontend/index.html` | Task type radios; cls annotate chrome |
| `frontend/js/api.js` | `task_type`, label endpoints |
| `frontend/js/components/projectsHub.js` | Type on create + badge |
| `frontend/js/app.js` + `dataHub.js` + `trainingDrawer.js` + `autoLabelModal.js` | Branch UI on `task_type` |

---

### Task 1: Domain — `task_type`, `ImageLabel`, status, stratified split

**Files:**
- Modify: `backend/app/domain/enums.py`
- Modify: `backend/app/domain/entities/project.py`
- Create: `backend/app/domain/entities/image_label.py`
- Modify: `backend/app/domain/entities/image.py`
- Modify: `backend/app/domain/entities/dataset_version.py`
- Modify: `backend/app/domain/services/split.py`
- Create: `backend/app/domain/services/class_dir_name.py`
- Modify: `backend/app/domain/exceptions.py`
- Test: `backend/tests/unit/domain/test_project_task_type.py`
- Test: `backend/tests/unit/domain/test_image_label.py`
- Test: `backend/tests/unit/domain/test_split_stratified.py`
- Test: `backend/tests/unit/application/test_projects.py` (existing `Project.create` still works)

**Interfaces:**
- Consumes: existing `Image`, `SourceType`, `VerificationStatus`, `assign_splits`
- Produces:
  - `class ProjectTaskType(str, Enum): DETECTION = "DETECTION"; CLASSIFICATION = "CLASSIFICATION"`
  - `Project.create(name, description=None, project_id=None, task_type=ProjectTaskType.DETECTION) -> Project`
  - `Project.task_type: ProjectTaskType` — no setter on `rename`
  - `ImageLabel.create_manual(image_id, class_id) -> ImageLabel`
  - `ImageLabel.create_prediction(image_id, class_id, confidence, model_version_id=None) -> ImageLabel`
  - `ImageLabel.confirm() -> None` — `AUTO_VERIFIED` if source is `MODEL_PREDICTION`, else `VERIFIED`
  - `ImageLabel.assign_manual(class_id) -> None` — source `MANUAL`, status `VERIFIED`, confidence `1.0`
  - `Image.recalculate_status_from_label(label: ImageLabel | None) -> None`
  - `Image.mark_as_background` raises `DomainValidationException` if called from classification use cases later; domain method itself stays but classification must not call it
  - `SnapshotClassLabel(class_id: UUID, class_index: int)` with `to_dict` / `from_dict` (no bbox keys)
  - `snapshot_entry_from_dict(raw: dict) -> SnapshotAnnotation | SnapshotClassLabel`
  - `DatasetItem.snapshot_annotations: list[SnapshotAnnotation | SnapshotClassLabel]`
  - `assign_splits_stratified(class_ids: Sequence[UUID], ratios: SplitRatios | None = None, *, rng: Random | None = None) -> list[SplitType]`
  - `class_dir_name(name: str) -> str`
  - `class TaskTypeMismatchException(DomainError)`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/domain/test_project_task_type.py
from app.domain.entities.project import Project
from app.domain.enums import ProjectTaskType


def test_create_defaults_to_detection() -> None:
    project = Project.create("Det")
    assert project.task_type == ProjectTaskType.DETECTION


def test_create_classification() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    assert project.task_type == ProjectTaskType.CLASSIFICATION


def test_rename_does_not_change_task_type() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    project.rename("Other", "desc")
    assert project.task_type == ProjectTaskType.CLASSIFICATION
```

```python
# backend/tests/unit/domain/test_image_label.py
from uuid import uuid4

import pytest

from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.enums import (
    ImageSourceType,
    ImageStatus,
    SourceType,
    SplitType,
    VerificationStatus,
)
from app.domain.exceptions import DomainValidationException


def _image() -> Image:
    return Image.create(
        project_id=uuid4(),
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
        source_type=ImageSourceType.MANUAL_UPLOAD,
    )


def test_manual_label_verifies_image() -> None:
    image = _image()
    label = ImageLabel.create_manual(image.id, uuid4())
    image.recalculate_status_from_label(label)
    assert label.source == SourceType.MANUAL
    assert label.verification_status == VerificationStatus.VERIFIED
    assert label.confidence == 1.0
    assert image.status == ImageStatus.VERIFIED


def test_prediction_requires_review() -> None:
    image = _image()
    label = ImageLabel.create_prediction(image.id, uuid4(), 0.91)
    image.recalculate_status_from_label(label)
    assert image.status == ImageStatus.REQUIRES_REVIEW
    assert image.can_be_included_in_dataset() is False


def test_confirm_prediction_auto_verifies() -> None:
    image = _image()
    label = ImageLabel.create_prediction(image.id, uuid4(), 0.91)
    label.confirm()
    image.recalculate_status_from_label(label)
    assert label.verification_status == VerificationStatus.AUTO_VERIFIED
    assert image.status == ImageStatus.AUTO_VERIFIED


def test_assign_manual_after_prediction() -> None:
    label = ImageLabel.create_prediction(uuid4(), uuid4(), 0.4)
    new_class = uuid4()
    label.assign_manual(new_class)
    assert label.class_id == new_class
    assert label.source == SourceType.MANUAL
    assert label.verification_status == VerificationStatus.VERIFIED
    assert label.confidence == 1.0


def test_clear_label_unannotates() -> None:
    image = _image()
    image.recalculate_status_from_label(ImageLabel.create_manual(image.id, uuid4()))
    image.recalculate_status_from_label(None)
    assert image.status == ImageStatus.UNANNOTATED


def test_prediction_confidence_range() -> None:
    with pytest.raises(DomainValidationException, match="confidence"):
        ImageLabel.create_prediction(uuid4(), uuid4(), 1.2)
```

```python
# backend/tests/unit/domain/test_split_stratified.py
from random import Random
from uuid import uuid4

from app.domain.services.class_dir_name import class_dir_name
from app.domain.services.split import assign_splits_stratified
from app.domain.value_objects.split_ratios import SplitRatios


def test_stratified_keeps_each_class_in_train_when_tiny() -> None:
    a, b = uuid4(), uuid4()
    class_ids = [a, a, b]
    splits = assign_splits_stratified(class_ids, SplitRatios(), rng=Random(0))
    assert len(splits) == 3


def test_class_dir_name_strips_separators() -> None:
    assert class_dir_name("good") == "good"
    assert "/" not in class_dir_name("a/b")
    assert "\\" not in class_dir_name("a\\b")
```

Also add a snapshot round-trip test in `test_image_label.py` or a tiny `test_snapshot_class_label.py`:

```python
from app.domain.entities.dataset_version import (
    SnapshotClassLabel,
    snapshot_entry_from_dict,
)

def test_snapshot_class_label_roundtrip() -> None:
    cid = uuid4()
    raw = SnapshotClassLabel(class_id=cid, class_index=2).to_dict()
    assert "x_center" not in raw
    restored = snapshot_entry_from_dict(raw)
    assert isinstance(restored, SnapshotClassLabel)
    assert restored.class_index == 2
```

- [ ] **Step 2: Run tests, expect FAIL** (import errors)

Run: `python -m pytest tests/unit/domain/test_project_task_type.py tests/unit/domain/test_image_label.py tests/unit/domain/test_split_stratified.py -v`

Expected: FAIL (`ProjectTaskType` / `ImageLabel` not defined)

- [ ] **Step 3: Implement domain**

Add enum after existing enums in `enums.py`:

```python
class ProjectTaskType(str, Enum):
    DETECTION = "DETECTION"
    CLASSIFICATION = "CLASSIFICATION"
```

`Project`: add field `task_type: ProjectTaskType`. In `create`, default `ProjectTaskType.DETECTION`. `rename` must not take or assign `task_type`.

`ImageLabel` — mirror `Annotation` constructors (manual vs prediction), without bbox. `confirm()` sets `verification_status=AUTO_VERIFIED` and `verified_at=now`. `assign_manual` as in tests.

`Image.recalculate_status_from_label`:

```python
def recalculate_status_from_label(self, label: ImageLabel | None) -> None:
    if self.status == ImageStatus.REJECTED:
        return
    if label is None:
        self.status = ImageStatus.UNANNOTATED
        return
    if label.verification_status == VerificationStatus.PENDING_REVIEW:
        self.status = ImageStatus.REQUIRES_REVIEW
        return
    if label.verification_status == VerificationStatus.AUTO_VERIFIED:
        self.status = ImageStatus.AUTO_VERIFIED
        return
    self.status = ImageStatus.VERIFIED
```

`SnapshotClassLabel` next to `SnapshotAnnotation`. `snapshot_entry_from_dict`: if `"x_center" in raw` → `SnapshotAnnotation.from_dict`, else `SnapshotClassLabel.from_dict`. Change `DatasetItem.snapshot_annotations` type to `list[SnapshotAnnotation | SnapshotClassLabel]`. `snapshot_as_dicts` calls `item.to_dict()`.

`assign_splits_stratified`: group indices by class_id; shuffle each group with `rng`; `assign_splits(len(group), ratios)` within group; write into a result list of length `len(class_ids)`.

`class_dir_name`: `strip`, replace `/`, `\\`, and `..` with `_`; if empty return `"class"`.

`TaskTypeMismatchException(DomainError)` in `exceptions.py`.

- [ ] **Step 4: Run domain tests**

Run: `python -m pytest tests/unit/domain/test_project_task_type.py tests/unit/domain/test_image_label.py tests/unit/domain/test_split_stratified.py tests/unit/application/test_projects.py tests/unit/domain/test_image_status.py -v`

Expected: PASS. Existing `Project.create("Alpha")` still detection.

- [ ] **Step 5: Commit** (skip unless user asked)

```bash
git add backend/app/domain backend/tests/unit/domain
git commit -m "feat(domain): add classification project type and image labels"
```

---

### Task 2: Persistence — column, `image_labels` table, mappers, repo

**Files:**
- Modify: `backend/app/infrastructure/db/tables.py`
- Modify: `backend/app/infrastructure/db/session.py`
- Modify: `backend/app/infrastructure/db/mappers.py`
- Create: `backend/app/application/ports/repositories/image_label_repository.py`
- Create: `backend/app/infrastructure/db/repositories/image_label_repository.py`
- Modify: `backend/app/infrastructure/db/repositories/project_repository.py` if mapper is the only touch
- Test: `backend/tests/integration/test_sqlite_repositories.py` (extend) or `backend/tests/integration/test_image_label_repository.py`

**Interfaces:**
- Consumes: `Project`, `ImageLabel`, `snapshot_entry_from_dict`
- Produces:
  - `ProjectRow.task_type: str` default `"DETECTION"`
  - `ImageLabelRow` table `image_labels`, unique `image_id`, FKs cascade
  - `ModelVersionRow.top1: float | None`
  - `IImageLabelRepository.get_by_image_id / list_by_image_ids / upsert / delete_by_image_id`
  - `row_to_project` reads `task_type` with fallback `DETECTION`
  - `row_to_dataset_item` uses `snapshot_entry_from_dict`

- [ ] **Step 1: Write failing integration test**

```python
# backend/tests/integration/test_image_label_repository.py
from uuid import uuid4

import pytest

from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.entities.project import Project
from app.domain.enums import ProjectTaskType, SplitType
from app.infrastructure.db.mappers import project_to_row, row_to_project
from app.infrastructure.db.repositories.image_label_repository import (
    SqliteImageLabelRepository,
)
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.tables import ClassRow


@pytest.mark.asyncio
async def test_project_task_type_roundtrip(tmp_path) -> None:
    engine, factory = await create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with factory() as session:
        repo = SqliteProjectRepository(session)
        project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
        await repo.add(project)
        await session.commit()
        loaded = await repo.get_by_id(project.id)
        assert loaded.task_type == ProjectTaskType.CLASSIFICATION
    await engine.dispose()


def test_row_to_project_defaults_missing_task_type() -> None:
    project = Project.create("Old")
    row = project_to_row(project)
    # simulate legacy row without attribute
    object.__setattr__ = getattr  # do not use; instead:
    # Build ProjectRow without relying on ORM default in mapper:
    restored = row_to_project(row)
    assert restored.task_type == project.task_type
```

If `test_row_to_project_defaults_missing_task_type` is awkward, instead in `row_to_project` use `getattr(row, "task_type", None) or "DETECTION"` and unit-test that with a simple namespace:

```python
def test_row_to_project_defaults_detection_when_column_missing() -> None:
    class _Row:
        id = str(uuid4())
        name = "Legacy"
        description = None
        created_at = None
        updated_at = None
    # set created_at/updated_at to datetime.now(UTC)
```

Better: mapper always reads `getattr(row, "task_type", ProjectTaskType.DETECTION.value)`.

Also test upsert uniqueness: two `upsert` calls for same `image_id` leave one row.

- [ ] **Step 2: Run test, expect FAIL**

Run: `python -m pytest tests/integration/test_image_label_repository.py -v`

Expected: FAIL (no `task_type` / no repo)

- [ ] **Step 3: Implement persistence**

`ProjectRow`:

```python
task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="DETECTION")
```

`_PROJECT_COLUMNS = (("task_type", "VARCHAR(32) NOT NULL DEFAULT 'DETECTION'"),)` in `session.py` and call `_ensure_table_columns(connection, "projects", _PROJECT_COLUMNS)`.

`_MODEL_VERSION_COLUMNS` add `("top1", "FLOAT")`. `ModelVersionRow.top1: Mapped[float | None]`.

`ImageLabelRow`:

```python
class ImageLabelRow(Base):
    __tablename__ = "image_labels"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_id: Mapped[str] = mapped_column(String(36), ForeignKey("images.id", ondelete="CASCADE"), unique=True, index=True)
    class_id: Mapped[str] = mapped_column(String(36), ForeignKey("annotation_classes.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
```

Mappers: include `task_type` in `project_to_row` / `row_to_project`. `label_to_row` / `row_to_label`. `row_to_dataset_item` uses `snapshot_entry_from_dict`. Model mappers include `top1` default None.

Port:

```python
class IImageLabelRepository(ABC):
    async def get_by_image_id(self, image_id: UUID) -> ImageLabel | None: ...
    async def list_by_image_ids(self, image_ids: Sequence[UUID]) -> list[ImageLabel]: ...
    async def upsert(self, label: ImageLabel) -> None: ...
    async def delete_by_image_id(self, image_id: UUID) -> None: ...
```

SQLite repo: `upsert` = merge/replace on `image_id` (delete+add or SQLAlchemy merge). `create_all` will create the new table.

`ModelVersion` entity: add `top1: float | None = None` to dataclass and `create(...)`.

- [ ] **Step 4: Run integration + existing sqlite tests**

Run: `python -m pytest tests/integration/test_image_label_repository.py tests/integration/test_sqlite_repositories.py tests/unit/application/test_projects.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 3: Label use cases + API + 409 guards

**Files:**
- Create: `backend/app/application/services/task_policy.py`
- Create: `backend/app/application/use_cases/labels/save_image_label.py`
- Modify: `backend/app/application/use_cases/projects/create_project.py`
- Modify: `backend/app/application/use_cases/images/get_image.py`
- Modify: `backend/app/application/use_cases/annotations/save_annotations.py` (require DETECTION)
- Modify: `backend/app/application/use_cases/annotations/mark_background.py` (require DETECTION)
- Modify: `backend/app/presentation/schemas.py`
- Modify: `backend/app/presentation/exception_handlers.py`
- Modify: `backend/app/presentation/api/v1/projects_router.py`
- Modify: `backend/app/presentation/api/v1/images_router.py`
- Create or modify: `backend/app/presentation/api/v1/annotations_router.py` (add label routes) **prefer new** `backend/app/presentation/api/v1/labels_router.py` included from `main.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py` if new router
- Test: `backend/tests/unit/application/test_save_image_label.py`
- Test: `backend/tests/unit/application/test_projects.py` (create with task_type)
- Test: `backend/tests/e2e/test_image_labels_api.py` (if e2e pattern exists; otherwise unit + a thin API test)

**Interfaces:**
- Consumes: `IImageLabelRepository`, `IProjectRepository`, `IImageRepository`, `IClassRepository`, `require_task`
- Produces:
  - `require_task(project: Project, expected: ProjectTaskType) -> None`
  - `CreateProjectUseCase.execute(name, description=None, task_type=ProjectTaskType.DETECTION)`
  - `SaveImageLabelUseCase.execute(image_id, class_id) -> ImageLabel` (classification, manual)
  - `ClearImageLabelUseCase.execute(image_id) -> None`
  - `ConfirmImageLabelUseCase.execute(image_id) -> ImageLabel`
  - `GetImageUseCase.execute -> tuple[Image, list[Annotation], ImageLabel | None]`
  - `ProjectCreate.task_type: ProjectTaskType = DETECTION`
  - `ProjectRead.task_type`
  - `ImageLabelRead` schema
  - `ImageRead.label: ImageLabelRead | None = None`
  - `ImageDetailRead` keeps `annotations` + `label`
  - Routes:
    - `PUT /images/{image_id}/label` body `{"class_id": UUID}`
    - `DELETE /images/{image_id}/label`
    - `POST /images/{image_id}/label/confirm`
    - `POST /images/{image_id}/label/reject` (same as delete + status unannotated)
  - 409 handler for `TaskTypeMismatchException`

- [ ] **Step 1: Write failing use-case tests**

```python
# backend/tests/unit/application/test_save_image_label.py
@pytest.mark.asyncio
async def test_save_manual_label_on_classification_project() -> None:
    ...
    label = await SaveImageLabelUseCase(...).execute(image.id, class_id)
    assert label.verification_status == VerificationStatus.VERIFIED
    assert images.images[0].status == ImageStatus.VERIFIED


@pytest.mark.asyncio
async def test_save_label_rejected_on_detection_project() -> None:
    with pytest.raises(TaskTypeMismatchException):
        await SaveImageLabelUseCase(...).execute(image.id, class_id)


@pytest.mark.asyncio
async def test_save_annotations_rejected_on_classification_project() -> None:
    with pytest.raises(TaskTypeMismatchException):
        await SaveAnnotationsUseCase(...).execute(image.id, [])
```

Fakes: projects, images, classes, labels (dict by image_id), uow. `SaveImageLabelUseCase` must load image → project → `require_task(..., CLASSIFICATION)` → class belongs to project → upsert label → `image.recalculate_status_from_label` → `images.update`.

Extend `test_create_list_and_get_project` to `assert created.task_type == ProjectTaskType.DETECTION`.

Add `test_create_classification_project` calling `execute("X", None, ProjectTaskType.CLASSIFICATION)`.

- [ ] **Step 2: Run, expect FAIL**

Run: `python -m pytest tests/unit/application/test_save_image_label.py tests/unit/application/test_projects.py -v`

- [ ] **Step 3: Implement use cases + HTTP**

`task_policy.py`:

```python
def require_task(project: Project, expected: ProjectTaskType) -> None:
    if project.task_type != expected:
        raise TaskTypeMismatchException(
            f"operation requires {expected.value} project, got {project.task_type.value}"
        )
```

`CreateProjectUseCase.execute` adds `task_type: ProjectTaskType = ProjectTaskType.DETECTION` and passes it to `Project.create`.

`GetImageUseCase` gains optional `labels: IImageLabelRepository | None`. Return `(image, boxes, label)`. Update every caller (images_router file endpoint can ignore label). Grep `GetImageUseCase` and `get_get_image_use_case`.

`SaveAnnotationsUseCase`: inject `IProjectRepository`, `require_task(project, DETECTION)` after loading image.

`MarkImageAsBackgroundUseCase`: same DETECTION guard.

Label use cases in one file `save_image_label.py` as three classes if they share deps.

Schemas:

```python
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    task_type: ProjectTaskType = ProjectTaskType.DETECTION

class ImageLabelRead(BaseModel):
    id: UUID
    image_id: UUID
    class_id: UUID
    source: str
    confidence: float
    verification_status: str
    verified_at: datetime | None = None
    model_version_id: UUID | None = None

class ImageRead(...):
    label: ImageLabelRead | None = None
```

`list_images` router: after listing, `labels.list_by_image_ids` and attach. Detection images have `label=None`.

Exception handler:

```python
@app.exception_handler(TaskTypeMismatchException)
async def task_type_handler(_request, exc: TaskTypeMismatchException) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})
```

Wire router + dependencies. `projects_router.create_project` passes `payload.task_type`.

- [ ] **Step 4: Run unit tests and fix GetImage callers**

Run: `python -m pytest tests/unit/application/test_save_image_label.py tests/unit/application/test_projects.py tests/unit/application/test_propagate_box.py -v`

Expected: PASS. Any `GetImageUseCase.execute` return arity mismatch must be fixed in this task.

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 4: Classification dataset build + export

**Files:**
- Modify: `backend/app/application/use_cases/dataset/create_dataset_version.py`
- Modify: `backend/app/application/use_cases/dataset/export_yolo.py`
- Modify: `backend/app/infrastructure/db/mappers.py` if snapshot_as_dicts already done
- Test: `backend/tests/unit/application/test_create_dataset_version.py` (keep detection tests)
- Test: `backend/tests/unit/application/test_create_classification_dataset.py`
- Test: `backend/tests/unit/application/test_export_yolo.py` if present; else add classification cases in a new file

**Interfaces:**
- Consumes: `IImageLabelRepository`, `assign_splits_stratified`, `class_dir_name`, `SnapshotClassLabel`
- Produces: READY version with files under `{root}/train|val|test/{class_dir}/{image_id}{suffix}`; `yaml_path == relative_root` (directory); no label txt files; no augmentation; empty class dirs still created for every project class in all three splits

- [ ] **Step 1: Write failing tests**

Reuse fakes from `test_create_dataset_version.py`. Classification project with 10 verified labeled images, two classes. `min_verified_images=10`. `rng=Random(0)`.

Assert:

- `version.yaml_path.endswith("datasets/v1")` or equals `projects/{id}/datasets/v1`
- saved paths look like `.../train/good/{uuid}.png` and `.../val/...` (folder `val` not `valid`)
- `snapshot_annotations` is one `SnapshotClassLabel` per item
- pending `REQUIRES_REVIEW` still raises `UnverifiedDataException`
- detection test `test_create_dataset_version_*` still writes `data.yaml` and `labels/*.txt`

Do **not** call `IAugmentationService.generate_samples` for classification; fake augmentation should record zero calls.

- [ ] **Step 2: Run, expect FAIL** (classification images ignored / yaml is data.yaml)

Run: `python -m pytest tests/unit/application/test_create_classification_dataset.py tests/unit/application/test_create_dataset_version.py -v`

- [ ] **Step 3: Branch `CreateDatasetVersionUseCase`**

Inject `IImageLabelRepository`. After loading project:

If `DETECTION`: existing path (annotations, aug, `data.yaml`).

If `CLASSIFICATION`:

1. Load labels for all images.
2. Block if any image status is `REQUIRES_REVIEW` or label is `PENDING_REVIEW`.
3. Verified images = `can_be_included_in_dataset()` and exactly one verified/auto-verified label in `class_by_id`.
4. Same min verified count.
5. `splits = assign_splits_stratified([label.class_id for ...], split_ratios, rng=rng)` aligned with verified image order (shuffle **within** the stratified helper, not a second global shuffle).
6. For each split name mapping: `SplitType.VALID` → disk `"val"`, others `split.value`.
7. `mkdir` conceptually via `storage.save` of files; also save a 0-byte placeholder only if storage cannot mkdir — prefer writing files; for empty class folders call `storage.save(f"{root}/{split}/{class_dir}", ".keep", b"")` **only if** the storage API has no mkdir. Check `IFileStorage`. If it only `save`s files, write `.keep` then you may omit `.keep` from export zip. Simpler: if a class+split has no images, skip; Ultralytics still needs `val/` to exist — write `f"{relative_root}/val/.keep"` and `train/.keep`.
8. Copy original bytes with `storage.read` / `storage.save` using `Path(image.file_name).suffix`.
9. `yaml_path = relative_root`.
10. `train_file_count = train_count` (same for valid/test).
11. Items use `SnapshotClassLabel`.

`ExportYOLOUseCase`: if classification, pack `train|val|test/{class_dir}/{id}{suffix}` for exportable labeled verified images (and skip empty-annotation YOLO txt). Detection path unchanged. Filename of zip can stay `project-{id}-yolo.zip` (YAGNI).

- [ ] **Step 4: Run dataset tests**

Run: `python -m pytest tests/unit/application/test_create_classification_dataset.py tests/unit/application/test_create_dataset_version.py tests/e2e/test_dataset_versions_api.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 5: Classification training

**Files:**
- Modify: `backend/app/application/ports/services/model_trainer.py`
- Modify: `backend/app/application/use_cases/ml/train_model.py`
- Modify: `backend/app/infrastructure/ml/ultralytics_trainer.py`
- Modify: `backend/app/domain/entities/model_version.py` (`top1` if not in Task 2)
- Modify: `backend/app/presentation/schemas.py` (`TrainModelRequest` default weights stay det; cls default applied in use case)
- Modify: mappers for `ModelVersion.top1`
- Test: `backend/tests/unit/application/test_train_model.py`

**Interfaces:**
- Consumes: `project.task_type`, dataset `yaml_path` as directory for cls
- Produces:
  - `_ALLOWED_PRETRAINED_CLS = frozenset({"yolov8n-cls.pt", "yolov8s-cls.pt", "yolov8m-cls.pt"})`
  - Default weights: detection `yolov8n.pt`, classification `yolov8n-cls.pt`
  - `TrainingConfig.task: str = "detection"`  # `"classification"` otherwise
  - `TrainingResult.top1: float | None = None`
  - Fine-tune `base_model_version_id` only if source project is same task (classification model on classification project)
  - Worker: if classification, `model.train(data=dir, ...)` and extract `metrics/accuracy_top1` into history `accuracy` and result `top1`
  - `ModelVersion.create(..., top1=result.top1)`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_train_classification_defaults_cls_weights() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    version = DatasetVersion.create(project.id, 1, "v1")
    version.mark_ready(..., yaml_path="projects/p/datasets/v1", items=[])
    job = await use_case.execute(project.id, version.id)
    assert job.base_weights == "yolov8n-cls.pt"


@pytest.mark.asyncio
async def test_train_classification_rejects_det_weights() -> None:
    with pytest.raises(DomainValidationException, match="base_weights"):
        await use_case.execute(..., base_weights="yolov8n.pt")


@pytest.mark.asyncio
async def test_train_detection_rejects_cls_weights() -> None:
    with pytest.raises(DomainValidationException, match="base_weights"):
        await use_case.execute(..., base_weights="yolov8n-cls.pt")
```

Existing detection test must still expect `yolov8n.pt`.

- [ ] **Step 2: Run, expect FAIL**

Run: `python -m pytest tests/unit/application/test_train_model.py -v`

- [ ] **Step 3: Implement trainer branch**

`TrainModelUseCase._resolve_base_weights`: if `project.task_type is CLASSIFICATION`, allowed set is cls; default `yolov8n-cls.pt`; else existing det set. If `base_model_version_id` is set, load that model; if its project matches but you cannot infer task from weights name, infer from current project only (same project already implies same task). Reject if weights filename contains `-cls` XOR project is classification when using pretrained names.

`TrainingJobRunner._run_locked`: set `TrainingConfig.task = "classification" if project.task_type == CLASSIFICATION else "detection"`. Load project in that session (already loads for name).

For classification, `get_absolute_path(version.yaml_path)` must be a directory. Detection still requires a file ending in `.yaml` (current behavior).

`ultralytics_trainer._training_worker`:

```python
train_kwargs = dict(
    data=config["data_yaml_path"],
    epochs=...,
    ...
)
# existing model.train(**train_kwargs)
```

Payload includes `"task": config.get("task", "detection")`. `_extract_metrics` for cls:

```python
"accuracy": _get("metrics/accuracy_top1", "metrics/accuracy_top5", "accuracy"),
"map50": _get("metrics/mAP50(B)", "mAP50"),  # None for cls
```

Final result includes `top1` from the same keys. Runner copies `result.top1` into `ModelVersion.create(..., top1=...)`. Detection leaves `top1=None`.

`ModelVersionRead.top1: float | None = None`.

- [ ] **Step 4: Run train tests**

Run: `python -m pytest tests/unit/application/test_train_model.py tests/unit/application/test_manage_dataset_model.py -v`

Expected: PASS

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 6: Classification auto-label

**Files:**
- Modify: `backend/app/application/ports/services/model_predictor.py`
- Create or modify infrastructure predictor (grep `class .*Predictor` under `backend/app/infrastructure/ml/`)
- Modify: `backend/app/application/use_cases/ml/batch_auto_label.py`
- Modify: `backend/app/presentation/schemas.py` (`AutoLabelRequest` IoU optional)
- Test: `backend/tests/unit/application/test_batch_auto_label.py` if exists, else `backend/tests/unit/application/test_batch_auto_label_classification.py`

**Interfaces:**
- Consumes: `IClassificationPredictor.predict(weights_path, image_paths, confidence_threshold) -> dict[str, Classification]`
- Produces: `Classification(class_index: int, confidence: float)` frozen dataclass
- Per image: if `confidence >= threshold` and `class_index` maps to a project class via `index_id`, upsert prediction label + `REQUIRES_REVIEW`; else leave unlabeled
- Skip images that already have VERIFIED/AUTO_VERIFIED labels
- No flip/stretch consistency
- Fail job if model class count/names do not match project classes (compare `model.names` to `{index_id: name}`)

- [ ] **Step 1: Write failing tests** with a fake predictor returning `{path: Classification(0, 0.93)}` and `{path: Classification(0, 0.01)}`. Assert one `ImageLabel` PENDING_REVIEW and one image still UNANNOTATED. Assert `annotations` repo not called.

Detection auto-label existing tests must still pass (do not change their behavior).

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement**

Add `IClassificationPredictor` next to `IModelPredictor` (same file). Implement with Ultralytics `YOLO(weights).predict` taking top-1 `probs` / `names`. Map `class_index` → `AnnotationClass` with matching `index_id`. If unmatched index, fail the job.

`BatchAutoLabelUseCase`: load project; if CLASSIFICATION, run cls path; else existing det path including consistency.

Wire predictor in `main.py` / dependencies the same way as the detection predictor.

- [ ] **Step 4: Run auto-label tests**

Run: `python -m pytest tests/unit/application/test_batch_auto_label.py tests/unit/application/test_batch_auto_label_classification.py tests/unit/application/test_annotation_audit.py -v`

Expected: PASS. Audit remains detection-only; add `require_task(DETECTION)` on audit use case if not already, with a unit test 409.

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 7: Frontend — project type, shell chrome, data hub, train/autolabel

**Files:**
- Modify: `frontend/index.html` (project modal radios; hide stream tab)
- Modify: `frontend/js/api.js`
- Modify: `frontend/js/components/projectsHub.js`
- Modify: `frontend/js/app.js` (`createProject` payload, `syncTabChrome`, hide stream)
- Modify: `frontend/js/components/dataHub.js`
- Modify: `frontend/js/components/trainingDrawer.js`
- Modify: `frontend/js/components/autoLabelModal.js`
- Modify: `frontend/js/components/modelsHub.js` (hide audit for cls; show top1)
- No frontend unit test harness for these components; verify in the running app (`uvicorn` + static frontend)

**Interfaces:**
- Consumes: `project.task_type`, `image.label`
- Produces: create payload `{ name, description, task_type }`; classification chrome without stream/background/IoU/audit

- [ ] **Step 1: API + create modal**

`api.createProject(name, description, task_type = "DETECTION")`.

In `#project-form`, only when creating (not edit), add:

```html
<fieldset id="project-task-type-fieldset" class="space-y-1">
  <legend class="text-xs text-zinc-400">Тип</legend>
  <label class="text-xs"><input type="radio" name="project-task-type" value="DETECTION" checked /> Детекция</label>
  <label class="text-xs"><input type="radio" name="project-task-type" value="CLASSIFICATION" /> Классификация</label>
</fieldset>
```

Hide fieldset in `openEditModal`. Submit reads checked radio.

Card badge: `DETECTION` → «Детекция», `CLASSIFICATION` → «Классификация».

- [ ] **Step 2: Shell + data hub**

`function isClassification() { return store.get("currentProject")?.task_type === "CLASSIFICATION"; }`

In `syncTabChrome` / `setProjectTab`: if classification and `tab === "stream"`, navigate to `data`. Hide `#tab-btn-stream` when classification.

Hide `#btn-mark-background`. Gallery tile: if `image.label`, show class name from `store.classes`; if pending, also `Math.round(confidence*100)%`. Else keep box count for detection.

- [ ] **Step 3: Training drawer + auto-label modal**

If classification, `PRETRAINED_OPTIONS` use `yolov8n-cls.pt` / `s` / `m`. Chart series: `metrics.accuracy` (fallback `map50` for detection). Hide IoU inputs in auto-label modal for classification. Hide audit button in models hub for classification. Model card: if `top1 != null`, show `Top-1: …` instead of mAP.

- [ ] **Step 4: Browser check**

Create a classification project, confirm badge, stream tab hidden, training dropdown shows `-cls` weights. Detection project unchanged (stream tab visible, det weights).

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 8: Frontend — classification annotate mode

**Files:**
- Modify: `frontend/index.html` (`#cls-class-bar` under canvas or right sidebar)
- Modify: `frontend/js/app.js` (`openImage`, `saveCurrent`, hotkeys)
- Modify: `frontend/js/hotkeys.js`
- Modify: `frontend/js/components/sidebar.js` (optional: class buttons vs box list)
- Modify: `frontend/js/api.js` (`putImageLabel`, `deleteImageLabel`, `confirmImageLabel`, `rejectImageLabel`)

**Interfaces:**
- Consumes: `PUT/DELETE/POST .../label`
- Produces: choosing a class saves immediately and goes to the next filmstrip image; Space confirms pending; U clears

- [ ] **Step 1: API helpers**

```javascript
putImageLabel: (imageId, classId) =>
  request(`/images/${imageId}/label`, {
    method: "PUT",
    body: JSON.stringify({ class_id: classId }),
  }),
deleteImageLabel: (imageId) =>
  request(`/images/${imageId}/label`, { method: "DELETE" }),
confirmImageLabel: (imageId) =>
  request(`/images/${imageId}/label/confirm`, { method: "POST" }),
rejectImageLabel: (imageId) =>
  request(`/images/${imageId}/label/reject`, { method: "POST" }),
```

- [ ] **Step 2: Annotate behavior**

When `isClassification()`:

- Do not enter DRAW mode; do not bind box-drawn / copy-paste / quick class popover.
- Hide `#tool-draw`, `#tool-select`, `#btn-copy-annotations`, `#btn-paste-annotations`, `#btn-save-annotations` (save is immediate), `#btn-clear-annotations` can map to delete label.
- `openImage`: read `detail.label`; show overlay text if `PENDING_REVIEW`.
- `assignClass(classId)`: `api.putImageLabel` → patch image status/label in store → `go(1)`.
- `confirmLabel`: `api.confirmImageLabel` then `go(1)`.
- `clearLabel`: `api.deleteImageLabel`.
- Canvas still loads the image for pan/zoom (`AnnotationCanvas.loadImage`) but drawing must no-op: in `canvas.js` skip draw if `store.get("currentProject")?.task_type === "CLASSIFICATION"` **or** pass a `readOnly` flag from `app.js` to avoid storing a task check inside canvas if you prefer `canvas.setReadOnly(true)` when opening a cls project.

Right panel: large buttons for each class (`[1] name`). Review bar: Confirm / Reject calling label endpoints, not box verify.

- [ ] **Step 3: Hotkeys**

In `hotkeys.js`, if classification: digits call `assignClass` (not `selectClass` / quick class); Space confirms label if pending else no-op (do not verify boxes); Del/U reject or clear. Detection path unchanged.

- [ ] **Step 4: Browser check**

Classification: assign class with `1`, auto-advance, confirm prediction with Space, clear with U. Detection: boxes still draw and save. Create dataset + open train drawer still works for both (dataset already backend-complete).

- [ ] **Step 5: Commit** (skip unless user asked)

---

## Spec coverage (self-review)

| Spec section | Task |
| --- | --- |
| Immutable `task_type`, default detection | 1, 2, 3 |
| `ImageLabel` + status table | 1, 3 |
| SQLite column/table/`top1` | 2 |
| Label API + 409 | 3, 6 (audit) |
| Stratified cls dataset, `val/` folders, no aug | 4 |
| Export zip folders | 4 |
| Cls train weights/metrics | 5 |
| Auto-label threshold, no IoU consistency | 6 |
| UI create/badge/hide stream/background | 7 |
| Annotate class keys + review | 8 |
| No stream/keypoints/multilabel/aug | Global + 7–8 omit them |

No TBD remaining. Names: `ProjectTaskType`, `ImageLabel`, `require_task`, `assign_splits_stratified`, `class_dir_name`, `IClassificationPredictor`, `TrainingConfig.task`, routes under `/images/{id}/label`.
