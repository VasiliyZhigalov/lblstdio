# Stream & Test Hub: live validation and conditional data harvesting

**Date:** 2026-09-15  
**Status:** approved (conversation); awaiting written-spec sign-off  
**Scope:** domain + application + infrastructure streaming runner + REST API + frontend Stream tab

## Problem

The platform can train YOLO and auto-label still images, but cannot:

1. **Validate** a trained model on a live video source without manually cutting/uploading frames.
2. **Harvest** only useful frames into the dataset (timer + uncertainty, tripwire), instead of dumping every frame.

Hooks already exist (`ImageSourceType.STREAM_INGEST`, `Image.stream_source_id`, `ModelVersion.is_active_for_stream`), but there is no `StreamSource`, runner, API, or UI.

## Goals

- Full Stream & Test Hub in one delivery: RTSP, local video file, webcam/DEVICE.
- Live MJPEG preview with boxes, tracks, and virtual tripwire overlay.
- Conditional capture: track-stability (ByteTrack N frames + avg conf + size variation); tripwire line crossing with direction + debounce.
- HITL ingest: clean frame → `STREAM_INGEST` / `REQUIRES_REVIEW` + `MODEL_PREDICTION` / `PENDING_REVIEW`.
- Fourth project tab: **Стрим и Сбор**.
- At most **one active stream per project**.

## Non-goals (v1)

- WebRTC / HLS.
- Multiple concurrent streams per project or multi-line tripwires.
- WebSocket push for capture events.
- Recording video clips (only still JPEG frames).
- Dual confidence modes (“all above threshold” vs uncertainty); v1 uses **uncertainty window only**.

## Decisions (from brainstorming)

| Topic | Choice |
| :--- | :--- |
| Scope | Full spec (sources + MJPEG + timer + tripwire + tab) |
| Concurrency | One active stream per project |
| Confidence filter | Uncertainty window only |
| Runtime architecture | Unified `OpenCVStreamRunner` (capture + track + triggers + overlay in one thread) |

## Architecture

### Approach: Unified Stream Runner

One background `threading.Thread` per running stream:

1. Read frame via `cv2.VideoCapture`.
2. `YOLO.track(frame, persist=True, tracker="bytetrack.yaml")`.
3. Evaluate tripwire and timer triggers.
4. On trigger: enqueue clean frame + detections for async ingest.
5. Draw overlay → JPEG → publish as `latest_jpeg` for MJPEG consumers.

`GET /live` does not run inference; it only streams the latest JPEG as `multipart/x-mixed-replace`.

### Layer map

| Layer | Additions |
| :--- | :--- |
| `domain/` | `StreamSource`, `StreamSourceType`, `TripwireDirection`, VO `StreamTriggerConfig`, line-crossing helpers |
| `application/` | `IStreamSourceRepository`, `IStreamRunner`; use cases for CRUD/upload, configure, start/stop, ingest |
| `infrastructure/` | SQLAlchemy table/repo, video file storage under `storage/projects/{id}/videos/`, `OpenCVStreamRunner` |
| `presentation/` | `stream_router.py`; frontend tab `streamHub.js` + tripwire overlay |

## Domain model

### `StreamSource`

- `id: UUID`, `project_id: UUID`
- `name: str`
- `source_type: StreamSourceType` — `RTSP` | `VIDEO_FILE` | `DEVICE`
- `source_uri: str` — RTSP URL, relative video path, or device index string (`"0"`)
- `is_active: bool` — whether the runner is (should be) running
- `model_version_id: UUID | None`
- `config: StreamTriggerConfig`
- `captured_frames_count: int`

### `StreamTriggerConfig`

- `track_stable_enabled: bool` (default `true`)
- `track_stable_min_frames: int` (default `12`) — continuous ByteTrack presence required
- `track_stable_max_size_variation: float` (default `0.35`) — max relative box-area span `max/min - 1`
- `track_stable_min_avg_conf: float` (default `0.75`, not exposed in UI)
- `track_stable_interval_seconds: float` (default `5.0`) — per-`track_id` gap between saves
- `tripwire_enabled: bool`
- `tripwire_line: tuple[float, float, float, float] | None` — normalized `(x1,y1,x2,y2)` in `[0,1]`
- `tripwire_classes: list[UUID]` — empty = all classes
- `tripwire_direction: TripwireDirection` — `ANY` | `FORWARD` | `BACKWARD`  
  (`FORWARD` = left→right / top→bottom relative to line normal; `BACKWARD` = opposite)
- `tripwire_debounce_seconds: float` (default `3.0`)
- `cooldown_seconds: float` (default `3.0`) — global gap for tripwire saves

### Invariants

