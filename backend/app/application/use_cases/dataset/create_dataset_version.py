from __future__ import annotations

from collections import defaultdict
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
    AugmentationConfig,
    DatasetItem,
    DatasetVersion,
    SnapshotAnnotation,
)
from app.domain.enums import ImageStatus, SplitType, VerificationStatus
from app.domain.exceptions import (
    InsufficientVerifiedDataException,
    ResourceNotFoundException,
    UnverifiedDataException,
)

DEFAULT_MIN_VERIFIED_IMAGES = 10


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
    ) -> DatasetVersion:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ResourceNotFoundException(f"project {project_id} not found")

        config = augmentation or AugmentationConfig()
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

        classes = sorted(
            await self._classes.list_by_project(project_id),
            key=lambda item: item.index_id,
        )
        class_by_id = {item.id: item for item in classes}
        names = {item.index_id: item.name for item in classes}

        version_number = await self._versions.next_version_number(project_id)
        version = DatasetVersion.create(
            project_id=project_id,
            version_number=version_number,
            name=name,
            augmentation=config,
        )
        await self._versions.add(version)
        await self._uow.commit()

        relative_root = f"projects/{project_id}/datasets/v{version_number}"
        try:
            items: list[DatasetItem] = []
            train_files = 0
            valid_files = 0
            test_files = 0

            for image in verified_images:
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
                        split=image.split,
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
                apply_aug = image.split == SplitType.TRAIN
                samples = self._augmentation.generate_samples(
                    raw,
                    labeled,
                    config,
                    apply_augmentation=apply_aug,
                )

                split = image.split.value
                for sample in samples:
                    stem = f"{image.id}{sample.suffix}"
                    image_name = f"{stem}.jpg"
                    label_name = f"{stem}.txt"
                    await self._storage.save(
                        f"{relative_root}/{split}/images",
                        image_name,
                        sample.image_bytes,
                    )
                    label_body = "\n".join(
                        f"{box.class_index} {box.x_center:.6f} {box.y_center:.6f} "
                        f"{box.width:.6f} {box.height:.6f}"
                        for box in sample.boxes
                    )
                    await self._storage.save(
                        f"{relative_root}/{split}/labels",
                        label_name,
                        label_body.encode("utf-8"),
                    )

                count = len(samples)
                if image.split == SplitType.TRAIN:
                    train_files += count
                elif image.split == SplitType.VALID:
                    valid_files += count
                else:
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
                train_count=train_files,
                valid_count=valid_files,
                test_count=test_files,
                yaml_path=yaml_relative,
                items=items,
            )
            await self._versions.update(version)
            await self._uow.commit()
            return version
        except Exception:
            version.mark_failed()
            try:
                await self._versions.update(version)
                await self._uow.commit()
            except Exception:
                pass
            await self._storage.delete_directory(relative_root)
            raise


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
