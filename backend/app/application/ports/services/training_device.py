from abc import ABC, abstractmethod


class ITrainingDeviceResolver(ABC):
    @abstractmethod
    def resolve(self, requested: str) -> str:
        raise NotImplementedError
