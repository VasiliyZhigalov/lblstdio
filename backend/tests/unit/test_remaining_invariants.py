from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.use_cases.classes.create_class import ListClassesUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, SourceType, SplitType, VerificationStatus
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.services.split import assign_splits
from app.domain.value_objects.bounding_box import BoundingBox
from app.domain.value_objects.split_ratios import SplitRatios
from tests.unit.application.test_create_class import (
    _FakeClasses,
    _FakeProjects,
    _FakeUow,
    _delete_use_case,
)
from tests.unit.application.test_upload_images import _use_case


def test_manual_annotation_requires_full_confidence() -> None:
    with pytest.raises(DomainValidationException, match="confidence"):
        Annotation(
            id=uuid4(),
            image_id=uuid4(),
            class_id=uuid4(),
            bbox=BoundingBox(0.5, 0.5, 0.1, 0.1),
            source=SourceType.MANUAL,
            verification_status=VerificationStatus.VERIFIED,
            confidence=0.9,
        )


def test_confidence_must_be_unit_interval() -> None:
    with pytest.raises(DomainValidationException, match="confidence"):
        Annotation(
            id=uuid4(),
            image_id=uuid4(),
            class_id=uuid4(),
            bbox=BoundingBox(0.5, 0.5, 0.1, 0.1),
            source=SourceType.MODEL_PREDICTION,
            verification_status=VerificationStatus.PENDING_REVIEW,
            confidence=1.5,
        )


def test_pending_prediction_cannot_have_verified_at() -> None:
    with pytest.raises(DomainValidationException, match="verified_at"):
        Annotation(
            id=uuid4(),
            image_id=uuid4(),
            class_id=uuid4(),
            bbox=BoundingBox(0.5, 0.5, 0.1, 0.1),
            source=SourceType.MODEL_PREDICTION,
            verification_status=VerificationStatus.PENDING_REVIEW,
            confidence=0.4,
            verified_at=datetime.now(UTC),
        )


def test_keypoint_annotation_is_pending_and_can_be_rejected() -> None:
    annotation = Annotation.create_from_keypoints(
        image_id=uuid4(),
        class_id=uuid4(),
        bbox=BoundingBox(0.5, 0.5, 0.1, 0.1),
        source_annotation_id=uuid4(),
    )
    assert annotation.source == SourceType.KEYPOINT_PROPAGATION
    assert annotation.is_exportable is False
    annotation.reject()
    assert annotation.verification_status == VerificationStatus.REJECTED


def test_image_invariants_and_dataset_gate() -> None:
    with pytest.raises(DomainValidationException, match="dimensions"):
        Image.create(
            project_id=uuid4(),
            file_path="a.png",
            file_name="a.png",
            width=0,
            height=10,
            split=SplitType.TRAIN,
        )
    with pytest.raises(DomainValidationException, match="file_name"):
        Image.create(
            project_id=uuid4(),
            file_path="a.png",
            file_name="  ",
            width=10,
            height=10,
            split=SplitType.TRAIN,
        )
    image = Image.create(
        project_id=uuid4(),
        file_path="a.png",
        file_name="a.png",
        width=10,
        height=10,
        split=SplitType.TRAIN,
    )
    image.recalculate_status([])
    assert image.status == ImageStatus.UNANNOTATED
    image.reject()
    image.recalculate_status(
        [Annotation.create_manual(image.id, uuid4(), BoundingBox(0.5, 0.5, 0.1, 0.1))]
    )
    assert image.status == ImageStatus.REJECTED
    assert image.can_be_included_in_dataset() is False


def test_project_rename() -> None:
    project = Project.create("Old")
    project.rename("New", "updated")
    assert project.name == "New"
    assert project.description == "updated"
    project.rename("Newer")
    assert project.name == "Newer"
    assert project.description == "updated"
    with pytest.raises(DomainValidationException, match="name"):
        project.rename("  ")


def test_split_validation_edges() -> None:
    with pytest.raises(DomainValidationException, match="negative"):
        assign_splits(-1)
    with pytest.raises(DomainValidationException, match="negative"):
        SplitRatios(train=-0.1, valid=0.6, test=0.5)


@pytest.mark.asyncio
async def test_list_classes_and_delete_last_class() -> None:
    project = Project.create("P")
    classes = _FakeClasses()
    listed = await ListClassesUseCase(classes).execute(project.id)
    assert listed == []

    from app.application.use_cases.classes.create_class import CreateClassUseCase

    created = await CreateClassUseCase(_FakeProjects(project), classes, _FakeUow()).execute(
        project.id, "only", "#ABCDEF"
    )
    await _delete_use_case(project, classes).execute(created.id, project.id)
    assert await classes.list_by_project(project.id) == []


@pytest.mark.asyncio
async def test_delete_missing_class() -> None:
    with pytest.raises(ResourceNotFoundException):
        await _delete_use_case(Project.create("P"), _FakeClasses()).execute(uuid4())


@pytest.mark.asyncio
async def test_upload_requires_files() -> None:
    use_case, _, _, uow, project = _use_case()
    with pytest.raises(DomainValidationException, match="file"):
        await use_case.execute(project.id, [])
    assert uow.committed is False
