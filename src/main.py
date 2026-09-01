import os
import sys
from typing import List
from flask import Flask, request, jsonify
from src.sdk.types import Track, AudioQuality, AudioStreamResponse
from src.sdk.base_plugin import BaseAudioSourcePlugin
from src.extractor import YouTubeExtractor

app = Flask(__name__)

class YouTubeAudioSourcePlugin(BaseAudioSourcePlugin):
    @property
    def id(self) -> str:
        return "org.musicare.audiosource.youtube"

    @property
    def name(self) -> str:
        return "MusicAre YouTube Audio Source"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_stream(self, track: Track, quality: AudioQuality) -> List[AudioStreamResponse]:
        return YouTubeExtractor.resolve_stream(track, quality)

plugin_instance = YouTubeAudioSourcePlugin()

@app.route('/ping', methods=['GET'])
def ping():
    """Health-check endpoint verifying the server is ready."""
    return jsonify({
        "status": "ready",
        "id": plugin_instance.id,
        "name": plugin_instance.name,
        "version": plugin_instance.version
    })

@app.route('/get_stream', methods=['POST'])
def get_stream():
    """Resolves a Track payload into an ordered list of AudioStreamResponses."""
    try:
        data = request.get_json(force=True)
        track_dict = data.get('track', {})
        quality = data.get('quality', 'high')

        track = Track.from_dict(track_dict)
        sources = plugin_instance.get_stream(track, quality)

        # Return JSON array of ordered stream sources
        return jsonify([source.to_dict() for source in sources]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def start_server():
    port = int(os.environ.get('PORT', 8765))
    app.run(host='127.0.0.1', port=port, threaded=True, debug=False, use_reloader=False)

if __name__ == '__main__':
    start_server()