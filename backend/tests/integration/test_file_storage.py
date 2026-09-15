import io
from pathlib import Path

import pytest
from PIL import Image as PILImage

from app.infrastructure.storage.local_storage import LocalFileStorage
from app.infrastructure.storage.pillow_metadata import PillowMetadataReader


@pytest.mark.asyncio
async def test_saves_binary_stream(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    relative = await storage.save("projects/abc/images", "shot.png", b"\x89PNG")

    assert relative == "projects/abc/images/shot.png"
    assert (tmp_path / relative).read_bytes() == b"\x89PNG"
    assert storage.get_absolute_path(relative) == str(tmp_path / relative)


@pytest.mark.asyncio
async def test_does_not_overwrite_on_name_collision(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    first = await storage.save("images", "dup.png", b"first")
    second = await storage.save("images", "dup.png", b"second")

    assert first != second
    assert (tmp_path / first).read_bytes() == b"first"
    assert (tmp_path / second).read_bytes() == b"second"
    assert Path(second).name.startswith("dup")
    assert Path(second).suffix == ".png"


@pytest.mark.asyncio
async def test_delete_removes_file_from_disk(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    relative = await storage.save("images", "gone.png", b"data")
    absolute = Path(storage.get_absolute_path(relative))
    assert absolute.exists()

    await storage.delete(relative)

    assert absolute.exists() is False


@pytest.mark.asyncio
async def test_list_files_returns_relative_entries(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.save("projects/p1/datasets/v1", "data.yaml", b"names: []\n")
    await storage.save("projects/p1/datasets/v1/train/images", "a.jpg", b"img")

    files = await storage.list_files("projects/p1/datasets/v1")

    assert files["data.yaml"] == b"names: []\n"
    assert files["train/images/a.jpg"] == b"img"


def test_pillow_reader_extracts_original_dimensions() -> None:
    buffer = io.BytesIO()
    PILImage.new("RGB", (96, 64), color=(1, 2, 3)).save(buffer, format="PNG")
    original = buffer.getvalue()

    width, height = PillowMetadataReader().read_size(original)

    assert (width, height) == (96, 64)
    # original bytes are not rewritten by the reader
    assert original == buffer.getvalue()


@pytest.mark.asyncio
async def test_absolute_filename_is_stored_under_root(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    outside = tmp_path.parent / "escaped.png"
    relative = await storage.save("projects/abc/images", str(outside), b"evil")

    assert outside.exists() is False
    assert Path(relative).name == "escaped.png"
    assert (tmp_path / relative).read_bytes() == b"evil"
    assert Path(relative).as_posix().startswith("projects/abc/images/")


@pytest.mark.asyncio
async def test_strips_directory_components_from_filename(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    relative = await storage.save("images", r"..\..\evil.png", b"data")
    assert Path(relative).name == "evil.png"
    assert (tmp_path / relative).read_bytes() == b"data"
    assert relative.startswith("images/")


def test_pillow_reader_maps_truncated_payload_to_domain_error() -> None:
    from app.domain.exceptions import DomainValidationException

    with pytest.raises(DomainValidationException):
        PillowMetadataReader().read_size(b"not-an-image")
