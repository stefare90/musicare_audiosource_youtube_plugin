from dataclasses import dataclass
from typing import List, Optional, Dict, Literal

AudioQuality = Literal['low', 'medium', 'high']

@dataclass
class Artist:
    name: str

@dataclass
class Track:
    name: str
    artists: List[Artist]
    duration_ms: int

    @classmethod
    def from_dict(cls, data: dict) -> 'Track':
        artists = [Artist(name=a.get('name', '')) for a in data.get('artists', [])]
        return cls(
            name=data.get('name', ''),
            artists=artists,
            duration_ms=data.get('durationMs', data.get('duration_ms', 0))
        )

@dataclass
class AudioStreamResponse:
    url: str
    quality: AudioQuality
    codec: Optional[str] = None
    bitrate: Optional[int] = None
    expires_at: Optional[int] = None
    headers: Optional[Dict[str, str]] = None

    def to_dict(self) -> dict:
        return {
            'url': self.url,
            'quality': self.quality,
            'codec': self.codec,
            'bitrate': self.bitrate,
            'expiresAt': self.expires_at,
            'headers': self.headers or {}
        }
    