from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories.image_repository import IImageRepository
from app.domain.entities.image import Image
from app.domain.enums import ImageListSort, ImageStatus, SourceType, SplitType
from app.infrastructure.db.mappers import image_to_row, row_to_image
from app.infrastructure.db.tables import AnnotationRow, DatasetItemRow, ImageLabelRow, ImageRow


def _model_confidence_expr():
    """Lowest model-prediction confidence on the frame, else the image label."""
    box_min = (
        select(func.min(AnnotationRow.confidence))
        .where(
            AnnotationRow.image_id == ImageRow.id,
            AnnotationRow.source == SourceType.MODEL_PREDICTION.value,
        )
        .correlate(ImageRow)
        .scalar_subquery()
    )
    label_conf = (
        select(ImageLabelRow.confidence)
        .where(
            ImageLabelRow.image_id == ImageRow.id,
            ImageLabelRow.source == SourceType.MODEL_PREDICTION.value,
        )
        .correlate(ImageRow)
        .scalar_subquery()
    )
    return func.coalesce(box_min, label_conf)


class SqliteImageRepository(IImageRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, images: Sequence[Image]) -> None:
        self._session.add_all([image_to_row(item) for item in images])
        await self._session.flush()

    async def get_by_id(self, image_id: UUID) -> Image | None:
        row = await self._session.get(ImageRow, str(image_id))
        return row_to_image(row) if row else None

    async def list_by_project(self, project_id: UUID) -> list[Image]:
        return await self.list_page(project_id)

    async def list_page(
        self,
        project_id: UUID,
        *,
        split: SplitType | None = None,
        status: ImageStatus | None = None,
        offset: int = 0,
        limit: int | None = None,
        sort: ImageListSort | None = None,
    ) -> list[Image]:
        stmt = select(ImageRow).where(ImageRow.project_id == str(project_id))
        if split is not None:
            stmt = stmt.where(ImageRow.split == split.value)
        if status is not None:
            stmt = stmt.where(ImageRow.status == status.value)
        if sort == ImageListSort.UNCERTAINTY:
            score = _model_confidence_expr()
            stmt = stmt.order_by(score.is_(None), score.asc(), ImageRow.created_at.asc())
        else:
            stmt = stmt.order_by(ImageRow.created_at.asc())
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.scalars(stmt)
        return [row_to_image(row) for row in result]

    async def min_model_confidence(self, image_ids: Sequence[UUID]) -> dict[UUID, float]:
        if not image_ids:
            return {}
        ids = [str(item) for item in image_ids]
        model_source = SourceType.MODEL_PREDICTION.value
        label_rows = await self._session.execute(
            select(ImageLabelRow.image_id, ImageLabelRow.confidence).where(
                ImageLabelRow.image_id.in_(ids),
                ImageLabelRow.source == model_source,
            )
        )
        scores = {UUID(image_id): float(confidence) for image_id, confidence in label_rows}
        box_rows = await self._session.execute(
            select(AnnotationRow.image_id, func.min(AnnotationRow.confidence))
            .where(
                AnnotationRow.image_id.in_(ids),
                AnnotationRow.source == model_source,
            )
            .group_by(AnnotationRow.image_id)
        )
        for image_id, confidence in box_rows:
            scores[UUID(image_id)] = float(confidence)
        return scores

    async def update(self, image: Image) -> None:
        row = await self._session.get(ImageRow, str(image.id))
        if row is None:
            return
        row.file_path = image.file_path
        row.file_name = image.file_name
        row.width = image.width
        row.height = image.height
        row.source_type = image.source_type.value
        row.split = image.split.value
        row.status = image.status.value
        row.is_background = 1 if image.is_background else 0
        row.stream_source_id = (
            str(image.stream_source_id) if image.stream_source_id else None
        )
        await self._session.flush()

    async def delete(self, image_id: UUID) -> None:
        await self._session.execute(
            delete(DatasetItemRow).where(DatasetItemRow.image_id == str(image_id))
        )
        row = await self._session.get(ImageRow, str(image_id))
        if row is None:
            return
        await self._session.delete(row)
        await self._session.flush()
