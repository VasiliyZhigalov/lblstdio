from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.application.dto import UploadedFile
from app.application.use_cases.images.get_image import GetImageUseCase, ListImagesUseCase
from app.application.use_cases.images.upload_images import UploadImagesUseCase
from app.domain.enums import ImageStatus, SplitType
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.split_ratios import SplitRatios
from app.infrastructure.storage.local_storage import LocalFileStorage
from app.presentation.dependencies import (
    get_get_image_use_case,
    get_list_images_use_case,
    get_storage,
    get_upload_images_use_case,
)
from app.presentation.schemas import AnnotationRead, ImageDetailRead, ImageRead

router = APIRouter(tags=["images"])


def _image_to_read(image) -> ImageRead:
    return ImageRead(
        id=image.id,
        project_id=image.project_id,
        file_path=image.file_path,
        file_name=image.file_name,
        width=image.width,
        height=image.height,
        split=image.split.value,
        status=image.status.value,
        source_type=image.source_type.value,
        created_at=image.created_at,
    )


def _annotation_to_read(annotation) -> AnnotationRead:
    return AnnotationRead(
        id=annotation.id,
        image_id=annotation.image_id,
        class_id=annotation.class_id,
        x_center=annotation.bbox.x_center,
        y_center=annotation.bbox.y_center,
        width=annotation.bbox.width,
        height=annotation.bbox.height,
        source=annotation.source.value,
        confidence=annotation.confidence,
        verification_status=annotation.verification_status.value,
        verified_at=annotation.verified_at,
        source_annotation_id=annotation.source_annotation_id,
    )


@router.post(
    "/projects/{project_id}/images/upload",
    response_model=list[ImageRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_images(
    project_id: UUID,
    files: list[UploadFile] = File(...),
    train: float = Form(0.7),
    valid: float = Form(0.2),
    test: float = Form(0.1),
    use_case: UploadImagesUseCase = Depends(get_upload_images_use_case),
) -> list[ImageRead]:
    uploaded = [
        UploadedFile(filename=item.filename or "upload.bin", content=await item.read())
        for item in files
    ]
    images = await use_case.execute(
        project_id,
        uploaded,
        ratios=SplitRatios(train=train, valid=valid, test=test),
    )
    return [_image_to_read(item) for item in images]


@router.get("/projects/{project_id}/images", response_model=list[ImageRead])
async def list_images(
    project_id: UUID,
    split: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1),
    use_case: ListImagesUseCase = Depends(get_list_images_use_case),
) -> list[ImageRead]:
    split_value: SplitType | None = None
    status_value: ImageStatus | None = None
    if split is not None:
        try:
            split_value = SplitType(split)
        except ValueError as exc:
            raise DomainValidationException(f"unknown split '{split}'") from exc
    if status_filter is not None:
        try:
            status_value = ImageStatus(status_filter)
        except ValueError as exc:
            raise DomainValidationException(f"unknown status '{status_filter}'") from exc
    images = await use_case.execute(
        project_id,
        split=split_value,
        status=status_value,
        offset=offset,
        limit=limit,
    )
    return [_image_to_read(item) for item in images]


@router.get("/images/{image_id}", response_model=ImageDetailRead)
async def get_image(
    image_id: UUID,
    use_case: GetImageUseCase = Depends(get_get_image_use_case),
) -> ImageDetailRead:
    image, annotations = await use_case.execute(image_id)
    payload = _image_to_read(image).model_dump()
    payload["annotations"] = [_annotation_to_read(item) for item in annotations]
    return ImageDetailRead(**payload)


@router.get("/images/{image_id}/file")
async def get_image_file(
    image_id: UUID,
    use_case: GetImageUseCase = Depends(get_get_image_use_case),
    storage: LocalFileStorage = Depends(get_storage),
) -> FileResponse:
    image, _ = await use_case.execute(image_id)
    return FileResponse(
        path=storage.get_absolute_path(image.file_path),
        filename=image.file_name,
        content_disposition_type="inline",
    )
