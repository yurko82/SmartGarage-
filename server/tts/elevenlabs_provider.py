"""
Smart Garage - ElevenLabs Flash/Turbo TTS Provider Adapter
-----------------------------------------------------------
Адаптер для ElevenLabs API з підтримкою надшвидкої моделі Flash v2.5
(eleven_flash_v2_5) та Multilingual v2.
- Офіційно підтримує українську мову (uk).
- Тариф API Flash: ~$0.04 за 1 000 символів (наднизька затримка ~75ms).
- Тариф API Multilingual v2: ~$0.08 за 1 000 символів.
- ELEVENLABS_API_KEY зберігається виключно на сервері.
"""

import logging
import time
from typing import Any, Dict, List, Optional

import requests

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

logger = logging.getLogger("ElevenLabsTTSProvider")

ELEVENLABS_API_BASE = "https://api.elevenlabs.io"


class ElevenLabsTTSProvider(TTSProvider):
    """Адаптер для сервісу ElevenLabs."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "eleven_flash_v2_5",
        default_voice_id: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        base_url: str = ELEVENLABS_API_BASE,
    ):
        super().__init__(name="elevenlabs", timeout=timeout, max_retries=max_retries)
        self.api_key = (api_key or "").strip()
        self.model = model or "eleven_flash_v2_5"
        self.default_voice_id = (default_voice_id or "").strip()
        self.base_url = base_url.rstrip("/")
        self._cached_voices: list[TTSVoiceInfo] | None = None

    def is_configured(self) -> bool:
        """Перевіряє, чи налаштовано API-ключ на сервері."""
        return bool(self.api_key)

    def _get_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise TTSAuthError("Відсутній ELEVENLABS_API_KEY на сервері. Синтез через ElevenLabs неможливий.")
        return {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

    def get_available_voices(self) -> list[TTSVoiceInfo]:
        """
        Отримує перелік доступних голосів ElevenLabs з акаунта або публічної бібліотеки.
        """
        if not self.is_configured():
            logger.info("ELEVENLABS_API_KEY не налаштовано; отримання списку голосів неможливе.")
            return []

        if self._cached_voices is not None:
            return self._cached_voices

        url = f"{self.base_url}/v1/voices"
        try:
            headers = {"xi-api-key": self.api_key, "Accept": "application/json"}
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code in (401, 403):
                raise TTSAuthError("Недійсний ELEVENLABS_API_KEY при запиті списку голосів.")
            if resp.status_code != 200:
                logger.warning(f"ElevenLabs /v1/voices повернув {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json().get("voices", [])
            voices: list[TTSVoiceInfo] = []
            for item in data:
                v_id = item.get("voice_id")
                name = item.get("name", "ElevenLabs Voice")
                labels = item.get("labels") or {}
                gender = labels.get("gender", "unknown")
                lang = labels.get("language") or "multilingual"
                preview = item.get("preview_url")

                if v_id:
                    voices.append(
                        TTSVoiceInfo(
                            voice_id=v_id,
                            name=name,
                            language=lang,
                            gender=gender,
                            preview_url=preview,
                            description=f"ElevenLabs {name} ({gender})",
                            is_default=(v_id == self.default_voice_id),
                        )
                    )

            self._cached_voices = voices
            return voices
        except Exception as e:
            logger.warning(f"Не вдалося отримати голоси ElevenLabs: {e}")
            return []

    def synthesize(self, text: str, voice_id: str | None = None, **kwargs) -> TTSResult:
        """
        Синтезує аудіо через POST /v1/text-to-speech/{voice_id}.
        Повертає безпосередньо бінарні MP3-дані (audio/mpeg).
        """
        if not text:
            raise TTSError("Порожній текст для синтезу ElevenLabs")

        if not self.is_configured():
            raise TTSAuthError("ELEVENLABS_API_KEY не налаштовано у середовищі сервера")

        chosen_voice = voice_id or self.default_voice_id
        if not chosen_voice:
            # Якщо голос не задано, шукаємо перший доступний
            avail = self.get_available_voices()
            if avail:
                chosen_voice = avail[0].voice_id
            else:
                raise TTSVoiceNotFoundError(
                    "ElevenLabs voice_id не вказано в конфігурації і не знайдено серед доступних голосів акаунта."
                )

        url = f"{self.base_url}/v1/text-to-speech/{chosen_voice}"
        params = {"output_format": kwargs.get("output_format", "mp3_44100_128")}
        headers = self._get_headers()

        payload = {
            "text": text,
            "model_id": kwargs.get("model", self.model),
            "voice_settings": kwargs.get(
                "voice_settings",
                {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "use_speaker_boost": True,
                },
            ),
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    params=params,
                    timeout=self.timeout,
                )

                # Автентифікація
                if resp.status_code in (401, 403):
                    raise TTSAuthError(f"Помилка автентифікації ElevenLabs API ({resp.status_code})")

                # Rate Limit (429)
                if resp.status_code == 429:
                    if attempt < self.max_retries:
                        backoff = 1.0 * (2 ** attempt)
                        logger.warning(f"ElevenLabs 429 Rate Limit. Пауза {backoff:.1f}с перед спробою {attempt + 1}")
                        time.sleep(backoff)
                        continue
                    raise TTSRateLimitError("Перевищено ліміт частоти запитів ElevenLabs (429 Too Many Requests)")

                # Server Error (5xx)
                if resp.status_code >= 500:
                    if attempt < self.max_retries:
                        backoff = 1.0 * (2 ** attempt)
                        logger.warning(f"ElevenLabs Server Error {resp.status_code}. Спроба {attempt + 1}")
                        time.sleep(backoff)
                        continue
                    raise TTSServerError(f"Помилка сервера ElevenLabs ({resp.status_code}): {resp.text[:200]}")

                if resp.status_code != 200:
                    raise TTSError(f"ElevenLabs API повернув статус {resp.status_code}: {resp.text[:200]}")

                audio_bytes = resp.content
                if not audio_bytes:
                    raise TTSMalformedResponseError("ElevenLabs повернув порожній аудіопотік")

                return TTSResult(
                    audio_bytes=audio_bytes,
                    content_type="audio/mpeg",
                    provider="elevenlabs",
                    voice_id=chosen_voice,
                    cached=False,
                    fallback_used=False,
                )

            except requests.exceptions.Timeout:
                last_error = TTSTimeoutError(f"Вичерпано таймаут ElevenLabs TTS ({self.timeout}с)")
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise last_error
            except requests.exceptions.RequestException as e:
                last_error = TTSError(f"Мережева помилка зв'язку з ElevenLabs: {e}")
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise last_error

        raise last_error or TTSError("Невідома помилка під час виконання запиту до ElevenLabs")