1. **One active stream per project:** starting stream A stops any other active stream in the same project.
2. **HITL on ingest:** clean JPEG (no overlay) saved via file storage; `Image` with `source_type=STREAM_INGEST`, `status=REQUIRES_REVIEW`, `stream_source_id` set; annotations with `source=MODEL_PREDICTION`, `verification_status=PENDING_REVIEW`, `confidence` set.
3. **Track-stable capture:** for each `track_id`, require ≥ N continuous frames, mean confidence ≥ `track_stable_min_avg_conf`, and size variation ≤ `track_stable_max_size_variation`. On trigger, save the **best-confidence** frame from the window; then enforce per-track `track_stable_interval_seconds` before another save of the same id.
4. **Tripwire capture:** segment intersection of motion vector `(P_{t-1}, P_t)` with line `(A,B)`, optional `tripwire_classes` filter, direction filter, per-`track_id` debounce; track-stable gate is **not** required for tripwire (event-driven). Global cooldown still applies.
5. **VIDEO_FILE:** loop from start on EOF by default.

## Runtime details

### Ingest bridge

Runner thread must not hold the async SQLAlchemy session. Pattern:

- Thread pushes `(stream_id, jpeg_bytes, detections, reason)` onto a thread-safe queue.
- Async consumer (started with the app or on first `start`) calls `IngestStreamFrameUseCase` and increments `captured_frames_count`.

### MJPEG

```
yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
```

Delivery rate ~10–15 FPS from `latest_jpeg`; inference may be slower.

### Failure handling

- Missing/invalid model or `VideoCapture` open failure → `start` returns HTTP 400.
- RTSP disconnect → runner reconnects with exponential backoff; `/status` reports `reconnecting`.

### Capture UI flash

Frontend polls `GET /streams/{id}/status` ~1s; on `captured_count` increase → brief green border flash. No WebSocket in v1.

## REST API

```http
GET    /api/v1/projects/{project_id}/streams
POST   /api/v1/projects/{project_id}/streams/rtsp
POST   /api/v1/projects/{project_id}/streams/device
POST   /api/v1/projects/{project_id}/streams/upload-video
DELETE /api/v1/streams/{stream_id}

PUT    /api/v1/streams/{stream_id}/triggers
POST   /api/v1/streams/{stream_id}/start
POST   /api/v1/streams/{stream_id}/stop
GET    /api/v1/streams/{stream_id}/live
GET    /api/v1/streams/{stream_id}/status
```

`status` payload: `is_running`, `state` (`stopped`|`running`|`reconnecting`|`error`), `fps`, `captured_count`, `last_capture_at`, `error_message`.

## Frontend UI

- New tab button + `#tab-view-stream`; `projectTab = "stream"`.
- Layout: video pane (MJPEG `<img>` + transparent canvas for tripwire) | settings sidebar | bottom capture queue bar.
- Tools: Start / Stop / Draw line (click A, click B; drag endpoints).
- Source panel: RTSP URL form, DEVICE index, video upload + list (play/delete).
- Triggers: uncertainty min/max, timer toggle+interval, tripwire toggle+classes+direction.
- Persist triggers via `PUT /triggers` on control change / line mouseup (not every mousemove).
- Bottom bar: captured count + jump to Annotate filtered to stream-ingested / `REQUIRES_REVIEW`.

Visual language: existing dark zinc / Tailwind chrome; tripwire stroke cyan or bright yellow with circular endpoints.

## Testing

| Level | Coverage |
| :--- | :--- |
| Unit | Line-segment intersection, direction, debounce; `StreamTriggerConfig` validation; `IngestStreamFrameUseCase` HITL statuses |
| Unit/integration | Start stops other project stream; video upload/delete storage+DB |
| E2E | Fixture `VIDEO_FILE` → start → `status.is_running` → `/live` is multipart → forced/trigger ingest creates `STREAM_INGEST` image |

## Files (expected)

**Backend**

- `domain/entities/stream_source.py`, `domain/enums.py` (extend), `domain/services/tripwire.py` (or VO methods)
- `application/ports/repositories/stream_source_repository.py`
- `application/ports/services/stream_runner.py`
- `application/use_cases/streaming/*`
- `infrastructure/db/tables.py`, `session.py` migrations/bootstrap, repositories
- `infrastructure/streaming/opencv_stream_runner.py`
- `presentation/api/v1/stream_router.py`, schemas, dependencies

**Frontend**

- `index.html` tab chrome + view shell
- `js/components/streamHub.js`, tripwire overlay helpers
- `js/api.js` stream endpoints
- `js/app.js` / `router.js` tab wiring

## Alignment with existing docs

This design **supersedes** the thinner Phase 5 sketch in `docs/plan.md` / `ProcessStreamFrameUseCase` in `docs/back.md` for product behavior: live MJPEG hub + tripwire + full tab, while keeping the same HITL ingest invariant and uncertainty-based timer sampling. Follow-up doc sync of `back.md` / `model.md` / `front.md` can happen after implementation.
