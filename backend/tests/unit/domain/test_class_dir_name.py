import pytest

from app.domain.exceptions import DomainValidationException
from app.domain.services.class_dir_name import class_dir_name, require_unique_class_dirs


def test_class_dir_name_strips_separators() -> None:
    assert class_dir_name(" a/b ") == "a_b"
    assert class_dir_name("   ") == "class"


def test_require_unique_class_dirs_rejects_collision() -> None:
    with pytest.raises(DomainValidationException, match="same folder"):
        require_unique_class_dirs(["a/b", "a_b"])


def test_require_unique_class_dirs_accepts_distinct_names() -> None:
    assert require_unique_class_dirs(["apple", "zebra"]) == {
        "apple": "apple",
        "zebra": "zebra",
    }
