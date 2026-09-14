from fastapi import APIRouter, Depends

from app.application.dto import BoxInput
from app.application.use_cases.keypoints.propagate_box import PropagateBoxViaKeypointsUseCase
from app.presentation.api.v1.images_router import _annotation_to_read
from app.presentation.dependencies import get_propagate_box_use_case
from app.presentation.schemas import (
    AnnotationRead,
    DebugArrowRead,
    PropagateBoxRequest,
    PropagateBoxesRequest,
    PropagateBoxesResponse,
    TransformDebugRead,
)

router = APIRouter(tags=["matching"])


def _box_input(box) -> BoxInput:
    return BoxInput(
        class_id=box.class_id,
        x_center=box.x_center,
        y_center=box.y_center,
        width=box.width,
        height=box.height,
        annotation_id=box.id,
    )


@router.post("/matching/propagate-box", response_model=AnnotationRead)
async def propagate_box(
    payload: PropagateBoxRequest,
    use_case: PropagateBoxViaKeypointsUseCase = Depends(get_propagate_box_use_case),
) -> AnnotationRead:
    created = await use_case.execute(
        source_image_id=payload.source_image_id,
        target_image_id=payload.target_image_id,
        source_box=_box_input(payload.source_box),
    )
    return _annotation_to_read(created)


@router.post("/matching/propagate-boxes", response_model=PropagateBoxesResponse)
async def propagate_boxes(
    payload: PropagateBoxesRequest,
    use_case: PropagateBoxViaKeypointsUseCase = Depends(get_propagate_box_use_case),
) -> PropagateBoxesResponse:
    result = await use_case.execute_many(
        source_image_id=payload.source_image_id,
        target_image_id=payload.target_image_id,
        source_boxes=[_box_input(box) for box in payload.source_boxes],
    )
    transform = result.transform
    return PropagateBoxesResponse(
        annotations=[_annotation_to_read(item) for item in result.annotations],
        transform=TransformDebugRead(
            tx=transform.tx,
            ty=transform.ty,
            rotation_deg=transform.rotation_deg,
            scale=transform.scale,
            match_score=transform.match_score,
            matrix=[list(transform.matrix[0]), list(transform.matrix[1])],
        ),
        debug_arrows=[
            DebugArrowRead(
                from_x=arrow.from_x,
                from_y=arrow.from_y,
                to_x=arrow.to_x,
                to_y=arrow.to_y,
            )
            for arrow in result.debug_arrows
        ],
    )
