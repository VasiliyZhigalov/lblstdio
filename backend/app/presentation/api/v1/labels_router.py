from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.application.use_cases.labels.save_image_label import (
    ClearImageLabelUseCase,
    ConfirmImageLabelUseCase,
    SaveImageLabelUseCase,
)
from app.presentation.api.v1.images_router import _image_to_read, _label_to_read
from app.presentation.dependencies import (
    get_clear_image_label_use_case,
    get_confirm_image_label_use_case,
    get_save_image_label_use_case,
)
from app.presentation.schemas import ImageLabelAssign, ImageLabelRead

router = APIRouter(tags=["labels"])


@router.put("/images/{image_id}/label", response_model=ImageLabelRead)
async def save_image_label(
    image_id: UUID,
    payload: ImageLabelAssign,
    use_case: SaveImageLabelUseCase = Depends(get_save_image_label_use_case),
) -> ImageLabelRead:
    label = await use_case.execute(image_id, payload.class_id)
    return _label_to_read(label)


@router.delete("/images/{image_id}/label", status_code=status.HTTP_204_NO_CONTENT)
async def clear_image_label(
    image_id: UUID,
    use_case: ClearImageLabelUseCase = Depends(get_clear_image_label_use_case),
) -> Response:
    await use_case.execute(image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/images/{image_id}/label/confirm", response_model=ImageLabelRead)
async def confirm_image_label(
    image_id: UUID,
    use_case: ConfirmImageLabelUseCase = Depends(get_confirm_image_label_use_case),
) -> ImageLabelRead:
    label = await use_case.execute(image_id)
    return _label_to_read(label)


@router.post("/images/{image_id}/label/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_image_label(
    image_id: UUID,
    use_case: ClearImageLabelUseCase = Depends(get_clear_image_label_use_case),
) -> Response:
    await use_case.execute(image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
