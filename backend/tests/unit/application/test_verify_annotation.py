from uuid import UUID, uuid4

import pytest

from app.application.use_cases.annotations.verify_annotation import (
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
    def __init__(self, image: Image) -> None:
        self.image = image

    async def get_by_id(self, image_id: UUID) -> Image | None:
        return self.image if self.image.id == image_id else None

    async def update(self, image: Image) -> None:
        self.image = image


class _FakeAnnotations:
    def __init__(self, items: list[Annotation]) -> None:
        self.store = {items[0].image_id: list(items)} if items else {}

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
