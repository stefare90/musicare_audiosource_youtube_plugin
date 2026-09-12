import unittest
from unittest.mock import MagicMock, patch

from musicare_plugin_sdk import (
    AudioQuality,
    Track,
)
from src.plugin import YouTubeAudioSourcePlugin


class TestYouTubePluginUnit(unittest.TestCase):
    def setUp(self):
        self.plugin = YouTubeAudioSourcePlugin()

    def test_plugin_metadata(self):
        self.assertEqual(self.plugin.id, "org.musicare.audiosource.youtube")
        self.assertEqual(self.plugin.name, "YouTube Audio Source")
        self.assertEqual(self.plugin.version, "1.0.0")

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


if __name__ == "__main__":
    unittest.main()
