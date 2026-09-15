from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.application.use_cases.classes.create_class import CreateClassUseCase, ListClassesUseCase
from app.application.use_cases.classes.delete_class import DeleteClassUseCase
from app.application.use_cases.dataset.create_dataset_version import (
    CreateDatasetVersionUseCase,
    GetDatasetVersionUseCase,
    ListDatasetVersionsUseCase,
)
from app.application.use_cases.dataset.export_yolo import ExportYOLOUseCase
from app.application.use_cases.dataset.manage_dataset_version import (
    DeleteDatasetVersionUseCase,
    ExportDatasetVersionUseCase,
    RenameDatasetVersionUseCase,
)
from app.application.use_cases.images.get_image import GetImageUseCase, ListImagesUseCase
from app.application.use_cases.images.upload_images import UploadImagesUseCase
from app.application.use_cases.keypoints.propagate_box import PropagateBoxViaKeypointsUseCase
from app.application.use_cases.projects.create_project import (
    CreateProjectUseCase,
    GetProjectUseCase,
    ListProjectsUseCase,
    UpdateProjectUseCase,
)
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
from app.application.use_cases.projects.delete_project import DeleteProjectUseCase
from app.application.use_cases.streaming.control_stream import (
    GetStreamStatusUseCase,
    StartStreamUseCase,
    StopStreamUseCase,
)
from app.application.use_cases.streaming.manage_stream_source import ManageStreamSourceUseCase
from app.infrastructure.db.repositories.annotation_repository import (
    SqliteAnnotationRepository,
)
from app.infrastructure.db.repositories.auto_label_job_repository import (
    SqliteAutoLabelJobRepository,
)
from app.infrastructure.db.repositories.class_repository import SqliteClassRepository
from app.infrastructure.db.repositories.dataset_version_repository import (
    SqliteDatasetVersionRepository,
)
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.model_version_repository import (
    SqliteModelVersionRepository,
)
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.repositories.stream_source_repository import (
    SqliteStreamSourceRepository,
)
from app.infrastructure.db.repositories.training_job_repository import (
    SqliteTrainingJobRepository,
)
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.ml.albumentations_service import AlbumentationsAugmentationService
from app.infrastructure.ml.sift_matcher import SiftKeypointMatcher
from app.infrastructure.ml.ultralytics_predictor import UltralyticsPredictor
from app.infrastructure.storage.local_storage import LocalFileStorage
from app.infrastructure.storage.pillow_metadata import PillowMetadataReader
from app.infrastructure.storage.zip_packer import ZipArchivePacker

async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_storage(request: Request) -> LocalFileStorage:
    return request.app.state.storage


def get_metadata_reader(request: Request) -> PillowMetadataReader:
    return request.app.state.metadata_reader


def get_project_repo(session: AsyncSession = Depends(get_session)) -> SqliteProjectRepository:
    return SqliteProjectRepository(session)


def get_class_repo(session: AsyncSession = Depends(get_session)) -> SqliteClassRepository:
    return SqliteClassRepository(session)


def get_image_repo(session: AsyncSession = Depends(get_session)) -> SqliteImageRepository:
    return SqliteImageRepository(session)


def get_annotation_repo(
    session: AsyncSession = Depends(get_session),
) -> SqliteAnnotationRepository:
    return SqliteAnnotationRepository(session)


def get_dataset_version_repo(
    session: AsyncSession = Depends(get_session),
) -> SqliteDatasetVersionRepository:
    return SqliteDatasetVersionRepository(session)


def get_training_job_repo(
    session: AsyncSession = Depends(get_session),
) -> SqliteTrainingJobRepository:
    return SqliteTrainingJobRepository(session)


def get_model_version_repo(
    session: AsyncSession = Depends(get_session),
) -> SqliteModelVersionRepository:
    return SqliteModelVersionRepository(session)


def get_auto_label_job_repo(
    session: AsyncSession = Depends(get_session),
) -> SqliteAutoLabelJobRepository:
    return SqliteAutoLabelJobRepository(session)


def get_stream_source_repo(
    session: AsyncSession = Depends(get_session),
) -> SqliteStreamSourceRepository:
    return SqliteStreamSourceRepository(session)


def get_uow(session: AsyncSession = Depends(get_session)) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session)


