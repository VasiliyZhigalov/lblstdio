import tempfile
from pathlib import Path, PurePosixPath
from uuid import UUID

from app.application.dto import UploadedFile
from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.services.image_metadata import IImageMetadataReader
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.enums import ImageSourceType, ImageStatus, ProjectTaskType, SplitType
from app.domain.exceptions import (
    DomainValidationException,
    ResourceNotFoundException,
    TaskTypeMismatchException,
)
from app.domain.services.class_index import allocate_next_index
from app.domain.services.yolo_label_import import (
    expand_upload_bundle,
    pair_images_and_labels,
    parse_class_names,
    parse_yolo_label_file,
)
from app.domain.value_objects.bounding_box import BoundingBox

_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_ALLOWED_SIDECAR_EXTENSIONS = {".txt", ".yaml", ".yml", ".zip", ".json"}
MAX_UPLOAD_FILES = 5000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_ZIP_BYTES = 512 * 1024 * 1024


def _image_bytes(payload: bytes | Path) -> bytes:
    if isinstance(payload, Path):
        return payload.read_bytes()
    return payload

_CLASS_COLORS = (
    "#EF4444",
    "#F59E0B",
    "#10B981",
    "#3B82F6",
    "#8B5CF6",
    "#EC4899",
    "#14B8A6",
    "#F97316",
    "#6366F1",
    "#84CC16",
)


class UploadImagesUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        images: IImageRepository,
        storage: IFileStorage,
        metadata: IImageMetadataReader,
        uow: IUnitOfWork,
        annotations: IAnnotationRepository,
        classes: IClassRepository,
    ) -> None:
        self._projects = projects
        self._images = images
        self._storage = storage
        self._metadata = metadata
        self._uow = uow
        self._annotations = annotations
        self._classes = classes

    async def execute(
        self,
        project_id: UUID,
        files: list[UploadedFile],
    ) -> list[Image]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")
        if not files:
            raise DomainValidationException("at least one image file is required")
        if len(files) > MAX_UPLOAD_FILES:
            raise DomainValidationException(
                f"too many files: maximum is {MAX_UPLOAD_FILES}"
            )

        with tempfile.TemporaryDirectory() as staging_name:
            staging = Path(staging_name)
            image_dir = staging / "images"
            image_dir.mkdir()
            staged: list[tuple[str, Path]] = []
            for index, uploaded in enumerate(files):
                extension = Path(uploaded.filename).suffix.lower()
                if extension not in _ALLOWED_IMAGE_EXTENSIONS | _ALLOWED_SIDECAR_EXTENSIONS:
                    raise DomainValidationException(
                        f"unsupported file format '{extension or uploaded.filename}'"
                    )
                if uploaded.body_path:
                    source = Path(uploaded.body_path)
                else:
                    source = staging / f"part_{index:05d}"
                    source.write_bytes(uploaded.content)
                size_limit = (
                    MAX_UPLOAD_ZIP_BYTES if extension == ".zip" else MAX_UPLOAD_BYTES
                )
                if source.stat().st_size > size_limit:
                    raise DomainValidationException(
                        f"file '{uploaded.filename}' exceeds the size limit"
                    )
                staged.append((uploaded.filename, source))

            images_map, labels_map, class_files = expand_upload_bundle(
                staged, image_staging_dir=image_dir
            )
            if project.task_type == ProjectTaskType.CLASSIFICATION and (
                labels_map or class_files
            ):
                raise TaskTypeMismatchException(
                    "classification projects accept images only"
                )
            return await self._persist_bundle(project_id, images_map, labels_map, class_files)

    async def _persist_bundle(
        self,
        project_id: UUID,
        images_map: dict[str, bytes | Path],
        labels_map: dict[str, bytes],
        class_files: dict[str, bytes],
    ) -> list[Image]:
        if not images_map:
            raise DomainValidationException("at least one image file is required")

        yaml_files = {
            path: payload
            for path, payload in class_files.items()
            if PurePosixPath(path).suffix.lower() in {".yaml", ".yml"}
        }
        text_class_files = {
            path: payload
            for path, payload in class_files.items()
            if PurePosixPath(path).name.lower() == "classes.txt"
        }
        json_class_files = {
            path: payload
            for path, payload in class_files.items()
            if PurePosixPath(path).name.lower() == "notes.json"
        }
        class_names = parse_class_names(yaml_files, text_class_files, json_class_files)

        paired = pair_images_and_labels(images_map, labels_map)
        prepared_labels: dict[str, list] = {}
        max_class_index = -1
        for image_path, label_path in paired.items():
            if label_path is None:
                continue
            try:
                text = labels_map[label_path].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DomainValidationException(
                    f"cannot decode label '{label_path}'"
                ) from exc
            boxes = parse_yolo_label_file(text)
            prepared_labels[image_path] = boxes
            for box in boxes:
                max_class_index = max(max_class_index, box.class_index)

        if max_class_index >= 0:
            if class_names is None:
                class_names = [f"class_{index}" for index in range(max_class_index + 1)]
            if max_class_index >= len(class_names):
                raise DomainValidationException(
                    f"class index {max_class_index} is out of range for "
                    f"{len(class_names)} class name(s)"
                )

        existing_classes = await self._classes.list_by_project(project_id)
        class_by_name = {item.name: item for item in existing_classes}
        created_classes: list[AnnotationClass] = []
        if class_names:
            for name in class_names:
                if name in class_by_name:
                    continue
                index_id = allocate_next_index(
                    [item.index_id for item in existing_classes + created_classes]
                )
                color = _CLASS_COLORS[index_id % len(_CLASS_COLORS)]
                annotation_class = AnnotationClass.create(
                    project_id=project_id,
                    name=name,
                    color_hex=color,
                    index_id=index_id,
                )
                created_classes.append(annotation_class)
                class_by_name[name] = annotation_class

        created: list[Image] = []
        saved_paths: list[str] = []
        annotations_by_image: dict[UUID, list[Annotation]] = {}
        try:
            for created_class in created_classes:
                await self._classes.add(created_class)

            for image_path, payload in images_map.items():
                content = _image_bytes(payload)
                width, height = self._metadata.read_size(content)
                basename = PurePosixPath(image_path).name
                relative_dir = f"projects/{project_id}/images"
                try:
                    relative_path = await self._storage.save(
                        relative_dir, basename, content
                    )
                except ValueError as exc:
                    raise DomainValidationException(str(exc)) from exc
                saved_paths.append(relative_path)
                image = Image.create(
                    project_id=project_id,
                    file_path=relative_path,
                    file_name=Path(relative_path).name,
                    width=width,
                    height=height,
                    split=SplitType.TRAIN,
                    source_type=ImageSourceType.MANUAL_UPLOAD,
                )

                label_boxes = prepared_labels.get(image_path)
                if label_boxes is not None:
                    if not label_boxes:
                        image.mark_as_background()
                    else:
                        assert class_names is not None
                        annotations = [
                            Annotation.create_manual(
                                image_id=image.id,
                                class_id=class_by_name[class_names[box.class_index]].id,
                                bbox=BoundingBox(
                                    x_center=box.x_center,
                                    y_center=box.y_center,
                                    width=box.width,
                                    height=box.height,
                                ),
                            )
                            for box in label_boxes
                        ]
                        annotations_by_image[image.id] = annotations
                        image.recalculate_status(annotations)
                created.append(image)

            await self._images.add_many(created)
            for image_id, annotations in annotations_by_image.items():
                await self._annotations.replace_for_image(image_id, annotations)
            for image in created:
                if image.status != ImageStatus.UNANNOTATED or image.is_background:
                    await self._images.update(image)
            await self._uow.commit()
        except Exception:
            for path in saved_paths:
                await self._storage.delete(path)
            raise
        return created
