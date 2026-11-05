from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


_MAX_IMAGES = 20000

# Windows share / credential failures that Path.is_dir() raises instead of False.
_WINERR_LOGON = {86, 1326, 1909}
_WINERR_NETWORK = {5, 51, 53, 59, 64, 67, 1231}


def describe_folder_access_error(exc: BaseException, folder: Path | str) -> str:
    path = str(folder)
    winerr = getattr(exc, "winerror", None)
    if winerr in _WINERR_LOGON:
        return (
            f"Нет доступа к «{path}»: неверное имя пользователя или пароль. "
            "Откройте этот сетевой путь в Проводнике, введите учётные данные "
            "и сохраните их, затем запустите стрим снова."
        )
    if winerr in _WINERR_NETWORK:
        return f"Нет доступа к «{path}»: {exc}"
    return f"Не удалось открыть папку «{path}»: {exc}"


def list_image_files(folder: Path) -> list[Path]:
    """Images in `folder` and its subfolders, sorted by relative path."""
    try:
        if not folder.is_dir():
            return []
    except OSError:
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
