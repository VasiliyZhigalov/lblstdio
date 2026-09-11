from uuid import UUID

from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.exceptions import ResourceNotFoundException


class DeleteProjectUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        storage: IFileStorage,
        uow: IUnitOfWork,
    ) -> None:
        self._projects = projects
        self._storage = storage
        self._uow = uow

    async def execute(self, project_id: UUID) -> None:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")
        await self._projects.delete(project_id)
        await self._uow.commit()
        await self._storage.delete_directory(f"projects/{project_id}")
