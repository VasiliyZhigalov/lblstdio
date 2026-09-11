from abc import ABC, abstractmethod


class IArchivePacker(ABC):
    @abstractmethod
    def pack(self, entries: dict[str, bytes]) -> bytes:
        raise NotImplementedError
