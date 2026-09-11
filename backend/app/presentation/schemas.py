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


class ImageDetailRead(ImageRead):
    annotations: list[AnnotationRead] = Field(default_factory=list)
