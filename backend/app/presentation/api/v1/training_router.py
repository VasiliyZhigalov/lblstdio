from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from app.application.use_cases.ml.batch_auto_label import (
    BatchAutoLabelUseCase,
    GetAutoLabelJobUseCase,
)
from app.application.use_cases.ml.manage_model_version import (
    DeleteModelVersionUseCase,
    ExportModelVersionUseCase,
    RenameModelVersionUseCase,
    UploadModelVersionUseCase,
)
from app.application.use_cases.ml.train_model import (
    GetTrainingJobUseCase,
    ListModelVersionsUseCase,
    TrainModelUseCase,
)
from app.presentation.dependencies import (
    get_batch_auto_label_use_case,
    get_delete_model_version_use_case,
    get_export_model_version_use_case,
    get_get_auto_label_job_use_case,
    get_get_training_job_use_case,
    get_list_model_versions_use_case,
    get_rename_model_version_use_case,
    get_train_model_use_case,
    get_upload_model_version_use_case,
)
from app.presentation.schemas import (
    AutoLabelJobRead,
    AutoLabelRequest,
    ModelVersionRead,
    RenameRequest,
    TrainModelRequest,
    TrainingDeviceRead,
    TrainingJobRead,
)
from app.infrastructure.ml.device import describe_training_device, probe_training_device

router = APIRouter(tags=["training"])


def _job_to_read(job) -> TrainingJobRead:
    return TrainingJobRead(
        id=job.id,
        project_id=job.project_id,
        dataset_version_id=job.dataset_version_id,
        status=job.status.value,
        epochs=job.epochs,
        patience=job.patience,
        batch_size=job.batch_size,
        imgsz=job.imgsz,
        device=job.device,
        device_label=describe_training_device(job.device),
        base_weights=job.base_weights,
        current_epoch=job.current_epoch,
        stopped_early=job.stopped_early,
        progress_percent=job.progress_percent,
        metrics_history=list(job.metrics_history),
        model_version_id=job.model_version_id,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _model_to_read(model) -> ModelVersionRead:
    return ModelVersionRead(
        id=model.id,
        project_id=model.project_id,
        dataset_version_id=model.dataset_version_id,
        training_job_id=model.training_job_id,
        version_number=model.version_number,
        name=model.name,
        weights_path=model.weights_path,
        map50=model.map50,
        map50_95=model.map50_95,
        precision=model.precision,
        recall=model.recall,
        is_active_for_stream=model.is_active_for_stream,
        display_name=model.display_name,
        created_at=model.created_at,
    )


def _auto_to_read(job) -> AutoLabelJobRead:
    return AutoLabelJobRead(
        id=job.id,
        project_id=job.project_id,
        model_version_id=job.model_version_id,
        confidence_threshold=job.confidence_threshold,
        iou_threshold=job.iou_threshold,
        status=job.status.value,
        image_ids=list(job.image_ids),
        total_images_processed=job.total_images_processed,
        total_predictions_generated=job.total_predictions_generated,
        error_message=job.error_message,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


@router.get("/training/device", response_model=TrainingDeviceRead)
async def get_training_device() -> TrainingDeviceRead:
    payload = probe_training_device("auto")
    return TrainingDeviceRead(**payload)


@router.post(
    "/projects/{project_id}/train",
    response_model=TrainingJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_training(
    project_id: UUID,
    payload: TrainModelRequest,
    use_case: TrainModelUseCase = Depends(get_train_model_use_case),
) -> TrainingJobRead:
    job = await use_case.execute(
        project_id,
        payload.dataset_version_id,
        epochs=payload.epochs,
        batch_size=payload.batch_size,
        imgsz=payload.imgsz,
        device=payload.device,
        base_weights=payload.base_weights,
        base_model_version_id=payload.base_model_version_id,
        patience=payload.patience,
    )
    return _job_to_read(job)


@router.get("/training-jobs/{job_id}", response_model=TrainingJobRead)
async def get_training_job(
    job_id: UUID,
    use_case: GetTrainingJobUseCase = Depends(get_get_training_job_use_case),
) -> TrainingJobRead:
    return _job_to_read(await use_case.execute(job_id))


@router.get(
    "/projects/{project_id}/models",
    response_model=list[ModelVersionRead],
)
async def list_models(
    project_id: UUID,
    use_case: ListModelVersionsUseCase = Depends(get_list_model_versions_use_case),
) -> list[ModelVersionRead]:
    return [_model_to_read(item) for item in await use_case.execute(project_id)]


@router.post(
    "/projects/{project_id}/models/upload",
    response_model=ModelVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_model(
    project_id: UUID,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    use_case: UploadModelVersionUseCase = Depends(get_upload_model_version_use_case),
) -> ModelVersionRead:
    raw = await file.read()
    model = await use_case.execute(
        project_id,
        filename=file.filename or "best.pt",
        data=raw,
        name=name,
    )
    return _model_to_read(model)


@router.patch(
    "/projects/{project_id}/models/{model_id}",
    response_model=ModelVersionRead,
)
async def rename_model(
    project_id: UUID,
    model_id: UUID,
    payload: RenameRequest,
    use_case: RenameModelVersionUseCase = Depends(get_rename_model_version_use_case),
) -> ModelVersionRead:
    return _model_to_read(await use_case.execute(project_id, model_id, payload.name))


@router.get("/projects/{project_id}/models/{model_id}/export")
async def export_model(
    project_id: UUID,
    model_id: UUID,
    use_case: ExportModelVersionUseCase = Depends(get_export_model_version_use_case),
) -> Response:
    archive, filename = await use_case.execute(project_id, model_id)
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/projects/{project_id}/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_model(
    project_id: UUID,
    model_id: UUID,
    use_case: DeleteModelVersionUseCase = Depends(get_delete_model_version_use_case),
) -> None:
    await use_case.execute(project_id, model_id)


@router.post(
    "/projects/{project_id}/models/{model_id}/auto-label",
    response_model=AutoLabelJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def auto_label(
    project_id: UUID,
    model_id: UUID,
    payload: AutoLabelRequest,
    use_case: BatchAutoLabelUseCase = Depends(get_batch_auto_label_use_case),
) -> AutoLabelJobRead:
    job = await use_case.execute(
        project_id,
        model_id,
        image_ids=payload.image_ids,
        all_unannotated=payload.all_unannotated,
        confidence_threshold=payload.confidence_threshold,
        iou_threshold=payload.iou_threshold,
    )
    return _auto_to_read(job)


@router.get(
    "/auto-label-jobs/{job_id}",
    response_model=AutoLabelJobRead,
)
async def get_auto_label_job(
    job_id: UUID,
    use_case: GetAutoLabelJobUseCase = Depends(get_get_auto_label_job_use_case),
) -> AutoLabelJobRead:
    return _auto_to_read(await use_case.execute(job_id))
