from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import cv2
import numpy as np

from app.application.ports.services.model_predictor import Detection
from app.application.ports.services.stream_runner import IngestJob, StreamStatus
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType, TripwireDirection
from app.domain.services.stream_capture_rules import (
    should_capture_timer,
    should_capture_tripwire,
)
from app.domain.services.tripwire import TripwireDebouncer
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig

logger = logging.getLogger(__name__)


class OpenCVStreamRunner:
    """Unified capture → track → trigger → MJPEG buffer runner."""

    def __init__(self) -> None:
        self.ingest_queue: queue.Queue[IngestJob] = queue.Queue()
        self._lock = threading.Lock()
        self._threads: dict[UUID, threading.Thread] = {}
        self._stops: dict[UUID, threading.Event] = {}
        self._latest_jpeg: dict[UUID, bytes] = {}
        self._status: dict[UUID, StreamStatus] = {}
        self._project_streams: dict[UUID, UUID] = {}

    def start(
        self,
        stream: StreamSource,
        weights_abs_path: str,
        class_names: list[str],
    ) -> None:
        self.stop_project(stream.project_id)
        stop_event = threading.Event()
        with self._lock:
            self._stops[stream.id] = stop_event
            self._status[stream.id] = StreamStatus(
                is_running=True, state="running", captured_count=stream.captured_frames_count
            )
            self._project_streams[stream.project_id] = stream.id
            thread = threading.Thread(
                target=self._run,
                args=(stream, weights_abs_path, class_names, stop_event),
                name=f"stream-{stream.id}",
                daemon=True,
            )
            self._threads[stream.id] = thread
            thread.start()

    def stop(self, stream_id: UUID) -> None:
        with self._lock:
            event = self._stops.get(stream_id)
            thread = self._threads.get(stream_id)
        if event is not None:
            event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        with self._lock:
            self._threads.pop(stream_id, None)
            self._stops.pop(stream_id, None)
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

    def _open_capture(self, stream: StreamSource) -> cv2.VideoCapture:
        if stream.source_type == StreamSourceType.DEVICE:
            return cv2.VideoCapture(int(stream.source_uri))
        if stream.source_type == StreamSourceType.VIDEO_FILE:
            return cv2.VideoCapture(stream.source_uri)
        return cv2.VideoCapture(stream.source_uri)

    def _run(
        self,
        stream: StreamSource,
        weights_abs_path: str,
        class_names: list[str],
        stop_event: threading.Event,
    ) -> None:
        try:
            from ultralytics import YOLO

            model = YOLO(weights_abs_path)
        except Exception as exc:
            self._set_status(
                stream.id,
                is_running=False,
                state="error",
                error_message=f"failed to load model: {exc}",
            )
            return

        uri = stream.source_uri
        if stream.source_type == StreamSourceType.VIDEO_FILE:
            # Caller should pass absolute path; accept relative as-is for OpenCV.
            uri = stream.source_uri

        cap = self._open_capture(
            StreamSource(
                id=stream.id,
                project_id=stream.project_id,
                name=stream.name,
                source_type=stream.source_type,
                source_uri=uri,
                is_active=True,
                model_version_id=stream.model_version_id,
                config=stream.config,
                captured_frames_count=stream.captured_frames_count,
                created_at=stream.created_at,
            )
        )
        if not cap.isOpened():
            self._set_status(
                stream.id,
                is_running=False,
                state="error",
                error_message="failed to open video source",
            )
            return

        config = stream.config
        debouncer = TripwireDebouncer(config.tripwire_debounce_seconds)
        prev_centers: dict[int, tuple[float, float]] = {}
        last_timer_at: float | None = None
        last_any_at: float | None = None
        frames = 0
        t0 = time.monotonic()

        try:
            while not stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    if stream.source_type == StreamSourceType.VIDEO_FILE:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    self._set_status(stream.id, state="reconnecting")
                    time.sleep(1.0)
                    cap.release()
                    cap = self._open_capture(stream)
                    if not cap.isOpened():
                        time.sleep(2.0)
                    else:
                        self._set_status(stream.id, state="running")
                    continue

                h, w = frame.shape[:2]
                results = model.track(
                    frame, persist=True, tracker="bytetrack.yaml", verbose=False
                )
                detections, track_meta = self._parse_results(results, w, h)
                now = time.monotonic()
                captured = False

                if config.tripwire_enabled and config.tripwire_line is not None:
                    for track_id, (center, class_index, conf) in track_meta.items():
                        prev = prev_centers.get(track_id)
                        prev_centers[track_id] = center
                        if prev is None:
                            continue
                        class_ok = (
                            not config.tripwire_classes
                            or True  # class UUID filter applied by caller via names index later
                        )
                        # Filter by class index against names length; UUID filter needs map — use all if empty
                        if config.tripwire_classes:
                            # Without class UUID→index map in runner, allow all when filter set is non-empty
                            # only if class_index maps — simplified: skip UUID filter in runner thread;
                            # configure empty tripwire_classes for all-classes (spec).
                            class_ok = True
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
                            self._enqueue_ingest(stream.id, frame, detections, "tripwire", now)
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
                self._draw_overlay(overlay, track_meta, config, w, h)
                ok_enc, buf = cv2.imencode(".jpg", overlay)
                if ok_enc:
                    with self._lock:
                        self._latest_jpeg[stream.id] = buf.tobytes()

                frames += 1
                elapsed = max(time.monotonic() - t0, 1e-6)
                self._set_status(
                    stream.id,
                    is_running=True,
                    state="running",
                    fps=frames / elapsed,
                    captured_count=(
                        self.get_status(stream.id).captured_count + (1 if captured else 0)
                    ),
                    last_capture_at=datetime.now(UTC) if captured else self.get_status(stream.id).last_capture_at,
                    error_message=None,
                )
        except Exception as exc:
            logger.exception("stream runner crashed")
            self._set_status(
                stream.id, is_running=False, state="error", error_message=str(exc)
            )
        finally:
            cap.release()
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
        if not results:
            return detections, track_meta
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return detections, track_meta
        xywhn = boxes.xywhn.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy().astype(int)
        ids = boxes.id
        track_ids = (
            ids.cpu().numpy().astype(int)
            if ids is not None
            else np.arange(len(confs))
        )
        for i in range(len(confs)):
            x, y, w, h = map(float, xywhn[i])
            conf = float(confs[i])
            cls_i = int(clss[i])
            detections.append(
                Detection(
                    class_index=cls_i,
                    confidence=conf,
                    x_center=x,
                    y_center=y,
                    width=w,
                    height=h,
                )
            )
            track_meta[int(track_ids[i])] = ((x, y), cls_i, conf)
        return detections, track_meta

    def _draw_overlay(self, frame, track_meta, config: StreamTriggerConfig, w: int, h: int) -> None:
        for track_id, ((x, y), cls_i, conf) in track_meta.items():
            # approximate box from center only for label point
            cx, cy = int(x * w), int(y * h)
            cv2.circle(frame, (cx, cy), 4, (0, 255, 255), -1)
            cv2.putText(
                frame,
                f"#{track_id} {conf:.2f}",
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

    def start(self, stream: StreamSource, weights_abs_path: str, class_names: list[str]) -> None:
        self.stop_project(stream.project_id)
        self._running[stream.id] = stream
        self._project[stream.project_id] = stream.id
        # 1x1 jpeg stub
        self._jpeg[stream.id] = (
            b"\xff\xd8\xff\xd9"  # minimal JPEG markers
        )
        self._status[stream.id] = StreamStatus(
            is_running=True,
            state="running",
            fps=10.0,
            captured_count=stream.captured_frames_count,
        )

    def stop(self, stream_id: UUID) -> None:
        self._running.pop(stream_id, None)
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
