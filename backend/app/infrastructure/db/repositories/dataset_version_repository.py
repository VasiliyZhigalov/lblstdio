from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.ports.repositories.dataset_version_repository import (
    IDatasetVersionRepository,
)
from app.domain.entities.dataset_version import DatasetVersion
from app.domain.exceptions import DatasetVersionConflictException
from app.infrastructure.db.mappers import (
    augmentation_to_dict,
    dataset_item_to_row,
    dataset_version_to_row,
    row_to_dataset_version,
)
from app.infrastructure.db.tables import DatasetVersionRow
from app.infrastructure.db.version_sequence import reserve_version_number


class SqliteDatasetVersionRepository(IDatasetVersionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, version: DatasetVersion) -> None:
        self._session.add(dataset_version_to_row(version))
        for item in version.items:
            self._session.add(dataset_item_to_row(item))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DatasetVersionConflictException(
                f"dataset version v{version.version_number} already exists"
            ) from exc

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
        row.train_file_count = version.train_file_count
        row.valid_file_count = version.valid_file_count
        row.test_file_count = version.test_file_count
        row.yaml_path = version.yaml_path
        row.augmentation_json = augmentation_to_dict(version.augmentation)
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
        return await reserve_version_number(
            self._session, project_id, "dataset", DatasetVersionRow
        )

    async def delete(self, version_id: UUID) -> None:
        row = await self._session.get(
            DatasetVersionRow,
            str(version_id),
            options=(selectinload(DatasetVersionRow.items),),
        )
        if row is None:
            return
        await self._session.delete(row)
        await self._session.flush()
