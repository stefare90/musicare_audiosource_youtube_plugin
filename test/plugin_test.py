from builtins import any
import unittest
import time
import urllib.request
from src.main import app
from src.sdk.types import Track, Artist
from src.matcher import TrackMatcher, CandidateTrack

class TestYouTubeAudioPlugin(unittest.TestCase):
    def setUp(self):
        """Initializes Flask test client before each test execution."""
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_health_check_returns_plugin_metadata(self):
        """Verifies that GET /ping returns 200 OK with correct plugin identity metadata."""
        response = self.client.get('/ping')
        self.assertEqual(response.status_code, 200)
        
        data = response.get_json()
        self.assertEqual(data['status'], 'ready')
        self.assertEqual(data['id'], 'org.musicare.audiosource.youtube')
        self.assertEqual(data['name'], 'MusicAre YouTube Audio Source')

    def test_matcher_ranks_candidates_by_adherence(self):
        """Verifies that TrackMatcher ranks candidates descending by duration and title score."""
        original = Track(
            name="Bohemian Rhapsody",
            artists=[Artist(name="Queen")],
            duration_ms=354000
        )

        candidates = [
            CandidateTrack(id="1", title="Bohemian Rhapsody (Live)", artist="Queen", duration_ms=420000),
            CandidateTrack(id="2", title="Bohemian Rhapsody - Metal Cover", artist="Random Band", duration_ms=354000),
            CandidateTrack(id="3", title="Bohemian Rhapsody (Official Audio)", artist="Queen", duration_ms=355000)
        ]

        ranked = TrackMatcher.rank_candidates(original, candidates)
        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0].id, "3")  # Official studio track must be ranked #1

    def test_resolve_stream_returns_playable_sources(self):
        """Verifies that POST /get_stream deciphers real stream URLs and CDN responds to HTTP Range requests."""
        test_tracks = [
            {
                "name": "Come Together",
                "artists": [{"name": "The Beatles"}],
                "durationMs": 259000
            },
            {
                "name": "Bohemian Rhapsody",
                "artists": [{"name": "Queen"}],
                "durationMs": 354000
            }
        ]

        for track_payload in test_tracks:
            with self.subTest(track=track_payload["name"]):
                response = self.client.post('/get_stream', json={
                    "track": track_payload,
                    "quality": "high"
                })

                self.assertEqual(response.status_code, 200)
                sources = response.get_json()

                self.assertIsInstance(sources, list)
                self.assertGreater(len(sources), 0)

                # Validate the primary resolved stream
                primary = sources[0]
                self.assertTrue(primary['url'].startswith('https://'))
                self.assertIn('googlevideo.com', primary['url'])
                self.assertGreater(primary['bitrate'], 0)
                self.assertIsNotNone(primary['codec'])
                self.assertGreater(primary['expiresAt'], int(time.time() * 1000))

                # Live HTTP Range handshake against Google CDN
                req = urllib.request.Request(
                    primary['url'],
                    headers={**(primary.get('headers') or {}), 'Range': 'bytes=0-1024'}
                )
                with urllib.request.urlopen(req, timeout=15) as cdn_response:
                    self.assertIn(cdn_response.status, [200, 206])
                    content_type = cdn_response.headers.get('Content-Type', '')
                    self.assertTrue(any(t in content_type for t in ['audio', 'video/mp4']))
                    self.assertGreater(len(cdn_response.read()), 0)

if __name__ == '__main__':
    unittest.main()