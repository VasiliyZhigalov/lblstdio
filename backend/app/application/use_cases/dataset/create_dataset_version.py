from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from random import Random
from uuid import UUID, uuid4

import yaml

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.dataset_version_repository import (
    IDatasetVersionRepository,
)
from app.application.ports.repositories.image_label_repository import IImageLabelRepository
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.services.augmentation import IAugmentationService, LabeledBox
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.application.services.version_staging import (
    attempt_staging_dir,
    cleanup_attempt,
    publish_attempt,
    published_version_dir,
)
from app.domain.entities.dataset_version import (
    DEFAULT_MIN_VERIFIED_IMAGES,
    AugmentationConfig,
    DatasetItem,
    DatasetVersion,
    SnapshotAnnotation,
    SnapshotClassLabel,
)
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, ProjectTaskType, SplitType, VerificationStatus
from app.domain.exceptions import (
    DatasetVersionConflictException,
    DomainValidationException,
    InsufficientVerifiedDataException,
    ResourceNotFoundException,
    UnverifiedDataException,
)
from app.domain.services.class_dir_name import class_dir_name, require_unique_class_dirs
from app.domain.services.split import assign_with_holdout
from app.domain.value_objects.split_ratios import SplitRatios

_MAX_VERSION_ALLOC_ATTEMPTS = 5


def _disk_split(split: SplitType) -> str:
    return "val" if split == SplitType.VALID else split.value


