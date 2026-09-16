from datetime import UTC, datetime
from uuid import UUID

from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.dataset_version import (
    AugmentationConfig,
    DatasetItem,
    DatasetVersion,
    SnapshotAnnotation,
)
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import (
    DatasetVersionStatus,
    ImageSourceType,
    ImageStatus,
    SourceType,
    SplitType,
    StreamSourceType,
    TripwireDirection,
    VerificationStatus,
)
from app.domain.value_objects.bounding_box import BoundingBox
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig
from app.domain.entities.stream_source import StreamSource
from app.infrastructure.db.tables import (
    AnnotationRow,
    ClassRow,
    DatasetItemRow,
    DatasetVersionRow,
    ImageRow,
    ProjectRow,
    StreamSourceRow,
)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def project_to_row(project: Project) -> ProjectRow:
    return ProjectRow(
        id=str(project.id),
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def row_to_project(row: ProjectRow) -> Project:
    return Project(
        id=UUID(row.id),
        name=row.name,
        description=row.description,
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
    )


def class_to_row(item: AnnotationClass) -> ClassRow:
    return ClassRow(
        id=str(item.id),
        project_id=str(item.project_id),
        name=item.name,
        color_hex=item.color_hex,
        index_id=item.index_id,
    )


def row_to_class(row: ClassRow) -> AnnotationClass:
    return AnnotationClass(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        name=row.name,
        color_hex=row.color_hex,
        index_id=row.index_id,
    )


def image_to_row(image: Image) -> ImageRow:
    return ImageRow(
        id=str(image.id),
        project_id=str(image.project_id),
        file_path=image.file_path,
        file_name=image.file_name,
        width=image.width,
        height=image.height,
        source_type=image.source_type.value,
        split=image.split.value,
        status=image.status.value,
        created_at=image.created_at,
        stream_source_id=str(image.stream_source_id) if image.stream_source_id else None,
        is_background=1 if image.is_background else 0,
    )


def row_to_image(row: ImageRow) -> Image:
    return Image(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        file_path=row.file_path,
        file_name=row.file_name,
        width=row.width,
        height=row.height,
        source_type=ImageSourceType(row.source_type),
        split=SplitType(row.split),
        status=ImageStatus(row.status),
        created_at=ensure_utc(row.created_at),
        stream_source_id=UUID(row.stream_source_id) if row.stream_source_id else None,
        is_background=bool(getattr(row, "is_background", 0)),
    )


def annotation_to_row(annotation: Annotation) -> AnnotationRow:
    return AnnotationRow(
        id=str(annotation.id),
        image_id=str(annotation.image_id),
        class_id=str(annotation.class_id),
        x_center=annotation.bbox.x_center,
        y_center=annotation.bbox.y_center,
        width=annotation.bbox.width,
        height=annotation.bbox.height,
        source=annotation.source.value,
        confidence=annotation.confidence,
        verification_status=annotation.verification_status.value,
        verified_at=annotation.verified_at,
        model_version_id=(
            str(annotation.model_version_id) if annotation.model_version_id else None
        ),
        source_annotation_id=(
            str(annotation.source_annotation_id)
            if annotation.source_annotation_id
            else None
        ),
    )


def row_to_annotation(row: AnnotationRow) -> Annotation:
    return Annotation(
        id=UUID(row.id),
        image_id=UUID(row.image_id),
        class_id=UUID(row.class_id),
        bbox=BoundingBox(
            x_center=row.x_center,
            y_center=row.y_center,
            width=row.width,
            height=row.height,
        ),
        source=SourceType(row.source),
        verification_status=VerificationStatus(row.verification_status),
        confidence=row.confidence,
        verified_at=ensure_utc(row.verified_at),
        model_version_id=UUID(row.model_version_id) if row.model_version_id else None,
        source_annotation_id=(
            UUID(row.source_annotation_id) if row.source_annotation_id else None
        ),
    )


def augmentation_to_dict(config: AugmentationConfig) -> dict:
    return {
        "resize_width": config.resize_width,
        "resize_height": config.resize_height,
        "horizontal_flip": config.horizontal_flip,
        "vertical_flip": config.vertical_flip,
        "rotate": config.rotate,
        "shear": config.shear,
        "hue_saturation": config.hue_saturation,
        "brightness_contrast": config.brightness_contrast,
        "blur": config.blur,
        "noise": config.noise,
        "grayscale": config.grayscale,
        "cutout": config.cutout,
        "shift_scale_rotate": config.shift_scale_rotate,
        "multiplier": config.multiplier,
    }


def dict_to_augmentation(raw: dict) -> AugmentationConfig:
    legacy_ssr = bool(raw.get("shift_scale_rotate", False))
    has_new_geo = "rotate" in raw or "shear" in raw
    if has_new_geo:
        rotate = bool(raw.get("rotate", True))
        shear = bool(raw.get("shear", True))
    else:
        # Older snapshots stored geometry as shift_scale_rotate.
        rotate = legacy_ssr if "shift_scale_rotate" in raw else True
        shear = legacy_ssr if "shift_scale_rotate" in raw else True
    return AugmentationConfig(
        resize_width=int(raw.get("resize_width", 640)),
        resize_height=int(raw.get("resize_height", 640)),
        horizontal_flip=bool(raw.get("horizontal_flip", True)),
        vertical_flip=bool(raw.get("vertical_flip", False)),
        rotate=rotate,
        shear=shear,
        hue_saturation=bool(raw.get("hue_saturation", True)),
        brightness_contrast=bool(raw.get("brightness_contrast", True)),
        blur=bool(raw.get("blur", False)),
        noise=bool(raw.get("noise", False)),
        grayscale=bool(raw.get("grayscale", False)),
        cutout=bool(raw.get("cutout", False)),
        shift_scale_rotate=False,
        multiplier=int(raw.get("multiplier", 3)),
    )


def dataset_version_to_row(version: DatasetVersion) -> DatasetVersionRow:
    return DatasetVersionRow(
        id=str(version.id),
        project_id=str(version.project_id),
        version_number=version.version_number,
        name=version.name,
        status=version.status.value,
        train_count=version.train_count,
        valid_count=version.valid_count,
        test_count=version.test_count,
        train_file_count=version.train_file_count,
        valid_file_count=version.valid_file_count,
        test_file_count=version.test_file_count,
        yaml_path=version.yaml_path,
        created_at=version.created_at,
        augmentation_json=augmentation_to_dict(version.augmentation),
    )


def dataset_item_to_row(item: DatasetItem) -> DatasetItemRow:
    return DatasetItemRow(
        id=str(item.id),
        dataset_version_id=str(item.dataset_version_id),
        image_id=str(item.image_id),
        split=item.split.value,
        snapshot_annotations=item.snapshot_as_dicts(),
        source_file_name=item.source_file_name,
    )


def row_to_dataset_item(row: DatasetItemRow) -> DatasetItem:
    return DatasetItem(
        id=UUID(row.id),
        dataset_version_id=UUID(row.dataset_version_id),
        image_id=UUID(row.image_id),
        split=SplitType(row.split),
        snapshot_annotations=[
            SnapshotAnnotation.from_dict(raw) for raw in (row.snapshot_annotations or [])
        ],
        source_file_name=row.source_file_name,
    )


def row_to_dataset_version(row: DatasetVersionRow) -> DatasetVersion:
    return DatasetVersion(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        version_number=row.version_number,
        name=row.name,
        status=DatasetVersionStatus(row.status),
        train_count=row.train_count,
        valid_count=row.valid_count,
        test_count=row.test_count,
        train_file_count=getattr(row, "train_file_count", 0) or 0,
        valid_file_count=getattr(row, "valid_file_count", 0) or 0,
        test_file_count=getattr(row, "test_file_count", 0) or 0,
        yaml_path=row.yaml_path,
        created_at=ensure_utc(row.created_at),
        augmentation=dict_to_augmentation(row.augmentation_json or {}),
        items=[row_to_dataset_item(item) for item in (row.items or [])],
    )


def stream_trigger_config_to_dict(config: StreamTriggerConfig) -> dict:
    return {
        "track_stable_enabled": config.track_stable_enabled,
        "track_stable_min_frames": config.track_stable_min_frames,
        "track_stable_max_size_variation": config.track_stable_max_size_variation,
        "track_stable_min_avg_conf": config.track_stable_min_avg_conf,
        "track_stable_interval_seconds": config.track_stable_interval_seconds,
        "timer_enabled": config.timer_enabled,
        "timer_interval_seconds": config.timer_interval_seconds,
        "tripwire_enabled": config.tripwire_enabled,
        "tripwire_line": list(config.tripwire_line) if config.tripwire_line else None,
        "tripwire_classes": [str(item) for item in config.tripwire_classes],
        "tripwire_direction": config.tripwire_direction.value,
        "tripwire_debounce_seconds": config.tripwire_debounce_seconds,
        "cooldown_seconds": config.cooldown_seconds,
    }


def dict_to_stream_trigger_config(raw: dict) -> StreamTriggerConfig:
    line = raw.get("tripwire_line")
    if "track_stable_enabled" in raw:
        track_enabled = bool(raw.get("track_stable_enabled"))
    else:
        # Legacy: timer-only configs stay timer; new default enables track-stable.
        track_enabled = True
    interval = raw.get("track_stable_interval_seconds")
    if interval is None:
        interval = 5.0
    return StreamTriggerConfig(
        track_stable_enabled=track_enabled,
        track_stable_min_frames=int(raw.get("track_stable_min_frames", 12)),
        track_stable_max_size_variation=float(
            raw.get("track_stable_max_size_variation", 0.35)
        ),
        track_stable_min_avg_conf=float(raw.get("track_stable_min_avg_conf", 0.75)),
        track_stable_interval_seconds=float(interval),
        timer_enabled=bool(raw.get("timer_enabled", False)),
        timer_interval_seconds=float(raw.get("timer_interval_seconds", 5.0)),
        tripwire_enabled=bool(raw.get("tripwire_enabled", False)),
        tripwire_line=tuple(line) if line else None,
        tripwire_classes=tuple(UUID(item) for item in (raw.get("tripwire_classes") or [])),
        tripwire_direction=TripwireDirection(
            raw.get("tripwire_direction", TripwireDirection.ANY.value)
        ),
        tripwire_debounce_seconds=float(raw.get("tripwire_debounce_seconds", 3.0)),
        cooldown_seconds=float(raw.get("cooldown_seconds", 3.0)),
    )


def stream_source_to_row(stream: StreamSource) -> StreamSourceRow:
    return StreamSourceRow(
        id=str(stream.id),
        project_id=str(stream.project_id),
        name=stream.name,
        source_type=stream.source_type.value,
        source_uri=stream.source_uri,
        is_active=1 if stream.is_active else 0,
        model_version_id=str(stream.model_version_id) if stream.model_version_id else None,
        config_json=stream_trigger_config_to_dict(stream.config),
        captured_frames_count=stream.captured_frames_count,
        created_at=stream.created_at,
    )


def row_to_stream_source(row: StreamSourceRow) -> StreamSource:
    return StreamSource(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        name=row.name,
        source_type=StreamSourceType(row.source_type),
        source_uri=row.source_uri,
        is_active=bool(row.is_active),
        model_version_id=UUID(row.model_version_id) if row.model_version_id else None,
        config=dict_to_stream_trigger_config(row.config_json or {}),
        captured_frames_count=row.captured_frames_count,
        created_at=ensure_utc(row.created_at),
    )
