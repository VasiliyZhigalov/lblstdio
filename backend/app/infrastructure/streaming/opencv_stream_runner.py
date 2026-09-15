from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import UTC, datetime
from uuid import UUID

import cv2
import numpy as np

from app.application.ports.services.model_predictor import Detection
from app.application.ports.services.stream_runner import IngestJob, StreamStatus
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType
from app.domain.services.stream_capture_rules import (
    should_capture_timer,
    should_capture_tripwire,
)
from app.domain.services.tripwire import TripwireDebouncer
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig

logger = logging.getLogger(__name__)

_VIDEO_FAIL_LIMIT = 30
_VIDEO_FAIL_SLEEP_S = 0.05


class OpenCVStreamRunner:
    """Unified capture → track → trigger → MJPEG buffer runner."""

    def __init__(self) -> None:
        self.ingest_queue: queue.Queue[IngestJob] = queue.Queue()
        self._lock = threading.Lock()
        self._threads: dict[UUID, threading.Thread] = {}
        self._stops: dict[UUID, threading.Event] = {}
        self._ready: dict[UUID, threading.Event] = {}
        self._latest_jpeg: dict[UUID, bytes] = {}
        self._status: dict[UUID, StreamStatus] = {}
        self._project_streams: dict[UUID, UUID] = {}
        self._live_config: dict[UUID, StreamTriggerConfig] = {}
        self._allowed_classes: dict[UUID, frozenset[int] | None] = {}

    def start(
        self,
        stream: StreamSource,
        weights_abs_path: str,
        *,
        allowed_class_indices: frozenset[int] | None = None,
    ) -> None:
        self.stop_project(stream.project_id)
        stop_event = threading.Event()
        ready_event = threading.Event()
        with self._lock:
            self._stops[stream.id] = stop_event
            self._ready[stream.id] = ready_event
            self._live_config[stream.id] = stream.config
            self._allowed_classes[stream.id] = allowed_class_indices
            self._status[stream.id] = StreamStatus(
                is_running=False,
                state="starting",
                captured_count=stream.captured_frames_count,
            )
            self._project_streams[stream.project_id] = stream.id
            thread = threading.Thread(
                target=self._run,
                args=(stream, weights_abs_path, stop_event, ready_event),
                name=f"stream-{stream.id}",
                daemon=True,
            )
            self._threads[stream.id] = thread
            thread.start()

    def wait_until_ready(self, stream_id: UUID, timeout: float = 30.0) -> StreamStatus:
        with self._lock:
            ready = self._ready.get(stream_id)
        if ready is None:
            return self.get_status(stream_id)
        ready.wait(timeout=timeout)
        return self.get_status(stream_id)

    def update_triggers(
        self,
        stream_id: UUID,
        config: StreamTriggerConfig,
        *,
        allowed_class_indices: frozenset[int] | None = None,
    ) -> None:
        with self._lock:
            if stream_id not in self._status:
                return
            self._live_config[stream_id] = config
            self._allowed_classes[stream_id] = allowed_class_indices

    def stop(self, stream_id: UUID) -> None:
        with self._lock:
            event = self._stops.get(stream_id)
            thread = self._threads.get(stream_id)
            ready = self._ready.get(stream_id)
        if event is not None:
            event.set()
        if ready is not None:
            ready.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        with self._lock:
            self._threads.pop(stream_id, None)
            self._stops.pop(stream_id, None)
            self._ready.pop(stream_id, None)
            self._live_config.pop(stream_id, None)
            self._allowed_classes.pop(stream_id, None)
            status = self._status.get(stream_id)
            if status is not None:
                self._status[stream_id] = StreamStatus(
                    is_running=False,
                    state="stopped",
                    fps=status.fps,
                    captured_count=status.captured_count,
                    last_capture_at=status.last_capture_at,
                    error_message=status.error_message,
                )
            for project_id, sid in list(self._project_streams.items()):
                if sid == stream_id:
                    self._project_streams.pop(project_id, None)

    def stop_project(self, project_id: UUID) -> None:
        with self._lock:
            stream_id = self._project_streams.get(project_id)
        if stream_id is not None:
            self.stop(stream_id)

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self._threads.keys())
        for stream_id in ids:
            self.stop(stream_id)

    def get_status(self, stream_id: UUID) -> StreamStatus:
        with self._lock:
            return self._status.get(
                stream_id,
                StreamStatus(is_running=False, state="stopped"),
            )

    def latest_jpeg(self, stream_id: UUID) -> bytes | None:
        with self._lock:
            return self._latest_jpeg.get(stream_id)

    def push_ingest_for_tests(self, job: IngestJob) -> None:
        self.ingest_queue.put(job)

    def _get_live(self, stream_id: UUID) -> tuple[StreamTriggerConfig, frozenset[int] | None]:
        with self._lock:
            config = self._live_config.get(stream_id)
            allowed = self._allowed_classes.get(stream_id)
        if config is None:
            raise RuntimeError(f"no live config for stream {stream_id}")
        return config, allowed

    def _set_status(self, stream_id: UUID, **kwargs) -> None:
        with self._lock:
            current = self._status.get(
                stream_id, StreamStatus(is_running=False, state="stopped")
            )
            data = {
                "is_running": current.is_running,
                "state": current.state,
                "fps": current.fps,
                "captured_count": current.captured_count,
                "last_capture_at": current.last_capture_at,
                "error_message": current.error_message,
            }
            data.update(kwargs)
            self._status[stream_id] = StreamStatus(**data)

    def _fail_ready(self, stream_id: UUID, ready: threading.Event, message: str) -> None:
        self._set_status(
            stream_id,
            is_running=False,
            state="error",
            error_message=message,
        )
        ready.set()

    def _open_capture(self, stream: StreamSource) -> cv2.VideoCapture:
        if stream.source_type == StreamSourceType.DEVICE:
            return cv2.VideoCapture(int(stream.source_uri))
        return cv2.VideoCapture(stream.source_uri)

    def _run(
        self,
        stream: StreamSource,
        weights_abs_path: str,
        stop_event: threading.Event,
        ready_event: threading.Event,
    ) -> None:
        try:
            from ultralytics import YOLO

            model = YOLO(weights_abs_path)
        except Exception as exc:
            self._fail_ready(stream.id, ready_event, f"failed to load model: {exc}")
            return

        cap = self._open_capture(stream)
        if not cap.isOpened():
            self._fail_ready(stream.id, ready_event, "failed to open video source")
            return

        debouncer = TripwireDebouncer(stream.config.tripwire_debounce_seconds)
        prev_centers: dict[int, tuple[float, float]] = {}
        last_timer_at: float | None = None
        last_any_at: float | None = None
        frames = 0
        t0 = time.monotonic()
        video_fail_streak = 0
        marked_ready = False

        try:
            while not stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    if stream.source_type == StreamSourceType.VIDEO_FILE:
                        video_fail_streak += 1
                        if video_fail_streak >= _VIDEO_FAIL_LIMIT:
                            self._fail_ready(
                                stream.id,
                                ready_event,
                                "video file unreadable (repeated read failures)",
                            )
                            break
                        time.sleep(_VIDEO_FAIL_SLEEP_S)
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    video_fail_streak = 0
                    self._set_status(stream.id, state="reconnecting")
                    time.sleep(1.0)
                    cap.release()
                    cap = self._open_capture(stream)
                    if not cap.isOpened():
                        time.sleep(2.0)
                    else:
                        self._set_status(stream.id, state="running", is_running=True)
                    continue

                video_fail_streak = 0
                h, w = frame.shape[:2]
                results = model.track(
                    frame, persist=True, tracker="bytetrack.yaml", verbose=False
                )
                detections, track_meta, box_xyxy = self._parse_results(results, w, h)
                now = time.monotonic()
                config, allowed = self._get_live(stream.id)
                captured = False

                if config.tripwire_enabled and config.tripwire_line is not None:
                    for track_id, (center, class_index, conf) in track_meta.items():
                        prev = prev_centers.get(track_id)
                        prev_centers[track_id] = center
                        if prev is None:
                            continue
                        class_ok = allowed is None or class_index in allowed
                        if should_capture_tripwire(
                            track_id=track_id,
                            p_prev=prev,
                            p_curr=center,
                            line=config.tripwire_line,
                            direction=config.tripwire_direction,
                            classes_ok=class_ok,
                            debouncer=debouncer,
                            now=now,
                            last_any_at=last_any_at,
                            cooldown=config.cooldown_seconds,
                        ):
                            self._enqueue_ingest(
                                stream.id, frame, detections, "tripwire", now
                            )
                            last_any_at = now
                            captured = True
                            break

                if (
                    not captured
                    and config.timer_enabled
                    and should_capture_timer(
                        now=now,
                        last_timer_at=last_timer_at,
                        last_any_at=last_any_at,
                        interval=config.timer_interval_seconds,
                        cooldown=config.cooldown_seconds,
                        confidences=[d.confidence for d in detections],
                        unc_range=config.uncertainty_range,
                    )
                ):
                    self._enqueue_ingest(stream.id, frame, detections, "timer", now)
                    last_timer_at = now
                    last_any_at = now
                    captured = True

                overlay = frame.copy()
                self._draw_overlay(overlay, track_meta, box_xyxy, config, w, h)
                ok_enc, buf = cv2.imencode(".jpg", overlay)
                if ok_enc:
                    with self._lock:
                        self._latest_jpeg[stream.id] = buf.tobytes()

                frames += 1
                elapsed = max(time.monotonic() - t0, 1e-6)
                status_kwargs = {
                    "is_running": True,
                    "state": "running",
                    "fps": frames / elapsed,
                    "error_message": None,
                }
                if captured:
                    status_kwargs["last_capture_at"] = datetime.now(UTC)
                self._set_status(stream.id, **status_kwargs)

                if not marked_ready:
                    marked_ready = True
                    ready_event.set()
        except Exception as exc:
            logger.exception("stream runner crashed")
            self._fail_ready(stream.id, ready_event, str(exc))
        finally:
            cap.release()
            if not ready_event.is_set():
                ready_event.set()
            status = self.get_status(stream.id)
            if status.state != "error":
                self._set_status(stream.id, is_running=False, state="stopped")

    def _enqueue_ingest(
        self,
        stream_id: UUID,
        frame,
        detections: list[Detection],
        reason: str,
        now: float,
    ) -> None:
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            return
        self.ingest_queue.put(
            IngestJob(
                stream_id=stream_id,
                jpeg_bytes=buf.tobytes(),
                detections=list(detections),
                reason=reason,
                captured_at=now,
            )
        )

    def _parse_results(self, results, width: int, height: int):
        detections: list[Detection] = []
        track_meta: dict[int, tuple[tuple[float, float], int, float]] = {}
        box_xyxy: dict[int, tuple[int, int, int, int]] = {}
        if not results:
            return detections, track_meta, box_xyxy
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return detections, track_meta, box_xyxy
        xywhn = boxes.xywhn.cpu().numpy()
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy().astype(int)
        ids = boxes.id
        track_ids = (
            ids.cpu().numpy().astype(int)
            if ids is not None
            else np.arange(len(confs))
        )
        for i in range(len(confs)):
            x, y, bw, bh = map(float, xywhn[i])
            conf = float(confs[i])
            cls_i = int(clss[i])
            tid = int(track_ids[i])
            detections.append(
                Detection(
                    class_index=cls_i,
                    confidence=conf,
                    x_center=x,
                    y_center=y,
                    width=bw,
                    height=bh,
                )
            )
            track_meta[tid] = ((x, y), cls_i, conf)
            x1, y1, x2, y2 = map(int, xyxy[i])
            box_xyxy[tid] = (x1, y1, x2, y2)
        return detections, track_meta, box_xyxy

    def _draw_overlay(
        self,
        frame,
        track_meta,
        box_xyxy: dict[int, tuple[int, int, int, int]],
        config: StreamTriggerConfig,
        w: int,
        h: int,
    ) -> None:
        for track_id, ((x, y), cls_i, conf) in track_meta.items():
            if track_id in box_xyxy:
                x1, y1, x2, y2 = box_xyxy[track_id]
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
            cx, cy = int(x * w), int(y * h)
            cv2.putText(
                frame,
                f"#{track_id} cls{cls_i} {conf:.2f}",
                (cx + 6, cy - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )
        if config.tripwire_line is not None:
            x1, y1, x2, y2 = config.tripwire_line
            p1 = (int(x1 * w), int(y1 * h))
            p2 = (int(x2 * w), int(y2 * h))
            cv2.line(frame, p1, p2, (255, 255, 0), 2)
            cv2.circle(frame, p1, 6, (255, 255, 0), -1)
            cv2.circle(frame, p2, 6, (255, 255, 0), -1)


class FakeStreamRunner:
    """In-memory runner for API tests without OpenCV/YOLO."""

    def __init__(self) -> None:
        self.ingest_queue: queue.Queue[IngestJob] = queue.Queue()
        self._running: dict[UUID, StreamSource] = {}
        self._project: dict[UUID, UUID] = {}
        self._jpeg: dict[UUID, bytes] = {}
        self._status: dict[UUID, StreamStatus] = {}
        self._live_config: dict[UUID, StreamTriggerConfig] = {}
        self._allowed: dict[UUID, frozenset[int] | None] = {}
        self.fail_start_message: str | None = None

    def start(
        self,
        stream: StreamSource,
        weights_abs_path: str,
        *,
        allowed_class_indices: frozenset[int] | None = None,
    ) -> None:
        self.stop_project(stream.project_id)
        if self.fail_start_message:
            self._status[stream.id] = StreamStatus(
                is_running=False,
                state="error",
                error_message=self.fail_start_message,
            )
            return
        self._running[stream.id] = stream
        self._project[stream.project_id] = stream.id
        self._jpeg[stream.id] = b"\xff\xd8\xff\xd9"
        self._live_config[stream.id] = stream.config
        self._allowed[stream.id] = allowed_class_indices
        self._status[stream.id] = StreamStatus(
            is_running=True,
            state="running",
            fps=10.0,
            captured_count=stream.captured_frames_count,
        )

    def wait_until_ready(self, stream_id: UUID, timeout: float = 30.0) -> StreamStatus:
        return self.get_status(stream_id)

    def update_triggers(
        self,
        stream_id: UUID,
        config: StreamTriggerConfig,
        *,
        allowed_class_indices: frozenset[int] | None = None,
    ) -> None:
        if stream_id in self._status:
            self._live_config[stream_id] = config
            self._allowed[stream_id] = allowed_class_indices

    def stop(self, stream_id: UUID) -> None:
        self._running.pop(stream_id, None)
        self._live_config.pop(stream_id, None)
        self._allowed.pop(stream_id, None)
        for pid, sid in list(self._project.items()):
            if sid == stream_id:
                self._project.pop(pid, None)
        prev = self._status.get(stream_id)
        self._status[stream_id] = StreamStatus(
            is_running=False,
            state="stopped",
            fps=prev.fps if prev else 0.0,
            captured_count=prev.captured_count if prev else 0,
            last_capture_at=prev.last_capture_at if prev else None,
            error_message=prev.error_message if prev else None,
        )

    def stop_project(self, project_id: UUID) -> None:
        sid = self._project.get(project_id)
        if sid:
            self.stop(sid)

    def stop_all(self) -> None:
        for sid in list(self._running.keys()):
            self.stop(sid)

    def get_status(self, stream_id: UUID) -> StreamStatus:
        return self._status.get(
            stream_id, StreamStatus(is_running=False, state="stopped")
        )

    def latest_jpeg(self, stream_id: UUID) -> bytes | None:
        return self._jpeg.get(stream_id)

    def push_ingest_for_tests(self, job: IngestJob) -> None:
        self.ingest_queue.put(job)
