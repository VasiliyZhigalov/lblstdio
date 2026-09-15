from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.auto_label_job import AutoLabelJob
from app.domain.enums import AutoLabelJobStatus


class IAutoLabelJobRepository(ABC):
    @abstractmethod
    async def add(self, job: AutoLabelJob) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update(self, job: AutoLabelJob) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, job_id: UUID) -> AutoLabelJob | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_statuses(
        self, statuses: Sequence[AutoLabelJobStatus]
    ) -> list[AutoLabelJob]:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_model_version(self, model_version_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_model_versions(
        self, model_version_ids: Sequence[UUID]
    ) -> None:
        raise NotImplementedError
