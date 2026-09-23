from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.image_label import ImageLabel


class IImageLabelRepository(ABC):
    @abstractmethod
    async def get_by_image_id(self, image_id: UUID) -> ImageLabel | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_image_ids(self, image_ids: Sequence[UUID]) -> list[ImageLabel]:
        raise NotImplementedError

    @abstractmethod
    async def upsert(self, label: ImageLabel) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_image_id(self, image_id: UUID) -> None:
        raise NotImplementedError
