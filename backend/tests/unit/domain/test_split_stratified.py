from random import Random
from uuid import uuid4

from app.domain.services.class_dir_name import class_dir_name
from app.domain.services.split import assign_splits_stratified
from app.domain.value_objects.split_ratios import SplitRatios


def test_stratified_keeps_each_class_in_train_when_tiny() -> None:
    a, b = uuid4(), uuid4()
    class_ids = [a, a, b]
    splits = assign_splits_stratified(class_ids, SplitRatios(), rng=Random(0))
    assert len(splits) == 3


def test_class_dir_name_strips_separators() -> None:
    assert class_dir_name("good") == "good"
    assert "/" not in class_dir_name("a/b")
    assert "\\" not in class_dir_name("a\\b")
