"""
Smart Garage - HeyGen Voice Turbo REST TTS Provider Adapter
------------------------------------------------------------
Адаптер для HeyGen Voice Turbo REST TTS (POST /v3/models/audio/tts).
Офіційно підтримує українську мову (uk).
Зауваження щодо лімітів та надійності:
- Turbo Free має спільну обмежену потужність і не гарантує SLA/час відповіді.
- Безоплатна пропозиція Turbo Free діє до 30 листопада 2026 року.
- HEYGEN_API_KEY зберігається виключно на сервері.
- Заборонено створення клонів голосу або завантаження аудіо користувача без окремого дозволу.
- Список голосів отримується динамічно через GET /v3/voices; фіктивні voice_id не вигадуються.
"""

import time
import logging
from typing import List, Optional, Dict, Any
import requests

from server.tts.base import (
    TTSProvider,
    TTSResult,
    TTSVoiceInfo,
    TTSError,
    TTSAuthError,
    TTSRateLimitError,
    TTSServerError,
    TTSTimeoutError,
    TTSVoiceNotFoundError,
    TTSMalformedResponseError,
)

logger = logging.getLogger("HeyGenTTSProvider")

HEYGEN_API_BASE = "https://api.heygen.com"


class HeyGenTTSProvider(TTSProvider):
    """Адаптер для сервісу HeyGen Voice Turbo."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "heygen-voice-1-turbo-free",
        default_voice_id: Optional[str] = None,
        timeout: float = 12.0,
        max_retries: int = 2,
        base_url: str = HEYGEN_API_BASE,
    ):
        super().__init__(name="heygen", timeout=timeout, max_retries=max_retries)
        self.api_key = (api_key or "").strip()
        self.model = model or "heygen-voice-1-turbo-free"
        self.default_voice_id = (default_voice_id or "").strip()
        self.base_url = base_url.rstrip("/")
        self._cached_voices: Optional[List[TTSVoiceInfo]] = None

    def is_configured(self) -> bool:
        """Перевіряє, чи задано API-ключ на сервері."""
        return bool(self.api_key)

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise TTSAuthError("Відсутній HEYGEN_API_KEY на сервері. Синтез через HeyGen неможливий.")
        return {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_available_voices(self) -> List[TTSVoiceInfo]:
        """
        Отримує актуальний перелік доступних публічних українських голосів з HeyGen API.
        Не хардкодить вигадані ID.
        """
        if not self.is_configured():
            logger.info("HEYGEN_API_KEY не налаштовано; отримання списку голосів неможливе.")
            return []

        if self._cached_voices is not None:
            return self._cached_voices

        url = f"{self.base_url}/v3/voices"
        params = {"language": "Ukrainian", "type": "public"}

        try:
            resp = requests.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=self.timeout
            )
            if resp.status_code == 401 or resp.status_code == 403:
                raise TTSAuthError("Недійсний HEYGEN_API_KEY при запиті списку голосів.")
            if resp.status_code != 200:
                logger.warning(f"HeyGen /v3/voices повернув статус {resp.status_code}: {resp.text}")
                return []

            data = resp.json().get("data", [])
            voices: List[TTSVoiceInfo] = []
            for item in data:
                v_id = item.get("voice_id") or item.get("id")
                name = item.get("name", "HeyGen Voice")
                lang = item.get("language", "Ukrainian")
                gender = item.get("gender", "unknown")
                preview = item.get("preview_audio_url")
                if v_id:
                    voices.append(
                        TTSVoiceInfo(
                            voice_id=v_id,
                            name=name,
                            language=lang,
                            gender=gender,
                            preview_url=preview,
                            description=f"HeyGen Voice ({gender})",
                            is_default=(v_id == self.default_voice_id),
                        )
                    )

            self._cached_voices = voices
            return voices
        except Exception as e:
            logger.warning(f"Не вдалося отримати голоси HeyGen: {e}")
            return []

    def synthesize(self, text: str, voice_id: Optional[str] = None, **kwargs) -> TTSResult:
        """
        Виконує REST TTS запит до POST /v3/models/audio/tts та завантажує готовий WAV.
        Підтримує обмежені повтори з експоненційним backoff для 429 та 5xx.
        """
        if not text:
            raise TTSError("Порожній текст для синтезу HeyGen")

        if not self.is_configured():
            raise TTSAuthError("HEYGEN_API_KEY не налаштовано у середовищі сервера")

        chosen_voice = voice_id or self.default_voice_id
        if not chosen_voice:
            # Спробуємо отримати перший доступний український голос
            avail = self.get_available_voices()
            if avail:
                chosen_voice = avail[0].voice_id
            else:
                raise TTSVoiceNotFoundError(
                    "HeyGen voice_id не вказано в конфігурації і не знайдено серед доступних голосів акаунта."
                )

        payload = {
            "voice_id": chosen_voice,
            "text": text,
            "model": kwargs.get("model", self.model),
        }

        url = f"{self.base_url}/v3/models/audio/tts"
        headers = self._get_headers()

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)

                # Автентифікація
                if resp.status_code in (401, 403):
                    raise TTSAuthError(f"Помилка автентифікації HeyGen API ({resp.status_code})")

                # Rate Limit (429)
                if resp.status_code == 429:
                    if attempt < self.max_retries:
                        backoff = 1.0 * (2 ** attempt)
                        logger.warning(f"HeyGen 429 Rate Limit. Пауза {backoff:.1f}с перед спробою {attempt + 1}")
                        time.sleep(backoff)
                        continue
                    raise TTSRateLimitError("Перевищено ліміт частоти запитів HeyGen (429 Too Many Requests)")

                # Server Errors (5xx)
                if resp.status_code >= 500:
                    if attempt < self.max_retries:
                        backoff = 1.0 * (2 ** attempt)
                        logger.warning(f"HeyGen Server Error {resp.status_code}. Спроба {attempt + 1}")
                        time.sleep(backoff)
                        continue
                    raise TTSServerError(f"Помилка сервера HeyGen ({resp.status_code}): {resp.text[:200]}")

                if resp.status_code != 200:
                    raise TTSError(f"HeyGen API повернув статус {resp.status_code}: {resp.text[:200]}")

                # Парсинг успішної відповіді
                data = resp.json().get("data", {})
                audio_url = data.get("audio_url")
                duration = data.get("duration")

                if not audio_url:
                    raise TTSMalformedResponseError("HeyGen відповідь не містить audio_url")

                # Завантаження готового аудіофайлу (WAV)
                audio_resp = requests.get(audio_url, timeout=self.timeout)
                if audio_resp.status_code != 200 or not audio_resp.content:
                    raise TTSMalformedResponseError(f"Не вдалося завантажити аудіофайл за адресою {audio_url}")

                return TTSResult(
                    audio_bytes=audio_resp.content,
                    content_type="audio/wav",
                    provider="heygen",
                    voice_id=chosen_voice,
                    cached=False,
                    fallback_used=False,
                    duration_seconds=float(duration) if duration else None,
                )

            except requests.exceptions.Timeout:
                last_error = TTSTimeoutError(f"Вичерпано таймаут HeyGen TTS ({self.timeout}с)")
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise last_error
            except requests.exceptions.RequestException as e:
                last_error = TTSError(f"Мережева помилка зв'язку з HeyGen: {e}")
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise last_error

        raise last_error or TTSError("Невідома помилка під час виконання запиту до HeyGen")
