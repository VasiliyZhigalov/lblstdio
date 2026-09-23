import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse, Response
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

from app.application.dto import UploadedFile
from app.application.use_cases.images.delete_image import DeleteImageUseCase
from app.application.use_cases.images.get_image import GetImageUseCase, ListImagesUseCase
from app.application.use_cases.images.set_test_holdout import SetImageTestHoldoutUseCase
from app.application.use_cases.images.upload_images import (
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_ZIP_BYTES,
    UploadImagesUseCase,
)
from app.domain.enums import ImageStatus, SplitType
from app.domain.exceptions import DomainValidationException
from app.infrastructure.storage.local_storage import LocalFileStorage
from app.infrastructure.db.repositories.image_label_repository import (
    SqliteImageLabelRepository,
)
from app.presentation.dependencies import (
    get_delete_image_use_case,
    get_get_image_use_case,
    get_image_label_repo,
    get_list_images_use_case,
    get_set_image_holdout_use_case,
    get_storage,
    get_upload_images_use_case,
)
from app.presentation.schemas import (
    AnnotationRead,
    ImageDetailRead,
    ImageHoldoutRequest,
    ImageLabelRead,
    ImageRead,
)

router = APIRouter(tags=["images"])

_UPLOAD_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["files"],
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "description": "Images, YOLO labels, class metadata, or a zip archive",
                        },
                        "relative_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Relative path for each file, same order as files",
                        },
                    },
                }
            }
        },
    }
}


def _label_to_read(label) -> ImageLabelRead:
    return ImageLabelRead(
        id=label.id,
        image_id=label.image_id,
        class_id=label.class_id,
        source=label.source.value,
        confidence=label.confidence,
        verification_status=label.verification_status.value,
        verified_at=label.verified_at,
        model_version_id=label.model_version_id,
    )


def _image_to_read(image, label=None) -> ImageRead:
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
        is_background=bool(getattr(image, "is_background", False)),
        label=_label_to_read(label) if label is not None else None,
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
        model_version_id=annotation.model_version_id,
    )


@router.post(
    "/projects/{project_id}/images/upload",
    response_model=list[ImageRead],
    status_code=status.HTTP_201_CREATED,
    openapi_extra=_UPLOAD_OPENAPI,
)
async def upload_images(
    project_id: UUID,
    request: Request,
    use_case: UploadImagesUseCase = Depends(get_upload_images_use_case),
) -> list[ImageRead]:
    staging = tempfile.TemporaryDirectory()
    form = None
    try:
        try:
            form = await request.form(
                max_files=MAX_UPLOAD_FILES,
                max_fields=MAX_UPLOAD_FILES + 16,
                max_part_size=MAX_UPLOAD_ZIP_BYTES,
            )
        except MultiPartException as exc:
            raise DomainValidationException(exc.message) from exc
        except HTTPException as exc:
            if exc.status_code == 400:
                raise DomainValidationException(str(exc.detail)) from exc
            raise

        files = [item for item in form.getlist("files") if isinstance(item, UploadFile)]
        paths = [str(item) for item in form.getlist("relative_paths")]
        if paths and len(paths) != len(files):
            raise DomainValidationException(
                "relative_paths count must match files count"
            )
        uploaded: list[UploadedFile] = []
        for index, item in enumerate(files):
            raw_name = paths[index] if paths else (item.filename or "upload.bin")
            # Browsers may use backslashes; normalize early.
            filename = str(raw_name).replace("\\", "/")
            dest = Path(staging.name) / f"{index:05d}"
            with dest.open("wb") as handle:
                while True:
                    chunk = await item.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            await item.close()
            uploaded.append(UploadedFile(filename=filename, body_path=str(dest)))
        images = await use_case.execute(project_id, uploaded)
        return [_image_to_read(item) for item in images]
    finally:
        if form is not None:
            try:
                await form.close()
            except OSError:
                pass
        staging.cleanup()


@router.get("/projects/{project_id}/images", response_model=list[ImageRead])
async def list_images(
    project_id: UUID,
    split: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1),
    use_case: ListImagesUseCase = Depends(get_list_images_use_case),
    labels: SqliteImageLabelRepository = Depends(get_image_label_repo),
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
    by_image = {
        item.image_id: item
        for item in await labels.list_by_image_ids([image.id for image in images])
    }
    return [_image_to_read(item, by_image.get(item.id)) for item in images]


@router.get("/images/{image_id}", response_model=ImageDetailRead)
async def get_image(
    image_id: UUID,
    use_case: GetImageUseCase = Depends(get_get_image_use_case),
) -> ImageDetailRead:
    image, annotations, label = await use_case.execute(image_id)
    payload = _image_to_read(image, label).model_dump()
    payload["annotations"] = [_annotation_to_read(item) for item in annotations]
    return ImageDetailRead(**payload)


@router.get("/images/{image_id}/file")
async def get_image_file(
    image_id: UUID,
    use_case: GetImageUseCase = Depends(get_get_image_use_case),
    storage: LocalFileStorage = Depends(get_storage),
) -> FileResponse:
    image, _, _ = await use_case.execute(image_id)
    return FileResponse(
        path=storage.get_absolute_path(image.file_path),
        filename=image.file_name,
        content_disposition_type="inline",
    )


@router.put("/images/{image_id}/holdout", response_model=ImageRead)
async def set_image_holdout(
    image_id: UUID,
    payload: ImageHoldoutRequest,
    use_case: SetImageTestHoldoutUseCase = Depends(get_set_image_holdout_use_case),
) -> ImageRead:
    image = await use_case.execute(image_id, payload.holdout)
    return _image_to_read(image)


@router.delete(
    "/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_image(
    image_id: UUID,
    use_case: DeleteImageUseCase = Depends(get_delete_image_use_case),
) -> Response:
    await use_case.execute(image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
