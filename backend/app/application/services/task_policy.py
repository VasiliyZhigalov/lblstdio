from app.domain.entities.project import Project
from app.domain.enums import ProjectTaskType
from app.domain.exceptions import TaskTypeMismatchException


def require_task(project: Project, expected: ProjectTaskType) -> None:
    if project.task_type != expected:
        raise TaskTypeMismatchException(
            f"operation requires {expected.value} project, got {project.task_type.value}"
        )
