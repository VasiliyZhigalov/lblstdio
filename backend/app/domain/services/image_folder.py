from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


_MAX_IMAGES = 20000


def list_image_files(folder: Path) -> list[Path]:
    """Images in `folder` and its subfolders, sorted by relative path."""
    if not folder.is_dir():
        return []
    files: list[Path] = []
    try:
        candidates = folder.rglob("*")
    except OSError:
        return []
    for path in candidates:
        try:
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            relative = path.relative_to(folder)
        except OSError:
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        files.append(path)
        if len(files) >= _MAX_IMAGES:
            break
    return sorted(files, key=lambda path: path.relative_to(folder).as_posix().lower())
