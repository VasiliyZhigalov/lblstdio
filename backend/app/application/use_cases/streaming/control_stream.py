from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from uuid import UUID

from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.application.ports.repositories.stream_source_repository import (
    IStreamSourceRepository,
)
from app.application.ports.services.stream_runner import IStreamRunner, StreamStatus
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.services.image_folder import (
    describe_folder_access_error,
    list_image_files,
)
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig


def allowed_class_indices_for(
    config: StreamTriggerConfig,
    classes: list,
) -> frozenset[int] | None:
    """Map tripwire class UUIDs to YOLO indices.

    None means every class. Stale or foreign ids are rejected instead of
    being dropped into an empty filter.
    """
    if not config.tripwire_classes:
        return None
    by_id = {item.id: item.index_id for item in classes}
    unknown = [cid for cid in config.tripwire_classes if cid not in by_id]
    if unknown:
        joined = ", ".join(str(cid) for cid in unknown)
        raise DomainValidationException(f"unknown class ids: {joined}")
    return frozenset(by_id[cid] for cid in config.tripwire_classes)


class StartStreamUseCase:
    def __init__(
        self,
        streams: IStreamSourceRepository,
        models: IModelVersionRepository,
        classes: IClassRepository,
        storage: IFileStorage,
        runner: IStreamRunner,
        uow: IUnitOfWork,
    ) -> None:
        self._streams = streams
        self._models = models
        self._classes = classes
        self._storage = storage
        self._runner = runner
        self._uow = uow

    async def execute(self, stream_id: UUID) -> StreamSource:
        stream = await self._streams.get_by_id(stream_id)
        if stream is None:
            raise ResourceNotFoundException(f"stream source {stream_id} not found")
        launch = await self._prepare_launch(stream)

        if stream.is_active:
            await asyncio.to_thread(self._runner.stop, stream.id)

        await self._start_and_wait(stream, launch)

        stream.activate()
        await self._streams.update(stream)
        await self._uow.commit()
        return stream

    async def _prepare_launch(
        self, stream: StreamSource
    ) -> tuple[str, str | None, frozenset[int] | None]:
        if stream.model_version_id is None and not stream.config.timer_enabled:
            raise DomainValidationException("stream has no model_version_id configured")
        weights_abs = None
        if stream.model_version_id is not None:
            model = await self._models.get_by_id(stream.model_version_id)
            if model is None or model.project_id != stream.project_id:
                raise ResourceNotFoundException(
                    f"model version {stream.model_version_id} not found"
                )
            try:
                weights_abs = self._storage.get_absolute_path(model.weights_path)
            except Exception as exc:
                raise DomainValidationException(
                    f"weights not found: {model.weights_path}"
                ) from exc

        source_uri = stream.source_uri
        if stream.source_type == StreamSourceType.VIDEO_FILE:
            try:
                source_uri = self._storage.get_absolute_path(stream.source_uri)
            except Exception as exc:
                raise DomainValidationException(
                    f"video file not found: {stream.source_uri}"
                ) from exc
        elif stream.source_type == StreamSourceType.IMAGE_FOLDER:
            folder = Path(source_uri)
            try:
                accessible = folder.is_dir()
            except OSError as exc:
                raise DomainValidationException(
                    describe_folder_access_error(exc, source_uri)
                ) from exc
            if not accessible:
                raise DomainValidationException(f"Папка не найдена: {source_uri}")
            if not list_image_files(folder):
                raise DomainValidationException(
                    "В папке нет изображений jpg, png или webp"
                )

        project_classes = await self._classes.list_by_project(stream.project_id)
        if stream.model_version_id is not None:
            mapping = (model.class_metadata or {}).get("class_mapping")
            if mapping:
                by_id = {str(c.id): c.index_id for c in project_classes}
                if any(cid not in by_id for cid in mapping.values()):
                    raise DomainValidationException("Словарь модели ссылается на удалённые классы проекта")
                stream.class_index_mapping = {int(i): by_id[cid] for i, cid in mapping.items() if cid in by_id}
        allowed = allowed_class_indices_for(stream.config, project_classes)
        return source_uri, weights_abs, allowed

    async def _start_and_wait(
        self,
        stream: StreamSource,
        launch: tuple[str, str | None, frozenset[int] | None],
    ) -> None:
        source_uri, weights_abs, allowed = launch
        runner_stream = StreamSource(
            id=stream.id,
            project_id=stream.project_id,
            name=stream.name,
            source_type=stream.source_type,
            source_uri=source_uri,
            is_active=False,
            model_version_id=stream.model_version_id,
            config=stream.config,
            captured_frames_count=stream.captured_frames_count,
            created_at=stream.created_at,
            class_index_mapping=stream.class_index_mapping,
        )
        await asyncio.to_thread(
            partial(
                self._runner.start,
                runner_stream,
                weights_abs,
                allowed_class_indices=allowed,
            )
        )
        status = await asyncio.to_thread(self._runner.wait_until_ready, stream.id, 45.0)
        if status.state in {"scheduled", "waiting_gpu"}: return
        if status.state != "running" or not status.is_running:
            await asyncio.to_thread(self._runner.stop, stream.id)
            message = status.error_message or f"stream failed to start ({status.state})"
            raise DomainValidationException(message)

class StopStreamUseCase:
    def __init__(
        self,
        streams: IStreamSourceRepository,
        runner: IStreamRunner,
        uow: IUnitOfWork,
    ) -> None:
        self._streams = streams
        self._runner = runner
        self._uow = uow

    async def execute(self, stream_id: UUID) -> StreamSource:
        stream = await self._streams.get_by_id(stream_id)
        if stream is None:
            raise ResourceNotFoundException(f"stream source {stream_id} not found")
        await asyncio.to_thread(self._runner.stop, stream_id)
        stream.deactivate()
        await self._streams.update(stream)
        await self._uow.commit()
        return stream


class GetStreamStatusUseCase:
    def __init__(
        self,
        streams: IStreamSourceRepository,
        runner: IStreamRunner,
    ) -> None:
        self._streams = streams
        self._runner = runner

    async def execute(self, stream_id: UUID) -> StreamStatus:
        stream = await self._streams.get_by_id(stream_id)
        if stream is None:
            raise ResourceNotFoundException(f"stream source {stream_id} not found")
        status = self._runner.get_status(stream_id)
        return StreamStatus(
            is_running=status.is_running,
            state=status.state,
            fps=status.fps,
            captured_count=stream.captured_frames_count,
            last_capture_at=status.last_capture_at,
            error_message=status.error_message,
        )
