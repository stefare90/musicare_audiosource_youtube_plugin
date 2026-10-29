import json
import os
import unittest
from unittest.mock import MagicMock, patch

from musicare_audio_plugin_sdk import (
    AudioQuality,
    Track,
    code_of,
)
from yt_dlp.utils import DownloadError
from src.extractor import YouTubeExtractor
from src.plugin import YouTubeAudioSourcePlugin

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "youtube_entries.json")


def load_fixture(key):
    with open(FIXTURES, encoding="utf-8") as fh:
        case = json.load(fh)[key]
    return case["entries"], case["track"]


def track_from_fixture(key, **overrides):
    _, data = load_fixture(key)
    return Track(
        name=overrides.get("name", data["name"]),
        artists=overrides.get("artists", data["artists"]),
        duration_ms=overrides.get("duration_ms", data["duration_ms"]),
    )


class TestYouTubePluginUnit(unittest.TestCase):
    def setUp(self):
        self.plugin = YouTubeAudioSourcePlugin()

    def test_plugin_metadata(self):
        self.assertEqual(self.plugin.id, "org.musicare.audiosource.youtube")
        self.assertEqual(self.plugin.name, "YouTube Audio Source")
        self.assertEqual(self.plugin.version, "1.2.5")

    def test_manifest_version_matches_plugin_version(self):
        manifest = os.path.join(os.path.dirname(__file__), "..", "plugin.json")
        with open(manifest, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["version"], self.plugin.version)

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_search_candidates_parsing(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "fJ9rUzIMcZQ",
                    "title": "Bohemian Rhapsody (Official Video)",
                    "uploader": "Queen Official",
                    "duration": 359,
                }
            ]
        }

        track = Track(name="Bohemian Rhapsody", artists=["Queen"], duration_ms=354000)
        candidates = self.plugin.search_candidates(track)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.id, "fJ9rUzIMcZQ")
        self.assertEqual(candidate.title, "Bohemian Rhapsody (Official Video)")
        self.assertEqual(candidate.artist, "Queen Official")
        self.assertEqual(candidate.duration_ms, 359000)

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_resolve_stream_parsing(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "url": "https://rr1---sn.googlevideo.com/videoplayback?expire=1750000000",
            "acodec": "m4a",
            "abr": 160,
            "http_headers": {"User-Agent": "Mozilla/5.0 Test"},
        }

        stream = self.plugin.resolve_stream("fJ9rUzIMcZQ", AudioQuality.HIGH)
        self.assertTrue(stream.url.startswith("https://"))
        self.assertEqual(stream.quality, AudioQuality.HIGH)
        self.assertEqual(stream.codec, "m4a")
        self.assertEqual(stream.bitrate, 160000)
        self.assertEqual(stream.expires_at, 1750000000 * 1000)
        self.assertEqual(stream.headers.get("User-Agent"), "Mozilla/5.0 Test")

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_search_joint_query_first_finds_duet(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        def fake_extract(query, download=False):
            if query == "ytsearch15:Fanculo - Marracash 22simba":
                return {
                    "entries": [
                        {
                            "id": "Odvboh6aOWY",
                            "title": "22simba - Fanculo feat. Marracash",
                            "uploader": "22simba",
                            "duration": 172,
                        }
                    ]
                }
            return {"entries": []}

        mock_ydl.extract_info.side_effect = fake_extract

        track = Track(name="Fanculo", artists=["Marracash", "22simba"])
        candidates = self.plugin.search_candidates(track)

        self.assertIn("Odvboh6aOWY", [c.id for c in candidates])
        issued = [c.args[0] for c in mock_ydl.extract_info.call_args_list]
        self.assertEqual(issued, ["ytsearch15:Fanculo - Marracash 22simba"])

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_search_splits_packed_artist_credit_as_fallback(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        def fake_extract(query, download=False):
            if query == "ytsearch15:Fanculo - 22simba Marracash":
                return {
                    "entries": [
                        {
                            "id": "Odvboh6aOWY",
                            "title": "22simba - Fanculo feat. Marracash",
                            "uploader": "22simba",
                            "duration": 172,
                        }
                    ]
                }
            return {"entries": []}

        mock_ydl.extract_info.side_effect = fake_extract

        for artist in ("22simba feat. Marracash", "22simba & Marracash", "22simba, Marracash"):
            mock_ydl.extract_info.reset_mock()
            candidates = self.plugin.search_candidates(Track(name="Fanculo", artists=[artist]))
            self.assertIn("Odvboh6aOWY", [c.id for c in candidates])
            issued = [c.args[0] for c in mock_ydl.extract_info.call_args_list]
            self.assertEqual(
                issued,
                [f"ytsearch15:Fanculo - {artist}", "ytsearch15:Fanculo - 22simba Marracash"],
            )

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_search_first_hit_issues_single_query(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "fJ9rUzIMcZQ",
                    "title": "Bohemian Rhapsody (Official Video)",
                    "uploader": "Queen Official",
                    "duration": 359,
                }
            ]
        }

        track = Track(name="Bohemian Rhapsody", artists=["Queen"], duration_ms=354000)
        candidates = self.plugin.search_candidates(track)

        self.assertEqual(len(candidates), 1)
        mock_ydl.extract_info.assert_called_once_with(
            "ytsearch15:Bohemian Rhapsody - Queen", download=False
        )

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_search_without_artists_queries_title(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {"entries": []}

        track = Track(name="Fanculo", artists=[])
        self.assertEqual(self.plugin.search_candidates(track), [])
        mock_ydl.extract_info.assert_called_once_with(
            "ytsearch15:Fanculo", download=False
        )
    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_resolve_retries_with_mobile_clients_on_bot_wall(self, mock_ydl_cls):
        seen_opts = []

        def factory(opts):
            seen_opts.append(opts)
            mock_ydl = MagicMock()
            mock_ydl.__enter__.return_value = mock_ydl
            if len(seen_opts) == 1:
                mock_ydl.extract_info.side_effect = DownloadError(
                    "ERROR: [youtube] Odvboh6aOWY: Sign in to confirm "
                    "you're not a bot. Use --cookies-from-browser"
                )
            else:
                mock_ydl.extract_info.return_value = {
                    "url": "https://rr1---sn.googlevideo.com/videoplayback?expire=1750000000",
                    "acodec": "mp4a.40.2",
                    "abr": 129,
                    "http_headers": {},
                }
            return mock_ydl

        mock_ydl_cls.side_effect = factory

        stream = self.plugin.resolve_stream("Odvboh6aOWY", AudioQuality.HIGH)

        self.assertTrue(stream.url.startswith("https://"))
        self.assertEqual(mock_ydl_cls.call_count, 2)
        self.assertNotIn("extractor_args", seen_opts[0])
        self.assertEqual(
            seen_opts[1]["extractor_args"],
            {"youtube": {"player_client": ["android", "ios"]}},
        )

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_resolve_bot_wall_on_both_attempts_is_retryable(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = DownloadError(
            "ERROR: [youtube] Odvboh6aOWY: Sign in to confirm you're not a bot. "
            "Use --cookies-from-browser. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ "
            "for how to manually pass cookies"
        )

        with self.assertRaises(Exception) as ctx:
            self.plugin.resolve_stream("Odvboh6aOWY", AudioQuality.HIGH)

        self.assertEqual(code_of(ctx.exception), "rate_limited")
        self.assertTrue(ctx.exception.retryable)
        self.assertIn("not a bot", str(ctx.exception))
        self.assertIn("mobile clients", str(ctx.exception))
        self.assertNotIn("http", str(ctx.exception))
        self.assertEqual(mock_ydl_cls.call_count, 2)

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_resolve_persistent_age_gate_is_not_found(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = DownloadError(
            "ERROR: [youtube] Odvboh6aOWY: Sign in to confirm your age"
        )

        with self.assertRaises(Exception) as ctx:
            self.plugin.resolve_stream("Odvboh6aOWY", AudioQuality.HIGH)

        self.assertEqual(code_of(ctx.exception), "not_found")
        self.assertIn("confirm your age", str(ctx.exception))

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_resolve_transport_error_skips_mobile_retry(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = DownloadError(
            "ERROR: [youtube] Odvboh6aOWY: Unable to download API page: "
            "HTTPSConnectionPool Read timed out"
        )

        with self.assertRaises(Exception) as ctx:
            self.plugin.resolve_stream("Odvboh6aOWY", AudioQuality.HIGH)

        self.assertEqual(code_of(ctx.exception), "transport_error")
        self.assertEqual(mock_ydl_cls.call_count, 1)

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_search_retries_with_mobile_clients_on_bot_wall(self, mock_ydl_cls):
        seen_opts = []

        def factory(opts):
            seen_opts.append(opts)
            mock_ydl = MagicMock()
            mock_ydl.__enter__.return_value = mock_ydl
            if len(seen_opts) == 1:
                mock_ydl.extract_info.side_effect = DownloadError(
                    "ERROR: [youtube:search] Sign in to confirm you're not a bot"
                )
            else:
                mock_ydl.extract_info.return_value = {
                    "entries": [
                        {
                            "id": "Odvboh6aOWY",
                            "title": "22simba - Fanculo feat. Marracash",
                            "uploader": "22simba",
                            "duration": 172,
                        }
                    ]
                }
            return mock_ydl

        mock_ydl_cls.side_effect = factory

        candidates = self.plugin.search_candidates(
            Track(name="Fanculo", artists=["22simba feat. Marracash"])
        )

        self.assertIn("Odvboh6aOWY", [c.id for c in candidates])
        self.assertEqual(mock_ydl_cls.call_count, 2)
        self.assertEqual(
            seen_opts[1]["extractor_args"],
            {"youtube": {"player_client": ["android", "ios"]}},
        )


    def _entries(self, rows):
        return {
            "entries": [
                {"id": cid, "title": title, "uploader": uploader,
                 "duration": duration, "view_count": views}
                for cid, title, uploader, duration, views in rows
            ]
        }

    def _search(self, mock_ydl_cls, rows, track):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = self._entries(rows)
        return self.plugin.search_candidates(track)

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_il_tipo_keeps_only_the_official_upload(self, mock_ydl_cls):
        rows = [
            ("8BwM3t3oKdQ", "Guè - Il Tipo (Visual)", "Guè", 159, 1900824),
            ("JCcK5rLjcIY", "Guè - Le Tipe ([Visual)", "Guè", 162, 500000),
            ("IlysrwpiIpY", "Guè, DJ Harsh, Vettosi - Marco Da Tropoja (Visual)", "Guè", 139, 300000),
            ("Q10lvmZox-Y", "Gue Pequeno entra a sorpresa cantando Il Tipo", "Dandy", 75, 3706),
            ("n0YmcbgZJ5k", "Guè, DJ Harsh - Lifestyle (Official Video)", "Guè", 144, 800000),
        ]
        track = Track(name="Il tipo", artists=["Guè Pequeno"], duration_ms=159000)
        candidates = self._search(mock_ydl_cls, rows, track)
        self.assertEqual([c.id for c in candidates], ["8BwM3t3oKdQ"])

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_fanculo_official_first_other_songs_out(self, mock_ydl_cls):
        rows = [
            ("Odvboh6aOWY", "22simba - Fanculo feat. Marracash", "ItalianHype", 173, 392278),
            ("WHxYkr2HU90", "22simba, Marracash - Fanculo (Visual)", "22simba", 172, 1097422),
            ("0XIcEw3mLYA", "22simba, Marracash - Fanculo - Live Room Version (Visual)", "22simba", 181, 112017),
            ("t3nF9z8btAQ", "Marracash - fanculo - 22simba - concerto Unipolforum Milano ", "instablogmusic ", 168, 13882),
            ("iTXUkE9DsLE", "22simba, Marracash - Fanculo (Testo/Lyrics)", "Italian Universe", 173, 19343),
            ("SSMqb2A3Bl0", "22simba, Marracash - Fanculo (Versione Karaoke)", "KaraItalia", 190, 3858),
            ("zh00Cp5T8jU", "22simba - It's Worth It (feat. Sayf) (Visual Audio)", "22simba", 201, 160880),
            ("3pVCFx1kptk", "Marracash, BLANCO - NEMESI (Visual)", "Marracash", 176, 50000),
        ]
        track = Track(name="Fanculo", artists=["Marracash", "22simba"], duration_ms=172000)
        candidates = self._search(mock_ydl_cls, rows, track)
        ids = [c.id for c in candidates]
        self.assertEqual(ids[0], "WHxYkr2HU90")
        self.assertIn("Odvboh6aOWY", ids)
        for dropped in ("zh00Cp5T8jU", "3pVCFx1kptk"):
            self.assertNotIn(dropped, ids)
        # The karaoke is an alternative, never the autoplayed first match.
        self.assertGreater(ids.index("SSMqb2A3Bl0"), 0)
        for candidate in candidates:
            self.assertIn("fanculo", candidate.title.lower())

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_bohemian_official_first_shortened_live_out(self, mock_ydl_cls):
        rows = [
            ("fJ9rUzIMcZQ", "Queen – Bohemian Rhapsody (Official Video Remastered)", "Queen Official", 360, 2106251890),
            ("5zLnaNY58j8", "Queen - Bohemian Rhapsody (Lyrics)", "7clouds Rock", 355, 6392614),
            ("vbvyNnw8Qjg", "Queen - Bohemian Rhapsody (Live Aid 1985)", "Live Aid and Queen Official", 165, 9000000),
        ]
        track = Track(name="Bohemian Rhapsody", artists=["Queen"], duration_ms=354000)
        candidates = self._search(mock_ydl_cls, rows, track)
        ids = [c.id for c in candidates]
        self.assertEqual(ids[0], "fJ9rUzIMcZQ")
        self.assertNotIn("vbvyNnw8Qjg", ids)

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_thriller_long_official_film_kept_audio_first(self, mock_ydl_cls):
        rows = [
            ("sOnqjkJTMaA", "Michael Jackson - Thriller (Official 4K Video)", "Michael Jackson", 822, 1204190195),
            ("sO4vI8P88NM", "Thriller", "Michael Jackson", 358, 20029000),
            ("4V90AmXnguw", "Michael Jackson - Thriller (Official Video - Shortened Version)", "Michael Jackson", 202, 415192169),
            ("ZEHsIcsjtdI", "Michael Jackson - Thriller - Thriller", "Sccuderia", 358, 54402109),
            ("T6RLNZWbcpo", "Michael (2026) 4K - Michael Jackson Records Thriller (7/11)", "Movieclips", 122, 2051966),
        ]
        track = Track(name="Thriller", artists=["Michael Jackson"], duration_ms=358000)
        candidates = self._search(mock_ydl_cls, rows, track)
        ids = [c.id for c in candidates]
        self.assertEqual(ids[0], "sO4vI8P88NM")
        self.assertIn("sOnqjkJTMaA", ids)
        self.assertNotIn("T6RLNZWbcpo", ids)

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_official_suffix_kept_when_part_of_artist_name(self, mock_ydl_cls):
        rows = [
            ("bbb", "Topic, A7S - Breaking Me (Lyrics)", "LyricChannel", 174, 9000000),
            ("aaa", "Topic, A7S - Breaking Me (Official Video)", "Topic", 174, 5000),
        ]
        track = Track(name="Breaking Me", artists=["Topic", "A7S"], duration_ms=174000)
        candidates = self._search(mock_ydl_cls, rows, track)
        self.assertEqual([c.id for c in candidates], ["aaa", "bbb"])


class TestSearchGates(unittest.TestCase):
    """Offline gates against recorded ytsearch15 responses (test/fixtures)."""

    def setUp(self):
        self.plugin = YouTubeAudioSourcePlugin()

    def candidates(self, key, **overrides):
        entries, _ = load_fixture(key)
        return YouTubeExtractor._rank_entries(entries, track_from_fixture(key, **overrides))

    def test_core_title_strips_disambiguators_and_edition_tails(self):
        self.assertEqual(
            YouTubeExtractor._core_title("Una chiave (Il colloquio - Aprirsi o chiudersi)"),
            "Una chiave",
        )
        self.assertEqual(YouTubeExtractor._core_title("Song [Live] {2019}"), "Song")
        self.assertEqual(YouTubeExtractor._core_title("Song - Remastered 2019"), "Song")
        self.assertEqual(YouTubeExtractor._core_title("Song - 2011 Remaster"), "Song")
        self.assertEqual(YouTubeExtractor._core_title("Song – Remastered"), "Song")
        # A title made only of a bracketed group must not collapse to nothing.
        self.assertEqual(YouTubeExtractor._core_title("(Intro)"), "(Intro)")

    def test_tokens_keep_non_latin_titles(self):
        self.assertEqual(
            YouTubeExtractor._title_recall(
                "YOASOBI - 夜に駆ける (Official Video)", "夜に駆ける"
            ),
            1.0,
        )
        self.assertEqual(YouTubeExtractor._core_title("夜に駆ける (Official Video)"), "夜に駆ける")
        self.assertEqual(YouTubeExtractor._compact("Guè Pequeno"), "guepequeno")
        self.assertEqual(YouTubeExtractor._compact("R.E.M."), "rem")
        self.assertEqual(YouTubeExtractor._compact("blink-182"), "blink182")

    def test_tokens_fold_accents_and_keep_other_scripts(self):
        self.assertEqual(YouTubeExtractor._tokens("Beyoncé"), ["beyonce"])
        self.assertEqual(YouTubeExtractor._tokens("però"), ["pero"])
        self.assertEqual(YouTubeExtractor._tokens("Måneskin"), ["maneskin"])
        self.assertEqual(YouTubeExtractor._compact("Beyoncé"), "beyonce")
        self.assertEqual(YouTubeExtractor._tokens("夜に駆ける"), ["夜に駆ける"])

    def test_accented_track_matches_unaccented_uploads(self):
        # Recorded query "Halo - Beyoncé": the unaccented VEVO uploads were
        # rejected by the 1.2.4 gates (recall 0.5, artist gate false).
        candidates = self.candidates(
            "halo_unaccented_official",
            name="Beyoncé - Halo",
            artists=["Beyoncé"],
            duration_ms=261000,
        )
        ids = [candidate.id for candidate in candidates]
        self.assertEqual(candidates[0].id, "bnVUHWCynig")
        for candidate_id in ("51IZ02KTQxY", "aIaarQuOJ5Q", "S6bJcnXBhbc"):
            self.assertIn(candidate_id, ids)
        self.assertTrue(YouTubeExtractor._is_official_channel("Beyonce VEVO", ["Beyoncé"]))

    def test_accented_track_recall_and_artist_gate(self):
        title = "Maneskin Zitti e Buoni Sanremo 2021 - Orchestrated and Conducted"
        self.assertEqual(
            YouTubeExtractor._title_recall(title, "Måneskin - Zitti e buoni"), 1.0
        )
        self.assertGreater(
            YouTubeExtractor._artist_tier(title, "Melox", ["Måneskin"], False), 0.0
        )

    def test_multiword_artist_anchored_on_consecutive_tokens(self):
        tranne = self.candidates("tranne_te_multiword")
        ids = [candidate.id for candidate in tranne]
        self.assertEqual(tranne[0].id, "VkE9YpbqJHI")
        # Third-party uploads spelling the name out, capped at top N.
        self.assertEqual(len(tranne), 10)
        for candidate_id in ("6MNYzr596DA", "KSfnFjovqJ4", "Nbd3gBqHw9M"):
            self.assertIn(candidate_id, ids)
        blinding = self.candidates("blinding_lights_multiword")
        self.assertEqual(blinding[0].id, "fHI8X4OXluQ")
        self.assertIn("XwxLwG2_Sxk", [candidate.id for candidate in blinding])

    def test_related_artist_tier(self):
        self.assertEqual(
            YouTubeExtractor._artist_tier(
                "Have You Ever Seen the Rain",
                "Creedence Clearwater Revival",
                ["Creedence Clearwater Revisited"],
                False,
            ),
            0.8,
        )
        self.assertEqual(
            YouTubeExtractor._artist_tier(
                "Sowing the Seeds of Love", "Radio X", ["Tears for Fears"], False
            ),
            0.0,
        )
        self.assertEqual(
            YouTubeExtractor._artist_tier(
                "This Is the Day", "Radio X", ["The The"], False
            ),
            0.0,
        )
        self.assertEqual(
            YouTubeExtractor._artist_tier("UNA CHIAVE", "telecaparezza", ["Caparezza"], False),
            0.9,
        )

    def test_sensitive_tracks_counts_and_first_candidate(self):
        """Every sensitive track at once: count (top N) and first candidate."""
        expected = {
            "nelle_mani": (6, "j6Ztfikf6Ds"),
            "un_mestiere_qualunque": (6, "BoR9aQ2pJxU"),
            "qua_dentro": (1, "9VUD-W5nj5I"),
            "cose_preziose": (10, "IRTbuEQXUpM"),
            "serpi": (6, "7wSCDySZay8"),
            "have_you_ever_seen_the_rain": (9, "bO28lB1uwp4"),
            "una_chiave": (9, "orgycZTgvUQ"),
            "ti_fa_stare_bene_core": (8, "84rgsCJOMUA"),
            "everybody_hurts": (10, "5rOiW_xY-kc"),
            "all_the_small_things": (10, "9Ht5RZpzPqw"),
            "come_together": (10, "45cYwDMibGo"),
            "back_in_black": (10, "pAgnJDJN4VA"),
            "grande_amore": (10, "w1f6o1HQBvg"),
            "with_or_without_you": (10, "6Q2mFw4VYBo"),
            "breaking_me": (10, "jIoEaTN7GGo"),
            "la_caduta_di_atlante_core": (5, "2xMotUsFsVY"),
            "headlight": (0, None),
            "bohemian_live_aid": (5, "vbvyNnw8Qjg"),
            "tranne_te_multiword": (10, "VkE9YpbqJHI"),
            "blinding_lights_multiword": (10, "fHI8X4OXluQ"),
        }
        for key, (count, first_id) in expected.items():
            with self.subTest(track=key):
                candidates = self.candidates(key)
                self.assertEqual(len(candidates), count)
                self.assertEqual(candidates[0].id if candidates else None, first_id)

    def test_have_you_ever_seen_the_rain_scored(self):
        candidates = self.candidates("have_you_ever_seen_the_rain")
        ids = [candidate.id for candidate in candidates]
        self.assertEqual(candidates[0].id, "bO28lB1uwp4")
        # The studio CCR uploads win over the Revisited live recordings.
        for candidate_id in ("bO28lB1uwp4", "oZael8uSAJo", "wUjT5Yt6TbU"):
            self.assertIn(candidate_id, ids)
        # A cover with the same title but a 28 s longer duration is dropped.
        self.assertNotIn("2oX2FSv4Rys", ids)

    def test_una_chiave_relaxed_recovers_exact_upload(self):
        candidates = self.candidates("una_chiave")
        self.assertTrue(candidates)
        self.assertEqual(candidates[0].id, "orgycZTgvUQ")
        self.assertEqual(candidates[0].artist, "telecaparezza")

    def test_ti_fa_stare_bene_relaxed_pass_returns_candidates(self):
        candidates = self.candidates("ti_fa_stare_bene")
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertIn("ti fa stare bene", candidate.title.lower())

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_core_query_runs_when_first_hit_is_a_live_bootleg(self, mock_ydl_cls):
        raw = "ytsearch15:Ti fa stare bene (L'ora d'aria - Frivolo o impegnato) - Caparezza"
        core = "ytsearch15:Ti fa stare bene - Caparezza"
        responses = {
            raw: load_fixture("ti_fa_stare_bene")[0],
            core: load_fixture("ti_fa_stare_bene_core")[0],
        }
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = lambda query, download=False: {
            "entries": responses[query]
        }

        candidates = self.plugin.search_candidates(track_from_fixture("ti_fa_stare_bene"))

        self.assertEqual(candidates[0].id, "84rgsCJOMUA")
        self.assertEqual(candidates[0].artist, "telecaparezza")
        issued = [call.args[0] for call in mock_ydl.extract_info.call_args_list]
        self.assertEqual(issued, [raw, core])

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_core_query_is_the_only_source_when_raw_returns_nothing(self, mock_ydl_cls):
        raw = "ytsearch15:La caduta di Atlante (Il peso - Sopruso o giustizia) - Caparezza"
        core = "ytsearch15:La caduta di Atlante - Caparezza"
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = lambda query, download=False: {
            "entries": load_fixture("la_caduta_di_atlante_core")[0] if query == core else []
        }

        candidates = self.plugin.search_candidates(track_from_fixture("la_caduta_di_atlante"))

        self.assertEqual(candidates[0].id, "2xMotUsFsVY")
        self.assertEqual(candidates[0].artist, "telecaparezza")
        issued = [call.args[0] for call in mock_ydl.extract_info.call_args_list]
        self.assertEqual(issued, [raw, core])

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_core_query_skipped_when_artist_channel_wins(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {"entries": load_fixture("una_chiave")[0]}

        candidates = self.plugin.search_candidates(track_from_fixture("una_chiave"))

        self.assertEqual(candidates[0].artist, "telecaparezza")
        mock_ydl.extract_info.assert_called_once_with(
            "ytsearch15:Una chiave (Il colloquio - Aprirsi o chiudersi) - Caparezza",
            download=False,
        )

    def test_la_caduta_di_atlante_needs_core_title_in_query(self):
        # Recorded on 2026-10-25: the polluted query returns zero entries, so
        # no gate can rescue this track — it needs the core title in the query.
        entries, _ = load_fixture("la_caduta_di_atlante")
        self.assertEqual(entries, [])
        self.assertEqual(self.candidates("la_caduta_di_atlante"), [])

    def test_everybody_hurts_initials_artist_gate(self):
        candidates = self.candidates("everybody_hurts")
        self.assertTrue(candidates)
        self.assertEqual(candidates[0].id, "5rOiW_xY-kc")
        self.assertEqual(candidates[0].artist, "remhq")

    def test_all_the_small_things_official_first(self):
        candidates = self.candidates("all_the_small_things")
        self.assertEqual(candidates[0].id, "9Ht5RZpzPqw")
        self.assertEqual(candidates[0].artist, "blink-182")

    def test_headlight_singular_title_is_a_known_title_mismatch(self):
        # YouTube's official upload is "Headlights": recall is 0.00 on both
        # measures, so no gate change helps (open item, needs title matching).
        self.assertEqual(self.candidates("headlight"), [])

    def test_negative_other_artist_same_title_kept_out(self):
        candidates = self.candidates(
            "headlight", name="Headlights", artists=["Alex Warren"], duration_ms=164000
        )
        ids = [candidate.id for candidate in candidates]
        self.assertIn("hJskvsP--6o", ids)
        self.assertNotIn("kyLuzKbgXAs", ids)

    def test_parenthetical_title_is_not_diluted_by_studio(self):
        candidates = self.candidates(
            "bohemian_live_aid",
            name="Bohemian Rhapsody (Live Aid 1985)",
            duration_ms=165000,
        )
        ids = [candidate.id for candidate in candidates]
        # The exact Live Aid upload beats the official medley and the studio.
        self.assertEqual(ids[0], "vbvyNnw8Qjg")
        self.assertLess(ids.index("vbvyNnw8Qjg"), ids.index("keVH4_WdgmI"))
        self.assertLess(ids.index("vbvyNnw8Qjg"), ids.index("fJ9rUzIMcZQ"))

    def test_attached_suffixes_are_official(self):
        self.assertTrue(YouTubeExtractor._is_official_channel("blink182VEVO", ["blink-182"]))
        self.assertTrue(YouTubeExtractor._is_official_channel("TheBeatlesVEVO", ["The Beatles"]))
        self.assertTrue(YouTubeExtractor._is_official_channel("U2VEVO", ["U2"]))
        self.assertTrue(YouTubeExtractor._is_official_channel("IlVoloVEVO", ["Il Volo"]))
        self.assertFalse(YouTubeExtractor._is_official_channel("telecaparezza", ["Caparezza"]))

    def test_attached_suffix_kept_when_part_of_artist_name(self):
        self.assertTrue(YouTubeExtractor._is_official_channel("Topic", ["DJ Topic"]))
        self.assertTrue(YouTubeExtractor._is_official_channel("Topic", ["Topic", "A7S"]))

    def test_single_word_of_multiword_name_does_not_pass(self):
        self.assertEqual(
            YouTubeExtractor._artist_tier(
                "Sowing the Seeds of Love", "Radio X", ["Tears for Fears"], False
            ),
            0.0,
        )
        self.assertEqual(
            YouTubeExtractor._artist_tier(
                "This Is the Day", "Radio X", ["The The"], False
            ),
            0.0,
        )
        self.assertGreater(
            YouTubeExtractor._artist_tier(
                "Everybody Hurts", "remhq", ["R.E.M."], False
            ),
            0.0,
        )

    def test_beatles_official_first(self):
        candidates = self.candidates("come_together")
        self.assertEqual(candidates[0].id, "45cYwDMibGo")

    def test_acdc_official_first(self):
        candidates = self.candidates("back_in_black")
        self.assertEqual(candidates[0].id, "pAgnJDJN4VA")

    def test_il_volo_official_first(self):
        candidates = self.candidates("grande_amore")
        self.assertEqual(candidates[0].id, "w1f6o1HQBvg")

    def test_u2_official_first(self):
        candidates = self.candidates("with_or_without_you")
        self.assertEqual(candidates[0].id, "6Q2mFw4VYBo")

    def test_dj_topic_official_from_recorded_search(self):
        candidates = self.candidates("breaking_me")
        self.assertTrue(candidates)
        self.assertTrue(
            YouTubeExtractor._is_official_channel(candidates[0].artist, ["Topic", "A7S"])
        )

    def test_track_without_artists_relaxed_gate_is_neutral(self):
        entries = [
            {"id": "abc", "title": "Nightfall", "uploader": "Some Channel", "duration": 200},
            {"id": "def", "title": "Other Song", "uploader": "Some Channel", "duration": 200},
        ]
        track = Track(name="Nightfall", artists=[], duration_ms=200000)
        ids = [c.id for c in YouTubeExtractor._rank_entries(entries, track)]
        self.assertEqual(ids, ["abc"])

    def test_pooling_appends_relaxed_to_strict(self):
        # raw tokens 4, core 1: "Alpha Beta" is a strict survivor (raw 0.5),
        # "Alpha" only a relaxed one (raw 0.25, core 1.0). Both must survive,
        # strict first — a relaxed pass that replaced strict would drop one.
        entries = [
            {"id": "strict", "title": "Alpha Beta", "uploader": "Artist", "duration": 200},
            {"id": "relaxed", "title": "Alpha", "uploader": "Artist", "duration": 200},
        ]
        track = Track(name="Alpha (Beta Gamma Delta)", artists=["Artist"], duration_ms=200000)
        ids = [c.id for c in YouTubeExtractor._rank_entries(entries, track)]
        self.assertEqual(ids, ["strict", "relaxed"])

    def test_non_latin_track_survives_the_whole_pipeline(self):
        entries = [
            {
                "id": "yoasobi",
                "title": "YOASOBI - 夜に駆ける (Official Video)",
                "uploader": "YOASOBI",
                "duration": 260,
            }
        ]
        track = Track(name="夜に駆ける", artists=["YOASOBI"], duration_ms=260000)
        ids = [c.id for c in YouTubeExtractor._rank_entries(entries, track)]
        self.assertEqual(ids, ["yoasobi"])

    def test_lookalike_channel_is_not_official(self):
        self.assertFalse(YouTubeExtractor._is_official_channel("U23", ["U2"]))
        self.assertFalse(YouTubeExtractor._is_official_channel("U2 Tribute Band", ["U2"]))

    @patch("src.extractor.yt_dlp.YoutubeDL")
    def test_recorded_tracks_regression_table(self, mock_ydl_cls):
        """One row per measured track: first hit and query count must not drift."""
        with open(FIXTURES, encoding="utf-8") as fh:
            responses = {case["query"]: case["entries"] for case in json.load(fh).values()}

        expected = {
            "una_chiave": ("orgycZTgvUQ", 1),
            "ti_fa_stare_bene": ("84rgsCJOMUA", 2),
            "la_caduta_di_atlante": ("2xMotUsFsVY", 2),
            "everybody_hurts": ("5rOiW_xY-kc", 1),
            "all_the_small_things": ("9Ht5RZpzPqw", 1),
            "headlight": (None, 1),
            "come_together": ("45cYwDMibGo", 1),
            "back_in_black": ("pAgnJDJN4VA", 1),
            "grande_amore": ("w1f6o1HQBvg", 1),
            "with_or_without_you": ("6Q2mFw4VYBo", 1),
            "breaking_me": ("jIoEaTN7GGo", 1),
            "nelle_mani": ("j6Ztfikf6Ds", 1),
            "un_mestiere_qualunque": ("BoR9aQ2pJxU", 1),
            "qua_dentro": ("9VUD-W5nj5I", 2),
            "cose_preziose": ("IRTbuEQXUpM", 1),
            "serpi": ("7wSCDySZay8", 1),
            "have_you_ever_seen_the_rain": ("bO28lB1uwp4", 1),
            "tranne_te_multiword": ("VkE9YpbqJHI", 1),
            "blinding_lights_multiword": ("fHI8X4OXluQ", 1),
        }

        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        for key, (first_id, query_count) in expected.items():
            with self.subTest(track=key):
                mock_ydl.extract_info.reset_mock()
                mock_ydl.extract_info.side_effect = lambda query, download=False: {
                    "entries": responses.get(query, [])
                }
                candidates = self.plugin.search_candidates(track_from_fixture(key))
                self.assertEqual(
                    candidates[0].id if candidates else None, first_id
                )
                self.assertEqual(mock_ydl.extract_info.call_count, query_count)


if __name__ == "__main__":
    unittest.main()