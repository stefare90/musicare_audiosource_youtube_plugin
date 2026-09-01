import sys
import subprocess
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.sdk.types import Track, Artist
from src.extractor import YouTubeExtractor

def test_and_play(artist: str, title: str, quality: str = "high"):
    print(f"\n🔍 Resolving audio stream for: {artist} - {title} (Quality: {quality})...")
    track = Track(name=title, artists=[Artist(name=artist)], duration_ms=0)

    try:
        sources = YouTubeExtractor.resolve_stream(track, quality)
    except Exception as e:
        print(f"❌ Resolution failed: {e}")
        return

    print(f"✅ Found {len(sources)} audio stream candidates.\n")

    for idx, source in enumerate(sources, start=1):
        print(f"--- [Source #{idx}] ---")
        print(f"Codec:   {source.codec}")
        print(f"Bitrate: {source.bitrate} bps ({round((source.bitrate or 0) / 1000)} kbps)")
        print(f"Expires: {source.expires_at}")
        print(f"URL:     {source.url}\n")

    # Launch native playback of the primary (#1) source
    primary_source = sources[0]
    user_agent = (primary_source.headers or {}).get(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )

    # CLI players to attempt in sequence
    players = [
        ["mpv", f"--user-agent={user_agent}", primary_source.url],
        ["ffplay", "-nodisp", "-autoexit", "-user_agent", user_agent, primary_source.url],
        ["vlc", "--http-user-agent", user_agent, primary_source.url],
    ]

    played = False
    for cmd in players:
        try:
            print(f"▶️ Launching playback with '{cmd[0]}' (Press Ctrl+C to stop)...")
            subprocess.run(cmd, check=True)
            played = True
            break
        except FileNotFoundError:
            continue
        except KeyboardInterrupt:
            print("\n⏹ Playback stopped by user.")
            played = True
            break

    if not played:
        print("⚠️ No CLI player (mpv, ffplay, vlc) found.")
        print("👉 You can install mpv with: sudo pacman -S mpv")
        print("👉 Or copy-paste the URL above into VLC -> Media -> Open Network Stream.")

if __name__ == '__main__':
    artist_arg = sys.argv[1] if len(sys.argv) > 1 else "The Beatles"
    title_arg = sys.argv[2] if len(sys.argv) > 2 else "Come Together"
    quality_arg = sys.argv[3] if len(sys.argv) > 3 else "high"
    
    test_and_play(artist_arg, title_arg, quality_arg)
