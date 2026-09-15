from uuid import UUID

from fastapi import APIRouter, Depends

from app.application.dto import BoxInput
from app.application.use_cases.annotations.mark_background import (
    MarkImageAsBackgroundUseCase,
)
from app.application.use_cases.annotations.save_annotations import SaveAnnotationsUseCase
from app.application.use_cases.annotations.verify_annotation import (
    DeleteAnnotationUseCase,
    RejectAllPendingAnnotationsUseCase,
    VerifyAllAnnotationsUseCase,
    VerifyAnnotationUseCase,
)
from app.presentation.api.v1.images_router import _annotation_to_read, _image_to_read
from app.presentation.dependencies import (
    get_delete_annotation_use_case,
    get_mark_background_use_case,
    get_reject_all_pending_use_case,
    get_save_annotations_use_case,
    get_verify_all_annotations_use_case,
    get_verify_annotation_use_case,
)
from app.presentation.schemas import AnnotationRead, ImageRead, SaveAnnotationsRequest

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


@router.post(
    "/images/{image_id}/annotations/{annotation_id}/verify",
    response_model=AnnotationRead,
)
async def verify_annotation(
    image_id: UUID,
    annotation_id: UUID,
    use_case: VerifyAnnotationUseCase = Depends(get_verify_annotation_use_case),
) -> AnnotationRead:
    annotation = await use_case.execute(image_id, annotation_id)
    return _annotation_to_read(annotation)


@router.post("/images/{image_id}/verify-all", response_model=list[AnnotationRead])
async def verify_all_annotations(
    image_id: UUID,
    use_case: VerifyAllAnnotationsUseCase = Depends(get_verify_all_annotations_use_case),
) -> list[AnnotationRead]:
    annotations = await use_case.execute(image_id)
    return [_annotation_to_read(item) for item in annotations]


@router.post("/images/{image_id}/reject-pending", response_model=list[AnnotationRead])
async def reject_all_pending_annotations(
    image_id: UUID,
    use_case: RejectAllPendingAnnotationsUseCase = Depends(
        get_reject_all_pending_use_case
    ),
) -> list[AnnotationRead]:
    remaining = await use_case.execute(image_id)
    return [_annotation_to_read(item) for item in remaining]


@router.post("/images/{image_id}/mark-background", response_model=ImageRead)
async def mark_image_as_background(
    image_id: UUID,
    use_case: MarkImageAsBackgroundUseCase = Depends(get_mark_background_use_case),
) -> ImageRead:
    image = await use_case.execute(image_id)
    return _image_to_read(image)


@router.delete(
    "/images/{image_id}/annotations/{annotation_id}",
    response_model=list[AnnotationRead],
)
async def delete_annotation(
    image_id: UUID,
    annotation_id: UUID,
    use_case: DeleteAnnotationUseCase = Depends(get_delete_annotation_use_case),
) -> list[AnnotationRead]:
    remaining = await use_case.execute(image_id, annotation_id)
    return [_annotation_to_read(item) for item in remaining]
