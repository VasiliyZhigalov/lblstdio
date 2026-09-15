from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml

from app.domain.exceptions import DomainValidationException

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_LABEL_EXTENSIONS = {".txt"}
_CLASS_FILE_NAMES = {"data.yaml", "data.yml", "classes.txt"}

MAX_ZIP_MEMBERS = 10_000
MAX_ZIP_MEMBER_BYTES = 20 * 1024 * 1024
MAX_ZIP_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100.0


@dataclass(frozen=True)
class ParsedYoloBox:
    class_index: int
    x_center: float
    y_center: float
    width: float
    height: float


def _normalize_path(path: str) -> str:
    cleaned = path.replace("\\", "/")
    pure = PurePosixPath(cleaned)
    if pure.is_absolute():
        raise DomainValidationException(f"invalid path '{path}'")
    parts = [part for part in pure.parts if part not in ("", ".")]
    if ".." in parts:
        raise DomainValidationException(f"invalid path '{path}'")
    return "/".join(parts)


def parse_yolo_label_file(content: str) -> list[ParsedYoloBox]:
    boxes: list[ParsedYoloBox] = []
    for line_no, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 5:
            raise DomainValidationException(
                f"invalid YOLO label on line {line_no}: expected 5 values"
            )
        try:
            class_index = int(parts[0])
            x_center = float(parts[1])
            y_center = float(parts[2])
            width = float(parts[3])
            height = float(parts[4])
        except ValueError as exc:
            raise DomainValidationException(
                f"invalid YOLO label on line {line_no}: {exc}"
            ) from exc
        if class_index < 0:
            raise DomainValidationException(
                f"invalid YOLO label on line {line_no}: class index must be >= 0"
            )
        boxes.append(
            ParsedYoloBox(
                class_index=class_index,
                x_center=x_center,
                y_center=y_center,
                width=width,
                height=height,
            )
        )
    return boxes


