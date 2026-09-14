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
