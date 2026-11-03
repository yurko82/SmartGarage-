"""
Smart Garage - Microsoft Edge TTS Provider Adapter
--------------------------------------------------
Локальний безкоштовний провайдер на базі нейронних українських голосів
Microsoft (uk-UA-PolinaNeural, uk-UA-OstapNeural). Використовується як
надійний базовий або fallback провайдер, не потребує API-ключа.
"""

import asyncio
import io
import logging
from typing import List, Optional

from server.tts.base import (
    TTSProvider,
    TTSResult,
    TTSVoiceInfo,
    TTSError,
    TTSVoiceNotFoundError,
)

logger = logging.getLogger("EdgeTTSProvider")

EDGE_UKRAINIAN_VOICES = [
    TTSVoiceInfo(
        voice_id="uk-UA-PolinaNeural",
        name="Поліна (Нейронний жіночий)",
        language="uk-UA",
        gender="female",
        description="Природний, мелодійний жіночий український голос (за замовчуванням)",
        is_default=True,
    ),
    TTSVoiceInfo(
        voice_id="uk-UA-OstapNeural",
        name="Остап (Нейронний чоловічий)",
        language="uk-UA",
        gender="male",
        description="Чіткий, академічний чоловічий український голос",
        is_default=False,
    ),
]


class EdgeTTSProvider(TTSProvider):
    """Адаптер для Microsoft Edge TTS."""

    def __init__(
        self,
        default_voice_id: str = "uk-UA-PolinaNeural",
        rate: str = "+0%",
        timeout: float = 10.0,
        max_retries: int = 2
    ):
        super().__init__(name="edge", timeout=timeout, max_retries=max_retries)
        self.default_voice_id = default_voice_id
        self.rate = rate

    def is_configured(self) -> bool:
        """Edge TTS не потребує API-ключа і завжди доступний."""
        return True

    def get_available_voices(self) -> List[TTSVoiceInfo]:
        return list(EDGE_UKRAINIAN_VOICES)

    def synthesize(self, text: str, voice_id: Optional[str] = None, **kwargs) -> TTSResult:
        if not text:
            raise TTSError("Порожній текст для синтезу")

        chosen_voice = voice_id or self.default_voice_id
        # Перевірка валідності голосу
        valid_ids = [v.voice_id for v in EDGE_UKRAINIAN_VOICES]
        if chosen_voice not in valid_ids:
            logger.warning(f"Невідомий голос Edge TTS '{chosen_voice}', використовуємо '{self.default_voice_id}'")
            chosen_voice = self.default_voice_id

        try:
            import edge_tts
        except ImportError:
            raise TTSError("Пакет edge-tts не встановлено у системі")

        async def _synthesize():
            rate = kwargs.get("rate", self.rate)
            communicate = edge_tts.Communicate(text, chosen_voice, rate=rate)
            buffer = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer.write(chunk["data"])
            return buffer.getvalue()

        # Виконання асинхронного потоку в окремому loop
        loop = asyncio.new_event_loop()
        try:
            audio_bytes = loop.run_until_complete(
                asyncio.wait_for(_synthesize(), timeout=self.timeout)
            )
        except asyncio.TimeoutError:
            raise TTSError(f"Вичерпано таймаут Edge TTS ({self.timeout}с)")
        except Exception as e:
            raise TTSError(f"Помилка синтезу Edge TTS: {e}")
        finally:
            loop.close()

        if not audio_bytes:
            raise TTSError("Edge TTS повернув порожні аудіодані")

        return TTSResult(
            audio_bytes=audio_bytes,
            content_type="audio/mpeg",
            provider="edge",
            voice_id=chosen_voice,
            cached=False,
            fallback_used=False,
        )
