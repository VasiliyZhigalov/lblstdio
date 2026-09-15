from __future__ import annotations

from collections import defaultdict
from random import Random
from uuid import UUID, uuid4

import yaml

from app.application.ports.repositories.annotation_repository import IAnnotationRepository
from app.application.ports.repositories.class_repository import IClassRepository
from app.application.ports.repositories.dataset_version_repository import (
    IDatasetVersionRepository,
)
from app.application.ports.repositories.image_repository import IImageRepository
from app.application.ports.repositories.project_repository import IProjectRepository
from app.application.ports.services.augmentation import IAugmentationService, LabeledBox
from app.application.ports.storage.file_storage import IFileStorage
from app.application.ports.unit_of_work import IUnitOfWork
from app.domain.entities.dataset_version import (
    DEFAULT_MIN_VERIFIED_IMAGES,
    AugmentationConfig,
    DatasetItem,
    DatasetVersion,
    SnapshotAnnotation,
)
from app.domain.enums import ImageStatus, SplitType, VerificationStatus
from app.domain.exceptions import (
    DatasetVersionConflictException,
    InsufficientVerifiedDataException,
    ResourceNotFoundException,
    UnverifiedDataException,
)
from app.domain.services.split import assign_splits
from app.domain.value_objects.split_ratios import SplitRatios

_MAX_VERSION_ALLOC_ATTEMPTS = 5


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
            if item.status == ImageStatus.REQUIRES_REVIEW
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
        (rng or Random()).shuffle(ordered)
        assigned_splits = assign_splits(len(ordered), split_ratios)

        classes = sorted(
            await self._classes.list_by_project(project_id),
            key=lambda item: item.index_id,
        )
        class_by_id = {item.id: item for item in classes}
        names = {item.index_id: item.name for item in classes}

        last_error: Exception | None = None
        for _attempt in range(_MAX_VERSION_ALLOC_ATTEMPTS):
            version_number = await self._versions.next_version_number(project_id)
            version = DatasetVersion.create(
                project_id=project_id,
                version_number=version_number,
                name=name,
                augmentation=config,
            )
            relative_root = f"projects/{project_id}/datasets/v{version_number}"
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
                        if box.verification_status == VerificationStatus.VERIFIED
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
                            dataset_version_id=version.id,
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
                            f"{relative_root}/{split}/images",
                            f"{stem}.jpg",
                            sample.image_bytes,
                        )
                        label_body = "\n".join(
                            f"{box.class_index} {box.x_center:.6f} {box.y_center:.6f} "
                            f"{box.width:.6f} {box.height:.6f}"
                            for box in sample.boxes
                        )
                        await self._storage.save(
                            f"{relative_root}/{split}/labels",
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

                yaml_payload = {
                    "path": self._storage.get_absolute_path(relative_root),
                    "train": "train/images",
                    "val": "valid/images",
                    "test": "test/images",
                    "nc": len(names),
                    "names": names,
                }
                yaml_relative = f"{relative_root}/data.yaml"
                await self._storage.save(
                    relative_root,
                    "data.yaml",
                    yaml.safe_dump(
                        yaml_payload, sort_keys=False, allow_unicode=True
                    ).encode("utf-8"),
                )

                version.mark_ready(
                    train_count=train_frames,
                    valid_count=valid_frames,
                    test_count=test_frames,
                    train_file_count=train_files,
                    valid_file_count=valid_files,
                    test_file_count=test_files,
                    yaml_path=yaml_relative,
                    items=items,
                )
                try:
                    await self._versions.add(version)
                    await self._uow.commit()
                except DatasetVersionConflictException as exc:
                    last_error = exc
                    await self._storage.delete_directory(relative_root)
                    if hasattr(self._uow, "rollback"):
                        await self._uow.rollback()
                    continue
                return version
            except Exception:
                await self._storage.delete_directory(relative_root)
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
