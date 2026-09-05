from typing import List
from musicare_plugin_sdk import (
    BaseAudioSourcePlugin,
    Track,
    AudioQuality,
    AudioStreamResponse,
)
from extractor import YouTubeExtractor


class YouTubeAudioSourcePlugin(BaseAudioSourcePlugin):
    """
    MusicAre YouTube Audio Source Plugin implementation.
    """

    @property
    def id(self) -> str:
        return "org.musicare.audiosource.youtube"

    @property
    def name(self) -> str:
        return "YouTube Audio Source"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_stream(
        self,
        track: Track,
        quality: AudioQuality,
    ) -> List[AudioStreamResponse]:
        """
        Resolves track metadata into direct audio stream sources via YouTubeExtractor.
        """
        return YouTubeExtractor.resolve_stream(track, quality)