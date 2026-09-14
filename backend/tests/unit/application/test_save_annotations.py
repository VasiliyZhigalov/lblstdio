from uuid import UUID, uuid4

import pytest

from app.application.dto import BoxInput
from app.application.use_cases.annotations.save_annotations import SaveAnnotationsUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.enums import ImageStatus, SourceType, SplitType, VerificationStatus
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.value_objects.bounding_box import BoundingBox


class _FakeImages:
    def __init__(self, image: Image | None) -> None:
        self.image = image
        self.updated: Image | None = None

    async def get_by_id(self, image_id: UUID) -> Image | None:
        if self.image and self.image.id == image_id:
            return self.image
        return None

    async def update(self, image: Image) -> None:
        self.updated = image


class _FakeClasses:
    def __init__(self, classes: list[AnnotationClass]) -> None:
        self._classes = classes

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        return [item for item in self._classes if item.project_id == project_id]


class _FakeAnnotations:
    def __init__(self) -> None:
        self.store: dict[UUID, list[Annotation]] = {}
        self.calls = 0

    async def list_by_image(self, image_id: UUID) -> list[Annotation]:
        return list(self.store.get(image_id, []))

    async def replace_for_image(
        self, image_id: UUID, annotations: list[Annotation]
    ) -> None:
        self.calls += 1
        self.store[image_id] = list(annotations)


class _FakeUow:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def _box_input(class_id: UUID, **overrides) -> BoxInput:
    payload = {
        "class_id": class_id,
        "x_center": 0.5,
        "y_center": 0.5,
        "width": 0.2,
        "height": 0.1,
        **overrides,
    }
    return BoxInput(**payload)


def _setup() -> tuple[SaveAnnotationsUseCase, Image, AnnotationClass, _FakeAnnotations, _FakeUow]:
    image = Image.create(
        project_id=uuid4(),
        file_path="projects/p/images/a.png",
        file_name="a.png",
        width=100,
        height=80,
        split=SplitType.TRAIN,
    )
    annotation_class = AnnotationClass.create(
        project_id=image.project_id,
        name="defect",
        color_hex="#FF0000",
        index_id=0,
    )
    annotations = _FakeAnnotations()
    uow = _FakeUow()
    use_case = SaveAnnotationsUseCase(
        images=_FakeImages(image),
        classes=_FakeClasses([annotation_class]),
        annotations=annotations,
        uow=uow,
    )
    return use_case, image, annotation_class, annotations, uow


class TestSaveAnnotationsUseCase:
    @pytest.mark.asyncio
    async def test_replace_is_atomic_full_set_swap(self) -> None:
        use_case, image, annotation_class, repo, uow = _setup()
        first = [
            _box_input(annotation_class.id, x_center=0.3),
            _box_input(annotation_class.id, x_center=0.7),
        ]
        second = [_box_input(annotation_class.id, y_center=0.2)]

        await use_case.execute(image.id, first)
        result = await use_case.execute(image.id, second)

        assert repo.calls == 2
        assert len(repo.store[image.id]) == 1
        assert result[0].bbox.y_center == 0.2
        assert image.status == ImageStatus.VERIFIED
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_invalid_coordinates_roll_back_without_replace(self) -> None:
        use_case, image, annotation_class, repo, uow = _setup()
        await use_case.execute(image.id, [_box_input(annotation_class.id)])
        uow.committed = False

        with pytest.raises(DomainValidationException):
            await use_case.execute(
                image.id,
                [
                    _box_input(annotation_class.id),
                    _box_input(annotation_class.id, x_center=1.5),
                ],
            )

        assert repo.calls == 1
        assert len(repo.store[image.id]) == 1
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_missing_image_raises_not_found(self) -> None:
        use_case, *_ = _setup()
        with pytest.raises(ResourceNotFoundException):
            await use_case.execute(uuid4(), [])

    @pytest.mark.asyncio
    async def test_unknown_class_is_rejected(self) -> None:
        use_case, image, _, repo, uow = _setup()
        with pytest.raises(DomainValidationException, match="class"):
            await use_case.execute(image.id, [_box_input(uuid4())])
        assert repo.calls == 0
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_preserves_client_annotation_id(self) -> None:
        use_case, image, annotation_class, repo, _ = _setup()
        kept_id = uuid4()
        result = await use_case.execute(
            image.id,
            [_box_input(annotation_class.id, annotation_id=kept_id)],
        )
        assert result[0].id == kept_id
        assert repo.store[image.id][0].id == kept_id

    @pytest.mark.asyncio
    async def test_existing_keypoint_box_stays_pending_without_geometry_edit(self) -> None:
        use_case, image, annotation_class, repo, uow = _setup()
        pending = Annotation.create_from_keypoints(
            image_id=image.id,
            class_id=annotation_class.id,
            bbox=BoundingBox(0.40, 0.50, 0.20, 0.10),
            source_annotation_id=uuid4(),
            confidence=0.81,
        )
        repo.store[image.id] = [pending]
        image.recalculate_status([pending])

        result = await use_case.execute(
            image.id,
            [
                _box_input(
                    annotation_class.id,
                    annotation_id=pending.id,
                    x_center=0.40,
                    y_center=0.50,
                    width=0.20,
                    height=0.10,
                )
            ],
        )

        assert result[0].source == SourceType.KEYPOINT_PROPAGATION
        assert result[0].verification_status == VerificationStatus.PENDING_REVIEW
        assert result[0].confidence == 0.81
        assert image.status == ImageStatus.REQUIRES_REVIEW
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_editing_pending_box_geometry_verifies_it(self) -> None:
        use_case, image, annotation_class, repo, _ = _setup()
        pending = Annotation.create_from_keypoints(
            image_id=image.id,
            class_id=annotation_class.id,
            bbox=BoundingBox(0.40, 0.50, 0.20, 0.10),
            source_annotation_id=uuid4(),
            confidence=0.70,
        )
        repo.store[image.id] = [pending]

        result = await use_case.execute(
            image.id,
            [
                _box_input(
                    annotation_class.id,
                    annotation_id=pending.id,
                    x_center=0.42,
                    y_center=0.51,
                    width=0.22,
                    height=0.12,
                )
            ],
        )

        assert result[0].verification_status == VerificationStatus.VERIFIED
        assert result[0].verified_at is not None
        assert image.status == ImageStatus.VERIFIED

