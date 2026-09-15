# Stream & Test Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Stream & Test Hub — live MJPEG model validation plus conditional frame harvesting (timer + uncertainty, tripwire) into the HITL review queue.

**Architecture:** Unified `OpenCVStreamRunner` thread per active stream (capture → YOLO.track → triggers → overlay JPEG). Async ingest consumer persists clean frames as `STREAM_INGEST` / `REQUIRES_REVIEW` with `MODEL_PREDICTION` annotations. One active stream per project. Frontend fourth tab drives CRUD, live preview, and tripwire drawing.

**Tech Stack:** FastAPI, SQLAlchemy async + SQLite, OpenCV (`cv2.VideoCapture`), Ultralytics YOLO.track, vanilla JS frontend (existing tab/router patterns).

**Spec:** `docs/superpowers/specs/2026-09-15-stream-test-hub-design.md`

## Global Constraints

- One active stream per `project_id` (start stops any other active stream in that project).
- Timer capture: uncertainty window only; any class; plus global cooldown.
- Tripwire: geometry + direction + per-`track_id` debounce; no uncertainty gate; global cooldown still applies.
- Ingest HITL invariant: clean JPEG → `ImageSourceType.STREAM_INGEST`, `ImageStatus.REQUIRES_REVIEW`, annotations `SourceType.MODEL_PREDICTION` / `PENDING_REVIEW`.
- VIDEO_FILE loops on EOF.
- No WebRTC/HLS/WebSocket in v1; UI polls `/status` for capture flash.
- Follow Clean Architecture: domain has no OpenCV/Ultralytics imports.
- Commits: only when the user asks, or at the end of a task if the executing skill explicitly requires a commit step — prefer small focused commits matching repo style (`feat(backend):`, `feat(frontend):`).

---

## File Structure

| Path | Responsibility |
| :--- | :--- |
| `backend/app/domain/enums.py` | Add `StreamSourceType`, `TripwireDirection`, `StreamRunnerState` |
| `backend/app/domain/value_objects/stream_trigger_config.py` | Validated trigger config VO |
| `backend/app/domain/services/tripwire.py` | Segment intersection, direction, debounce helper |
| `backend/app/domain/entities/stream_source.py` | `StreamSource` entity |
| `backend/app/application/ports/repositories/stream_source_repository.py` | Repo port |
| `backend/app/application/ports/services/stream_runner.py` | Runner port + status DTO + ingest job DTO |
| `backend/app/application/use_cases/streaming/*.py` | CRUD, configure, start/stop, ingest |
| `backend/app/infrastructure/db/tables.py` | `StreamSourceRow` |
| `backend/app/infrastructure/db/repositories/stream_source_repository.py` | SQLAlchemy repo |
| `backend/app/infrastructure/db/mappers.py` | Entity ↔ row |
| `backend/app/infrastructure/streaming/opencv_stream_runner.py` | Thread runner + MJPEG buffer + ingest queue |
| `backend/app/presentation/api/v1/stream_router.py` | REST endpoints |
| `backend/app/presentation/schemas.py` | Stream schemas |
| `backend/app/presentation/dependencies.py` | Wire use cases + runner singleton |
| `backend/app/main.py` | Register router; start ingest consumer in lifespan |
| `frontend/index.html` | Tab button + `#tab-view-stream` shell |
| `frontend/js/router.js` / `app.js` | `stream` tab routing |
| `frontend/js/api.js` | Stream API helpers |
| `frontend/js/components/streamHub.js` | UI logic + tripwire overlay |

---

### Task 1: Tripwire geometry + `StreamTriggerConfig`

**Files:**
- Create: `backend/app/domain/services/tripwire.py`
- Create: `backend/app/domain/value_objects/stream_trigger_config.py`
- Modify: `backend/app/domain/enums.py`
- Test: `backend/tests/unit/domain/test_tripwire.py`
- Test: `backend/tests/unit/domain/test_stream_trigger_config.py`

**Interfaces:**
- Consumes: none (pure domain)
- Produces:
  - `StreamSourceType` = `RTSP` | `VIDEO_FILE` | `DEVICE`
  - `TripwireDirection` = `ANY` | `FORWARD` | `BACKWARD`
  - `segments_intersect(a1, a2, b1, b2) -> bool`
  - `crossing_direction(p_prev, p_curr, line_a, line_b) -> TripwireDirection` (`FORWARD` if cross product of line×motion > 0, else `BACKWARD`)
  - `TripwireDebouncer(debounce_seconds).allow(track_id, now) -> bool`
  - `StreamTriggerConfig(...)` frozen dataclass with validation in `__post_init__`

