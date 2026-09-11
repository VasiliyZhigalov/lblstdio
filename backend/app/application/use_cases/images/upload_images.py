from pathlib import Path
from uuid import UUID

from app.application.dto import UploadedFile
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.services.image_metadata import IImageMetadataReader
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.image import Image
from app.domain.enums import ImageSourceType
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.services.split import assign_splits
from app.domain.value_objects.split_ratios import SplitRatios

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class UploadImagesUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        images: IImageRepository,
        storage: IFileStorage,
        metadata: IImageMetadataReader,
        uow: IUnitOfWork,
    ) -> None:
        self._projects = projects
        self._images = images
        self._storage = storage
        self._metadata = metadata
        self._uow = uow

    async def execute(
        self,
        project_id: UUID,
        files: list[UploadedFile],
        ratios: SplitRatios | None = None,
    ) -> list[Image]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")
        if not files:
            raise DomainValidationException("at least one image file is required")

        prepared: list[tuple[UploadedFile, tuple[int, int]]] = []
        for uploaded in files:
            if len(uploaded.content) > MAX_UPLOAD_BYTES:
                raise DomainValidationException(
                    f"file '{uploaded.filename}' exceeds the size limit"
                )
            extension = Path(uploaded.filename).suffix.lower()
            if extension not in _ALLOWED_EXTENSIONS:
                raise DomainValidationException(
                    f"unsupported image format '{extension or uploaded.filename}'"
                )
            prepared.append((uploaded, self._metadata.read_size(uploaded.content)))

        splits = assign_splits(len(prepared), ratios)
        created: list[Image] = []
        saved_paths: list[str] = []
        try:
            for (uploaded, (width, height)), split in zip(prepared, splits, strict=True):
                relative_dir = f"projects/{project_id}/images"
                try:
                    relative_path = await self._storage.save(
                        relative_dir, uploaded.filename, uploaded.content
                    )
                except ValueError as exc:
                    raise DomainValidationException(str(exc)) from exc
                saved_paths.append(relative_path)
                created.append(
                    Image.create(
                        project_id=project_id,
                        file_path=relative_path,
                        file_name=Path(relative_path).name,
                        width=width,
                        height=height,
                        split=split,
                        source_type=ImageSourceType.MANUAL_UPLOAD,
                    )
                )
            await self._images.add_many(created)
            await self._uow.commit()
        except Exception:
            for path in saved_paths:
                await self._storage.delete(path)
            raise
        return created
