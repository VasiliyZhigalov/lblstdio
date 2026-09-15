from __future__ import annotations

import asyncio
import logging
import queue

from app.application.ports.services.stream_runner import IngestJob
from app.application.use_cases.streaming.ingest_stream_frame import IngestStreamFrameUseCase
from app.infrastructure.db.repositories.annotation_repository import (
    SqliteAnnotationRepository,
)
from app.infrastructure.db.repositories.class_repository import SqliteClassRepository
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.stream_source_repository import (
    SqliteStreamSourceRepository,
)
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.storage.local_storage import LocalFileStorage
from app.infrastructure.storage.pillow_metadata import PillowMetadataReader

logger = logging.getLogger(__name__)


class StreamIngestConsumer:
    def __init__(self, session_factory, storage: LocalFileStorage, runner) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._runner = runner
        self._task: asyncio.Task | None = None
        self._metadata = PillowMetadataReader()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="stream-ingest-consumer")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                job: IngestJob = await asyncio.to_thread(
                    self._runner.ingest_queue.get, True, 0.5
                )
            except queue.Empty:
                continue
            try:
                await self._handle(job)
            except Exception:
                logger.exception("failed to ingest stream frame")

    async def _handle(self, job: IngestJob) -> None:
        async with self._session_factory() as session:
            uow = SqlAlchemyUnitOfWork(session)
            use_case = IngestStreamFrameUseCase(
                streams=SqliteStreamSourceRepository(session),
                images=SqliteImageRepository(session),
                annotations=SqliteAnnotationRepository(session),
                classes=SqliteClassRepository(session),
                storage=self._storage,
                metadata=self._metadata,
                uow=uow,
            )
            await use_case.execute(
                job.stream_id, job.jpeg_bytes, job.detections, reason=job.reason
            )
