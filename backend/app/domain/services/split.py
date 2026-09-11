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


def assign_splits(count: int, ratios: SplitRatios | None = None) -> list[SplitType]:
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
    return (
        [SplitType.TRAIN] * counts[0]
        + [SplitType.VALID] * counts[1]
        + [SplitType.TEST] * counts[2]
    )
