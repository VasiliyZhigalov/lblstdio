from app.domain.entities.project import Project
from app.domain.enums import ProjectTaskType


def test_create_defaults_to_detection() -> None:
    project = Project.create("Det")
    assert project.task_type == ProjectTaskType.DETECTION


def test_create_classification() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    assert project.task_type == ProjectTaskType.CLASSIFICATION


def test_rename_does_not_change_task_type() -> None:
    project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
    project.rename("Other", "desc")
    assert project.task_type == ProjectTaskType.CLASSIFICATION
