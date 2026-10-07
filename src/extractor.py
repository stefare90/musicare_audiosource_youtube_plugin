import re
import urllib.parse
from typing import List, Optional

import yt_dlp
from musicare_audio_plugin_sdk import (
    AudioQuality,
    AudioStreamResponse,
    CandidateTrack,
    Track,
)


class YouTubeExtractor:
    # One artist entry may pack several names ("A feat. B", "A & B"); split before joining.
    _ARTIST_SPLIT_PATTERN = re.compile(
        r"\s*(?:\b(?:feat|ft|featuring|presents?|pres|vs|with|and|x)\b\.?|&|,|;|/|\|\+|×)\s*",
        re.IGNORECASE,
    )

    @staticmethod
    def _artist_terms(track: Track) -> List[str]:
        terms: List[str] = []
        for artist in track.artists or []:
            for part in YouTubeExtractor._ARTIST_SPLIT_PATTERN.split(artist or ""):
                part = part.strip().strip("()[]{}").strip()
                if part and part not in terms:
                    terms.append(part)
        return terms

    @staticmethod
    def _build_search_queries(track: Track) -> List[str]:
        # Raw join first (one request in the common case); the smart split
        # runs only when the raw form returns nothing. At most 2 queries.
        artists = [a.strip() for a in (track.artists or []) if a and a.strip()]
        title = track.name.strip()
        raw = f"ytsearch5:{title} - {' '.join(artists)}" if artists else f"ytsearch5:{title}"
        terms = YouTubeExtractor._artist_terms(track)
        smart = f"ytsearch5:{title} - {' '.join(terms)}" if terms else f"ytsearch5:{title}"
        return list(dict.fromkeys([raw, smart]))

    @staticmethod
    def _search_once(ydl: yt_dlp.YoutubeDL, query: str) -> List[CandidateTrack]:
        info = ydl.extract_info(query, download=False) or {}
        entries = info.get("entries") or []

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
    def search_candidates(track: Track) -> List[CandidateTrack]:
        """Fast search (< 0.4s) returning lightweight metadata candidates without extracting formats."""
        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for query in YouTubeExtractor._build_search_queries(track):
                candidates = YouTubeExtractor._search_once(ydl, query)
                if candidates:
                    return candidates
            return []

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
