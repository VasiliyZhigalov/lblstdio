from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None


class ProjectRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ClassCreate(BaseModel):
    name: str = Field(min_length=1)
    color_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class ClassRead(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    color_hex: str
    index_id: int


class ImageRead(BaseModel):
    id: UUID
    project_id: UUID
    file_path: str
    file_name: str
    width: int
    height: int
    split: str
    status: str
    source_type: str
    created_at: datetime


class BoxPayload(BaseModel):
    class_id: UUID
    x_center: float
    y_center: float
    width: float
    height: float
    id: UUID | None = None


class PropagateSourceBox(BaseModel):
    id: UUID
    class_id: UUID
    x_center: float
    y_center: float
    width: float
    height: float


class SaveAnnotationsRequest(BaseModel):
    boxes: list[BoxPayload] = Field(default_factory=list)


class AnnotationRead(BaseModel):
    id: UUID
    image_id: UUID
    class_id: UUID
    x_center: float
    y_center: float
    width: float
    height: float
    source: str
    confidence: float
    verification_status: str
    verified_at: datetime | None = None
    source_annotation_id: UUID | None = None


class ImageDetailRead(ImageRead):
    annotations: list[AnnotationRead] = Field(default_factory=list)


class PropagateBoxRequest(BaseModel):
    source_image_id: UUID
    target_image_id: UUID
    source_box: PropagateSourceBox


class PropagateBoxesRequest(BaseModel):
    source_image_id: UUID
    target_image_id: UUID
    source_boxes: list[PropagateSourceBox] = Field(min_length=1)


class TransformDebugRead(BaseModel):
    tx: float
    ty: float
    rotation_deg: float
    scale: float
    match_score: float
    matrix: list[list[float]]


class DebugArrowRead(BaseModel):
    from_x: float
    from_y: float
    to_x: float
    to_y: float


class PropagateBoxesResponse(BaseModel):
    annotations: list[AnnotationRead]
    transform: TransformDebugRead
    debug_arrows: list[DebugArrowRead] = Field(default_factory=list)


class AugmentationConfigPayload(BaseModel):
    resize_width: int = Field(default=640, ge=32, le=2048)
    resize_height: int = Field(default=640, ge=32, le=2048)
    horizontal_flip: bool = True
    brightness_contrast: bool = True
    blur: bool = False
    shift_scale_rotate: bool = True
    multiplier: int = Field(default=3, ge=1, le=5)


class CreateDatasetVersionRequest(BaseModel):
    name: str | None = None
    augmentation: AugmentationConfigPayload | None = None


class DatasetVersionRead(BaseModel):
    id: UUID
    project_id: UUID
    version_number: int
    name: str
    status: str
    train_count: int
    valid_count: int
    test_count: int
    yaml_path: str
    created_at: datetime
    augmentation: AugmentationConfigPayload
    item_count: int = 0
