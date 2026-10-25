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

    # Letters and digits of any script: an ASCII fold would turn a non-Latin
    # title (夜に駆ける) into an empty string and zero its recall.
    _WORD_PATTERN = re.compile(r"[^\W_]+")
    _BRACKETED_PATTERN = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
    _EDITION_SUFFIX_PATTERN = re.compile(
        r"\s*[-–—]\s*(?:(?:19|20)\d{2}\s+)?remaster(?:ed)?(?:\s+(?:19|20)\d{2})?.*$",
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
        # (packed artist credits) and the core title (MusicBrainz
        # disambiguators) are fallbacks. At most 3 queries, 1 in the happy
        # path. 15 hits cost the same as 5 (measured): depth for the
        # same-song filter below, which needs more than the top-5 to work with.
        artists = [a.strip() for a in (track.artists or []) if a and a.strip()]
        title = track.name.strip()
        suffix = f" - {' '.join(artists)}" if artists else ""
        raw = f"ytsearch15:{title}{suffix}"
        terms = YouTubeExtractor._artist_terms(track)
        smart = f"ytsearch15:{title} - {' '.join(terms)}" if terms else f"ytsearch15:{title}"
        queries = [raw, smart]
        core = YouTubeExtractor._core_title(title)
        # A disambiguator can wipe the results entirely
        # (measured: "La caduta di Atlante (Il peso - …)" -> 0 entries).
        if YouTubeExtractor._tokens(core) != YouTubeExtractor._tokens(title):
            queries.append(f"ytsearch15:{core}{suffix}")
        return list(dict.fromkeys(queries))

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
    def _tokens(text: str) -> List[str]:
        folded = unicodedata.normalize("NFKC", text or "").casefold()
        return YouTubeExtractor._WORD_PATTERN.findall(folded)

    @staticmethod
    def _compact(text: str) -> str:
        return "".join(YouTubeExtractor._tokens(text))

    @staticmethod
    def _core_title(title: str) -> str:
        """Title without disambiguators/edition tails: the part that names the song.

        MusicBrainz appends the disambiguation in parentheses ("Una chiave (Il
        colloquio - Aprirsi o chiudersi)"); keeping it in the recall denominator
        rejects the exact video (measured: 0.29).
        """
        text = YouTubeExtractor._BRACKETED_PATTERN.sub(" ", title or "")
        text = YouTubeExtractor._EDITION_SUFFIX_PATTERN.sub("", text)
        text = re.sub(r"\s+", " ", text).strip(" -–—:|/")
        return text or (title or "").strip()

    @staticmethod
    def _title_recall(candidate_title: str, track_title: str) -> float:
        wanted = YouTubeExtractor._tokens(track_title)
        if not wanted:
            return 0.0
        present = set(YouTubeExtractor._tokens(candidate_title))
        return sum(1 for token in wanted if token in present) / len(wanted)

    @staticmethod
    def _artist_keys(artists: List[str]) -> List[str]:
        keys = [YouTubeExtractor._compact(artist) for artist in artists or []]
        return [key for key in keys if key]

    @staticmethod
    def _anchored(key: str, tokens: List[str]) -> bool:
        return any(token.startswith(key) or token.endswith(key) for token in tokens)

    @staticmethod
    def _artist_ok(
        candidate_title: str, uploader: str, artists: List[str], official: bool
    ) -> bool:
        """Official upload, or the compacted whole artist name on a token edge.

        S1: compact full name ("caparezza" vs "telecaparezza", "rem" vs
        "remhq", "blink182" vs "blink182vevo"). S2: initials (R.E.M. -> "rem")
        compact to the same key. Never a single word of a multi-word name: that
        is how "Tears for Fears" used to pass on "for".
        """
        if official:
            return True
        tokens = [
            YouTubeExtractor._compact(token)
            for token in YouTubeExtractor._tokens(f"{candidate_title} {uploader}")
        ]
        return any(
            YouTubeExtractor._anchored(key, tokens)
            for key in YouTubeExtractor._artist_keys(artists)
        )

    @staticmethod
    def _from_artist(uploader: str, artists: List[str]) -> bool:
        """The upload comes from the artist side (official channel or own handle).

        Used to decide whether the core-title query is worth one more request:
        a live bootleg first hit does not come from the artist, the artist's
        own `telecaparezza` does.
        """
        if YouTubeExtractor._is_official_channel(uploader, artists):
            return True
        tokens = [
            YouTubeExtractor._compact(token)
            for token in YouTubeExtractor._tokens(uploader)
        ]
        return any(
            YouTubeExtractor._anchored(key, tokens)
            for key in YouTubeExtractor._artist_keys(artists)
        )

    @staticmethod
    def _is_official_channel(uploader: str, artists: List[str]) -> bool:
        channel = [
            YouTubeExtractor._compact(token)
            for token in YouTubeExtractor._tokens(uploader)
        ]
        names = set(YouTubeExtractor._tokens(" ".join(artists or [])))
        compact_names = {
            YouTubeExtractor._compact(artist) for artist in artists or []
        } - {""}
        # A suffix is stripped only when it is not part of the artist name
        # itself (e.g. DJ Topic keeps his "topic"); never strip to empty.
        kept = []
        for token in channel:
            if token in names or token in compact_names:
                kept.append(token)
                continue
            stem = token
            for suffix in YouTubeExtractor._CHANNEL_SUFFIXES:
                if stem == suffix:
                    stem = ""
                    break
                if stem.endswith(suffix) and len(stem) > len(suffix):
                    stem = stem[: -len(suffix)]
                    break
            if stem:
                kept.append(stem)
        kept = kept or channel
        uploader_set = set(kept)
        if not uploader_set or not (names or compact_names):
            return False
        if uploader_set <= names or names <= uploader_set:
            return len(uploader_set) <= len(names) + 1
        # Attached suffixes leave one compact token ("TheBeatlesVEVO" ->
        # "thebeatles", "U2VEVO" -> "u2"): compare whole names as well.
        return uploader_set <= compact_names

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
    def _fetch_entries(ydl: yt_dlp.YoutubeDL, query: str) -> list:
        info = ydl.extract_info(query, download=False) or {}
        return info.get("entries") or []

    @staticmethod
    def _merge_entries(new_entries: list, current: list) -> list:
        """Newest response first, videos already seen dropped (new keeps the position)."""
        seen = set()
        merged = []
        for entry in list(new_entries) + list(current):
            if not entry:
                continue
            entry_id = str(entry.get("id", ""))
            if entry_id and entry_id in seen:
                continue
            seen.add(entry_id)
            merged.append(entry)
        return merged

    @staticmethod
    def _rank_entries(entries: list, track: Track) -> List[CandidateTrack]:
        track_title = track.name
        core_title = YouTubeExtractor._core_title(track_title)
        artists = [a.strip() for a in (track.artists or []) if a and a.strip()]
        track_duration_s = track.duration_ms / 1000 if track.duration_ms else None

        rows = []
        for position, entry in enumerate(entries):
            if not entry:
                continue

            candidate_id = str(entry.get("id", "")).strip()
            title = str(entry.get("title", "")).strip()
            if not candidate_id or not title:
                continue

            uploader = entry.get("uploader") or entry.get("channel") or ""
            duration = entry.get("duration")
            official = YouTubeExtractor._is_official_channel(uploader, artists)
            rows.append(
                {
                    "id": candidate_id,
                    "title": title,
                    "uploader": uploader,
                    "duration": duration,
                    "duration_ms": int(duration * 1000) if duration is not None else None,
                    "views": entry.get("view_count"),
                    "position": position,
                    "official": official,
                    "recall_raw": YouTubeExtractor._title_recall(title, track_title),
                    "recall_core": YouTubeExtractor._title_recall(title, core_title),
                    "artist_ok": YouTubeExtractor._artist_ok(title, uploader, artists, official),
                }
            )

        def survives(row, recall_key, artist_gate=True):
            if row[recall_key] < YouTubeExtractor._TITLE_RECALL_MIN:
                return False
            if artist_gate and not row["artist_ok"]:
                return False
            duration = row["duration"]
            if (
                not row["official"]
                and duration is not None
                and track_duration_s is not None
                and abs(duration - track_duration_s) > YouTubeExtractor._DURATION_TOLERANCE_S
            ):
                return False
            return True

        def ordered(pool, recall_key):
            scored = [
                (
                    not row["official"],
                    -YouTubeExtractor._coherence_score(
                        row[recall_key],
                        row["duration"],
                        track_duration_s,
                        row["views"],
                    ),
                    row["position"],
                    row,
                )
                for row in pool
            ]
            # Official channel first, always; then coherence; YouTube order wins ties.
            scored.sort(key=lambda item: item[:3])
            return [row for _, _, _, row in scored]

        def to_candidates(pool):
            return [
                CandidateTrack(
                    id=row["id"],
                    title=row["title"],
                    artist=row["uploader"],
                    duration_ms=row["duration_ms"],
                )
                for row in pool
            ]

        strict = ordered([row for row in rows if survives(row, "recall_raw")], "recall_raw")
        # A perfect raw recall means the candidate title *is* the searched one:
        # a parenthetical that is part of the title ("Song (Live at X)") must
        # not be diluted by the studio version, so relaxed never runs.
        exact = [row for row in strict if row["recall_raw"] >= 1.0]
        if exact:
            return to_candidates(exact)

        relaxed = ordered(
            [
                row
                for row in rows
                if survives(row, "recall_core", artist_gate=bool(artists))
            ],
            "recall_core",
        )
        seen = {row["id"] for row in strict}
        return to_candidates(strict + [row for row in relaxed if row["id"] not in seen])

    @staticmethod
    def search_candidates(track: Track) -> List[CandidateTrack]:
        """Same-song candidates with the official upload first (~1s)."""
        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        artists = [a.strip() for a in (track.artists or []) if a and a.strip()]

        def run(ydl: yt_dlp.YoutubeDL) -> List[CandidateTrack]:
            entries, candidates = [], []
            for query in YouTubeExtractor._build_search_queries(track):
                entries = YouTubeExtractor._merge_entries(
                    YouTubeExtractor._fetch_entries(ydl, query), entries
                )
                candidates = YouTubeExtractor._rank_entries(entries, track)
                # Keep the extra request budget for real misses: a hit from the
                # artist's own channel is already the best answer available.
                if candidates and YouTubeExtractor._from_artist(candidates[0].artist, artists):
                    return candidates
            return candidates

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
