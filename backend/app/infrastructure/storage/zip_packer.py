import io
import zipfile

from app.application.ports.storage.archive_packer import IArchivePacker


class ZipArchivePacker(IArchivePacker):
    def pack(self, entries: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries.items():
                if name.endswith("/"):
                    info = zipfile.ZipInfo(name)
                    info.external_attr = 0o40755 << 16
                    archive.writestr(info, b"")
                    continue
                archive.writestr(name, payload)
        return buffer.getvalue()
