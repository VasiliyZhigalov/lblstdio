from pathlib import Path

from app.domain.services.image_folder import (
    describe_folder_access_error,
    list_image_files,
)


def test_list_image_files_sorted_and_filtered(tmp_path: Path) -> None:
    (tmp_path / "b.JPG").write_bytes(b"b")
    (tmp_path / "a.png").write_bytes(b"a")
    (tmp_path / "notes.txt").write_bytes(b"no")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.webp").write_bytes(b"c")

    names = [path.relative_to(tmp_path).as_posix() for path in list_image_files(tmp_path)]

    assert names == ["a.png", "b.JPG", "nested/c.webp"]


def test_list_image_files_missing_dir_is_empty(tmp_path: Path) -> None:
    assert list_image_files(tmp_path / "missing") == []


def test_list_image_files_oserror_on_is_dir_is_empty(
    tmp_path: Path, monkeypatch
) -> None:
    folder = tmp_path / "share"
    folder.mkdir()
    original = Path.is_dir

    def fake(self, *args, **kwargs):
        if Path(self) == folder:
            raise OSError(1326, "Logon failure", str(self), 1326)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", fake)
    assert list_image_files(folder) == []


def test_describe_folder_access_error_logon() -> None:
    exc = OSError(1326, "Logon failure", r"\\server\share", 1326)
    message = describe_folder_access_error(exc, r"\\server\share")
    assert "пользователя или пароль" in message
    assert r"\\server\share" in message
