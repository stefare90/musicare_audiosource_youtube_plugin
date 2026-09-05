import unittest
import time
import urllib.request
from musicare_sdk import Track, Artist, AudioStreamResponse
from src.main import get_plugin


class TestYouTubeAudioPluginRealApi(unittest.TestCase):
    def setUp(self):
        """Instantiates the plugin via the standard factory before each test."""
        self.plugin = get_plugin()

    def test_resolve_stream_returns_playable_sources(self):
        """Verifies that get_stream resolves real URLs and CDN responds to HTTP Range requests."""
        test_tracks = [
            Track(
                name="Come Together",
                artists=[Artist(name="The Beatles")],
                duration_ms=259000,
            ),
            Track(
                name="Bohemian Rhapsody",
                artists=[Artist(name="Queen")],
                duration_ms=354000,
            ),
        ]

        for track in test_tracks:
            with self.subTest(track=track.name):
                sources = self.plugin.get_stream(track, quality="high")

                self.assertIsInstance(sources, list)
                self.assertGreater(len(sources), 0, f"No streams resolved for '{track.name}'")

                # Validate the primary resolved stream object
                primary = sources[0]
                self.assertIsInstance(primary, AudioStreamResponse)
                self.assertTrue(primary.url.startswith("https://"))
                self.assertIn("googlevideo.com", primary.url)
                self.assertGreater(primary.bitrate or 0, 0)
                self.assertIsNotNone(primary.codec)
                self.assertGreater(primary.expires_at or 0, int(time.time() * 1000))

                # Live HTTP Range handshake against Google CDN
                headers = {**(primary.headers or {}), "Range": "bytes=0-1024"}
                req = urllib.request.Request(primary.url, headers=headers)

                with urllib.request.urlopen(req, timeout=15) as cdn_response:
                    self.assertIn(cdn_response.status, [200, 206])
                    content_type = cdn_response.headers.get("Content-Type", "")
                    self.assertTrue(
                        any(t in content_type for t in ["audio", "video/mp4", "video/webm"]),
                        f"Unexpected Content-Type: {content_type}",
                    )
                    self.assertGreater(len(cdn_response.read()), 0)


if __name__ == '__main__':
    unittest.main()