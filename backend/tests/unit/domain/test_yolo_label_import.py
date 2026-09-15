import io
import zipfile

import pytest

from app.domain.exceptions import DomainValidationException
from app.domain.services.yolo_label_import import (
    ParsedYoloBox,
    expand_upload_bundle,
    pair_images_and_labels,
    parse_class_names,
    parse_yolo_label_file,
)


def test_parse_yolo_label_file_boxes_and_empty() -> None:
    boxes = parse_yolo_label_file("0 0.5 0.5 0.2 0.1\n1 0.3 0.4 0.1 0.2\n")
    assert boxes == [
        ParsedYoloBox(class_index=0, x_center=0.5, y_center=0.5, width=0.2, height=0.1),
        ParsedYoloBox(class_index=1, x_center=0.3, y_center=0.4, width=0.1, height=0.2),
    ]
    assert parse_yolo_label_file("  \n") == []


def test_parse_yolo_label_file_rejects_bad_line() -> None:
    with pytest.raises(DomainValidationException, match="label"):
        parse_yolo_label_file("0 0.5 0.5\n")


def test_parse_class_names_from_yaml_list_and_classes_txt() -> None:
    assert parse_class_names(
        {"data.yaml": b"names: [person, car]\n"},
        {},
    ) == ["person", "car"]
    assert parse_class_names(
        {},
        {"classes.txt": b"dog\ncat\n"},
    ) == ["dog", "cat"]


def test_parse_class_names_rejects_bad_dict_keys() -> None:
    with pytest.raises(DomainValidationException, match="names"):
        parse_class_names({"data.yaml": b"names: {a: person}\n"}, {})


def test_pair_allows_same_stem_across_splits_via_siblings() -> None:
    images = {
        "train/images/x.jpg": b"img-train",
        "valid/images/x.jpg": b"img-valid",
    }
    labels = {
        "train/labels/x.txt": b"0 0.5 0.5 0.1 0.1\n",
        "valid/labels/x.txt": b"",
    }
    paired = pair_images_and_labels(images, labels)
    assert paired["train/images/x.jpg"] == "train/labels/x.txt"
    assert paired["valid/images/x.jpg"] == "valid/labels/x.txt"


def test_pair_rejects_ambiguous_labels_without_sibling() -> None:
    with pytest.raises(DomainValidationException, match="ambiguous"):
        pair_images_and_labels(
            {"flat/x.jpg": b"img"},
            {
                "elsewhere/x.txt": b"0 0.5 0.5 0.1 0.1\n",
                "other/x.txt": b"0 0.4 0.4 0.1 0.1\n",
            },
        )


def test_pair_rejects_shared_stem_with_single_global_label() -> None:
    """One global label must not attach to every image with the same stem."""
    with pytest.raises(DomainValidationException, match="ambiguous"):
        pair_images_and_labels(
            {
                "a/x.jpg": b"img-a",
                "b/x.jpg": b"img-b",
            },
            {"labels/x.txt": b"0 0.5 0.5 0.1 0.1\n"},
        )


def test_pair_allows_unique_global_stem_for_single_image() -> None:
    paired = pair_images_and_labels(
        {"photos/board.jpg": b"img"},
        {"annotations/board.txt": b"0 0.5 0.5 0.1 0.1\n"},
    )
    assert paired["photos/board.jpg"] == "annotations/board.txt"


def test_expand_upload_bundle_unpacks_zip_and_keeps_relative_paths() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("train/images/cat.jpg", b"jpg")
        archive.writestr("train/labels/cat.txt", b"0 0.5 0.5 0.2 0.2\n")
        archive.writestr("data.yaml", b"names: [cat]\n")
    images, labels, class_files = expand_upload_bundle(
        [
            ("bundle.zip", buf.getvalue()),
            ("loose/dog.png", b"png"),
            ("loose/dog.txt", b""),
        ]
    )
    assert "train/images/cat.jpg" in images
    assert "train/labels/cat.txt" in labels
    assert "loose/dog.png" in images
    assert "loose/dog.txt" in labels
    assert "data.yaml" in class_files


def test_expand_rejects_path_traversal_in_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("../evil.png", b"png")
    with pytest.raises(DomainValidationException, match="invalid path"):
        expand_upload_bundle([("bad.zip", buf.getvalue())])


def test_expand_rejects_duplicate_paths() -> None:
    with pytest.raises(DomainValidationException, match="duplicate path"):
        expand_upload_bundle(
            [
                ("a/img.png", b"one"),
                ("a/img.png", b"two"),
            ]
        )


def test_expand_rejects_oversized_zip_member(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.domain.services.yolo_label_import.MAX_ZIP_MEMBER_BYTES", 8
    )
    monkeypatch.setattr(
        "app.domain.services.yolo_label_import.MAX_ZIP_COMPRESSION_RATIO", 10_000
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("big.png", b"0123456789")
    with pytest.raises(DomainValidationException, match="size limit"):
        expand_upload_bundle([("big.zip", buf.getvalue())])


def test_expand_rejects_zip_bomb_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.domain.services.yolo_label_import.MAX_ZIP_COMPRESSION_RATIO", 2.0
    )
    # Highly compressible payload: tiny compressed size, larger declared size.
    payload = b"\x00" * 200
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.png", payload)
    with pytest.raises(DomainValidationException, match="zip bomb"):
        expand_upload_bundle([("bomb.zip", buf.getvalue())])
