from pathlib import Path

import pytest

from app.settings import ENV_DATA_ROOT, load_settings


def test_load_settings_default_uses_backend_dir(tmp_path: Path) -> None:
    settings = load_settings(backend_dir=tmp_path, environ={})
    assert settings.data_root == tmp_path.resolve()
    assert settings.database_path == (tmp_path / "app.db").resolve()
    assert settings.storage_root == (tmp_path / "storage").resolve()
    assert settings.storage_root.is_dir()
    assert settings.database_url.endswith("/app.db")
    assert settings.database_url.startswith("sqlite+aiosqlite:///")


def test_load_settings_from_config_file(tmp_path: Path) -> None:
    data = tmp_path / "net-data"
    (tmp_path / "config.yaml").write_text(
        f'data_root: "{data.as_posix()}"\n', encoding="utf-8"
    )
    settings = load_settings(backend_dir=tmp_path, environ={})
    assert settings.data_root == data.resolve()
    assert settings.storage_root == (data / "storage").resolve()


def test_load_settings_relative_config_path(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text('data_root: "shared"\n', encoding="utf-8")
    settings = load_settings(backend_dir=tmp_path, environ={})
    assert settings.data_root == (tmp_path / "shared").resolve()


def test_env_overrides_config_file(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text('data_root: "from-file"\n', encoding="utf-8")
    env_root = tmp_path / "from-env"
    settings = load_settings(
        backend_dir=tmp_path,
        environ={ENV_DATA_ROOT: str(env_root)},
    )
    assert settings.data_root == env_root.resolve()


def test_explicit_arg_overrides_env(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit"
    settings = load_settings(
        data_root=explicit,
        backend_dir=tmp_path,
        environ={ENV_DATA_ROOT: str(tmp_path / "env")},
    )
    assert settings.data_root == explicit.resolve()


def test_invalid_config_mapping(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_settings(backend_dir=tmp_path, environ={})


def test_trusted_local_defaults_off(tmp_path: Path) -> None:
    settings = load_settings(backend_dir=tmp_path, environ={})
    assert settings.trusted_local is False
    assert settings.allowed_roots == ()


def test_trusted_local_and_roots_from_config(tmp_path: Path) -> None:
    media = tmp_path / "media"
    (tmp_path / "config.yaml").write_text(
        "trusted_local: true\n"
        "allowed_roots:\n"
        f'  - "{media.as_posix()}"\n',
        encoding="utf-8",
    )
    settings = load_settings(backend_dir=tmp_path, environ={})
    assert settings.trusted_local is True
    assert settings.allowed_roots == (media.resolve(),)


def test_env_overrides_trusted_local(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("trusted_local: true\n", encoding="utf-8")
    settings = load_settings(
        backend_dir=tmp_path,
        environ={"LBLSTDIO_TRUSTED_LOCAL": "false"},
    )
    assert settings.trusted_local is False