- [ ] **Step 1: Write failing tripwire tests**

```python
# backend/tests/unit/domain/test_tripwire.py
from app.domain.enums import TripwireDirection
from app.domain.services.tripwire import (
    TripwireDebouncer,
    crossing_direction,
    segments_intersect,
)


def test_segments_intersect_when_crossing():
    assert segments_intersect((0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0)) is True


def test_segments_do_not_intersect_when_parallel():
    assert segments_intersect((0.0, 0.2), (1.0, 0.2), (0.0, 0.8), (1.0, 0.8)) is False


def test_crossing_direction_forward_left_to_right():
    # horizontal line left→right; motion top→bottom is FORWARD by convention
    direction = crossing_direction((0.5, 0.2), (0.5, 0.8), (0.0, 0.5), (1.0, 0.5))
    assert direction == TripwireDirection.FORWARD


def test_debouncer_blocks_same_track_within_window():
    debouncer = TripwireDebouncer(debounce_seconds=3.0)
    assert debouncer.allow(track_id=7, now=100.0) is True
    assert debouncer.allow(track_id=7, now=101.0) is False
    assert debouncer.allow(track_id=7, now=104.0) is True
```

- [ ] **Step 2: Run tests — expect FAIL (import/enum missing)**

Run: `cd backend; python -m pytest tests/unit/domain/test_tripwire.py -v`  
Expected: FAIL with `ImportError` or `AttributeError` for `TripwireDirection` / `tripwire`.

- [ ] **Step 3: Implement enums + tripwire helpers**

Add to `enums.py`:

```python
class StreamSourceType(str, Enum):
    RTSP = "RTSP"
    VIDEO_FILE = "VIDEO_FILE"
    DEVICE = "DEVICE"


class TripwireDirection(str, Enum):
    ANY = "ANY"
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"
```

Implement `tripwire.py` using CCW orientation for intersection; direction via sign of `(Bx-Ax)*(Py-Ay) - (By-Ay)*(Px-Ax)` on the **current** point relative to directed line A→B (or equivalently cross of line vector and motion vector). Document in module docstring: `FORWARD` = positive cross (approx. left→right / top→bottom relative to A→B).

- [ ] **Step 4: Write failing config tests + implement `StreamTriggerConfig`**

```python
# backend/tests/unit/domain/test_stream_trigger_config.py
import pytest
from app.domain.enums import TripwireDirection
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig
from app.domain.exceptions import DomainValidationException


def test_defaults_are_valid():
    cfg = StreamTriggerConfig()
    assert cfg.uncertainty_range == (0.70, 0.90)
    assert cfg.cooldown_seconds == 3.0
    assert cfg.tripwire_direction == TripwireDirection.ANY


def test_rejects_inverted_uncertainty_range():
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(uncertainty_range=(0.9, 0.5))


def test_rejects_line_coords_outside_unit_square():
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(tripwire_line=(0.0, 0.0, 1.5, 1.0))
```

`StreamTriggerConfig` fields (all with defaults matching the spec):  
`timer_enabled=False`, `timer_interval_seconds=5.0`, `tripwire_enabled=False`, `tripwire_line=None`, `tripwire_classes=()`, `tripwire_direction=ANY`, `tripwire_debounce_seconds=3.0`, `uncertainty_range=(0.70, 0.90)`, `cooldown_seconds=3.0`.  
Validate: intervals > 0; `0 <= unc_min < unc_max <= 1`; line coords in `[0,1]` when set; debounce/cooldown >= 0.

- [ ] **Step 5: Run all Task 1 tests — expect PASS**

Run: `cd backend; python -m pytest tests/unit/domain/test_tripwire.py tests/unit/domain/test_stream_trigger_config.py -v`

- [ ] **Step 6: Commit** (if user approved commits for this work)

```bash
git add backend/app/domain/enums.py backend/app/domain/services/tripwire.py backend/app/domain/value_objects/stream_trigger_config.py backend/tests/unit/domain/test_tripwire.py backend/tests/unit/domain/test_stream_trigger_config.py
git commit -m "feat(domain): add stream trigger config and tripwire geometry"
```

---

### Task 2: `StreamSource` entity + persistence

