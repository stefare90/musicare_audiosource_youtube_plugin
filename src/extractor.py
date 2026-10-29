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

    # One score, one confidence floor, top N: independent hard gates zeroed a
    # track when a single signal was missing (a different artist spelling, an
    # odd duration) even though the upload was the searched song. Official
    # uploads are never dropped for their duration (on the artist's channel an
    # odd duration is an artistic choice), but proximity still ranks them.
    _TITLE_RECALL_MIN = 0.5
    _DURATION_TOLERANCE_S = 15
    _DURATION_ARTIST_SPAN_S = 30
    _TOP_CANDIDATES = 10
    _EXACT_ARTIST_TIER = 0.9
    _RELATED_ARTIST_TIER = 0.8
    _TITLE_WEIGHT = 0.30
    _ARTIST_WEIGHT = 0.28
    _DURATION_WEIGHT = 0.10
    _CLEANLINESS_WEIGHT = 0.14
    _POSITION_WEIGHT = 0.13
    _POPULARITY_WEIGHT = 0.05
    _BRACKET_PENALTY = 0.03
    _CANONICAL_BONUS = 0.03
    _CHANNEL_BONUS = 0.04
    _STOPWORDS = frozenset(
        {
            "a", "an", "and", "at", "con", "da", "dei", "del", "della",
            "di", "e", "ed", "el", "feat", "featuring", "for", "ft", "gli",
            "i", "il", "in", "la", "le", "lo", "los", "of", "on", "or",
            "per", "su", "the", "to", "un", "una", "uno", "with", "y",
        }
    )

    @staticmethod
    def _tokens(text: str) -> List[str]:
        # Fold accents without an ASCII encode: an ASCII fold zeroes scripts
        # such as 夜に駆ける, while unaccented uploads ("Beyonce - Halo") must
        # still meet accented metadata ("Beyoncé").
        decomposed = unicodedata.normalize("NFKD", text or "")
        folded = "".join(
            char for char in decomposed if not unicodedata.combining(char)
        ).casefold()
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
        """The compact key on a run of consecutive tokens, whole-word edges only.

        A multi-word name is written as those same words in a title
        ("Fabri Fibra - Tranne Te"): matching the compact key against one token
        at a time rejects every upload that spells the name out. A single word
        of a multi-word name still never matches ("Tears for Fears" on "for").
        """
        for start in range(len(tokens)):
            joined = ""
            for token in tokens[start:]:
                joined += token
                if joined == key or joined.startswith(key) or joined.endswith(key):
                    return True
                if len(joined) > len(key):
                    break
        return False

    @staticmethod
    def _related_artist(artist: str, tokens: List[str]) -> bool:
        """A distinctive run of two or more name tokens in the candidate.

        Covers related names that differ in one word ("Creedence Clearwater
        Revival" vs "Revisited"). A single word, or a run made only of
        articles/prepositions, is not enough ("The The", "for").
        """
        name = YouTubeExtractor._tokens(artist)
        for start in range(len(name)):
            for offset in range(len(tokens)):
                length = 0
                while (
                    start + length < len(name)
                    and offset + length < len(tokens)
                    and name[start + length] == tokens[offset + length]
                ):
                    length += 1
                if length >= 2 and any(
                    len(token) >= 4 and token not in YouTubeExtractor._STOPWORDS
                    for token in name[start : start + length]
                ):
                    return True
        return False

    @staticmethod
    def _artist_tier(
        candidate_title: str, uploader: str, artists: List[str], official: bool
    ) -> float:
        """How strongly the candidate points at the artist (0 = not at all).

        1.0 official channel, 0.9 compacted whole name on a token run
        ("caparezza" vs "telecaparezza", "fabrifibra" vs the run
        "Fabri Fibra", initials such as R.E.M. -> "rem"), 0.7 a distinctive
        two-token run ("creedence clearwater"), 0 none. Never a single word of
        a multi-word name on its own: that is how "Tears for Fears" used to
        pass on "for".
        """
        if official:
            return 1.0
        if not artists:
            return 0.0
        words = YouTubeExtractor._tokens(f"{candidate_title} {uploader}")
        compact = [YouTubeExtractor._compact(token) for token in words]
        if any(
            YouTubeExtractor._anchored(key, compact)
            for key in YouTubeExtractor._artist_keys(artists)
        ):
            return YouTubeExtractor._EXACT_ARTIST_TIER
        if any(
            YouTubeExtractor._related_artist(artist, words) for artist in artists
        ):
            return YouTubeExtractor._RELATED_ARTIST_TIER
        return 0.0

    @staticmethod
    def _title_cleanliness(
        candidate_title: str, track_title: str, core_title: str, artists: List[str]
    ) -> float:
        """How much of the title outside brackets belongs to the searched song.

        Variants add words to the title itself ("NEW VERSION", "+ testo") or
        put them in brackets ("Official Video", "Live at ...", "HUGEL Remix").
        Artist names are removed first, then the remaining outside-bracket
        tokens are compared with the track title; any bracket carries a flat
        penalty so a marked version loses to its plain counterpart.
        """
        outside = YouTubeExtractor._BRACKETED_PATTERN.sub(" ", candidate_title)
        wanted = set(YouTubeExtractor._tokens(track_title))
        wanted |= set(YouTubeExtractor._tokens(core_title))
        artist_tokens = set()
        for artist in artists:
            artist_tokens |= set(YouTubeExtractor._tokens(artist))
            for term in YouTubeExtractor._ARTIST_SPLIT_PATTERN.split(artist):
                artist_tokens |= set(YouTubeExtractor._tokens(term))
        tokens = [
            token
            for token in YouTubeExtractor._tokens(outside)
            if token not in artist_tokens
        ]
        if not tokens:
            return 0.0
        precision = sum(1 for token in tokens if token in wanted) / len(tokens)
        penalty = (
            YouTubeExtractor._BRACKET_PENALTY
            if YouTubeExtractor._BRACKETED_PATTERN.search(candidate_title)
            else 0.0
        )
        return max(0.0, precision - penalty)

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
            recall_raw = YouTubeExtractor._title_recall(title, track_title)
            recall_core = YouTubeExtractor._title_recall(title, core_title)
            diff = (
                abs(duration - track_duration_s)
                if duration is not None and track_duration_s is not None
                else None
            )
            proximity = 1.0 if diff is None else max(0.0, 1 - diff / 300)
            views = entry.get("view_count")
            popularity = min(1.0, math.log10(1 + views) / 7) if views else 0.0
            artist_tier = YouTubeExtractor._artist_tier(
                title, uploader, artists, official
            )
            # Core recall carries the score (a MusicBrainz disambiguator is
            # noise), the raw recall only breaks ties toward the exact title.
            title_score = min(1.0, recall_core + 0.15 * recall_raw)
            cleanliness = YouTubeExtractor._title_cleanliness(
                title, track_title, core_title, artists
            )
            position_score = max(0.0, 1 - position / 15)
            rows.append(
                {
                    "id": candidate_id,
                    "title": title,
                    "uploader": uploader,
                    "duration_ms": int(duration * 1000) if duration is not None else None,
                    "position": position,
                    "official": official,
                    "recall_raw": recall_raw,
                    "title_score": title_score,
                    "artist_tier": artist_tier,
                    "diff": diff,
                    "score": (
                        YouTubeExtractor._TITLE_WEIGHT * title_score
                        + YouTubeExtractor._ARTIST_WEIGHT * artist_tier
                        + YouTubeExtractor._DURATION_WEIGHT * proximity
                        + YouTubeExtractor._CLEANLINESS_WEIGHT * cleanliness
                        + YouTubeExtractor._POSITION_WEIGHT * position_score
                        + YouTubeExtractor._POPULARITY_WEIGHT * popularity
                        + (
                            YouTubeExtractor._CHANNEL_BONUS
                            if official
                            else 0.0
                        )
                    ),
                }
            )

        # A plain official upload of the same song beats its own bracketed
        # official variants ("Song (NEW VERSION)", "Song (Remix)"): no keyword
        # list, only the presence of a bracketed sibling on the same channel.
        bracketed_official_keys = {
            tuple(sorted(YouTubeExtractor._tokens(YouTubeExtractor._core_title(row["title"]))))
            for row in rows
            if row["official"]
            and YouTubeExtractor._BRACKETED_PATTERN.search(row["title"])
        }
        for row in rows:
            if row["official"] and not YouTubeExtractor._BRACKETED_PATTERN.search(
                row["title"]
            ):
                key = tuple(
                    sorted(
                        YouTubeExtractor._tokens(
                            YouTubeExtractor._core_title(row["title"])
                        )
                    )
                )
                if key in bracketed_official_keys:
                    row["score"] += YouTubeExtractor._CANONICAL_BONUS

        def viable(row) -> bool:
            if row["title_score"] < YouTubeExtractor._TITLE_RECALL_MIN:
                return False
            if row["official"] or row["diff"] is None:
                duration_ok = True
            elif row["artist_tier"] >= 0.7:
                duration_ok = row["diff"] <= YouTubeExtractor._DURATION_ARTIST_SPAN_S
            else:
                duration_ok = row["diff"] <= YouTubeExtractor._DURATION_TOLERANCE_S
            if not duration_ok:
                return False
            # The related-name tier already covers metadata spellings such as
            # Creedence Clearwater Revisited vs Revival; without any artist
            # match an exact title is still someone else's recording.
            return not artists or row["artist_tier"] > 0

        kept = [row for row in rows if viable(row)]
        # An exact raw title comes first; the official channel is a bonus in
        # the score, not a hard key, so a clearly better title can win.
        kept.sort(
            key=lambda row: (
                row["recall_raw"] < 1.0,
                -row["score"],
                row["position"],
            )
        )
        return [
            CandidateTrack(
                id=row["id"],
                title=row["title"],
                artist=row["uploader"],
                duration_ms=row["duration_ms"],
            )
            for row in kept[: YouTubeExtractor._TOP_CANDIDATES]
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
