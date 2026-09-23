from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.model_version_repository import (
    IModelVersionRepository,
)
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.repositories.stream_source_repository import (
    IStreamSourceRepository,
)
from app.application.ports.services.stream_runner import IStreamRunner
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.application.use_cases.streaming.control_stream import allowed_class_indices_for
from app.domain.entities.stream_source import StreamSource
from app.domain.enums import StreamSourceType
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.services.image_folder import list_image_files
from app.domain.services.rtsp_url import validate_rtsp_url
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig

_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
_MAX_VIDEO_BYTES = 500 * 1024 * 1024


class _KeepModel:
    """Sentinel: configure_triggers leaves model_version_id unchanged."""


_KEEP_MODEL = _KeepModel()


class ManageStreamSourceUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        streams: IStreamSourceRepository,
        models: IModelVersionRepository,
        storage: IFileStorage,
        uow: IUnitOfWork,
        *,
        classes: IClassRepository | None = None,
        runner: IStreamRunner | None = None,
    ) -> None:
        self._projects = projects
        self._streams = streams
        self._models = models
        self._storage = storage
        self._uow = uow
        self._classes = classes
        self._runner = runner

    async def list_by_project(self, project_id: UUID) -> list[StreamSource]:
        await self._require_project(project_id)
        return await self._streams.list_by_project(project_id)

    async def create_rtsp(
        self, project_id: UUID, name: str, rtsp_url: str
    ) -> StreamSource:
        await self._require_project(project_id)
        url = validate_rtsp_url(rtsp_url)
        stream = StreamSource.create(
            project_id=project_id,
            name=name,
            source_type=StreamSourceType.RTSP,
            source_uri=url,
        )
        await self._streams.add(stream)
        await self._uow.commit()
        return stream

    async def create_device(
        self, project_id: UUID, name: str, device_index: int
    ) -> StreamSource:
        await self._require_project(project_id)
        if device_index < 0:
            raise DomainValidationException("device_index must be >= 0")
        stream = StreamSource.create(
            project_id=project_id,
            name=name,
            source_type=StreamSourceType.DEVICE,
            source_uri=str(device_index),
        )
        await self._streams.add(stream)
        await self._uow.commit()
        return stream

    async def create_image_folder(
        self, project_id: UUID, name: str, folder_path: str
    ) -> StreamSource:
        await self._require_project(project_id)
        raw = folder_path.strip().strip('"').strip("'")
        if not raw:
            raise DomainValidationException("Укажите путь к папке")
        try:
            resolved = Path(raw).expanduser().resolve(strict=True)
        except OSError as exc:
            raise DomainValidationException(f"Папка не найдена: {raw}") from exc
        if not resolved.is_dir():
            raise DomainValidationException("Укажите путь к папке, а не к файлу")
        if not list_image_files(resolved):
            raise DomainValidationException(
                "В папке нет изображений jpg, png или webp"
            )
        stream = StreamSource.create(
            project_id=project_id,
            name=name,
            source_type=StreamSourceType.IMAGE_FOLDER,
            source_uri=str(resolved),
        )
        await self._streams.add(stream)
        await self._uow.commit()
        return stream

    async def upload_video(
        self,
        project_id: UUID,
        name: str,
        filename: str,
        data: bytes,
    ) -> StreamSource:
        await self._require_project(project_id)
        ext = PurePosixPath(filename).suffix.lower()
        if ext not in _VIDEO_EXTENSIONS:
            raise DomainValidationException(
                f"unsupported video format {ext!r}; allowed: {sorted(_VIDEO_EXTENSIONS)}"
            )
        if not data:
            raise DomainValidationException("video file is empty")
        if len(data) > _MAX_VIDEO_BYTES:
            raise DomainValidationException(
                f"video file exceeds {_MAX_VIDEO_BYTES // (1024 * 1024)} MB limit"
            )
        video_id = uuid4()
        relative_dir = f"projects/{project_id}/videos"
        stored_name = f"{video_id}{ext}"
        relative_path = await self._storage.save(relative_dir, stored_name, data)
        stream = StreamSource.create(
            project_id=project_id,
            name=name or PurePosixPath(filename).stem,
            source_type=StreamSourceType.VIDEO_FILE,
            source_uri=relative_path,
        )
        try:
            await self._streams.add(stream)
            await self._uow.commit()
        except Exception:
            await self._storage.delete(relative_path)
            raise
        return stream

    async def configure_triggers(
        self,
        stream_id: UUID,
        config: StreamTriggerConfig,
        model_version_id: UUID | None | _KeepModel = _KEEP_MODEL,
    ) -> StreamSource:
        stream = await self._require_stream(stream_id)
        allowed = await self._allowed_classes(stream.project_id, config)
        if model_version_id is _KEEP_MODEL:
            if config.timer_enabled:
                stream.set_model(None)
        elif model_version_id is None:
            stream.set_model(None)
        else:
            model = await self._models.get_by_id(model_version_id)
            if model is None or model.project_id != stream.project_id:
                raise ResourceNotFoundException(
                    f"model version {model_version_id} not found"
                )
            stream.set_model(model_version_id)
        stream.update_config(config)
        await self._streams.update(stream)
        await self._uow.commit()

        if self._runner is not None and stream.is_active:
            self._runner.update_triggers(
                stream_id, config, allowed_class_indices=allowed
            )
        return stream

    async def _allowed_classes(
        self, project_id: UUID, config: StreamTriggerConfig
    ) -> frozenset[int] | None:
        if self._classes is None:
            if config.tripwire_classes:
                joined = ", ".join(str(item) for item in config.tripwire_classes)
                raise DomainValidationException(f"unknown class ids: {joined}")
            return None
        project_classes = await self._classes.list_by_project(project_id)
        return allowed_class_indices_for(config, project_classes)

    async def delete(self, stream_id: UUID) -> None:
        stream = await self._require_stream(stream_id)
        if stream.is_active:
            raise DomainValidationException("cannot delete an active stream; stop it first")
        video_path = (
            stream.source_uri
            if stream.source_type == StreamSourceType.VIDEO_FILE
            else None
        )
        await self._streams.delete(stream_id)
        await self._uow.commit()
        if video_path is not None:
            try:
                await self._storage.delete(video_path)
            except Exception:
                pass

    async def _require_project(self, project_id: UUID) -> None:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")

    async def _require_stream(self, stream_id: UUID) -> StreamSource:
        stream = await self._streams.get_by_id(stream_id)
        if stream is None:
            raise ResourceNotFoundException(f"stream source {stream_id} not found")
        return stream