**Files:**
- Create: `backend/app/domain/entities/stream_source.py`
- Create: `backend/app/application/ports/repositories/stream_source_repository.py`
- Create: `backend/app/infrastructure/db/repositories/stream_source_repository.py`
- Modify: `backend/app/infrastructure/db/tables.py` — add `StreamSourceRow`
- Modify: `backend/app/infrastructure/db/mappers.py` — map config JSON ↔ VO
- Modify: `backend/app/infrastructure/db/session.py` — `create_all` already covers new table via `Base.metadata`
- Test: `backend/tests/unit/domain/test_stream_source.py`
- Test: `backend/tests/integration/test_stream_source_repository.py` (follow existing integration test style)

**Interfaces:**
- Consumes: `StreamTriggerConfig`, `StreamSourceType`
- Produces:
  - `StreamSource.create(...)`, `.activate()`, `.deactivate()`, `.update_config(cfg)`, `.set_model(model_version_id)`, `.increment_captured()`
  - `IStreamSourceRepository`: `add`, `get_by_id`, `list_by_project`, `update`, `delete`, `get_active_for_project(project_id) -> StreamSource | None`

- [ ] **Step 1: Write failing entity test**

```python
from uuid import uuid4
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType


def test_create_defaults_inactive_zero_captures():
    src = StreamSource.create(
        project_id=uuid4(),
        name="Gate cam",
        source_type=StreamSourceType.RTSP,
        source_uri="rtsp://127.0.0.1/stream",
    )
    assert src.is_active is False
    assert src.captured_frames_count == 0
    assert src.model_version_id is None
```

- [ ] **Step 2: Implement entity**

Dataclass fields: `id`, `project_id`, `name`, `source_type`, `source_uri`, `is_active`, `model_version_id`, `config: StreamTriggerConfig`, `captured_frames_count`, `created_at`.  
`create` validates non-empty name/uri. Persist `config` as JSON dict in DB (`config_json` column).

- [ ] **Step 3: Add `StreamSourceRow`**

```python
class StreamSourceRow(Base):
    __tablename__ = "stream_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    captured_frames_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Optional: add `images.stream_source_id` FK later; for v1 keep nullable string as today (no migration required beyond new table).

- [ ] **Step 4: Implement repository + integration test**

Integration test: create project → add stream → list → update config → get_active_for_project after `activate()` → delete.  
Use the same session/factory helpers as other integration tests under `backend/tests/integration/`.

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd backend; python -m pytest tests/unit/domain/test_stream_source.py tests/integration/test_stream_source_repository.py -v`

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(backend): persist StreamSource entities"
```

---

### Task 3: `IngestStreamFrameUseCase`

**Files:**
- Create: `backend/app/application/use_cases/streaming/ingest_stream_frame.py`
- Test: `backend/tests/unit/application/test_ingest_stream_frame.py`

**Interfaces:**
- Consumes: `IImageRepository`, `IAnnotationRepository`, `IClassRepository`, `IStreamSourceRepository`, `IFileStorage`, `IUnitOfWork`, metadata size from JPEG bytes (use `IImageMetadataReader` / Pillow like uploads)
- Produces: `async def execute(stream_id, jpeg_bytes, detections: list[StreamDetection], reason: str) -> Image`
- `StreamDetection` dataclass: `class_index: int`, `confidence: float`, `x_center`, `y_center`, `width`, `height` (normalized) — can live in the use case module or reuse `Detection` from `model_predictor.py`

- [ ] **Step 1: Write failing unit test (HITL invariant)**

Mirror fakes from `test_batch_auto_label.py`. Assert:

1. Storage `save` called under `projects/{project_id}/images/` with `.jpg`.
2. Image `source_type == STREAM_INGEST`, `status == REQUIRES_REVIEW`, `stream_source_id == stream.id`, `split == TRAIN`.
3. Annotations via `Annotation.create_prediction` → `PENDING_REVIEW` / `MODEL_PREDICTION`.
4. `stream.captured_frames_count` incremented and `streams.update` called.
5. `uow.commit` called.
6. Class index maps via project classes’ `index_id`; unknown index skipped (do not fail whole ingest).

- [ ] **Step 2: Implement use case**

Algorithm:

1. Load stream; 404 if missing.
2. Decode size via metadata reader on `jpeg_bytes`.
3. `storage.save(f"projects/{stream.project_id}/images", f"{uuid}.jpg", jpeg_bytes)`.
4. `Image.create(..., source_type=STREAM_INGEST, stream_source_id=stream.id)` then set status via `recalculate_status` after creating prediction annotations (or set `REQUIRES_REVIEW` explicitly after attaching pending boxes).
5. Map detections → annotations with `bbox_from_detection` (import from `batch_auto_label` or move shared helper to `application/services/bbox_from_detection.py` — prefer small shared helper to avoid circular imports).
6. `images.add`, `annotations.replace_for_image`, increment stream counter, `commit`.
7. On failure after save: delete file (same pattern as `UploadImagesUseCase`).

- [ ] **Step 3: Run test — expect PASS**

Run: `cd backend; python -m pytest tests/unit/application/test_ingest_stream_frame.py -v`

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(backend): ingest stream frames into HITL review queue"
```

