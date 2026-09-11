from uuid import UUID

from fastapi import APIRouter, Depends

from app.application.dto import BoxInput
from app.application.use_cases.annotations.save_annotations import SaveAnnotationsUseCase
from app.presentation.api.v1.images_router import _annotation_to_read
from app.presentation.dependencies import get_save_annotations_use_case
from app.presentation.schemas import AnnotationRead, SaveAnnotationsRequest

router = APIRouter(tags=["annotations"])


@router.put("/images/{image_id}/annotations", response_model=list[AnnotationRead])
async def save_annotations(
    image_id: UUID,
    payload: SaveAnnotationsRequest,
    use_case: SaveAnnotationsUseCase = Depends(get_save_annotations_use_case),
) -> list[AnnotationRead]:
    annotations = await use_case.execute(
        image_id,
        [
            BoxInput(
                class_id=box.class_id,
                x_center=box.x_center,
                y_center=box.y_center,
                width=box.width,
                height=box.height,
                annotation_id=box.id,
            )
            for box in payload.boxes
        ],
    )
    return [_annotation_to_read(item) for item in annotations]
