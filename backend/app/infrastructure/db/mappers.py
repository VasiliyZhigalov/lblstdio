from datetime import UTC, datetime
from uuid import UUID

from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import (
    ImageSourceType,
    ImageStatus,
    SourceType,
    SplitType,
    VerificationStatus,
)
from app.domain.value_objects.bounding_box import BoundingBox
from app.infrastructure.db.tables import AnnotationRow, ClassRow, ImageRow, ProjectRow


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
