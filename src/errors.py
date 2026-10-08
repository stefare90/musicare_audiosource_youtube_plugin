"""Map yt-dlp failures to the plugin SDK error vocabulary.

yt-dlp raises :class:`yt_dlp.utils.DownloadError` with a message shaped like
``ERROR: [youtube] <id>: <reason>``. Left raw, the host runtime reports it as a
generic ``internal`` error and the app cannot tell a transient network wall
(bot-check) from a definitive one (removed video). The classifiers below keep
the original yt-dlp text inside the typed error, so the message shown to the
user (and the daemon logs) still carries the real cause.
"""

import re

from musicare_audio_plugin_sdk import (
    AudioPluginError,
    InternalError,
    NotFoundError,
    RateLimitedError,
    TransportError,
)

# Signatures of a client-side wall (IP/network flagged, or age-gated
# response): worth retrying with the mobile player clients before giving up.
WALL_MARKERS = (
    "sign in to confirm",
    "not a bot",
    "po token",
    "captcha",
    "age-restricted",
    "age check",
    "age_check",
    "age verification",
    "age_verification",
    "confirm your age",
    "inappropriate",
)

# Video genuinely restricted by age (definitive for this candidate): checked
# before WALL_MARKERS because "sign in to confirm your age" also matches
# the generic wall signature — the retry still happens via is_client_wall.
_AGE_GATE_MARKERS = (
    "confirm your age",
    "age-restricted",
    "age check",
    "age_check",
    "age verification",
    "age_verification",
    "inappropriate",
)

_NOT_FOUND_MARKERS = (
    "video unavailable",
    "private video",
    "has been removed",
    "no longer available",
    "not available in your country",
    "blocked",
    "geo",
    "region",
)

_RATE_LIMITED_MARKERS = (
    "429",
    "too many requests",
    "rate-limit",
    "rate limited",
    "try again later",
)

_TRANSPORT_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "urlerror",
    "network",
    "unreachable",
    "temporary failure",
    "ssl",
)


def _short_reason(text: str) -> str:
    # "ERROR: [youtube] <id>: <reason + cookie FAQ URLs>" -> "<id>: <reason>".
    # The snackbar shows this; the daemon log keeps the full tracebacks.
    match = re.search(r"\[([^\]]+)\] (?:([A-Za-z0-9_-]{11}): )?(.+)", text, re.DOTALL)
    if not match:
        return re.sub(r"\s+", " ", text).strip()[:500]
    source, video_id, reason = match.groups()
    reason = re.split(r"Use --cookies", reason)[0]
    reason = re.sub(r"https?://\S+", "", reason)
    reason = re.sub(r"\s+", " ", reason).strip().rstrip(".")
    head = f"[{source}] {video_id}" if video_id else f"[{source}]"
    return f"{head}: {reason}"[:500]


def is_client_wall(error: Exception) -> bool:
    """Whether ``error`` looks like a YouTube client wall (bot-check/age-gate)."""
    lowered = str(error).lower()
    return any(marker in lowered for marker in WALL_MARKERS)


def classify_download_error(
    error: Exception, *, fallback_of: Exception | None = None
) -> AudioPluginError:
    """Wrap a yt-dlp failure in the matching SDK error, keeping its text."""
    text = str(error)
    if fallback_of is not None:
        message = (
            f"{_short_reason(text)} "
            f"(mobile clients also blocked; "
            f"default clients: {_short_reason(str(fallback_of))})"
        )
    else:
        message = _short_reason(text)
    lowered = message.lower()
    if any(marker in lowered for marker in _AGE_GATE_MARKERS):
        return NotFoundError(message)
    if any(marker in lowered for marker in WALL_MARKERS):
        # A wall that survives the mobile clients is a network/IP condition
        # (transient), not a property of the candidate: retryable.
        return RateLimitedError(message)
    if any(marker in lowered for marker in _NOT_FOUND_MARKERS):
        return NotFoundError(message)
    if any(marker in lowered for marker in _RATE_LIMITED_MARKERS):
        return RateLimitedError(message)
    if any(marker in lowered for marker in _TRANSPORT_MARKERS):
        return TransportError(message)
    return InternalError(f"{type(error).__name__}: {message}")
