from __future__ import annotations

import asyncio
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

ArchiveMember = tuple[str, bytes | Path]


class IArchivePacker(ABC):
    @abstractmethod
    def pack(self, entries: dict[str, bytes]) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def write(self, dest: BinaryIO | Path, entries: Iterable[ArchiveMember]) -> None:
        """Write a zip. Payload is either small bytes or a filesystem path."""
        raise NotImplementedError

    async def pack_to_path(self, dest: Path, entries: Iterable[ArchiveMember]) -> None:
        """Compress off the event loop. A generator is consumed in that thread."""
        await asyncio.to_thread(self._pack_sync, dest, entries)

    def _pack_sync(self, dest: Path, entries: Iterable[ArchiveMember]) -> None:
        closer = getattr(entries, "close", None)
        try:
            self.write(dest, entries)
        finally:
            if callable(closer) and getattr(entries, "gi_frame", None) is not None:
                closer()


def allocate_archive_path() -> Path:
    descriptor, name = tempfile.mkstemp(suffix=".zip")
    os.close(descriptor)
    return Path(name)
