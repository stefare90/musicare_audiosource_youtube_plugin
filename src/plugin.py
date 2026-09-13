from typing import List

from src.extractor import YouTubeExtractor
from musicare_plugin_sdk import (
    AudioQuality,
    AudioStreamResponse,
    BaseAudioSourcePlugin,
    CandidateTrack,
    Track,
)


class YouTubeAudioSourcePlugin(BaseAudioSourcePlugin):
    @property
    def id(self) -> str:
        return "org.musicare.audiosource.youtube"

    @property
    def name(self) -> str:
        return "YouTube Audio Source"

    @property
    def version(self) -> str:
        return "1.0.0"

    def search_candidates(self, track: Track) -> List[CandidateTrack]:
        return YouTubeExtractor.search_candidates(track)

    def resolve_stream(
        self, candidate_id: str, quality: AudioQuality = AudioQuality.HIGH
    ) -> AudioStreamResponse:
        return YouTubeExtractor.resolve_stream(candidate_id, quality)
