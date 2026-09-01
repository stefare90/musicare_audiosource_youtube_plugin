from dataclasses import dataclass
from typing import List
from src.sdk.types import Track

@dataclass
class CandidateTrack:
    id: str
    title: str
    artist: str
    duration_ms: int

class TrackMatcher:
    @staticmethod
    def find_best_match(original: Track, candidates: List[CandidateTrack]) -> CandidateTrack:
        ranked = TrackMatcher.rank_candidates(original, candidates)
        if not ranked:
            raise ValueError(f"No candidates available to match for: '{original.name}'")
        return ranked[0]

    @staticmethod
    def rank_candidates(original: Track, candidates: List[CandidateTrack]) -> List[CandidateTrack]:
        """
        Scores all candidate tracks and returns them sorted descending by match score.
        """
        if not candidates:
            return []

        scored = [(candidate, TrackMatcher._calculate_score(original, candidate)) for candidate in candidates]
        # Sort descending by calculated score
        scored.sort(key=lambda item: item[1], reverse=True)

        return [item[0] for item in scored]

    @staticmethod
    def _calculate_score(original: Track, candidate: CandidateTrack) -> int:
        score = 100

        # 1. Duration delta scoring (primary heuristic)
        duration_diff_ms = abs(candidate.duration_ms - original.duration_ms)

        if duration_diff_ms <= 2000:
            score += 60  # <= 2s delta
        elif duration_diff_ms <= 5000:
            score += 30  # <= 5s delta
        elif duration_diff_ms <= 12000:
            score += 10  # <= 12s delta
        else:
            score -= min(100, (duration_diff_ms // 1000) * 5)

        original_title = original.name.lower()
        candidate_title = candidate.title.lower()
        primary_artist = original.artists[0].name.lower() if original.artists else ''

        # 2. Penalize unwanted variant keywords
        unwanted = ['live', 'cover', 'karaoke', 'remix', 'tribute', 'instrumental', 'parody', 'acoustic']
        for kw in unwanted:
            if kw in candidate_title and kw not in original_title:
                score -= 50

        # 3. Matching bonuses
        if original_title in candidate_title:
            score += 25

        if primary_artist and (primary_artist in candidate.artist.lower() or candidate.artist.lower() in primary_artist):
            score += 20

        if 'official audio' in candidate_title or 'topic' in candidate_title:
            score += 15

        return score