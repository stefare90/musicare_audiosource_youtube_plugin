from musicare_plugin_sdk import BaseAudioSourcePlugin
from src.plugin import YouTubeAudioSourcePlugin


def get_plugin() -> BaseAudioSourcePlugin:
    """Standard entry-point factory called dynamically by the host engine."""
    return YouTubeAudioSourcePlugin()
