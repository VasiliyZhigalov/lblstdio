from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.application.use_cases.classes.create_class import CreateClassUseCase, ListClassesUseCase
from app.application.use_cases.classes.delete_class import DeleteClassUseCase
from app.application.use_cases.dataset.export_yolo import ExportYOLOUseCase
from app.application.use_cases.projects.create_project import (
    CreateProjectUseCase,
    GetProjectUseCase,
    ListProjectsUseCase,
    UpdateProjectUseCase,
)
from app.application.use_cases.projects.delete_project import DeleteProjectUseCase
from app.presentation.dependencies import (
    get_create_class_use_case,
    get_create_project_use_case,
    get_delete_class_use_case,
    get_delete_project_use_case,
    get_export_yolo_use_case,
    get_get_project_use_case,
    get_list_classes_use_case,
    get_list_projects_use_case,
    get_update_project_use_case,
)
from app.presentation.schemas import (
    ClassCreate,
    ClassRead,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)

router = APIRouter(tags=["projects"])


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    use_case: CreateProjectUseCase = Depends(get_create_project_use_case),
) -> ProjectRead:
    project = await use_case.execute(payload.name, payload.description)
    return ProjectRead.model_validate(project, from_attributes=True)


@router.get("/projects", response_model=list[ProjectRead])
async def list_projects(
    use_case: ListProjectsUseCase = Depends(get_list_projects_use_case),
) -> list[ProjectRead]:
    projects = await use_case.execute()
    return [ProjectRead.model_validate(item, from_attributes=True) for item in projects]


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID,
    use_case: GetProjectUseCase = Depends(get_get_project_use_case),
) -> ProjectRead:
    project = await use_case.execute(project_id)
    return ProjectRead.model_validate(project, from_attributes=True)


@router.patch("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    use_case: UpdateProjectUseCase = Depends(get_update_project_use_case),
) -> ProjectRead:
    project = await use_case.execute(project_id, payload.name, payload.description)
    return ProjectRead.model_validate(project, from_attributes=True)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    use_case: DeleteProjectUseCase = Depends(get_delete_project_use_case),
) -> Response:
    await use_case.execute(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/classes",
    response_model=ClassRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_class(
    project_id: UUID,
    payload: ClassCreate,
    use_case: CreateClassUseCase = Depends(get_create_class_use_case),
) -> ClassRead:
    annotation_class = await use_case.execute(
        project_id, payload.name, payload.color_hex
    )
    return ClassRead.model_validate(annotation_class, from_attributes=True)


@router.get("/projects/{project_id}/classes", response_model=list[ClassRead])
async def list_classes(
    project_id: UUID,
    use_case: ListClassesUseCase = Depends(get_list_classes_use_case),
) -> list[ClassRead]:
    classes = await use_case.execute(project_id)
    return [ClassRead.model_validate(item, from_attributes=True) for item in classes]


@router.delete(
    "/projects/{project_id}/classes/{class_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_class(
    project_id: UUID,
    class_id: UUID,
    use_case: DeleteClassUseCase = Depends(get_delete_class_use_case),
) -> Response:
    await use_case.execute(class_id, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/export-yolo")
async def export_yolo(
    project_id: UUID,
    use_case: ExportYOLOUseCase = Depends(get_export_yolo_use_case),
) -> Response:
    payload = await use_case.execute(project_id)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="project-{project_id}-yolo.zip"'
        },
    )
