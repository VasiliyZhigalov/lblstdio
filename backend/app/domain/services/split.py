from collections.abc import Sequence
from random import Random
from uuid import UUID

from app.domain.enums import SplitType
from app.domain.exceptions import DomainValidationException
from app.domain.value_objects.split_ratios import SplitRatios


def _hamilton(count: int, weights: tuple[float, float, float]) -> list[int]:
    raw = [count * weight for weight in weights]
    floors = [int(value) for value in raw]
    leftover = count - sum(floors)
    order = sorted(
        range(3),
        key=lambda index: (raw[index] - floors[index], -index),
        reverse=True,
    )
    for step in range(leftover):
        floors[order[step % 3]] += 1
    return floors


def _labels_from_counts(counts: list[int]) -> list[SplitType]:
    return (
        [SplitType.TRAIN] * counts[0]
        + [SplitType.VALID] * counts[1]
        + [SplitType.TEST] * counts[2]
    )


def _require_nonempty_valid(
    splits: list[SplitType],
    *,
    protected: Sequence[bool] | None = None,
    class_ids: Sequence[UUID] | None = None,
) -> list[SplitType]:
    """Keep at least one valid image, or refuse a split that cannot have one."""
    if not splits:
        return splits
    flags = list(protected) if protected is not None else [False] * len(splits)
    if any(
        split == SplitType.VALID and not flagged
        for split, flagged in zip(splits, flags, strict=True)
    ):
        return splits
    movable = [index for index, flagged in enumerate(flags) if not flagged]
    if len(movable) < 2:
        raise DomainValidationException("cannot form a non-empty valid split")
    trains = [index for index in movable if splits[index] == SplitType.TRAIN]
    pool = trains or movable
    donor = pool[-1]
    if class_ids is not None:
        counts: dict[UUID, int] = {}
        for index in pool:
            counts[class_ids[index]] = counts.get(class_ids[index], 0) + 1
        duplicates = [index for index in pool if counts[class_ids[index]] > 1]
        if duplicates:
            donor = duplicates[-1]
    updated = list(splits)
    updated[donor] = SplitType.VALID
    return updated


def _assign_splits_raw(count: int, ratios: SplitRatios | None = None) -> list[SplitType]:
    if count < 0:
        raise DomainValidationException("image count cannot be negative")
    ratios = ratios or SplitRatios()
    counts = _hamilton(count, (ratios.train, ratios.valid, ratios.test))
    if count >= 3:
        for index in range(3):
            if counts[index] == 0:
                donor = max(range(3), key=lambda item: counts[item])
                if counts[donor] > 1:
                    counts[donor] -= 1
                    counts[index] += 1
    return _labels_from_counts(counts)


def assign_splits(count: int, ratios: SplitRatios | None = None) -> list[SplitType]:
    return _require_nonempty_valid(_assign_splits_raw(count, ratios))


def assign_splits_stratified(
    class_ids: Sequence[UUID],
    ratios: SplitRatios | None = None,
    *,
    rng: Random | None = None,
) -> list[SplitType]:
    ratios = ratios or SplitRatios()
    rng = rng or Random()
    by_class: dict[UUID, list[int]] = {}
    for index, class_id in enumerate(class_ids):
        by_class.setdefault(class_id, []).append(index)
    result = [SplitType.TRAIN] * len(class_ids)
    for indices in by_class.values():
        rng.shuffle(indices)
        splits = _assign_splits_raw(len(indices), ratios)
        for index, split in zip(indices, splits, strict=True):
            result[index] = split
    return _require_nonempty_valid(result, class_ids=class_ids)


def _train_valid_weights(ratios: SplitRatios | None) -> tuple[float, float]:
    ratios = ratios or SplitRatios()
    pool = ratios.train + ratios.valid
    if pool <= 0 or ratios.train <= 0 or ratios.valid <= 0:
        raise DomainValidationException("train and valid ratios must both be positive")
    return ratios.train / pool, ratios.valid / pool


def _assign_train_valid_raw(
    count: int, ratios: SplitRatios | None = None
) -> list[SplitType]:
    """Split images into train and valid only. Test is never assigned here."""
    if count < 0:
        raise DomainValidationException("image count cannot be negative")
    if count == 0:
        return []
    train_weight, valid_weight = _train_valid_weights(ratios)
    raw = [count * train_weight, count * valid_weight]
    floors = [int(value) for value in raw]
    leftover = count - sum(floors)
    if leftover:
        if (raw[1] - floors[1]) > (raw[0] - floors[0]):
            floors[1] += leftover
        else:
            floors[0] += leftover
    if count >= 2:
        if floors[0] == 0:
            floors[0] = 1
            floors[1] -= 1
        elif floors[1] == 0:
            floors[1] = 1
            floors[0] -= 1
    return [SplitType.TRAIN] * floors[0] + [SplitType.VALID] * floors[1]


def assign_train_valid(count: int, ratios: SplitRatios | None = None) -> list[SplitType]:
    return _require_nonempty_valid(_assign_train_valid_raw(count, ratios))


def assign_train_valid_stratified(
    class_ids: Sequence[UUID],
    ratios: SplitRatios | None = None,
    *,
    rng: Random | None = None,
) -> list[SplitType]:
    rng = rng or Random()
    by_class: dict[UUID, list[int]] = {}
    for index, class_id in enumerate(class_ids):
        by_class.setdefault(class_id, []).append(index)
    result = [SplitType.TRAIN] * len(class_ids)
    for indices in by_class.values():
        rng.shuffle(indices)
        splits = _assign_train_valid_raw(len(indices), ratios)
        for index, split in zip(indices, splits, strict=True):
            result[index] = split
    return _require_nonempty_valid(result, class_ids=class_ids)


def assign_with_holdout(
    holdout: Sequence[bool],
    ratios: SplitRatios | None = None,
    *,
    class_ids: Sequence[UUID] | None = None,
    rng: Random | None = None,
) -> list[SplitType]:
    """Keep manually marked test images in test; split the rest into train and valid."""
    if class_ids is not None and len(class_ids) != len(holdout):
        raise DomainValidationException("class ids must align with holdout flags")
    rng = rng or Random()
    pool_indexes = [index for index, flagged in enumerate(holdout) if not flagged]
    if not pool_indexes:
        raise DomainValidationException(
            "every verified image is marked as test; leave some images for train and valid"
        )
    if class_ids is None:
        rng.shuffle(pool_indexes)
        pool_splits = _assign_train_valid_raw(len(pool_indexes), ratios)
    else:
        pool_class_ids = [class_ids[index] for index in pool_indexes]
        pool_splits = assign_train_valid_stratified(pool_class_ids, ratios, rng=rng)
    result = [SplitType.TEST] * len(holdout)
    for index, split in zip(pool_indexes, pool_splits, strict=True):
        result[index] = split
    return _require_nonempty_valid(result, protected=holdout, class_ids=class_ids)
