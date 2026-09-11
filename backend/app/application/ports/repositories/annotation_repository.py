from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.annotation import Annotation


class IAnnotationRepository(ABC):
    @abstractmethod
    async def replace_for_image(
        self, image_id: UUID, annotations: Sequence[Annotation]
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_image(self, image_id: UUID) -> list[Annotation]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_image_ids(self, image_ids: Sequence[UUID]) -> list[Annotation]:
        raise NotImplementedError
