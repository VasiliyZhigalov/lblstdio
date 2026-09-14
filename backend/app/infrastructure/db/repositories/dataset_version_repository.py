from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.ports.repositories.dataset_version_repository import (
    IDatasetVersionRepository,
)
from app.domain.entities.dataset_version import DatasetVersion
from app.infrastructure.db.mappers import (
    dataset_item_to_row,
    dataset_version_to_row,
    row_to_dataset_version,
)
from app.infrastructure.db.tables import DatasetVersionRow


class SqliteDatasetVersionRepository(IDatasetVersionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, version: DatasetVersion) -> None:
        self._session.add(dataset_version_to_row(version))
        for item in version.items:
            self._session.add(dataset_item_to_row(item))
        await self._session.flush()

    async def update(self, version: DatasetVersion) -> None:
        row = await self._session.get(
            DatasetVersionRow,
            str(version.id),
            options=(selectinload(DatasetVersionRow.items),),
        )
        if row is None:
            return
        row.name = version.name
        row.status = version.status.value
        row.train_count = version.train_count
        row.valid_count = version.valid_count
        row.test_count = version.test_count
        row.yaml_path = version.yaml_path
        row.augmentation_json = {
            "resize_width": version.augmentation.resize_width,
            "resize_height": version.augmentation.resize_height,
            "horizontal_flip": version.augmentation.horizontal_flip,
            "brightness_contrast": version.augmentation.brightness_contrast,
            "blur": version.augmentation.blur,
            "shift_scale_rotate": version.augmentation.shift_scale_rotate,
            "multiplier": version.augmentation.multiplier,
        }
        for existing in list(row.items):
            await self._session.delete(existing)
        await self._session.flush()
        for item in version.items:
            self._session.add(dataset_item_to_row(item))
        await self._session.flush()

    async def get_by_id(self, version_id: UUID) -> DatasetVersion | None:
        row = await self._session.scalar(
            select(DatasetVersionRow)
            .where(DatasetVersionRow.id == str(version_id))
            .options(selectinload(DatasetVersionRow.items))
        )
        return row_to_dataset_version(row) if row else None

    async def list_by_project(self, project_id: UUID) -> list[DatasetVersion]:
        result = await self._session.scalars(
            select(DatasetVersionRow)
            .where(DatasetVersionRow.project_id == str(project_id))
            .options(selectinload(DatasetVersionRow.items))
            .order_by(DatasetVersionRow.version_number.desc())
        )
        return [row_to_dataset_version(row) for row in result]

    async def next_version_number(self, project_id: UUID) -> int:
        current = await self._session.scalar(
            select(func.max(DatasetVersionRow.version_number)).where(
                DatasetVersionRow.project_id == str(project_id)
            )
        )
        return int(current or 0) + 1
