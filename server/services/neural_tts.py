#!/usr/bin/env python3
"""
Smart Garage - High Quality Neural TTS Service (Ukrainian)
Uses Microsoft neural voices (uk-UA-OstapNeural / uk-UA-PolinaNeural) via edge-tts,
HeyGen Voice Turbo and ElevenLabs Flash/Turbo via server.tts subsystem.
Provides caching, HTTP streaming for web clients, and local PipeWire playback (pw-play).
"""
import os
import logging
from pathlib import Path
from typing import Optional

from server.tts.normalizer import normalize_ukrainian_text
from server.tts.manager import tts_manager, TTSManager
from server.tts.cache import DEFAULT_CACHE_DIR

logger = logging.getLogger("NeuralTTS")

CACHE_DIR = DEFAULT_CACHE_DIR
DEFAULT_VOICE = "uk-UA-PolinaNeural"


def clean_text_for_tts(text: str) -> str:
    """Очищає та нормалізує український текст для синтезу мовлення."""
    return normalize_ukrainian_text(text, max_length=500)


class NeuralTTSService:
    def __init__(self, default_voice: str = DEFAULT_VOICE, rate: str = "+0%"):
        self.default_voice = default_voice
        self.rate = rate
        self.manager = tts_manager

    def synthesize(self, text: str, voice: Optional[str] = None) -> Path:
        """Синхронний синтез мовлення, що повертає шлях до згенерованого MP3/WAV файлу."""
        clean = clean_text_for_tts(text)
        if not clean:
            raise ValueError("Empty text after cleaning")

        chosen_voice = voice or self.default_voice
        result = self.manager.synthesize(clean, voice_id=chosen_voice)

        ext = ".wav" if "wav" in result.content_type else ".mp3"
        out_file = self.manager.cache.cache_dir / f"service_out_{hash(clean)}_{chosen_voice}{ext}"
        out_file.write_bytes(result.audio_bytes)
        return out_file

    async def synthesize_async(self, text: str, voice: Optional[str] = None) -> Path:
        """Асинхронний метод для сумісності."""
        return self.synthesize(text, voice)

    def speak_locally(self, text: str, voice: Optional[str] = None):
        """Асинхронно синтезує та відтворює звук на Bluetooth/PipeWire виході."""
        self.manager.speak_locally(text, voice_id=voice or self.default_voice)


neural_tts = NeuralTTSService()
