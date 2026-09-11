from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.annotation_class import AnnotationClass


class IClassRepository(ABC):
    @abstractmethod
    async def add(self, annotation_class: AnnotationClass) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, class_id: UUID) -> AnnotationClass | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, class_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update_many(self, classes: Sequence[AnnotationClass]) -> None:
        raise NotImplementedError
