from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.application.use_cases.dataset.create_dataset_version import (
    CreateDatasetVersionUseCase,
    GetDatasetVersionUseCase,
    ListDatasetVersionsUseCase,
)
from app.application.use_cases.dataset.manage_dataset_version import (
    DeleteDatasetVersionUseCase,
    ExportDatasetVersionUseCase,
    RenameDatasetVersionUseCase,
)
from app.domain.entities.dataset_version import (
    DEFAULT_MIN_VERIFIED_IMAGES,
    AugmentationConfig,
)
from app.domain.value_objects.split_ratios import SplitRatios
from app.presentation.dependencies import (
    get_create_dataset_version_use_case,
    get_delete_dataset_version_use_case,
    get_export_dataset_version_use_case,
    get_get_dataset_version_use_case,
    get_list_dataset_versions_use_case,
    get_rename_dataset_version_use_case,
)
from app.presentation.schemas import (
    AugmentationConfigPayload,
    CreateDatasetVersionRequest,
    DatasetVersionRead,
    RenameRequest,
)

router = APIRouter(tags=["dataset-versions"])


def _aug_payload(version) -> AugmentationConfigPayload:
    aug = version.augmentation
    return AugmentationConfigPayload(
        resize_width=aug.resize_width,
        resize_height=aug.resize_height,
        horizontal_flip=aug.horizontal_flip,
        vertical_flip=aug.vertical_flip,
        rotate=aug.rotate,
        shear=aug.shear,
        hue_saturation=aug.hue_saturation,
        brightness_contrast=aug.brightness_contrast,
        blur=aug.blur,
        noise=aug.noise,
        grayscale=aug.grayscale,
        cutout=aug.cutout,
        shift_scale_rotate=aug.shift_scale_rotate,
        multiplier=aug.multiplier,
    )


def _to_read(version) -> DatasetVersionRead:
    return DatasetVersionRead(
        id=version.id,
        project_id=version.project_id,
        version_number=version.version_number,
        name=version.name,
        status=version.status.value,
        train_count=version.train_count,
        valid_count=version.valid_count,
        test_count=version.test_count,
        train_file_count=version.train_file_count,
        valid_file_count=version.valid_file_count,
        test_file_count=version.test_file_count,
        yaml_path=version.yaml_path,
        created_at=version.created_at,
        augmentation=_aug_payload(version),
        item_count=len(version.items),
        min_verified_required=DEFAULT_MIN_VERIFIED_IMAGES,
    )


@router.post(
    "/projects/{project_id}/dataset-versions",
    response_model=DatasetVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset_version(
    project_id: UUID,
    payload: CreateDatasetVersionRequest | None = None,
    use_case: CreateDatasetVersionUseCase = Depends(get_create_dataset_version_use_case),
) -> DatasetVersionRead:
    body = payload or CreateDatasetVersionRequest()
    aug = body.augmentation or AugmentationConfigPayload()
    version = await use_case.execute(
        project_id,
        AugmentationConfig(
            resize_width=aug.resize_width,
            resize_height=aug.resize_height,
            horizontal_flip=aug.horizontal_flip,
            vertical_flip=aug.vertical_flip,
            rotate=aug.rotate or aug.shift_scale_rotate,
            shear=aug.shear or aug.shift_scale_rotate,
            hue_saturation=aug.hue_saturation,
            brightness_contrast=aug.brightness_contrast,
            blur=aug.blur,
            noise=aug.noise,
            grayscale=aug.grayscale,
            cutout=aug.cutout,
            shift_scale_rotate=False,
            multiplier=aug.multiplier,
        ),
        name=body.name,
        ratios=SplitRatios(train=body.train, valid=body.valid, test=body.test),
    )
    return _to_read(version)


@router.get(
    "/projects/{project_id}/dataset-versions",
    response_model=list[DatasetVersionRead],
)
async def list_dataset_versions(
    project_id: UUID,
    use_case: ListDatasetVersionsUseCase = Depends(get_list_dataset_versions_use_case),
) -> list[DatasetVersionRead]:
    versions = await use_case.execute(project_id)
    return [_to_read(item) for item in versions]


@router.get(
    "/dataset-versions/{version_id}",
    response_model=DatasetVersionRead,
)
async def get_dataset_version(
    version_id: UUID,
    use_case: GetDatasetVersionUseCase = Depends(get_get_dataset_version_use_case),
) -> DatasetVersionRead:
    version = await use_case.execute(version_id)
    return _to_read(version)


@router.patch(
    "/dataset-versions/{version_id}",
    response_model=DatasetVersionRead,
)
async def rename_dataset_version(
    version_id: UUID,
    payload: RenameRequest,
    use_case: RenameDatasetVersionUseCase = Depends(get_rename_dataset_version_use_case),
) -> DatasetVersionRead:
    return _to_read(await use_case.execute(version_id, payload.name))


@router.get("/dataset-versions/{version_id}/export")
async def export_dataset_version(
    version_id: UUID,
    use_case: ExportDatasetVersionUseCase = Depends(get_export_dataset_version_use_case),
) -> Response:
    archive, filename = await use_case.execute(version_id)
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/dataset-versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_dataset_version(
    version_id: UUID,
    use_case: DeleteDatasetVersionUseCase = Depends(get_delete_dataset_version_use_case),
) -> None:
    await use_case.execute(version_id)
