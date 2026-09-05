import unittest
from musicare_sdk import Track, Artist, CandidateTrack, TrackMatcher
from src.main import get_plugin


class TestYouTubeAudioPluginUnit(unittest.TestCase):
    def setUp(self):
        """Instantiates the plugin via the standard factory before each test."""
        self.plugin = get_plugin()

    def test_plugin_metadata(self):
        """Verifies plugin identity properties and contract adherence."""
        self.assertEqual(self.plugin.id, "org.musicare.audiosource.youtube")
        self.assertEqual(self.plugin.name, "YouTube Audio Source")
        self.assertEqual(self.plugin.version, "1.0.0")

    def test_matcher_ranks_candidates_by_adherence(self):
        """Verifies that TrackMatcher ranks candidates descending by duration and title score."""
        original = Track(
            name="Bohemian Rhapsody",
            artists=[Artist(name="Queen")],
            duration_ms=354000,
        )

        candidates = [
            CandidateTrack(
                id="1",
                title="Bohemian Rhapsody (Live)",
                artist="Queen",
                duration_ms=420000,
            ),
            CandidateTrack(
                id="2",
                title="Bohemian Rhapsody - Metal Cover",
                artist="Random Band",
                duration_ms=354000,
            ),
            CandidateTrack(
                id="3",
                title="Bohemian Rhapsody (Official Audio)",
                artist="Queen",
                duration_ms=355000,
            ),
        ]

        ranked = TrackMatcher.rank_candidates(original, candidates)
        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0].id, "3")  # Official studio track must be ranked #1


if __name__ == '__main__':
    unittest.main()