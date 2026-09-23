from __future__ import annotations

import io
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from app.domain.exceptions import DomainValidationException

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_LABEL_EXTENSIONS = {".txt"}
_CLASS_FILE_NAMES = {"data.yaml", "data.yml", "classes.txt", "notes.json"}

MAX_ZIP_MEMBERS = 10_000
MAX_ZIP_MEMBER_BYTES = 20 * 1024 * 1024
MAX_ZIP_TOTAL_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
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


def _names_from_yaml_value(name: str, names: object) -> list[str]:
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


def _names_from_notes_json(name: str, payload: bytes) -> list[str] | None:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainValidationException(f"cannot parse {name}: {exc}") from exc
    if not isinstance(data, dict):
        return None
    categories = data.get("categories")
    if not isinstance(categories, list):
        return None
    indexed: list[tuple[int, str]] = []
    for offset, item in enumerate(categories):
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name")
        if raw_name is None:
            continue
        label = str(raw_name).strip()
        if not label:
            continue
        raw_id = item.get("id", offset)
        try:
            class_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise DomainValidationException(
                f"{name}: category id must be an integer"
            ) from exc
        indexed.append((class_id, label))
    indexed.sort(key=lambda item: item[0])
    return [label for _, label in indexed] or None


def _yaml_nc_matches(data: dict, parsed: list[str]) -> bool:
    raw_nc = data.get("nc")
    if raw_nc is None:
        return True
    try:
        return int(raw_nc) == len(parsed)
    except (TypeError, ValueError):
        return True


def parse_class_names(
    yaml_files: dict[str, bytes],
    text_files: dict[str, bytes],
    json_files: dict[str, bytes] | None = None,
) -> list[str] | None:
    yaml_fallback: list[str] | None = None
    for name, payload in yaml_files.items():
        lower = PurePosixPath(name).name.lower()
        if lower not in {"data.yaml", "data.yml"}:
            continue
        try:
            data = yaml.safe_load(payload.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise DomainValidationException(f"cannot parse {name}: {exc}") from exc
        if not isinstance(data, dict):
            continue
        names = data.get("names")
        if names is None:
            # Label Studio often writes `names:` without an indented mapping.
            continue
        parsed = _names_from_yaml_value(name, names)
        if not parsed:
            continue
        if _yaml_nc_matches(data, parsed):
            return parsed
        if yaml_fallback is None:
            yaml_fallback = parsed

    for name, payload in text_files.items():
        if PurePosixPath(name).name.lower() != "classes.txt":
            continue
        try:
            lines = payload.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise DomainValidationException(f"cannot parse {name}: {exc}") from exc
        parsed = [line.strip() for line in lines if line.strip()]
        if parsed:
            return parsed

    for name, payload in (json_files or {}).items():
        if PurePosixPath(name).name.lower() != "notes.json":
            continue
        parsed = _names_from_notes_json(name, payload)
        if parsed:
            return parsed
    return yaml_fallback


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

    When several images share a stem and a given image has no sibling/same-dir
    label, leave it unpaired instead of failing the whole upload (common when a
    zip contains both ``images/`` and ``train/images/`` copies).
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

        if images_per_stem.get(stem, 0) > 1:
            # Cannot safely attach a non-local label when the stem is shared.
            paired[image_path] = None
            continue

        raise DomainValidationException(
            f"ambiguous labels for image '{image_path}': {', '.join(sorted(candidates))}"
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


def _read_bytes(content: bytes | Path) -> bytes:
    if isinstance(content, Path):
        return content.read_bytes()
    return content


def _open_zip(content: bytes | Path) -> zipfile.ZipFile:
    if isinstance(content, Path):
        return zipfile.ZipFile(content)
    return zipfile.ZipFile(io.BytesIO(content))


def expand_upload_bundle(
    files: list[tuple[str, bytes | Path]],
    *,
    image_staging_dir: Path | None = None,
) -> tuple[dict[str, bytes | Path], dict[str, bytes], dict[str, bytes]]:
    images: dict[str, bytes | Path] = {}
    labels: dict[str, bytes] = {}
    class_files: dict[str, bytes] = {}
    seen_paths: set[str] = set()
    staged_index = 0

    def _stage_image(content: bytes | Path, suffix: str) -> Path:
        nonlocal staged_index
        assert image_staging_dir is not None
        if isinstance(content, Path):
            return content
        dest = image_staging_dir / f"{staged_index:05d}{suffix}"
        staged_index += 1
        dest.write_bytes(content)
        return dest

    def _ingest(path: str, content: bytes | Path) -> None:
        normalized = _normalize_path(path)
        if not normalized:
            return
        if normalized in seen_paths:
            raise DomainValidationException(f"duplicate path '{normalized}' in upload")
        seen_paths.add(normalized)
        name = PurePosixPath(normalized).name.lower()
        suffix = PurePosixPath(normalized).suffix.lower()
        if name in _CLASS_FILE_NAMES:
            class_files[normalized] = _read_bytes(content)
            return
        if suffix in _IMAGE_EXTENSIONS:
            if image_staging_dir is None:
                images[normalized] = _read_bytes(content)
            else:
                images[normalized] = _stage_image(content, suffix)
            return
        if suffix in _LABEL_EXTENSIONS:
            labels[normalized] = _read_bytes(content)
            return
        if suffix == ".zip":
            raise DomainValidationException("nested zip archives are not supported")
        # ignore other sidecar files (e.g. .json, .xml)

    def _ingest_zip_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> None:
        member = _normalize_path(info.filename)
        if not member:
            return
        suffix = PurePosixPath(member).suffix.lower()
        name = PurePosixPath(member).name.lower()
        stream_image = (
            image_staging_dir is not None
            and suffix in _IMAGE_EXTENSIONS
            and name not in _CLASS_FILE_NAMES
        )
        if stream_image:
            assert image_staging_dir is not None
            dest = image_staging_dir / f"zip_{staged_image_index[0]:05d}{suffix}"
            staged_image_index[0] += 1
            with archive.open(info, "r") as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            if dest.stat().st_size > MAX_ZIP_MEMBER_BYTES:
                dest.unlink(missing_ok=True)
                raise DomainValidationException(
                    f"zip member '{info.filename}' exceeds the size limit"
                )
            _ingest(member, dest)
            return
        payload = archive.read(info)
        if len(payload) > MAX_ZIP_MEMBER_BYTES:
            raise DomainValidationException(
                f"zip member '{info.filename}' exceeds the size limit"
            )
        _ingest(member, payload)

    staged_image_index = [0]

    for filename, content in files:
        normalized = _normalize_path(filename)
        suffix = PurePosixPath(normalized).suffix.lower()
        if suffix == ".zip":
            try:
                with _open_zip(content) as archive:
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
                        _ingest_zip_member(archive, info)
            except zipfile.BadZipFile as exc:
                raise DomainValidationException(
                    f"invalid zip archive '{filename}'"
                ) from exc
            continue
        _ingest(normalized, content)

    return images, labels, class_files
