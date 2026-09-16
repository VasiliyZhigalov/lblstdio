from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.image import Image


class IImageRepository(ABC):
    @abstractmethod
    async def add_many(self, images: Sequence[Image]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, image_id: UUID) -> Image | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> list[Image]:
        raise NotImplementedError

    @abstractmethod
    async def update(self, image: Image) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, image_id: UUID) -> None:
        raise NotImplementedError
