from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None


class ProjectUpdate(BaseModel):
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
    is_background: bool = False


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
    model_version_id: UUID | None = None


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
    vertical_flip: bool = False
    rotate: bool = True
    shear: bool = True
    hue_saturation: bool = True
    brightness_contrast: bool = True
    blur: bool = False
    noise: bool = False
    grayscale: bool = False
    cutout: bool = False
    shift_scale_rotate: bool = False
    multiplier: int = Field(default=3, ge=1, le=5)


class CreateDatasetVersionRequest(BaseModel):
    name: str | None = None
    augmentation: AugmentationConfigPayload | None = None
    train: float = Field(default=0.7, ge=0.0, le=1.0)
    valid: float = Field(default=0.2, ge=0.0, le=1.0)
    test: float = Field(default=0.1, ge=0.0, le=1.0)


class DatasetVersionRead(BaseModel):
    id: UUID
    project_id: UUID
    version_number: int
    name: str
    status: str
    train_count: int
    valid_count: int
    test_count: int
    train_file_count: int = 0
    valid_file_count: int = 0
    test_file_count: int = 0
    yaml_path: str
    created_at: datetime
    augmentation: AugmentationConfigPayload
    item_count: int = 0
    min_verified_required: int = 10


class TrainModelRequest(BaseModel):
    dataset_version_id: UUID
    epochs: int = Field(default=100, ge=1, le=500)
    patience: int = Field(default=20, ge=0, le=100)
    batch_size: int = Field(default=16, ge=1, le=64)
    imgsz: int = Field(default=640, ge=32, le=1280)
    device: str = Field(
        default="auto",
        pattern=r"^(?i)(auto|cpu|cuda|gpu|cuda:\d+|\d+)$",
    )
    base_weights: str | None = Field(
        default="yolov8n.pt",
        description="Pretrained checkpoint name, e.g. yolov8n.pt",
    )
    base_model_version_id: UUID | None = Field(
        default=None,
        description="Fine-tune from a project ModelVersion instead of pretrained weights",
    )


class TrainingJobRead(BaseModel):
    id: UUID
    project_id: UUID
    dataset_version_id: UUID
    status: str
    epochs: int
    patience: int = 20
    batch_size: int
    imgsz: int
    device: str
    device_label: str = "CPU"
    base_weights: str | None = None
    current_epoch: int
    stopped_early: bool = False
    progress_percent: float
    metrics_history: list[dict] = Field(default_factory=list)
    model_version_id: UUID | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TrainingDeviceRead(BaseModel):
    requested: str
    device: str
    label: str
    backend: str


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ModelVersionRead(BaseModel):
    id: UUID
    project_id: UUID
    dataset_version_id: UUID | None = None
    training_job_id: UUID | None = None
    version_number: int
    name: str
    weights_path: str
    map50: float | None = None
    map50_95: float | None = None
    precision: float | None = None
    recall: float | None = None
    is_active_for_stream: bool = False
    display_name: str
    created_at: datetime


class AutoLabelRequest(BaseModel):
    image_ids: list[UUID] | None = None
    all_unannotated: bool = False
    confidence_threshold: float = Field(default=0.05, ge=0.01, le=0.95)


class AutoLabelJobRead(BaseModel):
    id: UUID
    project_id: UUID
    model_version_id: UUID
    confidence_threshold: float
    status: str
    image_ids: list[UUID]
    total_images_processed: int
    total_predictions_generated: int
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class StreamTriggerConfigPayload(BaseModel):
    timer_enabled: bool = False
    timer_interval_seconds: float = Field(default=5.0, gt=0)
    tripwire_enabled: bool = False
    tripwire_line: tuple[float, float, float, float] | None = None
    tripwire_classes: list[UUID] = Field(default_factory=list)
    tripwire_direction: str = "ANY"
    tripwire_debounce_seconds: float = Field(default=3.0, ge=0)
    uncertainty_range: tuple[float, float] = (0.70, 0.90)
    cooldown_seconds: float = Field(default=3.0, ge=0)


class StreamTriggersUpdate(BaseModel):
    config: StreamTriggerConfigPayload
    model_version_id: UUID | None = None


class StreamRtspCreate(BaseModel):
    name: str = Field(min_length=1)
    rtsp_url: str = Field(min_length=1)


class StreamDeviceCreate(BaseModel):
    name: str = Field(min_length=1)
    device_index: int = Field(default=0, ge=0)


class StreamSourceRead(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    source_type: str
    source_uri: str
    is_active: bool
    model_version_id: UUID | None = None
    config: StreamTriggerConfigPayload
    captured_frames_count: int
    created_at: datetime


class StreamStatusRead(BaseModel):
    is_running: bool
    state: str
    fps: float = 0.0
    captured_count: int = 0
    last_capture_at: datetime | None = None
    error_message: str | None = None