---

### Task 4: Stream source management use cases + REST CRUD

**Files:**
- Create: `backend/app/application/use_cases/streaming/manage_stream_source.py` (create RTSP/device, upload video, delete, list, configure triggers, set model)
- Modify: `backend/app/presentation/schemas.py`
- Create: `backend/app/presentation/api/v1/stream_router.py` (CRUD + triggers only in this task)
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py` — `include_router(stream_router)`
- Test: `backend/tests/unit/application/test_manage_stream_source.py`
- Test: `backend/tests/e2e/test_stream_crud_api.py`

**Interfaces:**
- Consumes: `IStreamSourceRepository`, `IFileStorage`, `IProjectRepository` (existence check), `IModelVersionRepository` (optional model bind), `IUnitOfWork`
- Produces use case methods:
  - `create_rtsp(project_id, name, rtsp_url) -> StreamSource`
  - `create_device(project_id, name, device_index: int) -> StreamSource` (uri = `str(device_index)`)
  - `upload_video(project_id, name, filename, data: bytes) -> StreamSource` — save to `projects/{id}/videos/{uuid}{ext}`, type `VIDEO_FILE`
  - `delete(stream_id)` — if `VIDEO_FILE`, delete file; refuse or force-stop if active (call runner stop in Task 5; for now if `is_active` raise `DomainValidationException`)
  - `list_by_project(project_id)`
  - `configure_triggers(stream_id, config: StreamTriggerConfig, model_version_id: UUID | None) -> StreamSource`

Allowed video extensions: `.mp4`, `.avi`, `.mov`, `.mkv` (case-insensitive).

- [ ] **Step 1: Write failing unit tests for create/upload/configure/delete**

- [ ] **Step 2: Implement use cases**

- [ ] **Step 3: Add Pydantic schemas + router endpoints**

```http
GET    /api/v1/projects/{project_id}/streams
POST   /api/v1/projects/{project_id}/streams/rtsp
POST   /api/v1/projects/{project_id}/streams/device
POST   /api/v1/projects/{project_id}/streams/upload-video
PUT    /api/v1/streams/{stream_id}/triggers
DELETE /api/v1/streams/{stream_id}
```

Wire dependencies like other routers (`get_uow`, repos from session).

- [ ] **Step 4: E2E API test with `httpx.AsyncClient` + `create_app(database_url=..., storage_root=...)`**

Create project → POST rtsp → GET list → PUT triggers → DELETE.

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd backend; python -m pytest tests/unit/application/test_manage_stream_source.py tests/e2e/test_stream_crud_api.py -v`

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(backend): stream source CRUD and trigger configuration API"
```

---

### Task 5: `OpenCVStreamRunner` + start/stop/live/status

**Files:**
- Create: `backend/app/application/ports/services/stream_runner.py`
- Create: `backend/app/infrastructure/streaming/opencv_stream_runner.py`
- Create: `backend/app/application/use_cases/streaming/control_stream.py` (`StartStreamUseCase`, `StopStreamUseCase`)
- Create: `backend/app/application/use_cases/streaming/ingest_consumer.py` (async loop draining queue → `IngestStreamFrameUseCase`)
- Modify: `stream_router.py` — start/stop/live/status
- Modify: `main.py` lifespan — construct singleton runner + start ingest consumer task; on shutdown stop all runners
- Modify: `dependencies.py`
- Test: `backend/tests/unit/infrastructure/test_tripwire_eval_in_runner.py` (pure helpers if extracted)
- Test: `backend/tests/e2e/test_stream_live_api.py` (VIDEO_FILE fixture; may mock YOLO)

**Interfaces:**
- Consumes: `IStreamSourceRepository`, model weights via storage, `IngestStreamFrameUseCase`
- Produces `IStreamRunner`:
  - `start(stream: StreamSource, weights_abs_path: str, class_names: list[str]) -> None`
  - `stop(stream_id: UUID) -> None`
  - `stop_project(project_id: UUID) -> None` — enforce one-active-per-project
  - `get_status(stream_id: UUID) -> StreamStatus`
  - `mjpeg_frames(stream_id: UUID) -> AsyncIterator[bytes]` (or sync generator polled by StreamingResponse)
  - `ingest_queue: queue.Queue[IngestJob]`

`StreamStatus`: `is_running: bool`, `state: str`, `fps: float`, `captured_count: int`, `last_capture_at: datetime | None`, `error_message: str | None`

`IngestJob`: `stream_id`, `jpeg_bytes`, `detections: list[Detection]`, `reason: str` (`timer`|`tripwire`), `captured_at`

- [ ] **Step 1: Write failing unit test for timer/tripwire decision helpers**

Extract pure functions used by the runner (easier to test without YOLO):

```python
# e.g. in domain/services/stream_capture_rules.py or inside tripwire module
def should_capture_timer(*, now, last_timer_at, last_any_at, interval, cooldown, confidences, unc_range) -> bool: ...
def should_capture_tripwire(*, track_id, p_prev, p_curr, line, direction, classes_ok, debouncer, now, last_any_at, cooldown) -> bool: ...
```

- [ ] **Step 2: Implement helpers + runner skeleton**

Runner loop (pseudocode to implement faithfully):

```python
while not stop_event.is_set():
    ok, frame = cap.read()
    if not ok:
        if source_type == VIDEO_FILE:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
        # RTSP: reconnect with backoff; set state=reconnecting
        continue
    results = model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False)
    # parse boxes, track ids, confidences, class indices
    # evaluate tripwire / timer → maybe queue IngestJob with clean frame encode
    overlay = draw(frame, boxes, line)
    ok, buf = cv2.imencode(".jpg", overlay)
    self._latest_jpeg[stream_id] = buf.tobytes()
