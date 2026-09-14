from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.application.use_cases.images.get_image import GetImageUseCase, ListImagesUseCase
from app.application.use_cases.images.upload_images import UploadImagesUseCase
from app.application.use_cases.keypoints.propagate_box import PropagateBoxViaKeypointsUseCase
from app.application.use_cases.projects.create_project import (
    CreateProjectUseCase,
    GetProjectUseCase,
    ListProjectsUseCase,
)
from app.application.use_cases.projects.delete_project import DeleteProjectUseCase
from app.infrastructure.db.repositories.annotation_repository import (
    SqliteAnnotationRepository,
)
from app.infrastructure.db.repositories.class_repository import SqliteClassRepository
from app.infrastructure.db.repositories.dataset_version_repository import (
    SqliteDatasetVersionRepository,
)
from app.infrastructure.db.repositories.image_repository import SqliteImageRepository
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.ml.albumentations_service import AlbumentationsAugmentationService
from app.infrastructure.ml.sift_matcher import SiftKeypointMatcher
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


def get_uow(session: AsyncSession = Depends(get_session)) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session)

def get_create_project_use_case(
    projects: SqliteProjectRepository = Depends(get_project_repo),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CreateProjectUseCase:
    return CreateProjectUseCase(projects, uow)


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
) -> UploadImagesUseCase:
    return UploadImagesUseCase(projects, images, storage, metadata, uow)


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
