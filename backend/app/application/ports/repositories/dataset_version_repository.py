from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.dataset_version import DatasetVersion


class IDatasetVersionRepository(ABC):
    @abstractmethod
    async def add(self, version: DatasetVersion) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update(self, version: DatasetVersion) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, version_id: UUID) -> DatasetVersion | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> list[DatasetVersion]:
        raise NotImplementedError

    @abstractmethod
    async def next_version_number(self, project_id: UUID) -> int:
        raise NotImplementedError
