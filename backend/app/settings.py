from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ENV_DATA_ROOT = "LBLSTDIO_DATA_ROOT"
ENV_TRUSTED_LOCAL = "LBLSTDIO_TRUSTED_LOCAL"
ENV_ALLOWED_ROOTS = "LBLSTDIO_ALLOWED_ROOTS"
BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = "."
_TRUE_TOKENS = {"1", "true", "yes", "on"}
_FALSE_TOKENS = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class AppSettings:
    data_root: Path
    trusted_local: bool = False
    allowed_roots: tuple[Path, ...] = ()

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


def _read_config(backend_dir: Path) -> dict:
    for path in _config_candidates(backend_dir):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"config must be a mapping: {path}")
        return payload
    return {}


def _read_data_root(payload: dict) -> str | None:
    if "data_root" not in payload:
        return None
    value = payload.get("data_root")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("data_root must be a non-empty string")
    return value.strip()


def _parse_bool(value: object, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
    raise ValueError(f"{label} must be a boolean")


def _parse_root_list(value: object, *, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of paths")
    roots: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label} must be a list of non-empty paths")
        roots.append(item.strip())
    return roots


def _resolve_data_root(raw: str | Path, base_dir: Path) -> Path:
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _resolve_trusted_local(
    explicit: bool | None,
    env: dict[str, str],
    payload: dict,
) -> bool:
    if explicit is not None:
        return explicit
    env_value = env.get(ENV_TRUSTED_LOCAL)
    if env_value is not None and env_value.strip():
        return _parse_bool(env_value, label=ENV_TRUSTED_LOCAL)
    if "trusted_local" in payload and payload.get("trusted_local") is not None:
        return _parse_bool(payload.get("trusted_local"), label="trusted_local")
    return False


def _resolve_allowed_roots(
    explicit: list[str | Path] | tuple[str | Path, ...] | None,
    env: dict[str, str],
    payload: dict,
    base_dir: Path,
) -> tuple[Path, ...]:
    if explicit is not None:
        raw_items = [str(item).strip() for item in explicit if str(item).strip()]
    else:
        env_value = env.get(ENV_ALLOWED_ROOTS)
        if env_value is not None and env_value.strip():
            raw_items = [part.strip() for part in env_value.split(os.pathsep) if part.strip()]
        elif "allowed_roots" in payload:
            raw_items = _parse_root_list(payload.get("allowed_roots"), label="allowed_roots")
        else:
            raw_items = []
    return tuple(_resolve_data_root(item, base_dir) for item in raw_items)


def load_settings(
    data_root: str | Path | None = None,
    *,
    trusted_local: bool | None = None,
    allowed_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    backend_dir: Path | None = None,
    environ: dict[str, str] | None = None,
) -> AppSettings:
    """Resolve data root: explicit arg → env → config.yaml → default ``.``.

    ``trusted_local`` defaults to false. Set it explicitly (config, env, or
    argument) to keep folder picker and filesystem sources on a local install.
    ``allowed_roots`` restricts those sources when non-empty; an empty list
    keeps the unrestricted local behavior.
    """
    base = (backend_dir or BACKEND_DIR).resolve()
    env = environ if environ is not None else os.environ
    payload = _read_config(base)

    raw: str | Path | None = data_root
    if raw is None:
        env_value = env.get(ENV_DATA_ROOT)
        if env_value and env_value.strip():
            raw = env_value.strip()
    if raw is None:
        raw = _read_data_root(payload)
    if raw is None:
        raw = DEFAULT_DATA_ROOT

    root = _resolve_data_root(raw, base)
    root.mkdir(parents=True, exist_ok=True)
    storage = root / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    return AppSettings(
        data_root=root,
        trusted_local=_resolve_trusted_local(trusted_local, env, payload),
        allowed_roots=_resolve_allowed_roots(allowed_roots, env, payload, base),
    )
