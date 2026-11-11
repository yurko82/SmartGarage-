"""
Smart Garage - Ukrainian Text-To-Speech (TTS) Subsystem
"""

from server.tts.base import (
    TTSAuthError,
    TTSError,
    TTSMalformedResponseError,
    TTSProvider,
    TTSRateLimitError,
    TTSResult,
    TTSServerError,
    TTSTimeoutError,
    TTSVoiceInfo,
    TTSVoiceNotFoundError,
)
from server.tts.cache import TTSAudioCache
from server.tts.edge_provider import EdgeTTSProvider
from server.tts.elevenlabs_provider import ElevenLabsTTSProvider
from server.tts.heygen_provider import HeyGenTTSProvider
from server.tts.manager import TTSManager, tts_manager
from server.tts.normalizer import clean_markdown_and_markup, normalize_ukrainian_text

__all__ = [
    "TTSProvider",
    "TTSResult",
    "TTSVoiceInfo",
    "TTSError",
    "TTSAuthError",
    "TTSRateLimitError",
    "TTSServerError",
    "TTSTimeoutError",
    "TTSVoiceNotFoundError",
    "TTSMalformedResponseError",
    "normalize_ukrainian_text",
    "clean_markdown_and_markup",
    "TTSAudioCache",
    "EdgeTTSProvider",
    "HeyGenTTSProvider",
    "ElevenLabsTTSProvider",
    "TTSManager",
    "tts_manager",
]
