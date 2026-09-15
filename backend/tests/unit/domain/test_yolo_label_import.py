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


def test_pair_prefers_sibling_labels_dir_and_rejects_duplicate_stems() -> None:
    images = {
        "train/images/a.jpg": b"img",
        "valid/images/b.jpg": b"img",
    }
    labels = {
        "train/labels/a.txt": b"0 0.5 0.5 0.1 0.1\n",
        "valid/labels/b.txt": b"",
    }
    paired = pair_images_and_labels(images, labels)
    assert paired["train/images/a.jpg"] == "train/labels/a.txt"
    assert paired["valid/images/b.jpg"] == "valid/labels/b.txt"

    with pytest.raises(DomainValidationException, match="duplicate"):
        pair_images_and_labels(
            {"train/images/x.jpg": b"a", "valid/images/x.jpg": b"b"},
            {},
        )


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
