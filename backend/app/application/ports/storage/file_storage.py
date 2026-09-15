from abc import ABC, abstractmethod


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

    @abstractmethod
    async def list_files(self, relative_dir: str) -> dict[str, bytes]:
        """Return relative-path → bytes for all files under a directory."""
        raise NotImplementedError
