import io
import os
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

from app.application.ports.storage.archive_packer import ArchiveMember, IArchivePacker


class ZipArchivePacker(IArchivePacker):
    def pack(self, entries: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        self.write(buffer, entries.items())
        return buffer.getvalue()

    def write(self, dest: BinaryIO | Path, entries: Iterable[ArchiveMember]) -> None:
        with zipfile.ZipFile(dest, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                if name.endswith("/"):
                    info = zipfile.ZipInfo(name)
                    info.external_attr = 0o40755 << 16
                    archive.writestr(info, b"")
                    continue
                if isinstance(payload, (bytes, bytearray, memoryview)):
                    archive.writestr(name, bytes(payload))
                    continue
                archive.write(os.fspath(payload), arcname=name)
