from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    classes: Mapped[list["ClassRow"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    images: Mapped[list["ImageRow"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    dataset_versions: Mapped[list["DatasetVersionRow"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ClassRow(Base):
    __tablename__ = "annotation_classes"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_class_project_name"),
        UniqueConstraint("project_id", "index_id", name="uq_class_project_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color_hex: Mapped[str] = mapped_column(String(7), nullable=False)
    index_id: Mapped[int] = mapped_column(Integer, nullable=False)

    project: Mapped[ProjectRow] = relationship(back_populates="classes")
    annotations: Mapped[list["AnnotationRow"]] = relationship(
        back_populates="annotation_class",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ImageRow(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stream_source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_background: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped[ProjectRow] = relationship(back_populates="images")
    annotations: Mapped[list["AnnotationRow"]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AnnotationRow(Base):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    class_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("annotation_classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    x_center: Mapped[float] = mapped_column(Float, nullable=False)
    y_center: Mapped[float] = mapped_column(Float, nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    model_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_annotation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    image: Mapped[ImageRow] = relationship(back_populates="annotations")
    annotation_class: Mapped[ClassRow] = relationship(back_populates="annotations")


class DatasetVersionRow(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version_number", name="uq_dataset_version_project_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    train_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    test_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    train_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    test_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    yaml_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    augmentation_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    project: Mapped[ProjectRow] = relationship(back_populates="dataset_versions")
    items: Mapped[list["DatasetItemRow"]] = relationship(
        back_populates="dataset_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DatasetItemRow(Base):
    __tablename__ = "dataset_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_id: Mapped[str] = mapped_column(String(36), nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_annotations: Mapped[list] = mapped_column(JSON, nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)

    dataset_version: Mapped[DatasetVersionRow] = relationship(back_populates="items")


class TrainingJobRow(Base):
    __tablename__ = "training_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    dataset_version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    epochs: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    imgsz: Mapped[int] = mapped_column(Integer, nullable=False, default=640)
    device: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    base_weights: Mapped[str] = mapped_column(String(255), nullable=False, default="yolov8n.pt")
    patience: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    metrics_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    current_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stopped_early: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelVersionRow(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version_number", name="uq_model_version_project_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    dataset_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    training_job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    weights_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    map50: Mapped[float | None] = mapped_column(Float, nullable=True)
    map50_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active_for_stream: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AutoLabelJobRow(Base):
    __tablename__ = "auto_label_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    model_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    image_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    total_images_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_predictions_generated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
