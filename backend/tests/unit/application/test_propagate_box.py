from uuid import UUID, uuid4

import pytest

from app.application.dto import BoxInput, ProjectBoxesResult, ProjectedBox, TransformDebug
from app.application.use_cases.keypoints.propagate_box import (
    PropagateBoxViaKeypointsUseCase,
)
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.enums import ImageStatus, SourceType, SplitType, VerificationStatus
from app.domain.exceptions import (
    DomainValidationException,
    KeypointMatchingFailedException,
    ResourceNotFoundException,
)
from app.domain.value_objects.bounding_box import BoundingBox


class _FakeImages:
    def __init__(self, images: list[Image]) -> None:
        self.by_id = {item.id: item for item in images}
        self.updated: Image | None = None

    async def get_by_id(self, image_id: UUID) -> Image | None:
        return self.by_id.get(image_id)

    async def update(self, image: Image) -> None:
        self.updated = image
        self.by_id[image.id] = image


class _FakeClasses:
    def __init__(self, classes: list[AnnotationClass]) -> None:
        self._classes = classes

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        return [item for item in self._classes if item.project_id == project_id]


class _FakeAnnotations:
    def __init__(self, existing: dict[UUID, list[Annotation]] | None = None) -> None:
        self.store = existing or {}
        self.replace_calls = 0

    async def list_by_image(self, image_id: UUID) -> list[Annotation]:
        return list(self.store.get(image_id, []))

    async def replace_for_image(
        self, image_id: UUID, annotations: list[Annotation]
    ) -> None:
        self.replace_calls += 1
        self.store[image_id] = list(annotations)


class _FakeUow:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _FakeStorage:
    def get_absolute_path(self, relative_path: str) -> str:
        return f"/abs/{relative_path}"


class _FakeMatcher:
    def __init__(
        self,
        result: ProjectedBox | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str, BoundingBox]] = []

    def project_box(
        self,
        source_image_path: str,
        target_image_path: str,
        source_box: BoundingBox,
        source_width: int,
        source_height: int,
        target_width: int,
        target_height: int,
    ) -> ProjectedBox:
        results = self.project_boxes(
            source_image_path,
            target_image_path,
            [source_box],
            source_width,
            source_height,
            target_width,
            target_height,
        )
        assert results[0] is not None
        return results[0]

    def project_boxes(
        self,
        source_image_path: str,
        target_image_path: str,
        source_boxes: list[BoundingBox],
        source_width: int,
        source_height: int,
        target_width: int,
        target_height: int,
    ) -> ProjectBoxesResult:
        for box in source_boxes:
            self.calls.append((source_image_path, target_image_path, box))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return ProjectBoxesResult(
            boxes=[self.result for _ in source_boxes],
            transform=TransformDebug(
                tx=10.0,
                ty=0.0,
                rotation_deg=0.0,
                scale=1.0,
                match_score=self.result.match_score,
                matrix=((1.0, 0.0, 10.0), (0.0, 1.0, 0.0)),
            ),
        )


def _image(project_id: UUID, name: str = "a.png") -> Image:
    return Image.create(
        project_id=project_id,
        file_path=f"projects/p/images/{name}",
        file_name=name,
        width=200,
        height=160,
        split=SplitType.TRAIN,
    )


def _setup(
    matcher: _FakeMatcher,
    *,
    with_donor: bool = True,
) -> tuple[
    PropagateBoxViaKeypointsUseCase,
    Image,
    Image,
    AnnotationClass,
    _FakeAnnotations,
    _FakeUow,
    Annotation | None,
]:
    project_id = uuid4()
    source = _image(project_id, "src.png")
    target = _image(project_id, "dst.png")
    annotation_class = AnnotationClass.create(project_id, "crack", "#EF4444", 0)
    donor = None
    existing: dict[UUID, list[Annotation]] = {}
    if with_donor:
        donor = Annotation.create_manual(
            image_id=source.id,
            class_id=annotation_class.id,
            bbox=BoundingBox(x_center=0.40, y_center=0.50, width=0.20, height=0.16),
        )
        existing[source.id] = [donor]
    annotations = _FakeAnnotations(existing)
    uow = _FakeUow()
    use_case = PropagateBoxViaKeypointsUseCase(
        images=_FakeImages([source, target]),
        classes=_FakeClasses([annotation_class]),
        annotations=annotations,
        storage=_FakeStorage(),
        matcher=matcher,
        uow=uow,
    )
    return use_case, source, target, annotation_class, annotations, uow, donor