def get_manage_stream_source_use_case(
    request: Request,
    projects: SqliteProjectRepository = Depends(get_project_repo),
    streams: SqliteStreamSourceRepository = Depends(get_stream_source_repo),
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    storage: LocalFileStorage = Depends(get_storage),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> ManageStreamSourceUseCase:
    return ManageStreamSourceUseCase(
        projects,
        streams,
        models,
        storage,
        uow,
        classes=classes,
        runner=request.app.state.stream_runner,
    )


def get_stream_runner(request: Request):
    return request.app.state.stream_runner


def get_start_stream_use_case(
    request: Request,
    streams: SqliteStreamSourceRepository = Depends(get_stream_source_repo),
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    storage: LocalFileStorage = Depends(get_storage),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> StartStreamUseCase:
    return StartStreamUseCase(
        streams, models, classes, storage, request.app.state.stream_runner, uow
    )


def get_stop_stream_use_case(
    request: Request,
    streams: SqliteStreamSourceRepository = Depends(get_stream_source_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> StopStreamUseCase:
    return StopStreamUseCase(streams, request.app.state.stream_runner, uow)


def get_stream_status_use_case(
    request: Request,
    streams: SqliteStreamSourceRepository = Depends(get_stream_source_repo),
) -> GetStreamStatusUseCase:
    return GetStreamStatusUseCase(streams, request.app.state.stream_runner)

def get_create_project_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CreateProjectUseCase:
    return CreateProjectUseCase(projects, uow)


def get_update_project_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> UpdateProjectUseCase:
    return UpdateProjectUseCase(projects, uow)


def get_list_projects_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
) -> ListProjectsUseCase:
    return ListProjectsUseCase(projects)


def get_get_project_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
) -> GetProjectUseCase:
    return GetProjectUseCase(projects)


def get_delete_project_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    storage: LocalFileStorage = Depends(get_storage),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> DeleteProjectUseCase:
    return DeleteProjectUseCase(projects, storage, uow)


def get_create_class_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CreateClassUseCase:
    return CreateClassUseCase(projects, classes, uow)


def get_list_classes_use_case(
    classes: SqliteClassRepository = Depends(get_class_repo),
) -> ListClassesUseCase:
    return ListClassesUseCase(classes)


def get_packer() -> ZipArchivePacker:
    return ZipArchivePacker()


def get_delete_class_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
) -> DeleteClassUseCase:
    return DeleteClassUseCase(projects, classes, uow, images, annotations)


def get_upload_images_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    images: SqliteImageRepository = Depends(get_image_repo),
    storage: LocalFileStorage = Depends(get_storage),
    metadata: PillowMetadataReader = Depends(get_metadata_reader),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
) -> UploadImagesUseCase:
    return UploadImagesUseCase(
        projects, images, storage, metadata, uow, annotations, classes
    )


def get_list_images_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
) -> ListImagesUseCase:
    return ListImagesUseCase(images)


def get_get_image_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
) -> GetImageUseCase:
    return GetImageUseCase(images, annotations)


def get_save_annotations_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> SaveAnnotationsUseCase:
    return SaveAnnotationsUseCase(images, classes, annotations, uow)


def get_verify_annotation_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> VerifyAnnotationUseCase:
    return VerifyAnnotationUseCase(images, annotations, uow)


def get_verify_all_annotations_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> VerifyAllAnnotationsUseCase:
    return VerifyAllAnnotationsUseCase(images, annotations, uow)


def get_reject_all_pending_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> RejectAllPendingAnnotationsUseCase:
    return RejectAllPendingAnnotationsUseCase(images, annotations, uow)


def get_mark_background_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> MarkImageAsBackgroundUseCase:
    return MarkImageAsBackgroundUseCase(images, annotations, uow)


def get_delete_annotation_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> DeleteAnnotationUseCase:
    return DeleteAnnotationUseCase(images, annotations, uow)


def get_matcher() -> SiftKeypointMatcher:
    return SiftKeypointMatcher()


