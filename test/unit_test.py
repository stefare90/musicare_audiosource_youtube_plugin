import unittest
from unittest.mock import MagicMock, patch

from musicare_audio_plugin_sdk import (
    AudioQuality,
    Track,
    code_of,
)
from yt_dlp.utils import DownloadError
from src.plugin import YouTubeAudioSourcePlugin


class TestYouTubePluginUnit(unittest.TestCase):
    def setUp(self):
        self.plugin = YouTubeAudioSourcePlugin()

    def test_plugin_metadata(self):
        self.assertEqual(self.plugin.id, "org.musicare.audiosource.youtube")
        self.assertEqual(self.plugin.name, "YouTube Audio Source")
        self.assertEqual(self.plugin.version, "1.2.3")

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
        for dropped in ("SSMqb2A3Bl0", "zh00Cp5T8jU", "3pVCFx1kptk"):
            self.assertNotIn(dropped, ids)
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


if __name__ == "__main__":
    unittest.main()