def _source_box(class_id: UUID, annotation_id: UUID | None = None) -> BoxInput:
    return BoxInput(
        class_id=class_id,
        x_center=0.99,
        y_center=0.99,
        width=0.01,
        height=0.01,
        annotation_id=annotation_id,
    )


class TestPropagateBoxViaKeypointsUseCase:
    @pytest.mark.asyncio
    async def test_created_box_is_always_pending_review(self) -> None:
        projected = ProjectedBox(
            bbox=BoundingBox(x_center=0.55, y_center=0.50, width=0.20, height=0.16),
            match_score=0.88,
        )
        matcher = _FakeMatcher(result=projected)
        use_case, source, target, annotation_class, repo, uow, donor = _setup(matcher)
        assert donor is not None

        created = await use_case.execute(
            source_image_id=source.id,
            target_image_id=target.id,
            source_box=_source_box(annotation_class.id, donor.id),
        )

        assert created.source == SourceType.KEYPOINT_PROPAGATION
        assert created.verification_status == VerificationStatus.PENDING_REVIEW
        assert created.confidence == 0.88
        assert created.source_annotation_id == donor.id
        assert created.image_id == target.id
        assert created.bbox.x_center == 0.55
        assert created.verified_at is None
        assert target.status == ImageStatus.REQUIRES_REVIEW
        assert repo.replace_calls == 1
        assert uow.committed is True
        assert matcher.calls[0][0].endswith("src.png")
        assert matcher.calls[0][1].endswith("dst.png")
        # Client-supplied geometry is ignored; donor bbox is used.
        assert matcher.calls[0][2] == donor.bbox

    @pytest.mark.asyncio
    async def test_matching_failure_does_not_open_write_transaction(self) -> None:
        matcher = _FakeMatcher(
            error=KeypointMatchingFailedException(
                "Не удалось найти объект на этом кадре. Разметьте вручную"
            )
        )
        use_case, source, target, annotation_class, repo, uow, donor = _setup(matcher)
        assert donor is not None

        with pytest.raises(KeypointMatchingFailedException, match="Разметьте вручную"):
            await use_case.execute(
                source_image_id=source.id,
                target_image_id=target.id,
                source_box=_source_box(annotation_class.id, donor.id),
            )

        assert repo.replace_calls == 0
        assert uow.committed is False
        assert target.status == ImageStatus.UNANNOTATED

    @pytest.mark.asyncio
    async def test_same_frame_is_rejected(self) -> None:
        matcher = _FakeMatcher(
            result=ProjectedBox(
                bbox=BoundingBox(0.5, 0.5, 0.2, 0.1), match_score=1.0
            )
        )
        use_case, source, _, annotation_class, repo, uow, donor = _setup(matcher)
        assert donor is not None

        with pytest.raises(DomainValidationException, match="другой кадр"):
            await use_case.execute(
                source_image_id=source.id,
                target_image_id=source.id,
                source_box=_source_box(annotation_class.id, donor.id),
            )

        assert matcher.calls == []
        assert repo.replace_calls == 0
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_missing_image_raises_not_found(self) -> None:
        matcher = _FakeMatcher(
            result=ProjectedBox(
                bbox=BoundingBox(0.5, 0.5, 0.2, 0.1), match_score=1.0
            )
        )
        use_case, source, _, annotation_class, repo, uow, donor = _setup(matcher)
        assert donor is not None

        with pytest.raises(ResourceNotFoundException):
            await use_case.execute(
                source_image_id=source.id,
                target_image_id=uuid4(),
                source_box=_source_box(annotation_class.id, donor.id),
            )

        assert repo.replace_calls == 0
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_missing_source_annotation_raises_not_found(self) -> None:
        matcher = _FakeMatcher(
            result=ProjectedBox(
                bbox=BoundingBox(0.5, 0.5, 0.2, 0.1), match_score=1.0
            )
        )
        use_case, source, target, annotation_class, repo, uow, _donor = _setup(
            matcher, with_donor=False
        )

        with pytest.raises(ResourceNotFoundException, match="not found on source image"):
            await use_case.execute(
                source_image_id=source.id,
                target_image_id=target.id,
                source_box=_source_box(annotation_class.id, uuid4()),
            )

        assert matcher.calls == []
        assert repo.replace_calls == 0
        assert uow.committed is False
