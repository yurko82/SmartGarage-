"""
server/voice/synthesizer.py — Синтез мовлення (Text-to-Speech)
Обгортка над server/tts/manager.py для озвучення відповідей асистента українською мовою.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("VoiceListener.Synthesizer")


class VoiceSynthesizer:
    """Синтезатор мовлення для голосового асистента."""

    def __init__(self, tts_manager=None):
        self._manager = tts_manager

    @property
    def manager(self):
        if self._manager is None:
            try:
                from server.tts.manager import TTSManager

                self._manager = TTSManager()
            except Exception as e:
                logger.error(f"Не вдалося ініціалізувати TTSManager: {e}")
        return self._manager

    def synthesize(self, text: str, provider: str | None = "edge") -> bytes | None:
        """Синтезувати текст у байти MP3."""
        if not self.manager or not text.strip():
            return None
        try:
            result = self.manager.synthesize(text, provider=provider)
            if result and hasattr(result, "audio_bytes"):
                return result.audio_bytes
        except Exception as e:
            logger.error(f"Помилка синтезу мовлення: {e}")
        return None

    def synthesize_to_file(self, text: str, output_path: str, provider: str | None = "edge") -> bool:
        """Синтезувати та зберегти аудіофайл."""
        audio = self.synthesize(text, provider=provider)
        if not audio:
            return False
        try:
            with open(output_path, "wb") as f:
                f.write(audio)
            return True
        except Exception as e:
            logger.error(f"Помилка запису файлу {output_path}: {e}")
            return False
