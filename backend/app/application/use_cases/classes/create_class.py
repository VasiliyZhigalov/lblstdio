from uuid import UUID

from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.services.class_index import allocate_next_index


class CreateClassUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        classes: IClassRepository,
        uow: IUnitOfWork,
    ) -> None:
        self._projects = projects
        self._classes = classes
        self._uow = uow

    async def execute(
        self, project_id: UUID, name: str, color_hex: str
    ) -> AnnotationClass:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")

        existing = await self._classes.list_by_project(project_id)
        normalized = name.strip()
        if any(item.name == normalized for item in existing):
            raise DomainValidationException(
                f"class name '{normalized}' already exists in this project"
            )

        index_id = allocate_next_index([item.index_id for item in existing])
        annotation_class = AnnotationClass.create(
            project_id=project_id,
            name=normalized,
            color_hex=color_hex,
            index_id=index_id,
        )
        await self._classes.add(annotation_class)
        await self._uow.commit()
        return annotation_class


class ListClassesUseCase:
    def __init__(self, classes: IClassRepository) -> None:
        self._classes = classes

    async def execute(self, project_id: UUID) -> list[AnnotationClass]:
        return await self._classes.list_by_project(project_id)
