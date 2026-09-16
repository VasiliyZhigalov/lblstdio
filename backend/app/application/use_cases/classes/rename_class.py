from uuid import UUID

from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException


class RenameClassUseCase:
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
        self, class_id: UUID, project_id: UUID, name: str
    ) -> AnnotationClass:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")

        annotation_class = await self._classes.get_by_id(class_id)
        if annotation_class is None or annotation_class.project_id != project_id:
            raise ResourceNotFoundException(f"class {class_id} not found")

        normalized = name.strip()
        existing = await self._classes.list_by_project(project_id)
        if any(
            item.id != class_id and item.name == normalized for item in existing
        ):
            raise DomainValidationException(
                f"class name '{normalized}' already exists in this project"
            )

        annotation_class.rename(normalized)
        await self._classes.update_many([annotation_class])
        await self._uow.commit()
        return annotation_class