class CreateDatasetVersionUseCase:
    def __init__(
        self,
        projects: IProjectRepository,
        images: IImageRepository,
        annotations: IAnnotationRepository,
        classes: IClassRepository,
        versions: IDatasetVersionRepository,
        storage: IFileStorage,
        augmentation: IAugmentationService,
        uow: IUnitOfWork,
        *,
        min_verified_images: int = DEFAULT_MIN_VERIFIED_IMAGES,
        labels: IImageLabelRepository | None = None,
    ) -> None:
        self._projects = projects
        self._images = images
        self._annotations = annotations
        self._classes = classes
        self._versions = versions
        self._storage = storage
        self._augmentation = augmentation
        self._uow = uow
        self._min_verified = min_verified_images
        self._labels = labels

    async def execute(
        self,
        project_id: UUID,
        augmentation: AugmentationConfig | None = None,
        name: str | None = None,
        ratios: SplitRatios | None = None,
        *,
        rng: Random | None = None,
    ) -> DatasetVersion:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")

        config = augmentation or AugmentationConfig()
        split_ratios = ratios or SplitRatios()
        if project.task_type == ProjectTaskType.CLASSIFICATION:
            return await self._execute_classification(
                project, config, name, split_ratios, rng
            )

        all_images = await self._images.list_by_project(project_id)
        annotations = await self._annotations.list_by_image_ids(
            [item.id for item in all_images]
        )
        by_image: dict[UUID, list] = defaultdict(list)
        for annotation in annotations:
            by_image[annotation.image_id].append(annotation)

        pending_images = [
            item
            for item in all_images
            if item.status
            in (ImageStatus.REQUIRES_REVIEW, ImageStatus.REQUIRES_RECHECK)
            or any(
                box.verification_status == VerificationStatus.PENDING_REVIEW
                for box in by_image.get(item.id, [])
            )
        ]
        if pending_images:
            raise UnverifiedDataException(
                f"cannot create dataset version: {len(pending_images)} frame(s) "
                "contain unverified annotations"
            )

        verified_images = [
            item for item in all_images if item.can_be_included_in_dataset()
        ]
        if len(verified_images) < self._min_verified:
            raise InsufficientVerifiedDataException(
                f"need at least {self._min_verified} verified frames, "
                f"got {len(verified_images)}"
            )

        ordered = list(verified_images)
        assigned_splits = assign_with_holdout(
            [image.split == SplitType.TEST for image in ordered],
            split_ratios,
            rng=rng or Random(),
        )

        classes = sorted(
            await self._classes.list_by_project(project_id),
            key=lambda item: item.index_id,
        )
        class_by_id = {item.id: item for item in classes}
        names = {item.index_id: item.name for item in classes}

        last_error: Exception | None = None
        for _attempt in range(_MAX_VERSION_ALLOC_ATTEMPTS):
            staging = attempt_staging_dir(project_id, "datasets")
            published: str | None = None
            version_id = uuid4()
            try:
                items: list[DatasetItem] = []
                train_frames = 0
                valid_frames = 0
                test_frames = 0
                train_files = 0
                valid_files = 0
                test_files = 0

                for image, split_type in zip(ordered, assigned_splits, strict=True):
                    verified_boxes = [
                        box
                        for box in by_image.get(image.id, [])
                        if box.verification_status
                        in (
                            VerificationStatus.VERIFIED,
                            VerificationStatus.AUTO_VERIFIED,
                        )
                        and box.class_id in class_by_id
                    ]
                    snapshot = [
                        SnapshotAnnotation(
                            class_id=box.class_id,
                            class_index=class_by_id[box.class_id].index_id,
                            x_center=box.bbox.x_center,
                            y_center=box.bbox.y_center,
                            width=box.bbox.width,
                            height=box.bbox.height,
                        )
                        for box in verified_boxes
                    ]
                    items.append(
                        DatasetItem(
                            id=uuid4(),
                            dataset_version_id=version_id,
                            image_id=image.id,
                            split=split_type,
                            snapshot_annotations=snapshot,
                            source_file_name=image.file_name,
                        )
                    )

                    labeled = [
                        LabeledBox(
                            x_center=item.x_center,
                            y_center=item.y_center,
                            width=item.width,
                            height=item.height,
                            class_index=item.class_index,
                        )
                        for item in snapshot
                    ]
                    raw = await self._storage.read(image.file_path)
                    apply_aug = split_type == SplitType.TRAIN
                    samples = self._augmentation.generate_samples(
                        raw,
                        labeled,
                        config,
                        apply_augmentation=apply_aug,
                    )

                    split = split_type.value
                    for sample in samples:
                        stem = f"{image.id}{sample.suffix}"
                        await self._storage.save(
                            f"{staging}/{split}/images",
                            f"{stem}.jpg",
                            sample.image_bytes,
                        )
                        label_body = "\n".join(
                            f"{box.class_index} {box.x_center:.6f} {box.y_center:.6f} "
                            f"{box.width:.6f} {box.height:.6f}"
                            for box in sample.boxes
                        )
                        await self._storage.save(
                            f"{staging}/{split}/labels",
                            f"{stem}.txt",
                            label_body.encode("utf-8"),
                        )

                    count = len(samples)
                    if split_type == SplitType.TRAIN:
                        train_frames += 1
                        train_files += count
                    elif split_type == SplitType.VALID:
                        valid_frames += 1
                        valid_files += count
                    else:
                        test_frames += 1
                        test_files += count

                version_number = await self._versions.next_version_number(project_id)
                version = DatasetVersion.create(
                    project_id=project_id,
                    version_number=version_number,
                    name=name,
                    augmentation=config,
                    version_id=version_id,
                )
                published_root = published_version_dir(
                    project_id, "datasets", version_number
                )
                yaml_payload = {
                    "path": self._storage.get_absolute_path(published_root),
                    "train": "train/images",
                    "val": "valid/images",
                    "test": "test/images",
                    "nc": len(names),
                    "names": names,
                }
                await self._storage.save(
                    staging,
                    "data.yaml",
                    yaml.safe_dump(
                        yaml_payload, sort_keys=False, allow_unicode=True
                    ).encode("utf-8"),
                )
                await publish_attempt(self._storage, staging, published_root)
                published = published_root

                version.mark_ready(
                    train_count=train_frames,
                    valid_count=valid_frames,
                    test_count=test_frames,
                    train_file_count=train_files,
                    valid_file_count=valid_files,
                    test_file_count=test_files,
                    yaml_path=f"{published_root}/data.yaml",
                    items=items,
                )
                try:
                    await self._versions.add(version)
                    await self._uow.commit()
                except DatasetVersionConflictException as exc:
                    last_error = exc
                    if hasattr(self._uow, "rollback"):
                        await self._uow.rollback()
                    await cleanup_attempt(self._storage, staging, published)
                    continue
                return version
            except FileExistsError as exc:
                last_error = exc
                await cleanup_attempt(self._storage, staging, published)
                continue
            except Exception:
                await cleanup_attempt(self._storage, staging, published)
                raise

        raise ResourceNotFoundException(
            f"could not allocate dataset version number after "
            f"{_MAX_VERSION_ALLOC_ATTEMPTS} attempts: {last_error}"
        )

    async def _execute_classification(
        self,
        project: Project,
        config: AugmentationConfig,
        name: str | None,
        split_ratios: SplitRatios,
        rng: Random | None,
    ) -> DatasetVersion:
        if self._labels is None:
            raise DomainValidationException("image label repository is not configured")
        all_images = await self._images.list_by_project(project.id)
        labels = await self._labels.list_by_image_ids([item.id for item in all_images])
        by_image = {item.image_id: item for item in labels}

        pending_images = [
            item
            for item in all_images
            if item.status
            in (ImageStatus.REQUIRES_REVIEW, ImageStatus.REQUIRES_RECHECK)
            or (
                by_image.get(item.id) is not None
                and by_image[item.id].verification_status
                == VerificationStatus.PENDING_REVIEW
            )
        ]
        if pending_images:
            raise UnverifiedDataException(
                f"cannot create dataset version: {len(pending_images)} frame(s) "
                "contain unverified annotations"
            )

        verified_pairs: list[tuple] = []
        for image in all_images:
            if not image.can_be_included_in_dataset():
                continue
            label = by_image.get(image.id)
            if label is None:
                continue
            if label.verification_status not in (
                VerificationStatus.VERIFIED,
                VerificationStatus.AUTO_VERIFIED,
            ):
                continue
            verified_pairs.append((image, label))

        if len(verified_pairs) < self._min_verified:
            raise InsufficientVerifiedDataException(
                f"need at least {self._min_verified} verified frames, "
                f"got {len(verified_pairs)}"
            )

        classes = sorted(
            await self._classes.list_by_project(project.id),
            key=lambda item: item.index_id,
        )
        class_by_id = {item.id: item for item in classes}
        verified_pairs = [
            (image, label)
            for image, label in verified_pairs
            if label.class_id in class_by_id
        ]
        class_ids = [label.class_id for _image, label in verified_pairs]
        assigned_splits = assign_with_holdout(
            [image.split == SplitType.TEST for image, _label in verified_pairs],
            split_ratios,
            class_ids=class_ids,
            rng=rng or Random(),
        )

        last_error: Exception | None = None
        for _attempt in range(_MAX_VERSION_ALLOC_ATTEMPTS):
            staging = attempt_staging_dir(project.id, "datasets")
            published: str | None = None
            version_id = uuid4()
            try:
                require_unique_class_dirs([item.name for item in classes])
                items: list[DatasetItem] = []
                train_frames = 0
                valid_frames = 0
                test_frames = 0
                for (image, label), split_type in zip(
                    verified_pairs, assigned_splits, strict=True
                ):
                    snapshot = [
                        SnapshotClassLabel(
                            class_id=label.class_id,
                            class_index=class_by_id[label.class_id].index_id,
                        )
                    ]
                    items.append(
                        DatasetItem(
                            id=uuid4(),
                            dataset_version_id=version_id,
                            image_id=image.id,
                            split=split_type,
                            snapshot_annotations=snapshot,
                            source_file_name=image.file_name,
                        )
                    )
                    raw = await self._storage.read(image.file_path)
                    suffix = Path(image.file_name).suffix.lower() or ".png"
                    folder = class_dir_name(class_by_id[label.class_id].name)
                    await self._storage.save(
                        f"{staging}/{_disk_split(split_type)}/{folder}",
                        f"{image.id}{suffix}",
                        raw,
                    )
                    if split_type == SplitType.TRAIN:
                        train_frames += 1
                    elif split_type == SplitType.VALID:
                        valid_frames += 1
                    else:
                        test_frames += 1

                version_number = await self._versions.next_version_number(project.id)
                version = DatasetVersion.create(
                    project_id=project.id,
                    version_number=version_number,
                    name=name,
                    augmentation=config,
                    version_id=version_id,
                )
                published_root = published_version_dir(
                    project.id, "datasets", version_number
                )
                await publish_attempt(self._storage, staging, published_root)
                published = published_root
                version.mark_ready(
                    train_count=train_frames,
                    valid_count=valid_frames,
                    test_count=test_frames,
                    train_file_count=train_frames,
                    valid_file_count=valid_frames,
                    test_file_count=test_frames,
                    yaml_path=published_root,
                    items=items,
                )
                try:
                    await self._versions.add(version)
                    await self._uow.commit()
                except DatasetVersionConflictException as exc:
                    last_error = exc
                    if hasattr(self._uow, "rollback"):
                        await self._uow.rollback()
                    await cleanup_attempt(self._storage, staging, published)
                    continue
                return version
            except FileExistsError as exc:
                last_error = exc
                await cleanup_attempt(self._storage, staging, published)
                continue
            except Exception:
                await cleanup_attempt(self._storage, staging, published)
                raise

        raise ResourceNotFoundException(
            f"could not allocate dataset version number after "
            f"{_MAX_VERSION_ALLOC_ATTEMPTS} attempts: {last_error}"
        )


class ListDatasetVersionsUseCase:
    def __init__(self, versions: IDatasetVersionRepository) -> None:
        self._versions = versions

    async def execute(self, project_id: UUID) -> list[DatasetVersion]:
        return await self._versions.list_by_project(project_id)


class GetDatasetVersionUseCase:
    def __init__(self, versions: IDatasetVersionRepository) -> None:
        self._versions = versions

    async def execute(self, version_id: UUID) -> DatasetVersion:
        version = await self._versions.get_by_id(version_id)
        if version is None:
            raise ResourceNotFoundException(f"dataset version {version_id} not found")
        return version
