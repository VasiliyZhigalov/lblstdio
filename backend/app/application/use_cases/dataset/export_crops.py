from __future__ import annotations

import io
from collections import defaultdict
from uuid import UUID

from PIL import Image as PILImage

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.storage.archive_packer import IArchivePacker
from app.application.ports.storage.file_storage import IFileStorage
from app.application.services.task_policy import require_task
from app.domain.entities.annotation import Annotation
from app.domain.enums import ProjectTaskType
from app.domain.exceptions import ResourceNotFoundException
from app.domain.services.class_dir_name import class_dir_name


def crop_archive_stem(project_name: str) -> str:
    return f"{class_dir_name(project_name)}_crop"


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

    async def execute(self, project_id: UUID) -> tuple[bytes, str]:
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
        entries: dict[str, bytes] = {
            f"{root}/{class_dir_name(item.name)}/": b"" for item in classes
        }

        for image in exportable:
            boxes = by_image.get(image.id, [])
            if not boxes:
                continue
            payload = await self._storage.read(image.file_path)
            decoded = PILImage.open(io.BytesIO(payload))
            decoded.load()
            try:
                counts: dict[str, int] = defaultdict(int)
                for annotation in boxes:
                    annotation_class = class_by_id.get(annotation.class_id)
                    if annotation_class is None:
                        continue
                    folder = class_dir_name(annotation_class.name)
                    index = counts[folder]
                    counts[folder] += 1
                    pixels = annotation.bbox.pixel_slice(decoded.width, decoded.height)
                    entries[f"{root}/{folder}/{image.id}_{index}.png"] = encode_crop(
                        decoded, pixels
                    )
            finally:
                decoded.close()

        return self._packer.pack(entries), f"{root}.zip"
