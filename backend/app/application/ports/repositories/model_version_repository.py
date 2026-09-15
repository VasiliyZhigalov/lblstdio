from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.model_version import ModelVersion


class IModelVersionRepository(ABC):
    @abstractmethod
    async def add(self, version: ModelVersion) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, version_id: UUID) -> ModelVersion | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> list[ModelVersion]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_dataset_version(
        self, dataset_version_id: UUID
    ) -> list[ModelVersion]:
        raise NotImplementedError

    @abstractmethod
    async def next_version_number(self, project_id: UUID) -> int:
        raise NotImplementedError

    @abstractmethod
    async def deactivate_stream_models(self, project_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update(self, version: ModelVersion) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, version_id: UUID) -> None:
        raise NotImplementedError
