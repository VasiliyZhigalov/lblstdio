from collections.abc import Sequence

from app.domain.exceptions import DomainValidationException


def class_dir_name(name: str) -> str:
    cleaned = name.strip().replace("/", "_").replace("\\", "_").replace("..", "_")
    return cleaned or "class"


def require_unique_class_dirs(names: Sequence[str]) -> dict[str, str]:
    """Map folder name to the class name. Reject names that collapse to one folder."""
    folders: dict[str, str] = {}
    for name in names:
        folder = class_dir_name(name)
        previous = folders.get(folder)
        if previous is not None:
            raise DomainValidationException(
                f"class names '{previous}' and '{name}' map to the same folder '{folder}'"
            )
        folders[folder] = name
    return folders