def get_propagate_box_use_case(
    images: SqliteImageRepository = Depends(get_image_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    storage: LocalFileStorage = Depends(get_storage),
    matcher: SiftKeypointMatcher = Depends(get_matcher),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> PropagateBoxViaKeypointsUseCase:
    return PropagateBoxViaKeypointsUseCase(
        images, classes, annotations, storage, matcher, uow
    )


def get_export_yolo_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    storage: LocalFileStorage = Depends(get_storage),
    packer: ZipArchivePacker = Depends(get_packer),
) -> ExportYOLOUseCase:
    return ExportYOLOUseCase(projects, classes, images, annotations, storage, packer)


def get_augmentation_service() -> AlbumentationsAugmentationService:
    return AlbumentationsAugmentationService()


def get_create_dataset_version_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    versions: SqliteDatasetVersionRepository = Depends(get_dataset_version_repo),
    storage: LocalFileStorage = Depends(get_storage),
    augmentation: AlbumentationsAugmentationService = Depends(get_augmentation_service),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CreateDatasetVersionUseCase:
    return CreateDatasetVersionUseCase(
        projects,
        images,
        annotations,
        classes,
        versions,
        storage,
        augmentation,
        uow,
    )


def get_list_dataset_versions_use_case(
    versions: SqliteDatasetVersionRepository = Depends(get_dataset_version_repo),
) -> ListDatasetVersionsUseCase:
    return ListDatasetVersionsUseCase(versions)


def get_get_dataset_version_use_case(
    versions: SqliteDatasetVersionRepository = Depends(get_dataset_version_repo),
) -> GetDatasetVersionUseCase:
    return GetDatasetVersionUseCase(versions)


def get_rename_dataset_version_use_case(
    versions: SqliteDatasetVersionRepository = Depends(get_dataset_version_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> RenameDatasetVersionUseCase:
    return RenameDatasetVersionUseCase(versions, uow)


def get_export_dataset_version_use_case(
    versions: SqliteDatasetVersionRepository = Depends(get_dataset_version_repo),
    storage: LocalFileStorage = Depends(get_storage),
    packer: ZipArchivePacker = Depends(get_packer),
) -> ExportDatasetVersionUseCase:
    return ExportDatasetVersionUseCase(versions, storage, packer)


def get_delete_dataset_version_use_case(
    versions: SqliteDatasetVersionRepository = Depends(get_dataset_version_repo),
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
    jobs: SqliteTrainingJobRepository = Depends(get_training_job_repo),
    auto_jobs: SqliteAutoLabelJobRepository = Depends(get_auto_label_job_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    storage: LocalFileStorage = Depends(get_storage),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> DeleteDatasetVersionUseCase:
    return DeleteDatasetVersionUseCase(
        versions, models, jobs, auto_jobs, annotations, storage, uow
    )


def get_predictor() -> UltralyticsPredictor:
    return UltralyticsPredictor()


def get_train_model_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    versions: SqliteDatasetVersionRepository = Depends(get_dataset_version_repo),
    jobs: SqliteTrainingJobRepository = Depends(get_training_job_repo),
    storage: LocalFileStorage = Depends(get_storage),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
) -> TrainModelUseCase:
    return TrainModelUseCase(projects, versions, jobs, storage, uow, models=models)


def get_get_training_job_use_case(
    jobs: SqliteTrainingJobRepository = Depends(get_training_job_repo),
) -> GetTrainingJobUseCase:
    return GetTrainingJobUseCase(jobs)


def get_list_model_versions_use_case(
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
) -> ListModelVersionsUseCase:
    return ListModelVersionsUseCase(models)


def get_rename_model_version_use_case(
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> RenameModelVersionUseCase:
    return RenameModelVersionUseCase(models, uow)


def get_export_model_version_use_case(
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
    storage: LocalFileStorage = Depends(get_storage),
    packer: ZipArchivePacker = Depends(get_packer),
) -> ExportModelVersionUseCase:
    return ExportModelVersionUseCase(models, storage, packer)


def get_delete_model_version_use_case(
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
    jobs: SqliteTrainingJobRepository = Depends(get_training_job_repo),
    auto_jobs: SqliteAutoLabelJobRepository = Depends(get_auto_label_job_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    storage: LocalFileStorage = Depends(get_storage),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> DeleteModelVersionUseCase:
    return DeleteModelVersionUseCase(
        models, jobs, auto_jobs, annotations, storage, uow
    )


def get_upload_model_version_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
    storage: LocalFileStorage = Depends(get_storage),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> UploadModelVersionUseCase:
    return UploadModelVersionUseCase(projects, models, storage, uow)


def get_batch_auto_label_use_case(
    models: SqliteModelVersionRepository = Depends(get_model_version_repo),
    images: SqliteImageRepository = Depends(get_image_repo),
    annotations: SqliteAnnotationRepository = Depends(get_annotation_repo),
    classes: SqliteClassRepository = Depends(get_class_repo),
    jobs: SqliteAutoLabelJobRepository = Depends(get_auto_label_job_repo),
    storage: LocalFileStorage = Depends(get_storage),
    predictor: UltralyticsPredictor = Depends(get_predictor),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> BatchAutoLabelUseCase:
    return BatchAutoLabelUseCase(
        models, images, annotations, classes, jobs, storage, predictor, uow
    )


def get_get_auto_label_job_use_case(
    jobs: SqliteAutoLabelJobRepository = Depends(get_auto_label_job_repo),
) -> GetAutoLabelJobUseCase:
    return GetAutoLabelJobUseCase(jobs)
