from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.application.use_cases.dataset.create_dataset_version import (
    CreateDatasetVersionUseCase,
    GetDatasetVersionUseCase,
    ListDatasetVersionsUseCase,
)
from app.domain.entities.dataset_version import AugmentationConfig
from app.presentation.dependencies import (
    get_create_dataset_version_use_case,
    get_get_dataset_version_use_case,
    get_list_dataset_versions_use_case,
)
from app.presentation.schemas import (
    AugmentationConfigPayload,
    CreateDatasetVersionRequest,
    DatasetVersionRead,
)

router = APIRouter(tags=["dataset-versions"])


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
        yaml_path=version.yaml_path,
        created_at=version.created_at,
        augmentation=AugmentationConfigPayload(
            resize_width=version.augmentation.resize_width,
            resize_height=version.augmentation.resize_height,
            horizontal_flip=version.augmentation.horizontal_flip,
            brightness_contrast=version.augmentation.brightness_contrast,
            blur=version.augmentation.blur,
            shift_scale_rotate=version.augmentation.shift_scale_rotate,
            multiplier=version.augmentation.multiplier,
        ),
        item_count=len(version.items),
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
            brightness_contrast=aug.brightness_contrast,
            blur=aug.blur,
            shift_scale_rotate=aug.shift_scale_rotate,
            multiplier=aug.multiplier,
        ),
        name=body.name,
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
