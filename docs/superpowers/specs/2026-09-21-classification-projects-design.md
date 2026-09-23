# Classification projects (single-label)

**Date:** 2026-09-21  
**Status:** design approved in conversation; awaiting written-spec sign-off  
**Scope:** backend + frontend MVP for image classification projects alongside existing detection

## Problem

The platform is detection-only: classes attach to bounding boxes, dataset export is YOLO det (`images/` + `labels/*.txt`), training calls `YOLO.train()` on `data.yaml`, and the annotate UI is a box canvas. Adding classification as a second product inside the same app must not break detection or pretend classification is a full-image box.

## Goal

Support a second project type: **single-label image classification**. One image has at most one class. The user can run the same active-learning loop as detection, minus stream and keypoints:

create project → classes → upload → assign class → dataset version → train `yolov8*-cls` → auto-label → verify → next dataset version.

## Non-goals

- Multilabel (several classes on one image).
- Changing `task_type` after create.
- Stream / tripwire / RTSP for classification.
- Keypoint copy-paste, box canvas, IoU annotation audit.
- Background / negative samples (`is_background`) in classification.
- Dataset augmentations for classification in this version (copy originals into split/class folders).
- Augmentation-consistency auto-verify used by detection auto-label.
- Separate ClassificationProject / duplicated upload-train-model stacks.

## Agreed decisions

| Topic | Decision |
| --- | --- |
| Label cardinality | Exactly one class per image, or none |
| Architecture | Same `Project`; `task_type` + `image_labels` table |
| Type mutability | Set only on create; existing rows default to `detection` |
| MVP surface | Label + dataset + train + auto-label; hide stream and detection tools |
| Augmentations | Off for classification dataset builds |
| Trainer | Ultralytics classify weights (`yolov8n-cls.pt` and siblings) |

## Domain

### `ProjectTaskType`

```text
DETECTION
CLASSIFICATION
```

`Project.task_type` is required. `Project.create(..., task_type=DETECTION)` by default. `rename` / update must not accept or change `task_type`.

### `ImageLabel`

New entity, at most one row per `image_id`:

| Field | Notes |
| --- | --- |
| `id` | UUID |
| `image_id` | unique |
| `class_id` | class of this project |
| `source` | `MANUAL` or `MODEL_PREDICTION` |
| `confidence` | `1.0` for manual; model score otherwise |
| `verification_status` | same enum as annotations |
| `verified_at` | set on human/auto verify |
| `model_version_id` | nullable; set for model predictions |

Classification image status is derived only from this label (never from `annotations`):

| Label | Image status |
| --- | --- |
| none | `UNANNOTATED` |
| `PENDING_REVIEW` | `REQUIRES_REVIEW` |
| `AUTO_VERIFIED` | `AUTO_VERIFIED` |
| `VERIFIED` | `VERIFIED` |
| removed / rejected | `UNANNOTATED` (row deleted) |

`Image.recalculate_status` stays detection-only. Classification use cases call a dedicated `recalculate_status_from_label(label | None)`.

`Image.mark_as_background` is forbidden when `project.task_type == CLASSIFICATION`.

Detection use cases never read or write `image_labels`. Classification use cases never read or write `annotations`.

## Persistence

Add column via existing SQLite `_ensure_table_columns`:

```text
projects.task_type  VARCHAR(32) NOT NULL DEFAULT 'DETECTION'
```

New table `image_labels` with unique `image_id`, FKs to `images` and `annotation_classes`, `ON DELETE CASCADE`.

`create_all` creates the table for new DBs; no Alembic.

`DatasetItem.snapshot_annotations` JSON for classification is a one-element list **without bbox fields**:

```json
[{"class_id": "...", "class_index": 0}]
```

Detection snapshots keep the current bbox shape. Mappers must parse by presence of `x_center` (or a `kind` field if cheaper). Prefer a frozen `SnapshotClassLabel` alongside `SnapshotAnnotation` rather than stuffing `0,0,1,1` boxes.

`dataset_versions.yaml_path` for classification is the **dataset root directory** (folder that contains `train/`, `valid/`, `test/`), not a `data.yaml` file. Detection keeps writing `.../data.yaml`.

Optional: `model_versions.top1` nullable float, added the same way as other columns. Classification fills `top1`; `map50` / `map50_95` stay null. Detection leaves `top1` null.

## Dataset build

`CreateDatasetVersionUseCase` branches on `project.task_type`.

Shared: project must exist; `REQUIRES_REVIEW` (and pending labels) block the build; at least `DEFAULT_MIN_VERIFIED_IMAGES` (10) frames with `VERIFIED` or `AUTO_VERIFIED`.

Classification extras:

- each included image must have exactly one verified/auto-verified label whose `class_id` is still in the project;
- split assignment is shuffled then **stratified by class** so each class appears in train/val/test when counts allow; if a class has fewer images than the number of requested non-zero splits, put remaining copies into train and still create empty val/test class folders;
- on-disk layout:

```text
projects/{project_id}/datasets/v{N}/
  train/{class_name}/{image_id}{suffix}
  valid/{class_name}/...
  test/{class_name}/...
```

Class folder names are the class `name` values (already unique per project). Sanitize only if a name contains path separators; otherwise keep as stored.

