from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ENV_DATA_ROOT = "LBLSTDIO_DATA_ROOT"
BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = "."


@dataclass(frozen=True)
class AppSettings:
    data_root: Path

    @property
    def database_path(self) -> Path:
        return (self.data_root / "app.db").resolve()

    @property
    def database_url(self) -> str:
        # Absolute paths: sqlite+aiosqlite:///C:/... or ////server/share/...
        return f"sqlite+aiosqlite:///{self.database_path.as_posix()}"

    @property
    def storage_root(self) -> Path:
        return (self.data_root / "storage").resolve()


def _config_candidates(backend_dir: Path) -> list[Path]:
    return [backend_dir / "config.yaml", backend_dir / "config.yml"]


def _read_data_root_from_file(backend_dir: Path) -> str | None:
    for path in _config_candidates(backend_dir):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"config must be a mapping: {path}")
        value = payload.get("data_root")
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"data_root must be a non-empty string: {path}")
        return value.strip()
    return None


def _resolve_data_root(raw: str | Path, base_dir: Path) -> Path:
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def load_settings(
    data_root: str | Path | None = None,
    *,
    backend_dir: Path | None = None,
    environ: dict[str, str] | None = None,
) -> AppSettings:
    """Resolve data root: explicit arg → env → config.yaml → default ``.``."""
    base = (backend_dir or BACKEND_DIR).resolve()
    env = environ if environ is not None else os.environ

    raw: str | Path | None = data_root
    if raw is None:
        env_value = env.get(ENV_DATA_ROOT)
        if env_value and env_value.strip():
            raw = env_value.strip()
    if raw is None:
        raw = _read_data_root_from_file(base)
    if raw is None:
        raw = DEFAULT_DATA_ROOT

    root = _resolve_data_root(raw, base)
    root.mkdir(parents=True, exist_ok=True)
    storage = root / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    return AppSettings(data_root=root)
