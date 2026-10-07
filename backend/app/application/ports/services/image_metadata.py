from abc import ABC, abstractmethod


class IImageMetadataReader(ABC):
    @abstractmethod
    def read_size(self, data: bytes) -> tuple[int, int]:
        raise NotImplementedError

    @abstractmethod
    def perceptual_hash(self, data: bytes) -> int:
        raise NotImplementedError