- no Albumentations; one file per source image;
- `train_file_count` equals `train_count` (same for valid/test);
- augmentation config stored as identity/default JSON but **not applied**.

Export zip (`GET /projects/{id}/export-yolo` may keep the path for compatibility): classification packs the same folder layout; detection unchanged.

## Training

Reuse `TrainingJob`, `TrainingJobRunner`, `IModelTrainer`.

`TrainingConfig` gains `task: detection | classification` (or equivalent). Worker:

- detection: current `YOLO(det_weights).train(data=yaml_file)`;
- classification: `YOLO(cls_weights).train(data=dataset_root_dir)`.

Allowed pretrained classification checkpoints: `yolov8n-cls.pt`, `yolov8s-cls.pt`, `yolov8m-cls.pt` (same size ladder as det; no `l`/`x` required in MVP). Default `yolov8n-cls.pt`.

Fine-tune from `base_model_version_id` only if that model belongs to the same project **and** was trained as classification (dataset/job of a classification project). Mixing det/cls weights is a domain validation error.

Epoch metrics JSON for classification uses `accuracy` / `metrics/accuracy_top1` (and val loss if present). UI charts that key instead of `map50`. Persist last top-1 onto `ModelVersion.top1`.

If Ultralytics classification `train()` expects `val` not `valid`, the builder must use the directory name Ultralytics actually reads, or pass `data` as a yaml that points at those folders. Implementation must match current Ultralytics cls layout (`train/` + `val/` class folders). Prefer renaming the valid split folder to `val/` **only on disk for classification**, while DB split enum stays `valid`.

## Auto-label and review

Reuse `AutoLabelJob` + runner.

Classification predictor: `YOLO(cls).predict` → top-1 class name/index mapped onto project classes by **index_id** (same as training `names` order). If the model class set does not match project classes (count or names), the job fails with a clear error.

Per image:

- confidence ≥ threshold → upsert `ImageLabel` (`MODEL_PREDICTION`, `PENDING_REVIEW`), status `REQUIRES_REVIEW`;
- below threshold → do not write a label; leave `UNANNOTATED`;
- skip images that already have a verified/auto-verified label unless the request explicitly retargets unannotated-only (same `all_unannotated` / `image_ids` contract as today).

No IoU, no three-run consistency check.

Review:

- confirm → `AUTO_VERIFIED` (or `VERIFIED` if the operator changed nothing but clicked confirm — use `AUTO_VERIFIED` for unmodified model label, `VERIFIED` if class was changed then saved);
- change class → `MANUAL`, `VERIFIED`, confidence `1.0`;
- reject / clear → delete label, `UNANNOTATED`.

`iou_threshold` / `consistency_iou_threshold` on the job row may keep defaults unused; API/UI omit them for classification.

## API

- `ProjectCreate.task_type`: `"DETECTION" | "CLASSIFICATION"`, default `"DETECTION"`.
- `ProjectRead.task_type` always present.
- `ProjectUpdate` has no `task_type`.
- Classification image detail: `label: ImageLabelRead | null`; `annotations` empty list.
- `PUT` (or `PUT /images/{id}/label`) body `{ "class_id": UUID }` assigns/replaces manual label and returns updated image+label.
- `DELETE` label endpoint or empty body clears the label.
- Verify/reject-all for classification operate on the single label, not boxes.
- Auto-label and train endpoints stay on the same routes; server branches on project type.
- Detection-only routes (propagate boxes, mark background, annotation audit, stream) return **409** with a stable message when `task_type != DETECTION`.
- Classification-only label routes return **409** on detection projects.

## UI

- Project modal: two options, detection default. Edit modal does not show type. Hub card shows a type badge.
- Classification studio tabs: Данные, Разметка, Модели. Hide Stream tab and stream hash routes (redirect to data).
- Data hub: show class name (and confidence if predicted) instead of box count. Hide background action.
- Annotate: canvas is pan/zoom image only (no draw, no box chrome, no keypoint overlay, no «Бэкграунд»). Right panel: class buttons. Choosing a class saves immediately and advances to the next filmstrip image.
- Hotkeys in classification annotate: `1`–`9` assign class; arrows change image; `Space` confirms pending prediction and advances; `U` or clear control removes label. Detection hotkeys for draw/copy/paste stay detection-only.
- Review chrome: show predicted class + confidence; Confirm / Change / Reject.
- Training drawer: cls weight list; chart accuracy; hide mAP.
- Auto-label modal: confidence only.

## Errors

- Wrong task for an operation → 409.
- Missing classes or insufficient verified frames → existing dataset exceptions.
- Unsupported `base_weights` for the task → 400 domain validation.
- Missing cls dataset root / empty class folders → dataset not ready / train fail as today.

## Testing

- Domain: `task_type` immutable; one label per image; status from label; background rejected on classification.
- Dataset: classification folder layout; stratification; review frames block; detection yaml path unchanged.
- Train: cls weights allowed, det weights rejected on classification project and vice versa.
- Auto-label: writes label above threshold, skips below; no annotations rows.
- API: 409 on crossed task operations; old projects without column behave as `DETECTION`.
- Keep existing detection unit tests green (default task type).

## Out of later iterations

Multilabel, stream sampling for classifiers, cls augmentations, changing task type, importing ImageNet-style folder zips as labeled data (nice-to-have later, not this spec).
