import math
import re
import unicodedata
import urllib.parse
from typing import List, Optional

import yt_dlp
from musicare_audio_plugin_sdk import (
    AudioQuality,
    AudioStreamResponse,
    CandidateTrack,
    InternalError,
    Track,
)

from .errors import classify_download_error, is_client_wall


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
        # 15 hits cost the same as 5 (measured): depth for the same-song
        # filter below, which needs more than the top-5 to work with.
        artists = [a.strip() for a in (track.artists or []) if a and a.strip()]
        title = track.name.strip()
        raw = f"ytsearch15:{title} - {' '.join(artists)}" if artists else f"ytsearch15:{title}"
        terms = YouTubeExtractor._artist_terms(track)
        smart = f"ytsearch15:{title} - {' '.join(terms)}" if terms else f"ytsearch15:{title}"
        return list(dict.fromkeys([raw, smart]))

    # YouTube channel naming conventions (not words with meaning): stripped
    # from the uploader name before the official-channel check below.
    _CHANNEL_SUFFIXES = frozenset({"official", "vevo", "topic", "music"})

    # Same-song gates: title token recall anyone must clear, and the
    # duration veto for third-party uploads only (unknown on either side
    # is neutral). Official-channel uploads are exempt from the veto: on
    # the artist's own channel an odd duration is an artistic choice
    # (short film, video edit), on a third-party channel it is junk signal.
    _TITLE_RECALL_MIN = 0.5
    _DURATION_TOLERANCE_S = 15

    @staticmethod
    def _normalize(text: str) -> str:
        folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", folded.lower())).strip()

    @staticmethod
    def _title_recall(candidate_title: str, track_title: str) -> float:
        wanted = YouTubeExtractor._normalize(track_title).split()
        if not wanted:
            return 0.0
        present = set(YouTubeExtractor._normalize(candidate_title).split())
        return sum(1 for token in wanted if token in present) / len(wanted)

    @staticmethod
    def _artist_present(candidate_title: str, uploader: str, artists: List[str]) -> bool:
        pool = set(
            YouTubeExtractor._normalize(candidate_title).split()
            + YouTubeExtractor._normalize(uploader).split()
        )
        for artist in artists or []:
            for token in YouTubeExtractor._normalize(artist).split():
                if len(token) >= 2 and token in pool:
                    return True
        return False

    @staticmethod
    def _is_official_channel(uploader: str, artists: List[str]) -> bool:
        channel = YouTubeExtractor._normalize(uploader).split()
        names = set()
        for artist in artists or []:
            names.update(YouTubeExtractor._normalize(artist).split())
        # A suffix is stripped only when it is not part of the artist name
        # itself (e.g. DJ Topic keeps his "topic"); never strip to empty.
        kept = [
            token
            for token in channel
            if token not in YouTubeExtractor._CHANNEL_SUFFIXES or token in names
        ] or channel
        uploader_set, artist_set = set(kept), names
        if not uploader_set or not artist_set:
            return False
        contains = uploader_set <= artist_set or artist_set <= uploader_set
        return contains and len(uploader_set) <= len(artist_set) + 1

    @staticmethod
    def _coherence_score(recall: float, duration_s, track_duration_s, views) -> float:
        if duration_s and track_duration_s:
            proximity = max(0.0, 1 - abs(duration_s - track_duration_s) / 300)
        else:
            proximity = 1.0
        popularity = min(1.0, math.log10(1 + views) / 7) if views else 0.0
        return recall + 0.15 * proximity + 0.05 * popularity

    # Mobile API clients for the fallback attempt: a different endpoint that
    # dodges the web-client bot-check, and for which yt-dlp auto-appends the
    # web_embedded variants that work around the age-gate without login.
    _MOBILE_FALLBACK_ARGS = {"youtube": {"player_client": ["android", "ios"]}}

    @staticmethod
    def _with_client_fallback(base_opts: dict, call):
        # First attempt with the default clients (full quality); on a
        # client wall (bot-check/age-gate) retry once with the mobile
        # clients instead of failing outright. Anything else is classified
        # immediately: no point retrying a timeout with another client.
        try:
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                return call(ydl)
        except yt_dlp.utils.DownloadError as first:
            if not is_client_wall(first):
                raise classify_download_error(first) from first
            fallback_opts = dict(base_opts)
            fallback_opts["extractor_args"] = {
                **base_opts.get("extractor_args", {}),
                **YouTubeExtractor._MOBILE_FALLBACK_ARGS,
            }
            try:
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    return call(ydl)
            except yt_dlp.utils.DownloadError as second:
                raise classify_download_error(second, fallback_of=first) from second

    @staticmethod
    def _search_once(ydl: yt_dlp.YoutubeDL, query: str, track: Track) -> List[CandidateTrack]:
        info = ydl.extract_info(query, download=False) or {}
        entries = info.get("entries") or []
        return YouTubeExtractor._rank_entries(entries, track)

    @staticmethod
    def _rank_entries(entries: list, track: Track) -> List[CandidateTrack]:
        track_title = track.name
        artists = track.artists or []
        track_duration_s = track.duration_ms / 1000 if track.duration_ms else None
        scored = []
        for position, entry in enumerate(entries):
            if not entry:
                continue

            candidate_id = str(entry.get("id", "")).strip()
            title = str(entry.get("title", "")).strip()
            if not candidate_id or not title:
                continue

            uploader = entry.get("uploader") or entry.get("channel") or ""
            duration = entry.get("duration")
            duration_ms = int(duration * 1000) if duration is not None else None

            recall = YouTubeExtractor._title_recall(title, track_title)
            official = YouTubeExtractor._is_official_channel(uploader, artists)
            if recall < YouTubeExtractor._TITLE_RECALL_MIN:
                continue
            if not YouTubeExtractor._artist_present(title, uploader, artists):
                continue
            if (
                not official
                and duration is not None
                and track_duration_s is not None
                and abs(duration - track_duration_s)
                > YouTubeExtractor._DURATION_TOLERANCE_S
            ):
                continue

            views = entry.get("view_count")
            score = YouTubeExtractor._coherence_score(recall, duration, track_duration_s, views)
            scored.append((official, score, position, candidate_id, title, uploader, duration_ms))

        # Official channel first, always; then coherence; YouTube order wins ties.
        scored.sort(key=lambda row: (not row[0], -row[1], row[2]))
        return [
            CandidateTrack(
                id=candidate_id,
                title=title,
                artist=uploader,
                duration_ms=duration_ms,
            )
            for _, _, _, candidate_id, title, uploader, duration_ms in scored
        ]

    @staticmethod
    def search_candidates(track: Track) -> List[CandidateTrack]:
        """Same-song candidates with the official upload first (~1s)."""
        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }

        def run(ydl: yt_dlp.YoutubeDL) -> List[CandidateTrack]:
            for query in YouTubeExtractor._build_search_queries(track):
                candidates = YouTubeExtractor._search_once(ydl, query, track)
                if candidates:
                    return candidates
            return []

        return YouTubeExtractor._with_client_fallback(ydl_opts, run)

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

        def fetch(ydl: yt_dlp.YoutubeDL) -> dict:
            return ydl.extract_info(video_url, download=False) or {}

        info = YouTubeExtractor._with_client_fallback(ydl_opts, fetch)

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
            raise InternalError(
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
