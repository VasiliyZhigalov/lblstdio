from __future__ import annotations

from dataclasses import dataclass

HASH_BITS = 64


@dataclass(frozen=True)
class HashCandidate:
    key: str
    phash: int
    keep_always: bool = False


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def max_hamming_for_similarity(similarity: float) -> int:
    if similarity <= 0:
        return HASH_BITS
    if similarity >= 1:
        return 0
    return int(round((1.0 - similarity) * HASH_BITS))


def _min_distance(phash: int, reference: list[int]) -> int:
    if not reference:
        return HASH_BITS
    return min(hamming_distance(phash, other) for other in reference)


def _mean_distance(phash: int, others: list[int]) -> float:
    if not others:
        return float(HASH_BITS)
    return sum(hamming_distance(phash, other) for other in others) / len(others)


def select_diverse_hashes(
    candidates: list[HashCandidate],
    existing: list[int],
    similarity: float,
) -> list[HashCandidate]:
    """Drop near-duplicates, then order the rest from most unlike to most typical."""
    max_dist = max_hamming_for_similarity(similarity)
    indexed = list(enumerate(candidates))
    selected: list[HashCandidate] = []
    reference = [item for item in existing]

    always = [(index, item) for index, item in indexed if item.keep_always]
    rest = [(index, item) for index, item in indexed if not item.keep_always]

    for _index, item in always:
        selected.append(item)
        reference.append(item.phash)

    remaining = list(rest)
    while remaining:
        if not reference:
            pool = [item.phash for _index, item in remaining]
            remaining.sort(
                key=lambda pair: (
                    -_mean_distance(pair[1].phash, pool),
                    pair[0],
                )
            )
        else:
            remaining.sort(
                key=lambda pair: (
                    -_min_distance(pair[1].phash, reference),
                    pair[0],
                )
            )
        _index, pick = remaining.pop(0)
        if reference and _min_distance(pick.phash, reference) <= max_dist:
            break
        selected.append(pick)
        reference.append(pick.phash)
    return selected
