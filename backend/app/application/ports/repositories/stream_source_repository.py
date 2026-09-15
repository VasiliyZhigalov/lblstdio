from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.stream_source import StreamSource


class IStreamSourceRepository(ABC):
    @abstractmethod
    async def add(self, stream: StreamSource) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, stream_id: UUID) -> StreamSource | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> list[StreamSource]:
        raise NotImplementedError

    @abstractmethod
    async def update(self, stream: StreamSource) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, stream_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_active_for_project(self, project_id: UUID) -> StreamSource | None:
        raise NotImplementedError
