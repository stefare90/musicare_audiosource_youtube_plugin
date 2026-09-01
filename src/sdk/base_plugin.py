from abc import ABC, abstractmethod
from typing import List
from .types import Track, AudioQuality, AudioStreamResponse

class BaseAudioSourcePlugin(ABC):
    @property
    @abstractmethod
    def id(self) -> str:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        pass

    @abstractmethod
    def get_stream(self, track: Track, quality: AudioQuality) -> List[AudioStreamResponse]:
        """
        Resolves track metadata into an ordered list of playable audio stream sources,
        sorted descending by matching adherence.
        """
        pass