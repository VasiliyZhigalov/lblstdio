from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.project import Project


class IProjectRepository(ABC):
    @abstractmethod
    async def add(self, project: Project) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, project_id: UUID) -> Project | None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Project]:
        raise NotImplementedError

    @abstractmethod
    async def update(self, project: Project) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, project_id: UUID) -> None:
        raise NotImplementedError