```

Use a process-global or app-state `OpenCVStreamRunner` singleton keyed by `stream_id`.  
`StartStreamUseCase`: load stream + model weights; `runner.stop_project(project_id)`; set previous active rows inactive; `stream.activate()`; `runner.start(...)`; commit.

For tests without GPU/weights: inject a fake `frame_processor` callable OR skip live inference in unit tests and cover e2e with a stub runner registered in `create_app`.

**Recommended test seam:** `IStreamRunner` with `FakeStreamRunner` in e2e for start/stop/status; separate unit tests for capture rules; one optional integration marked `@pytest.mark.slow` if real ultralytics available.

- [ ] **Step 3: Wire `/start`, `/stop`, `/status`, `/live`**

```python
@router.get("/streams/{stream_id}/live")
async def live(stream_id: UUID, runner: IStreamRunner = Depends(...)):
    async def gen():
        while True:
            jpeg = runner.latest_jpeg(stream_id)
            if jpeg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.07)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")
```

- [ ] **Step 4: Ingest consumer in lifespan**

```python
async def _ingest_loop():
    while True:
        job = await asyncio.to_thread(runner.ingest_queue.get)
        # open short-lived session / uow and call IngestStreamFrameUseCase
```

On shutdown: cancel task; `runner.stop_all()`.

- [ ] **Step 5: E2E with FakeStreamRunner**

Assert start → status `is_running` → live returns `multipart` content-type → stop.

- [ ] **Step 6: Run tests — expect PASS**

Run: `cd backend; python -m pytest tests/unit -k stream -v; python -m pytest tests/e2e/test_stream_live_api.py -v`

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(backend): OpenCV stream runner with MJPEG and ingest queue"
```

---

### Task 6: Frontend Stream tab

**Files:**
- Modify: `frontend/index.html` — 4th tab button, `#shell-actions-stream`, `#tab-view-stream` layout
- Modify: `frontend/js/router.js` — recognize `stream` subTab
- Modify: `frontend/js/app.js` — include `stream` in `syncTabChrome` / `setProjectTab`; init `streamHub`
- Modify: `frontend/js/api.js` — stream API functions
- Create: `frontend/js/components/streamHub.js`
- Modify: `frontend/index.html` scripts if components are loaded via script tags (match existing pattern)

**Interfaces:**
- Consumes: REST from Task 4–5
- Produces: interactive hub matching the approved wireframe

- [ ] **Step 1: Wire tab chrome + empty view**

Add button `tab-btn-stream` label «Стрим и Сбор».  
`#tab-view-stream` with left video pane (`#stream-live-img`, `#stream-tripwire-canvas`), controls, right settings, bottom bar `#stream-captured-count`.

Update `router.js`:

