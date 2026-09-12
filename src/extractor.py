import urllib.parse
from typing import List, Optional

import yt_dlp
from musicare_plugin_sdk import (
    AudioQuality,
    AudioStreamResponse,
    CandidateTrack,
    Track,
)


class YouTubeExtractor:
    @staticmethod
    def search_candidates(track: Track) -> List[CandidateTrack]:
        """Fast search (< 0.4s) returning lightweight metadata candidates without extracting formats."""
        artist_prefix = f"{track.artists[0]} - " if track.artists else ""
        query = f"ytsearch5:{artist_prefix}{track.name}".strip()

        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False) or {}
            entries = info.get("entries", [])

            candidates: List[CandidateTrack] = []
            for entry in entries:
                if not entry:
                    continue

                candidate_id = str(entry.get("id", "")).strip()
                title = str(entry.get("title", "")).strip()
                if not candidate_id or not title:
                    continue

                uploader = entry.get("uploader") or entry.get("channel")
                duration = entry.get("duration")
                duration_ms = int(duration * 1000) if duration is not None else None

                candidates.append(
                    CandidateTrack(
                        id=candidate_id,
                        title=title,
                        artist=uploader,
                        duration_ms=duration_ms,
                    )
                )

            return candidates

    @staticmethod
    def resolve_stream(
        candidate_id: str, quality: AudioQuality = AudioQuality.HIGH
    ) -> AudioStreamResponse:
        """Extract direct audio stream URL on-demand (~0.7s) for a chosen candidate ID."""
        video_url = f"https://www.youtube.com/watch?v={candidate_id}"

        format_selector = {
            AudioQuality.LOW: "worstaudio/bestaudio[abr<=96]/best",
            AudioQuality.MEDIUM: "bestaudio[abr<=128]/bestaudio/best",
            AudioQuality.HIGH: "bestaudio[ext=m4a]/bestaudio/best",
        }.get(quality, "bestaudio/best")

        ydl_opts = {
            "format": format_selector,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False) or {}

            stream_url = info.get("url")
            headers = dict(info.get("http_headers", {}))
            codec = info.get("acodec")
            abr = info.get("abr")
            bitrate = int(abr * 1000) if abr else None

            # Fallback to formats array if top-level url is absent
            if not stream_url and "formats" in info:
                audio_formats = [
                    f
                    for f in info["formats"]
                    if f.get("url") and f.get("acodec") != "none"
                ]
                if not audio_formats:
                    audio_formats = [f for f in info["formats"] if f.get("url")]

                if audio_formats:
                    chosen = audio_formats[-1]
                    stream_url = chosen.get("url")
                    headers = dict(chosen.get("http_headers", headers))
                    codec = chosen.get("acodec", codec)
                    format_abr = chosen.get("abr")
                    if format_abr:
                        bitrate = int(format_abr * 1000)

            if not stream_url:
                raise RuntimeError(
                    f"Could not resolve playable audio stream for YouTube video ID: {candidate_id}"
                )

            # Parse expiration timestamp from CDN query parameters if present
            expires_at: Optional[int] = None
            try:
                parsed_url = urllib.parse.urlparse(stream_url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                if "expire" in query_params:
                    expires_at = int(query_params["expire"][0]) * 1000
            except Exception:
                expires_at = None

            return AudioStreamResponse(
                url=stream_url,
                quality=quality,
                codec=codec,
                bitrate=bitrate,
                expires_at=expires_at,
                headers=headers,
            )
