from random import Random
from uuid import uuid4

import pytest

from app.domain.enums import SplitType
from app.domain.exceptions import DomainValidationException
from app.domain.services.split import assign_train_valid, assign_with_holdout
from app.domain.value_objects.split_ratios import SplitRatios


def test_assign_train_valid_never_emits_test() -> None:
    splits = assign_train_valid(10, SplitRatios(train=0.7, valid=0.2, test=0.1))
    assert splits.count(SplitType.TRAIN) == 8
    assert splits.count(SplitType.VALID) == 2
    assert SplitType.TEST not in splits


def test_assign_with_holdout_keeps_pinned_images_in_test() -> None:
    holdout = [False, True, False, False, True]
    splits = assign_with_holdout(
        holdout,
        SplitRatios(train=0.5, valid=0.5, test=0.0),
        rng=Random(0),
    )
    assert [split for split, flagged in zip(splits, holdout, strict=True) if flagged] == [
        SplitType.TEST,
        SplitType.TEST,
    ]
    pool = [split for split, flagged in zip(splits, holdout, strict=True) if not flagged]
    assert SplitType.TEST not in pool
    assert SplitType.TRAIN in pool
    assert SplitType.VALID in pool


def test_assign_with_holdout_stratified_does_not_train_on_test_class_rows() -> None:
    class_a, class_b = uuid4(), uuid4()
    holdout = [True, False, False, False]
    splits = assign_with_holdout(
        holdout,
        SplitRatios(train=0.5, valid=0.5, test=0.0),
        class_ids=[class_a, class_a, class_b, class_b],
        rng=Random(1),
    )
    assert splits[0] == SplitType.TEST
    assert SplitType.TEST not in splits[1:]


def test_assign_with_holdout_rejects_when_nothing_left_to_train() -> None:
    with pytest.raises(DomainValidationException):
        assign_with_holdout([True, True], SplitRatios(train=0.8, valid=0.2, test=0.0))
