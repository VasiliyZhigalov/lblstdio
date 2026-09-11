from uuid import UUID

from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.project import Project
from app.domain.exceptions import ResourceNotFoundException


class CreateProjectUseCase:
    def __init__(self, projects: IProjectRepository, uow: IUnitOfWork) -> None:
        self._projects = projects
        self._uow = uow

    async def execute(self, name: str, description: str | None = None) -> Project:
        project = Project.create(name=name, description=description)
        await self._projects.add(project)
        await self._uow.commit()
        return project


class ListProjectsUseCase:
    def __init__(self, projects: IProjectRepository) -> None:
        self._projects = projects

    async def execute(self) -> list[Project]:
        return await self._projects.list_all()


class GetProjectUseCase:
    def __init__(self, projects: IProjectRepository) -> None:
        self._projects = projects

    async def execute(self, project_id: UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")
        return project
