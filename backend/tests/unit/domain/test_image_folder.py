from pathlib import Path

from app.domain.services.image_folder import list_image_files


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
