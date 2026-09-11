from collections.abc import Sequence

from app.domain.entities.annotation_class import AnnotationClass
from app.domain.exceptions import DomainValidationException


def allocate_next_index(existing_indices: Sequence[int]) -> int:
    if len(existing_indices) != len(set(existing_indices)):
        raise DomainValidationException("duplicate class indices are not allowed")
    if not existing_indices:
        return 0
    return max(existing_indices) + 1


def compact_indices(classes: Sequence[AnnotationClass]) -> list[AnnotationClass]:
    ordered = sorted(classes, key=lambda item: (item.index_id, item.name))
    for new_index, annotation_class in enumerate(ordered):
        annotation_class.index_id = new_index
    return list(ordered)