def parse_class_names(
    yaml_files: dict[str, bytes],
    text_files: dict[str, bytes],
) -> list[str] | None:
    for name, payload in yaml_files.items():
        lower = PurePosixPath(name).name.lower()
        if lower not in {"data.yaml", "data.yml"}:
            continue
        try:
            data = yaml.safe_load(payload.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise DomainValidationException(f"cannot parse {name}: {exc}") from exc
        names = data.get("names")
        if names is None:
            return None
        if isinstance(names, dict):
            try:
                ordered = [
                    names[key]
                    for key in sorted(names.keys(), key=lambda item: int(item))
                ]
            except (TypeError, ValueError) as exc:
                raise DomainValidationException(
                    f"{name}: 'names' keys must be integers"
                ) from exc
            return [str(item).strip() for item in ordered if str(item).strip()]
        if isinstance(names, list):
            return [str(item).strip() for item in names if str(item).strip()]
        raise DomainValidationException(f"{name}: 'names' must be a list or mapping")

    for name, payload in text_files.items():
        if PurePosixPath(name).name.lower() != "classes.txt":
            continue
        try:
            lines = payload.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise DomainValidationException(f"cannot parse {name}: {exc}") from exc
        return [line.strip() for line in lines if line.strip()]
    return None


def _stem(path: str) -> str:
    return PurePosixPath(path).stem


def _sibling_label_path(image_path: str) -> str | None:
    path = PurePosixPath(image_path)
    if path.parent.name.lower() != "images":
        return None
    return str(path.parent.parent / "labels" / f"{path.stem}.txt")


def pair_images_and_labels(
    images: dict[str, bytes],
    labels: dict[str, bytes],
) -> dict[str, str | None]:
    """Pair images to labels.

    Same basename across train/valid/test is allowed (Roboflow layout).
    Prefer sibling ``labels/`` next to ``images/``, then same directory,
    then a unique global stem match only when exactly one image has that stem.
    """
    labels_by_stem: dict[str, list[str]] = {}
    for path in labels:
        labels_by_stem.setdefault(_stem(path), []).append(path)

    paired: dict[str, str | None] = {}
    images_per_stem: dict[str, int] = {}
    for image_path in images:
        images_per_stem[_stem(image_path)] = images_per_stem.get(_stem(image_path), 0) + 1

    for image_path in images:
        stem = _stem(image_path)
        candidates = labels_by_stem.get(stem, [])
        if not candidates:
            paired[image_path] = None
            continue

        sibling = _sibling_label_path(image_path)
        if sibling and sibling in labels:
            paired[image_path] = sibling
            continue

        same_dir = str(PurePosixPath(image_path).with_suffix(".txt"))
        if same_dir in labels:
            paired[image_path] = same_dir
            continue

        if len(candidates) == 1 and images_per_stem.get(stem, 0) == 1:
            paired[image_path] = candidates[0]
            continue

        raise DomainValidationException(
            f"ambiguous labels for image '{image_path}': "
            f"stem '{stem}' matches {images_per_stem.get(stem, 0)} images; "
            f"use sibling labels/ or same-directory .txt files"
            if images_per_stem.get(stem, 0) > 1
            else f"ambiguous labels for image '{image_path}': {', '.join(sorted(candidates))}"
        )
    return paired


def _check_zip_member(info: zipfile.ZipInfo, *, total_uncompressed: int) -> int:
    size = int(info.file_size)
    if size < 0:
        raise DomainValidationException("invalid zip member size")
    if size > MAX_ZIP_MEMBER_BYTES:
        raise DomainValidationException(
            f"zip member '{info.filename}' exceeds the size limit"
        )
    compressed = int(info.compress_size) if info.compress_size else 0
    if compressed > 0 and size / compressed > MAX_ZIP_COMPRESSION_RATIO:
        raise DomainValidationException(
            f"zip member '{info.filename}' looks like a zip bomb"
        )
    next_total = total_uncompressed + size
    if next_total > MAX_ZIP_TOTAL_UNCOMPRESSED:
        raise DomainValidationException("zip archive uncompressed size exceeds the limit")
    return next_total


def expand_upload_bundle(
    files: list[tuple[str, bytes]],
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, bytes]]:
    images: dict[str, bytes] = {}
    labels: dict[str, bytes] = {}
    class_files: dict[str, bytes] = {}
    seen_paths: set[str] = set()

    def _ingest(path: str, content: bytes) -> None:
        normalized = _normalize_path(path)
        if not normalized:
            return
        if normalized in seen_paths:
            raise DomainValidationException(f"duplicate path '{normalized}' in upload")
        seen_paths.add(normalized)
        name = PurePosixPath(normalized).name.lower()
        suffix = PurePosixPath(normalized).suffix.lower()
        if name in _CLASS_FILE_NAMES:
            class_files[normalized] = content
            return
        if suffix in _IMAGE_EXTENSIONS:
            images[normalized] = content
            return
        if suffix in _LABEL_EXTENSIONS:
            labels[normalized] = content
            return
        if suffix == ".zip":
            raise DomainValidationException("nested zip archives are not supported")
        # ignore other sidecar files (e.g. .json, .xml)

    for filename, content in files:
        normalized = _normalize_path(filename)
        suffix = PurePosixPath(normalized).suffix.lower()
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    members = [info for info in archive.infolist() if not info.is_dir()]
                    if len(members) > MAX_ZIP_MEMBERS:
                        raise DomainValidationException(
                            f"zip archive '{filename}' has too many files"
                        )
                    total_uncompressed = 0
                    for info in members:
                        total_uncompressed = _check_zip_member(
                            info, total_uncompressed=total_uncompressed
                        )
                        member = _normalize_path(info.filename)
                        if not member:
                            continue
                        payload = archive.read(info)
                        if len(payload) > MAX_ZIP_MEMBER_BYTES:
                            raise DomainValidationException(
                                f"zip member '{info.filename}' exceeds the size limit"
                            )
                        _ingest(member, payload)
            except zipfile.BadZipFile as exc:
                raise DomainValidationException(
                    f"invalid zip archive '{filename}'"
                ) from exc
            continue
        _ingest(normalized, content)

    return images, labels, class_files
