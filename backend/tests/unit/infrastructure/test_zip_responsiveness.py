import asyncio
import time
from pathlib import Path

import pytest

from app.infrastructure.storage.zip_packer import ZipArchivePacker


@pytest.mark.asyncio
async def test_pack_to_path_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    def slow_write(self, dest, entries) -> None:
        time.sleep(0.25)
        Path(dest).write_bytes(b"PK")

    monkeypatch.setattr(ZipArchivePacker, "write", slow_write)
    finished = False

    async def side() -> None:
        nonlocal finished
        await asyncio.sleep(0.05)
        finished = True

    task = asyncio.create_task(side())
    await ZipArchivePacker().pack_to_path(tmp_path / "out.zip", [("note.txt", b"hello")])
    assert finished
    await task
