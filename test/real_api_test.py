import unittest
import urllib.request

from musicare_plugin_sdk import AudioQuality, Track
from src.plugin import YouTubeAudioSourcePlugin


class TestYouTubePluginRealApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = YouTubeAudioSourcePlugin()

    def test_e2e_search_and_cdn_handshake(self):
        # 1. Search candidates (Fast flat search)
        track = Track(name="Come Together", artists=["The Beatles"], duration_ms=259000)
        candidates = self.plugin.search_candidates(track)

        self.assertGreater(len(candidates), 0, "Candidate search returned zero items")
        primary = candidates[0]
        self.assertTrue(bool(primary.id), "Primary candidate ID must not be empty")
        self.assertTrue(bool(primary.title), "Primary candidate title must not be empty")

        # 2. Resolve stream on-demand for primary candidate
        stream = self.plugin.resolve_stream(primary.id, AudioQuality.HIGH)
        self.assertTrue(stream.url.startswith("https://"), "Stream URL must use HTTPS")

        # 3. HTTP Range handshake (bytes 0-1024) against live CDN
        headers = {"User-Agent": stream.headers.get("User-Agent", "Mozilla/5.0"), "Range": "bytes=0-1024"}
        for k, v in stream.headers.items():
            headers[k] = v
        headers["Range"] = "bytes=0-1024"

        req = urllib.request.Request(stream.url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            status = response.getcode()
            self.assertIn(status, [200, 206], f"CDN returned unexpected HTTP status: {status}")
            data = response.read()
            self.assertGreater(len(data), 0, "CDN returned empty payload")


if __name__ == "__main__":
    unittest.main()
