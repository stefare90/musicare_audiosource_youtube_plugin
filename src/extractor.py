import time
from typing import List
import yt_dlp
from src.sdk.types import Track, AudioQuality, AudioStreamResponse
from src.matcher import CandidateTrack, TrackMatcher

class YouTubeExtractor:
    @staticmethod
    def resolve_stream(track: Track, quality: AudioQuality, max_sources: int = 3) -> List[AudioStreamResponse]:
        artist_names = ", ".join([a.name for a in track.artists])
        query = f"{artist_names} - {track.name}"

        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'skip_download': True,
        }

        # 1. Search YouTube for candidates (fetch top 5 results)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch5:{query} audio", download=False)
            entries = search_results.get('entries', []) if search_results else []

        if not entries:
            raise Exception(f"No audio candidates found on YouTube for: '{query}'")

        candidates: List[CandidateTrack] = []
        for entry in entries:
            if entry and entry.get('id') and entry.get('title'):
                duration_sec = entry.get('duration') or 0
                candidates.append(CandidateTrack(
                    id=entry.get('id'),
                    title=entry.get('title', ''),
                    artist=entry.get('uploader', '') or entry.get('channel', ''),
                    duration_ms=int(duration_sec * 1000)
                ))

        if not candidates:
            raise Exception(f"Failed to parse candidate metadata for: '{query}'")

        # 2. Rank candidates descending by adherence score
        ranked_candidates = TrackMatcher.rank_candidates(track, candidates)

        # 3. Extract stream URLs for top ranked candidates
        extract_opts = {
            'format': 'bestaudio/best' if quality != 'low' else 'worstaudio/worst',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }

        resolved_sources: List[AudioStreamResponse] = []

        with yt_dlp.YoutubeDL(extract_opts) as ydl:
            for candidate in ranked_candidates[:max_sources]:
                try:
                    video_info = ydl.extract_info(f"https://www.youtube.com/watch?v={candidate.id}", download=False)
                    if not video_info:
                        continue

                    stream_url = video_info.get('url')
                    if not stream_url:
                        formats = video_info.get('formats', [])
                        audio_formats = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
                        if audio_formats:
                            audio_formats.sort(key=lambda f: f.get('abr') or 0, reverse=(quality != 'low'))
                            stream_url = audio_formats[0].get('url')

                    if not stream_url:
                        continue

                    bitrate_kbps = video_info.get('abr') or video_info.get('tbr') or 128
                    http_headers = video_info.get('http_headers') or {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    }

                    resolved_sources.append(AudioStreamResponse(
                        url=stream_url,
                        quality=quality,
                        codec=video_info.get('audio_ext') or 'm4a',
                        bitrate=int(bitrate_kbps * 1000),
                        expires_at=int(time.time() * 1000) + (5 * 60 * 60 * 1000),
                        headers=http_headers
                    ))
                except Exception:
                    # Continue to next candidate if one fails
                    continue

        if not resolved_sources:
            raise Exception(f"Failed to resolve any playable audio stream URL for: '{query}'")

        return resolved_sources