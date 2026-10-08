#!/usr/bin/env python3
"""
Smart Garage - High Quality Neural TTS Service (Ukrainian)
Uses Microsoft neural voices (uk-UA-OstapNeural / uk-UA-PolinaNeural) via edge-tts.
Provides caching, HTTP streaming for web clients, and local PipeWire playback (pw-play).
Falls back gracefully to spd-say if offline.
"""
import os
import re
import hashlib
import asyncio
import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("NeuralTTS")

CACHE_DIR = Path("/tmp/smartgarage_tts_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_VOICE = "uk-UA-PolinaNeural"  # Природний мелодійний жіночий голос (Поліна) замість монотонного Остапа


def clean_text_for_tts(text: str) -> str:
    """Очищає текст від URL, емодзі, лапок та перетворює символи/скорочення на природну українську мову."""
    if not text:
        return ""
    # Strip URLs
    clean = re.sub(r'https?://\S+', '', text)
    # Strip emojis
    clean = re.sub(r'[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf\ufe00-\ufe0f\u200d]', '', clean)
    # Markdown formatting
    clean = re.sub(r'[*_#~\[\]()•·|`]', ' ', clean)
    # Strip single and double quotes (prevents Edge-TTS from inserting unnatural staccato pauses)
    clean = re.sub(r'[\'\"«»“”]', '', clean)
    # Measurements and units
    clean = re.sub(r'(\d+(?:[.,]\d+)?)\s*°C', r'\1 градусів', clean)
    clean = clean.replace('°C', ' градусів ')
    clean = re.sub(r'(\d+(?:[.,]\d+)?)\s*%', r'\1 відсотків', clean)
    clean = clean.replace('%', ' відсотків ')
    # Floors & location cleanups
    clean = re.sub(r'1-й\s*поверх', 'перший поверх', clean, flags=re.IGNORECASE)
    clean = re.sub(r'2-й\s*поверх', 'другий поверх', clean, flags=re.IGNORECASE)
    clean = re.sub(r'1-му\s*поверсі', 'першому поверсі', clean, flags=re.IGNORECASE)
    clean = re.sub(r'2-му\s*поверсі', 'другому поверсі', clean, flags=re.IGNORECASE)
    clean = re.sub(r'на\s+музика\s+(?:1-й|перший|1)\s+поверх', 'на першому поверсі', clean, flags=re.IGNORECASE)
    clean = re.sub(r'на\s+музика\s+1', 'на першому поверсі', clean, flags=re.IGNORECASE)
    # Status
    clean = re.sub(r'\[онлайн\]', 'онлайн', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\[офлайн\]', 'офлайн', clean, flags=re.IGNORECASE)
    # Radio & Latin names to phonetic Ukrainian
    clean = re.sub(r'\bhit\s*fm\b', 'Хіт ФМ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bkiss\s*fm\b', 'Кіс ФМ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\blounge\s*fm\b', 'Лаундж ФМ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bradio\s*roks\b', 'Радіо Рокс', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bradio\s*jazz\b', 'Радіо Джаз', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bfm\b', 'ФМ', clean, flags=re.IGNORECASE)
    # Punctuation to conversational intonational pauses
    clean = re.sub(r'[:;]+', ', ', clean)
    clean = re.sub(r'\s+[-—–]\s+', ', ', clean)
    clean = re.sub(r'[-—–]+', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    clean = re.sub(r'\s+([.,!?])', r'\1', clean)
    # Ensure proper sentence terminator for natural falling intonation cadence
    if clean and clean[-1] not in '.!?':
        clean += '.'
    return clean


class NeuralTTSService:
    def __init__(self, default_voice: str = DEFAULT_VOICE, rate: str = "+0%"):
        self.default_voice = default_voice
        self.rate = rate

    def get_cache_path(self, text: str, voice: str) -> Path:
        key = f"{voice}_{self.rate}_{text}"
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{digest}.mp3"

    async def synthesize_async(self, text: str, voice: Optional[str] = None) -> Path:
        """Synthesize text to MP3 file asynchronously with caching."""
        clean = clean_text_for_tts(text)
        if not clean:
            raise ValueError("Empty text after cleaning")

        chosen_voice = voice or self.default_voice
        cache_path = self.get_cache_path(clean, chosen_voice)

        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path

        try:
            import edge_tts
            communicate = edge_tts.Communicate(clean, chosen_voice, rate=self.rate)
            tmp_path = cache_path.with_suffix(".tmp")
            await communicate.save(str(tmp_path))
            os.replace(tmp_path, cache_path)
            return cache_path
        except Exception as e:
            logger.warning(f"edge-tts failed: {e}")
            raise

    def synthesize(self, text: str, voice: Optional[str] = None) -> Path:
        """Synchronous wrapper for synthesize_async."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.synthesize_async(text, voice))
        finally:
            loop.close()

    def speak_locally(self, text: str, voice: Optional[str] = None):
        """Asynchronously synthesizes and plays audio to system PipeWire/Bluetooth speaker."""
        def _play_worker():
            clean = clean_text_for_tts(text)
            if not clean:
                return
            try:
                mp3_path = self.synthesize(clean, voice)
                # 1. Try pw-play directly (PipeWire native player)
                res = subprocess.run(["pw-play", str(mp3_path)], capture_output=True, timeout=20)
                if res.returncode == 0:
                    return
                # 2. Try gst-play-1.0
                res = subprocess.run(["gst-play-1.0", "--no-interactive", str(mp3_path)], capture_output=True, timeout=20)
                if res.returncode == 0:
                    return
            except Exception as e:
                logger.warning(f"Neural TTS local playback failed: {e}")

            # Fallback to local spd-say only if audio player completely unavailable
            try:
                subprocess.run(["spd-say", "-l", "uk", "-r", "0", clean], timeout=15)
            except Exception as ex:
                logger.error(f"Fallback spd-say failed: {ex}")

        threading.Thread(target=_play_worker, daemon=True).start()


neural_tts = NeuralTTSService()
