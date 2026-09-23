from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from uuid import UUID

import yaml

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_label_repository import IImageLabelRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.storage.archive_packer import IArchivePacker
from app.application.ports.storage.file_storage import IFileStorage
from app.domain.entities.image import Image
from app.domain.enums import ProjectTaskType, SplitType, VerificationStatus
from app.domain.exceptions import ResourceNotFoundException
from app.domain.services.class_dir_name import class_dir_name, require_unique_class_dirs


def yolo_image_name(image: Image) -> str:
    suffix = Path(image.file_name).suffix.lower() or ".png"
    return f"{image.id}{suffix}"


def yolo_label_name(image: Image) -> str:
    return f"{image.id}.txt"


class ExportYOLOUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        classes: IClassRepository,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        storage: IFileStorage,
        packer: IArchivePacker,
        labels: IImageLabelRepository | None = None,
    ) -> None:
        self._projects = projects
        self._classes = classes
        self._images = images
        self._annotations = annotations
        self._storage = storage
        self._packer = packer
        self._labels = labels

    async def execute(self, project_id: UUID) -> bytes:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")

        if project.task_type == ProjectTaskType.CLASSIFICATION:
            return await self._execute_classification(project_id)

        classes = sorted(
            await self._classes.list_by_project(project_id),
            key=lambda item: item.index_id,
        )
        images = await self._images.list_by_project(project_id)
        exportable = [item for item in images if item.can_be_included_in_export()]
        annotations = await self._annotations.list_by_image_ids(
            [item.id for item in exportable]
        )
        by_image: dict[UUID, list] = defaultdict(list)
        for annotation in annotations:
            if annotation.is_exportable:
                by_image[annotation.image_id].append(annotation)

        class_by_id = {item.id: item for item in classes}
        names = {item.index_id: item.name for item in classes}
        yaml_payload = {
            "train": "train/images",
            "val": "valid/images",
            "test": "test/images",
            "nc": len(names),
            "names": names,
        }

        entries: dict[str, bytes] = {}
        for split in SplitType:
            entries[f"{split.value}/images/"] = b""
            entries[f"{split.value}/labels/"] = b""
        entries["data.yaml"] = yaml.safe_dump(
            yaml_payload, sort_keys=False, allow_unicode=True
        ).encode("utf-8")

        for image in exportable:
            split = image.split.value
            payload = await self._storage.read(image.file_path)
            entries[f"{split}/images/{yolo_image_name(image)}"] = payload
            lines = []
            for annotation in by_image.get(image.id, []):
                annotation_class = class_by_id[annotation.class_id]
                lines.append(
                    f"{annotation_class.index_id} {annotation.bbox.to_yolo_coords()}"
                )
            body = "\n".join(lines)
            entries[f"{split}/labels/{yolo_label_name(image)}"] = body.encode("utf-8")

        return self._packer.pack(entries)

    async def _execute_classification(self, project_id: UUID) -> bytes:
        classes = sorted(
            await self._classes.list_by_project(project_id),
            key=lambda item: item.index_id,
        )
        require_unique_class_dirs([item.name for item in classes])
        class_by_id = {item.id: item for item in classes}
        images = await self._images.list_by_project(project_id)
        exportable = [item for item in images if item.can_be_included_in_dataset()]
        labels = []
        if self._labels is not None:
            labels = await self._labels.list_by_image_ids([item.id for item in exportable])
        by_image = {item.image_id: item for item in labels}
        entries: dict[str, bytes] = {}
        for image in exportable:
            label = by_image.get(image.id)
            if label is None:
                continue
            if label.verification_status not in (
                VerificationStatus.VERIFIED,
                VerificationStatus.AUTO_VERIFIED,
            ):
                continue
            annotation_class = class_by_id.get(label.class_id)
            if annotation_class is None:
                continue
            folder = class_dir_name(annotation_class.name)
            disk_split = "val" if image.split == SplitType.VALID else image.split.value
            payload = await self._storage.read(image.file_path)
            entries[f"{disk_split}/{folder}/{yolo_image_name(image)}"] = payload
        return self._packer.pack(entries)
