from musicare_plugin_sdk import BaseAudioSourcePlugin
from plugin import YouTubeAudioSourcePlugin


def get_plugin() -> BaseAudioSourcePlugin:
    """
    Standard entry-point factory function used by host applications to instantiate the plugin.
    """
    return YouTubeAudioSourcePlugin()