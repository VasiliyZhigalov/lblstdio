from __future__ import annotations

import io
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from PIL import Image as PILImage

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.storage.archive_packer import (
    IArchivePacker,
    allocate_archive_path,
)
from app.application.ports.storage.file_storage import IFileStorage, read_member
from app.application.services.task_policy import require_task
from app.domain.entities.annotation import Annotation
from app.domain.enums import ProjectTaskType
from app.domain.exceptions import ResourceNotFoundException
from app.domain.services.class_dir_name import class_dir_name


def crop_archive_stem(project_name: str) -> str:
    return f"{class_dir_name(project_name)}_crop"


@dataclass
class _CropImage:
    source: bytes | Path
    crops: list[tuple[str, Annotation]]


def _open_image(source: bytes | Path) -> PILImage.Image:
    if isinstance(source, Path):
        image = PILImage.open(source)
    else:
        image = PILImage.open(io.BytesIO(source))
    image.load()
    return image


def _iter_crop_members(folders: list[str], images: list[_CropImage]):
    for folder in folders:
        yield folder, b""
    for item in images:
        decoded = _open_image(item.source)
        try:
            for arcname, annotation in item.crops:
                box = annotation.bbox.pixel_slice(decoded.width, decoded.height)
                yield arcname, encode_crop(decoded, box)
        finally:
            decoded.close()


def encode_crop(image: PILImage.Image, box: tuple[int, int, int, int]) -> bytes:
    cropped = image.crop(box)
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    return buffer.getvalue()


class ExportCropsUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        classes: IClassRepository,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        storage: IFileStorage,
        packer: IArchivePacker,
    ) -> None:
        self._projects = projects
        self._classes = classes
        self._images = images
        self._annotations = annotations
        self._storage = storage
        self._packer = packer

    async def _require_detection_project(self, project_id: UUID):
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")
        require_task(project, ProjectTaskType.DETECTION)
        return project

    async def archive_filename(self, project_id: UUID) -> str:
        project = await self._require_detection_project(project_id)
        return f"{crop_archive_stem(project.name)}.zip"

    async def execute(self, project_id: UUID) -> tuple[Path, str]:
        project = await self._require_detection_project(project_id)

        classes = sorted(
            await self._classes.list_by_project(project_id),
            key=lambda item: item.index_id,
        )
        images = await self._images.list_by_project(project_id)
        exportable = [item for item in images if item.can_be_included_in_export()]
        annotations = await self._annotations.list_by_image_ids(
            [item.id for item in exportable]
        )
        by_image: dict[UUID, list[Annotation]] = defaultdict(list)
        for annotation in annotations:
            if annotation.is_exportable:
                by_image[annotation.image_id].append(annotation)

        class_by_id = {item.id: item for item in classes}
        root = crop_archive_stem(project.name)
        folders = [f"{root}/{class_dir_name(item.name)}/" for item in classes]
        plans: list[_CropImage] = []

        for image in exportable:
            boxes = by_image.get(image.id, [])
            if not boxes:
                continue
            crops: list[tuple[str, Annotation]] = []
            counts: dict[str, int] = defaultdict(int)
            for annotation in boxes:
                annotation_class = class_by_id.get(annotation.class_id)
                if annotation_class is None:
                    continue
                folder = class_dir_name(annotation_class.name)
                index = counts[folder]
                counts[folder] += 1
                crops.append((f"{root}/{folder}/{image.id}_{index}.png", annotation))
            if not crops:
                continue
            plans.append(
                _CropImage(
                    source=await read_member(self._storage, image.file_path),
                    crops=crops,
                )
            )

        dest = allocate_archive_path()
        try:
            await self._packer.pack_to_path(dest, _iter_crop_members(folders, plans))
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        return dest, f"{root}.zip"