```javascript
if (subTab === "stream") {
  return { name: "stream", projectId, tab: "stream" };
}
```

Update `syncTabChrome` tab list: `["data", "annotate", "models", "stream"]`.

- [ ] **Step 2: Add `api.js` helpers**

`listStreams`, `createRtspStream`, `createDeviceStream`, `uploadStreamVideo`, `deleteStream`, `putStreamTriggers`, `startStream`, `stopStream`, `streamLiveUrl(streamId)`, `getStreamStatus`.

- [ ] **Step 3: Implement `streamHub.js`**

Responsibilities:

1. `refresh()` — list streams, models, classes; render source list.
2. Select stream → bind settings form; set `<img src=liveUrl>` only when running.
3. Start/Stop buttons → API; begin/clear `setInterval` status poll (1s).
4. On `captured_count` increase → add CSS class flash on video frame 300ms; update bottom counter.
5. Tripwire draw mode: click A, click B on overlay canvas (map to normalized coords via displayed image size); drag handles; on mouseup `putStreamTriggers`.
6. Video upload input + delete buttons.
7. «Перейти к верификации» → `setProjectTab("annotate")` (optionally filter client-side to `REQUIRES_REVIEW` / `STREAM_INGEST` if data hub already supports status filter — reuse existing annotate entry).

Keep visuals consistent with zinc dark UI; tripwire stroke `#22d3ee` (cyan), endpoint circles radius ~6px.

- [ ] **Step 4: Manual smoke checklist** (document in PR / commit body)

1. Open tab, create RTSP or upload MP4.
2. Select model, set uncertainty, enable timer.
3. Start — see MJPEG (or placeholder error if no weights).
4. Draw line, enable tripwire.
5. Confirm captured count / studio link.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(frontend): add Stream & Test Hub tab"
```

---

### Task 7: End-to-end verification + doc sync

**Files:**
- Create: `backend/tests/e2e/test_stream_ingest_flow.py`
- Modify (light): `docs/back.md` §3.5 / API table — point to new endpoints (replace old `/streams/configure` sketch)
- Modify (light): `docs/front.md` — replace `streamModal.js` with `streamHub.js` tab
- Modify (light): `docs/plan.md` Phase 5 — mark superseded by Stream & Test Hub spec

**Interfaces:**
- Consumes: full stack from Tasks 1–6
- Produces: regression coverage + docs aligned with shipped behavior

- [ ] **Step 1: E2E ingest flow with FakeStreamRunner pushing a job**

After create stream + start, push one `IngestJob` into the real consumer (or call ingest use case via API test double). Assert:

- `GET /projects/{id}/images` contains item with `source_type=STREAM_INGEST`, `status=REQUIRES_REVIEW`
- Image detail includes `PENDING_REVIEW` annotation

- [ ] **Step 2: Run full stream-related suite**

Run: `cd backend; python -m pytest tests/unit/domain/test_tripwire.py tests/unit/domain/test_stream_trigger_config.py tests/unit/domain/test_stream_source.py tests/unit/application/test_ingest_stream_frame.py tests/unit/application/test_manage_stream_source.py tests/e2e/test_stream_crud_api.py tests/e2e/test_stream_live_api.py tests/e2e/test_stream_ingest_flow.py -v`

Expected: all PASS.

- [ ] **Step 3: Patch docs sections listed above** (short; no rewrite of entire docs)

- [ ] **Step 4: Commit**

```bash
git commit -m "test(backend): cover stream ingest flywheel; sync stream docs"
```

---

## Spec Coverage Checklist

| Spec requirement | Task |
| :--- | :--- |
| RTSP / VIDEO_FILE / DEVICE sources | 4 |
| MJPEG live overlay | 5–6 |
| Timer + uncertainty window | 1, 5 |
| Tripwire geometry + direction + debounce | 1, 5–6 |
| HITL ingest invariant | 3, 7 |
| One active stream per project | 5 |
| Fourth project tab UI | 6 |
| Video upload/delete storage | 4 |
| Status poll / capture flash | 5–6 |
| VIDEO_FILE loop | 5 |
| Tests (unit/e2e) | 1–5, 7 |

## Self-Review Notes

- No TBD placeholders; confidence dual-mode explicitly out of scope (uncertainty only).
- Types consistent: `StreamTriggerConfig`, `StreamSource`, `IStreamRunner`, `IngestJob`.
- YOLO.track real inference may be heavy in CI — Task 5 mandates `IStreamRunner` fake seam for e2e; capture rules stay unit-tested without GPU.
