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
