from uuid import UUID, uuid4

import pytest

from app.application.use_cases.annotations.verify_annotation import (
    ClearReviewImagesAnnotationsUseCase,
    DeleteAnnotationUseCase,
    RejectAllPendingAnnotationsUseCase,
    VerifyAllAnnotationsUseCase,
    VerifyAnnotationUseCase,
)
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.enums import ImageStatus, SplitType, VerificationStatus
from app.domain.exceptions import ResourceNotFoundException
from app.domain.value_objects.bounding_box import BoundingBox


class _FakeImages:
    def __init__(self, image: Image | list[Image]) -> None:
        items = image if isinstance(image, list) else [image]
        self.by_id = {item.id: item for item in items}

    async def get_by_id(self, image_id: UUID) -> Image | None:
        return self.by_id.get(image_id)

    async def list_by_project(self, project_id: UUID) -> list[Image]:
        return [item for item in self.by_id.values() if item.project_id == project_id]

    async def update(self, image: Image) -> None:
        self.by_id[image.id] = image

    @property
    def image(self) -> Image:
        return next(iter(self.by_id.values()))

    @image.setter
    def image(self, value: Image) -> None:
        self.by_id[value.id] = value


class _FakeAnnotations:
    def __init__(self, items: list[Annotation]) -> None:
        self.store: dict[UUID, list[Annotation]] = {}
        for item in items:
            self.store.setdefault(item.image_id, []).append(item)

    async def list_by_image(self, image_id: UUID) -> list[Annotation]:
        return list(self.store.get(image_id, []))

    async def replace_for_image(self, image_id: UUID, annotations: list[Annotation]) -> None:
        self.store[image_id] = list(annotations)


class _FakeUow:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def _image() -> Image:
    return Image.create(
        project_id=uuid4(),
        file_path="projects/p/images/a.png",
        file_name="a.png",
        width=100,
        height=80,
        split=SplitType.TRAIN,
    )


def _pending(image_id: UUID) -> Annotation:
    return Annotation.create_from_keypoints(
        image_id=image_id,
        class_id=uuid4(),
        bbox=BoundingBox(0.5, 0.5, 0.2, 0.1),
        source_annotation_id=uuid4(),
        confidence=0.77,
    )


class TestVerifyAnnotationUseCase:
    @pytest.mark.asyncio
    async def test_pending_box_becomes_verified(self) -> None:
        image = _image()
        pending = _pending(image.id)
        image.recalculate_status([pending])
        images = _FakeImages(image)
        annotations = _FakeAnnotations([pending])
        uow = _FakeUow()
        use_case = VerifyAnnotationUseCase(images, annotations, uow)

        result = await use_case.execute(image.id, pending.id)

        assert result.verification_status == VerificationStatus.VERIFIED
        assert result.verified_at is not None
        assert image.status == ImageStatus.VERIFIED
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_missing_annotation_is_404(self) -> None:
        image = _image()
        use_case = VerifyAnnotationUseCase(_FakeImages(image), _FakeAnnotations([]), _FakeUow())
        with pytest.raises(ResourceNotFoundException):
            await use_case.execute(image.id, uuid4())


class TestVerifyAllAnnotationsUseCase:
    @pytest.mark.asyncio
    async def test_verifies_all_pending_on_frame(self) -> None:
        image = _image()
        first = _pending(image.id)
        second = _pending(image.id)
        manual = Annotation.create_manual(
            image_id=image.id,
            class_id=uuid4(),
            bbox=BoundingBox(0.2, 0.2, 0.1, 0.1),
        )
        image.recalculate_status([first, second, manual])
        images = _FakeImages(image)
        annotations = _FakeAnnotations([first, second, manual])
        uow = _FakeUow()

        result = await VerifyAllAnnotationsUseCase(images, annotations, uow).execute(
            image.id
        )

        assert all(
            item.verification_status == VerificationStatus.VERIFIED for item in result
        )
        assert image.status == ImageStatus.VERIFIED
        assert uow.committed is True


class TestRejectAllPendingAnnotationsUseCase:
    @pytest.mark.asyncio
    async def test_removes_only_pending_boxes(self) -> None:
        image = _image()
        pending = _pending(image.id)
        manual = Annotation.create_manual(
            image_id=image.id,
            class_id=uuid4(),
            bbox=BoundingBox(0.2, 0.2, 0.1, 0.1),
        )
        image.recalculate_status([pending, manual])
        images = _FakeImages(image)
        annotations = _FakeAnnotations([pending, manual])
        uow = _FakeUow()

        remaining = await RejectAllPendingAnnotationsUseCase(
            images, annotations, uow
        ).execute(image.id)

        assert len(remaining) == 1
        assert remaining[0].id == manual.id
        assert image.status == ImageStatus.VERIFIED
        assert uow.committed is True


class TestClearReviewImagesAnnotationsUseCase:
    @pytest.mark.asyncio
    async def test_clears_only_requires_review_images(self) -> None:
        project_id = uuid4()
        review = Image.create(
            project_id=project_id,
            file_path="projects/p/images/r.png",
            file_name="r.png",
            width=100,
            height=80,
            split=SplitType.TRAIN,
        )
        verified = Image.create(
            project_id=project_id,
            file_path="projects/p/images/v.png",
            file_name="v.png",
            width=100,
            height=80,
            split=SplitType.TRAIN,
        )
        pending = _pending(review.id)
        keep = Annotation.create_manual(
            image_id=verified.id,
            class_id=uuid4(),
            bbox=BoundingBox(0.3, 0.3, 0.1, 0.1),
        )
        review.recalculate_status([pending])
        verified.recalculate_status([keep])
        images = _FakeImages([review, verified])
        annotations = _FakeAnnotations([pending, keep])
        uow = _FakeUow()

        result = await ClearReviewImagesAnnotationsUseCase(
            images, annotations, uow
        ).execute(project_id)

        assert result == {"cleared_images": 1, "deleted_annotations": 1}
        assert annotations.store[review.id] == []
        assert images.by_id[review.id].status == ImageStatus.UNANNOTATED
        assert len(annotations.store[verified.id]) == 1
        assert images.by_id[verified.id].status == ImageStatus.VERIFIED
        assert uow.committed is True


class TestDeleteAnnotationUseCase:
    @pytest.mark.asyncio
    async def test_reject_removes_pending_box(self) -> None:
        image = _image()
        pending = _pending(image.id)
        image.recalculate_status([pending])
        images = _FakeImages(image)
        annotations = _FakeAnnotations([pending])
        uow = _FakeUow()

        remaining = await DeleteAnnotationUseCase(images, annotations, uow).execute(
            image.id, pending.id
        )

        assert remaining == []
        assert image.status == ImageStatus.UNANNOTATED
        assert uow.committed is True
