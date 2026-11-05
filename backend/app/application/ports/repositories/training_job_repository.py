from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.training_job import TrainingJob
from app.domain.enums import TrainingJobStatus


class ITrainingJobRepository(ABC):
    @abstractmethod
    async def add(self, job: TrainingJob) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update(self, job: TrainingJob) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, job_id: UUID) -> TrainingJob | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_dataset_version(
        self, dataset_version_id: UUID
    ) -> list[TrainingJob]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_statuses(
        self, statuses: Sequence[TrainingJobStatus]
    ) -> list[TrainingJob]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> list[TrainingJob]:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_dataset_version(self, dataset_version_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, job_id: UUID) -> None:
        raise NotImplementedError
