from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.application.use_cases.ml.batch_auto_label import (
    BatchAutoLabelUseCase,
    GetAutoLabelJobUseCase,
)
from app.application.use_cases.ml.audit_annotations import AuditAnnotationsRunner
from app.application.use_cases.ml.manage_model_version import (
    DeleteModelVersionUseCase,
    ExportModelVersionUseCase,
    RenameModelVersionUseCase,
    UploadModelVersionUseCase,
    MAX_MODEL_UPLOAD_BYTES,
)
from app.application.use_cases.ml.train_model import (
    GetTrainingJobUseCase,
    ListModelVersionsUseCase,
    TrainModelUseCase,
)
from app.domain.exceptions import DomainValidationException
from app.presentation.dependencies import (
    get_batch_auto_label_use_case,
    get_audit_annotations_runner,
    get_delete_model_version_use_case,
    get_export_model_version_use_case,
    get_get_auto_label_job_use_case,
    get_get_training_job_use_case,
    get_list_model_versions_use_case,
    get_rename_model_version_use_case,
    get_train_model_use_case,
    get_upload_model_version_use_case,
)
from app.presentation.streaming_io import UploadTooLarge, discard_file, spool_upload
from app.presentation.schemas import (
    AutoLabelJobRead,
    AutoLabelRequest,
    AnnotationAuditRequest,
    AnnotationAuditTaskRead,
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
        test_metrics=job.test_metrics,
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
        top1=getattr(model, "top1", None),
        test_metrics=getattr(model, "test_metrics", None),
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
        consistency_iou_threshold=job.consistency_iou_threshold,
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
    spooled: Path | None = None
    try:
        try:
            spooled = await spool_upload(file, max_bytes=MAX_MODEL_UPLOAD_BYTES)
        except UploadTooLarge as exc:
            raise DomainValidationException(
                f"weights file exceeds {exc.limit_bytes // (1024 * 1024)} MB limit"
            ) from exc
        model = await use_case.execute(
            project_id,
            filename=file.filename or "best.pt",
            source_path=spooled,
            name=name,
        )
        return _model_to_read(model)
    finally:
        if spooled is not None:
            spooled.unlink(missing_ok=True)
        await file.close()


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
) -> FileResponse:
    path, filename = await use_case.execute(project_id, model_id)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(discard_file, str(path)),
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
        consistency_iou_threshold=payload.consistency_iou_threshold,
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


@router.post(
    "/projects/{project_id}/models/{model_id}/audit-annotations",
    response_model=AnnotationAuditTaskRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def audit_annotations(
    project_id: UUID,
    model_id: UUID,
    payload: AnnotationAuditRequest,
    runner: AuditAnnotationsRunner = Depends(get_audit_annotations_runner),
) -> AnnotationAuditTaskRead:
    task = await runner.start(
        project_id,
        model_id,
        image_ids=payload.image_ids,
        max_images=payload.max_images,
        confidence_threshold=payload.confidence_threshold,
        iou_threshold=payload.iou_threshold,
    )
    return _audit_task_to_read(task)


def _audit_task_to_read(task) -> AnnotationAuditTaskRead:
    return AnnotationAuditTaskRead(
        id=task.id,
        project_id=task.project_id,
        model_version_id=task.model_version_id,
        status=task.status,
        total_images=task.total_images,
        processed_images=task.processed_images,
        suspicious_images=task.suspicious_images,
        error_message=task.error_message,
        created_at=task.created_at,
        finished_at=task.finished_at,
    )


@router.get(
    "/annotation-audit-jobs/{job_id}",
    response_model=AnnotationAuditTaskRead,
)
async def get_annotation_audit_job(
    job_id: UUID,
    runner: AuditAnnotationsRunner = Depends(get_audit_annotations_runner),
) -> AnnotationAuditTaskRead:
    task = await runner.get(job_id)
    if task is None:
        from app.domain.exceptions import ResourceNotFoundException

        raise ResourceNotFoundException(f"annotation audit job {job_id} not found")
    return _audit_task_to_read(task)
