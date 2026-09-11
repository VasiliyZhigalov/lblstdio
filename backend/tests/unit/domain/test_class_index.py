from uuid import uuid4

import pytest

from app.domain.entities.annotation_class import AnnotationClass
from app.domain.exceptions import DomainValidationException
from app.domain.services.class_index import allocate_next_index, compact_indices


class TestClassIndexAllocation:
    def test_first_class_gets_index_zero(self) -> None:
        assert allocate_next_index([]) == 0

    def test_next_index_is_max_plus_one(self) -> None:
        assert allocate_next_index([0, 1]) == 2
        assert allocate_next_index([0, 1, 2, 3]) == 4

    def test_rejects_duplicate_indices_in_existing_set(self) -> None:
        with pytest.raises(DomainValidationException, match="duplicate"):
            allocate_next_index([0, 1, 1])

    def test_compact_removes_gaps_after_deletion(self) -> None:
        project_id = uuid4()
        classes = [
            AnnotationClass.create(
                project_id=project_id,
                name="a",
                color_hex="#111111",
                index_id=0,
            ),
            AnnotationClass.create(
                project_id=project_id,
                name="c",
                color_hex="#333333",
                index_id=3,
            ),
            AnnotationClass.create(
                project_id=project_id,
                name="b",
                color_hex="#222222",
                index_id=2,
            ),
        ]

        compacted = compact_indices(classes)

        assert [item.index_id for item in compacted] == [0, 1, 2]
        assert [item.name for item in compacted] == ["a", "b", "c"]

    def test_rejects_invalid_hex_color(self) -> None:
        with pytest.raises(DomainValidationException, match="color"):
            AnnotationClass.create(
                project_id=uuid4(),
                name="defect",
                color_hex="red",
                index_id=0,
            )

    def test_rejects_empty_class_name(self) -> None:
        with pytest.raises(DomainValidationException, match="name"):
            AnnotationClass.create(
                project_id=uuid4(),
                name="   ",
                color_hex="#FF0000",
                index_id=0,
            )

    def test_rejects_negative_index(self) -> None:
        with pytest.raises(DomainValidationException, match="index"):
            AnnotationClass.create(
                project_id=uuid4(),
                name="defect",
                color_hex="#FF0000",
                index_id=-1,
            )
