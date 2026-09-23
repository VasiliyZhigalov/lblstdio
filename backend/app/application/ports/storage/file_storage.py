import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path


class IFileStorage(ABC):
    @abstractmethod
    async def save(self, relative_dir: str, filename: str, data: bytes) -> str:
        """Persist bytes and return the relative path actually used."""
        raise NotImplementedError

    @abstractmethod
    async def read(self, relative_path: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def get_absolute_path(self, relative_path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, relative_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_directory(self, relative_dir: str) -> None:
        raise NotImplementedError

    async def move_directory(self, source_rel: str, dest_rel: str) -> None:
        """Rename a directory onto dest. Fails if dest already exists."""
        source = Path(self.get_absolute_path(source_rel))
        dest = Path(self.get_absolute_path(dest_rel))
        if not source.is_dir():
            raise FileNotFoundError(source_rel)
        if dest.exists():
            raise FileExistsError(dest_rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(os.rename, source, dest)

    @abstractmethod
    async def list_files(self, relative_dir: str) -> dict[str, bytes]:
        """Return relative-path → bytes for all files under a directory."""
        raise NotImplementedError

    async def save_from_path(self, relative_dir: str, filename: str, source: Path) -> str:
        data = await asyncio.to_thread(Path(source).read_bytes)
        return await self.save(relative_dir, filename, data)


def resolve_stored_file(storage: object, relative_path: str) -> Path | None:
    """Absolute path when the bytes already live on disk. Otherwise None."""
    getter = getattr(storage, "get_absolute_path", None)
    if not callable(getter):
        return None
    candidate = Path(getter(relative_path))
    if candidate.is_file():
        return candidate
    return None


async def read_member(storage: IFileStorage, relative_path: str) -> bytes | Path:
    located = resolve_stored_file(storage, relative_path)
    if located is not None:
        return located
    return await storage.read(relative_path)


def upload_size(data: bytes | None, source_path: Path | None) -> int:
    if source_path is not None:
        return Path(source_path).stat().st_size
    if not data:
        return 0
    return len(data)


async def save_upload(
    storage: IFileStorage,
    relative_dir: str,
    filename: str,
    *,
    data: bytes | None = None,
    source_path: Path | None = None,
) -> str:
    if source_path is not None:
        return await storage.save_from_path(relative_dir, filename, Path(source_path))
    return await storage.save(relative_dir, filename, data or b"")
