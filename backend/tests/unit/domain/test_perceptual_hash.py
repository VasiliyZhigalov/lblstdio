from app.domain.services.perceptual_hash import (
    HASH_BITS,
    HashCandidate,
    hamming_distance,
    max_hamming_for_similarity,
    select_diverse_hashes,
)


def test_exact_hashes_have_zero_hamming() -> None:
    assert hamming_distance(0b1010, 0b1010) == 0


def test_similarity_one_only_drops_identical_hashes() -> None:
    assert max_hamming_for_similarity(1.0) == 0
    assert max_hamming_for_similarity(0.0) == HASH_BITS
    assert max_hamming_for_similarity(0.75) == HASH_BITS // 4


def test_select_skips_near_duplicates_of_kept_and_existing() -> None:
    existing = [0]
    candidates = [
        HashCandidate(key="clone", phash=1),
        HashCandidate(key="other", phash=(1 << 64) - 1),
        HashCandidate(key="clone-2", phash=2),
    ]

    kept = select_diverse_hashes(candidates, existing, similarity=0.9)

    assert [item.key for item in kept] == ["other"]


def test_select_puts_the_most_unlike_frame_first() -> None:
    candidates = [
        HashCandidate(key="a", phash=0),
        HashCandidate(key="b", phash=1),
        HashCandidate(key="far", phash=(1 << 64) - 1),
    ]

    kept = select_diverse_hashes(candidates, existing=[], similarity=0.75)

    assert [item.key for item in kept][0] == "far"
    assert "a" in {item.key for item in kept}
    assert "b" not in {item.key for item in kept}


def test_labeled_near_duplicates_are_kept() -> None:
    candidates = [
        HashCandidate(key="raw", phash=0),
        HashCandidate(key="labeled", phash=1, keep_always=True),
    ]

    kept = select_diverse_hashes(candidates, existing=[], similarity=0.9)

    assert [item.key for item in kept] == ["labeled"]
