"""
Smart Garage - Centralized TTS Manager & Fallback Orchestrator
--------------------------------------------------------------
Керує життєвим циклом синтезу мовлення:
- Адаптери провайдерів: Edge TTS, HeyGen Voice Turbo, ElevenLabs Flash/Turbo.
- Ланцюг fallback: Основний провайдер -> Резервний локальний (Edge TTS) -> Сигнал браузеру.
- Нормалізація українського тексту (числа, одиниці виміру, контроль довжини).
- Короткоживучий TTL-кеш аудіофайлів.
- Відтворення на хостовому PipeWire / Bluetooth аудіовиході.
"""

import os
import logging
import threading
import subprocess
from typing import Dict, List, Optional, Any
from pathlib import Path

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
)
from server.tts.normalizer import normalize_ukrainian_text
from server.tts.cache import TTSAudioCache, DEFAULT_CACHE_DIR
from server.tts.edge_provider import EdgeTTSProvider
from server.tts.heygen_provider import HeyGenTTSProvider
from server.tts.elevenlabs_provider import ElevenLabsTTSProvider
from server.config import config

logger = logging.getLogger("TTSManager")


class TTSManager:
    """Центральний координатор синтезу мовлення в системі Smart Garage."""

    def __init__(
        self,
        active_provider: Optional[str] = None,
        fallback_provider: Optional[str] = None,
        active_voice_id: Optional[str] = None,
        max_text_length: Optional[int] = None,
        cache_ttl_seconds: Optional[int] = None,
        max_cache_items: Optional[int] = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        tts_cfg = config.get("tts", {})
        self.enabled = tts_cfg.get("enabled", True) if enabled is None else enabled
        self.active_provider_name = (active_provider or tts_cfg.get("provider", "edge")).lower().strip()
        self.fallback_provider_name = (fallback_provider or tts_cfg.get("fallback_provider", "edge")).lower().strip()
        self.active_voice_id = active_voice_id or tts_cfg.get("voice_id", "uk-UA-PolinaNeural")
        self.max_text_length = int(max_text_length or tts_cfg.get("max_text_length", 500))
        self.timeout = float(timeout or tts_cfg.get("timeout_seconds", 10.0))
        self.max_retries = int(max_retries or tts_cfg.get("max_retries", 2))

        ttl = int(cache_ttl_seconds or tts_cfg.get("cache_ttl_seconds", 3600))
        max_items = int(max_cache_items or tts_cfg.get("max_cache_items", 100))

        self.cache = TTSAudioCache(
            cache_dir=cache_dir,
            ttl_seconds=ttl,
            max_items=max_items,
        )

        self._providers: Dict[str, TTSProvider] = {}
        self._init_providers()

    def _init_providers(self):
        """Ініціалізує доступні провайдери з конфігурації та безпечного оточення."""
        # 1. Edge TTS (завжди доступний локальний / хмарний безкоштовний сервіс)
        edge_voice = self.active_voice_id if self.active_provider_name == "edge" else "uk-UA-PolinaNeural"
        self._providers["edge"] = EdgeTTSProvider(
            default_voice_id=edge_voice or "uk-UA-PolinaNeural",
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

        # 2. HeyGen Voice Turbo
        heygen_key = os.environ.get("HEYGEN_API_KEY", "").strip()
        heygen_voice = self.active_voice_id if self.active_provider_name == "heygen" else None
        self._providers["heygen"] = HeyGenTTSProvider(
            api_key=heygen_key,
            default_voice_id=heygen_voice,
            timeout=self.timeout + 2.0,  # трохи більший таймаут для генерації WAV
            max_retries=self.max_retries,
        )

        # 3. ElevenLabs Flash/Turbo
        eleven_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        eleven_voice = self.active_voice_id if self.active_provider_name == "elevenlabs" else None
        self._providers["elevenlabs"] = ElevenLabsTTSProvider(
            api_key=eleven_key,
            model="eleven_flash_v2_5",
            default_voice_id=eleven_voice,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    def register_provider(self, name: str, provider: TTSProvider) -> None:
        """Реєструє або підміняє провайдер (корисно для тестів/моків)."""
        self._providers[name.lower()] = provider

    def get_provider(self, name: str) -> Optional[TTSProvider]:
        return self._providers.get(name.lower())

    def get_providers_status(self) -> Dict[str, Any]:
        """Повертає статус конфігурації провайдерів без розкриття секретних ключів."""
        status = {
            "active_provider": self.active_provider_name,
            "fallback_provider": self.fallback_provider_name,
            "active_voice_id": self.active_voice_id,
            "max_text_length": self.max_text_length,
            "providers": {},
        }
        for name, prov in self._providers.items():
            status["providers"][name] = {
                "name": name,
                "configured": prov.is_configured(),
                "available_voices_count": len(prov.get_available_voices()),
            }
        return status

    def synthesize(
        self,
        text: str,
        provider_name: Optional[str] = None,
        voice_id: Optional[str] = None,
        use_cache: bool = True,
        **kwargs,
    ) -> TTSResult:
        """
        Головна точка входу для синтезу аудіо:
        1. Нормалізація українського тексту (числа, одиниці, ліміт довжини).
        2. Перевірка кешу.
        3. Спроба синтезу через вибраний/основний провайдер.
        4. У разі помилки — автоматичний fallback на резервний провайдер.
        5. Збереження результату в кеш.
        """
        if not self.enabled:
            raise TTSError("Синтез мовлення вимкнено в налаштуваннях")

        if not text or not text.strip():
            raise TTSError("Порожній текст для синтезу мовлення")

        clean_text = normalize_ukrainian_text(text, max_length=self.max_text_length)
        if not clean_text:
            raise TTSError("Порожній текст після нормалізації")

        chosen_prov_name = (provider_name or self.active_provider_name).lower()
        primary_provider = self.get_provider(chosen_prov_name)
        if not primary_provider:
            logger.warning(f"Провайдер '{chosen_prov_name}' не знайдено, переходимо на '{self.fallback_provider_name}'")
            primary_provider = self.get_provider(self.fallback_provider_name)
            chosen_prov_name = self.fallback_provider_name

        chosen_voice = voice_id or self.active_voice_id

        # Перевірка кешу
        content_type = "audio/wav" if chosen_prov_name == "heygen" else "audio/mpeg"
        if use_cache:
            cached_bytes = self.cache.get(chosen_prov_name, chosen_voice or "default", clean_text, content_type)
            if cached_bytes:
                return TTSResult(
                    audio_bytes=cached_bytes,
                    content_type=content_type,
                    provider=chosen_prov_name,
                    voice_id=chosen_voice or "default",
                    cached=True,
                    fallback_used=False,
                )

        # Спроба синтезу через основний провайдер
        primary_error: Optional[Exception] = None
        if primary_provider and primary_provider.is_configured():
            try:
                res = primary_provider.synthesize(clean_text, voice_id=chosen_voice, **kwargs)
                if use_cache and res.audio_bytes:
                    self.cache.put(chosen_prov_name, res.voice_id, clean_text, res.audio_bytes, res.content_type)
                return res
            except Exception as e:
                primary_error = e
                logger.warning(
                    f"Основний TTS провайдер '{chosen_prov_name}' зазнав помилки ({type(e).__name__}: {e}). "
                    f"Запускаємо резервний fallback на '{self.fallback_provider_name}'."
                )
        else:
            primary_error = TTSAuthError(f"Провайдер '{chosen_prov_name}' не сконфігурований (відсутній API-ключ)")
            logger.info(f"Провайдер '{chosen_prov_name}' не налаштований. Використовуємо fallback '{self.fallback_provider_name}'.")

        # Fallback на резервний провайдер
        fallback_prov = self.get_provider(self.fallback_provider_name)
        if fallback_prov and fallback_prov.name != chosen_prov_name and fallback_prov.is_configured():
            try:
                fb_voice = "uk-UA-PolinaNeural" if fallback_prov.name == "edge" else None
                res = fallback_prov.synthesize(clean_text, voice_id=fb_voice, **kwargs)
                res.fallback_used = True
                res.fallback_reason = str(primary_error)
                if use_cache and res.audio_bytes:
                    self.cache.put(fallback_prov.name, res.voice_id, clean_text, res.audio_bytes, res.content_type)
                return res
            except Exception as fb_err:
                logger.error(f"Резервний TTS провайдер '{self.fallback_provider_name}' також зазнав помилки: {fb_err}")
                raise TTSError(
                    f"Синтез мовлення не вдався. Основний: {primary_error}; Резервний: {fb_err}"
                )

        # Якщо fallback не вдалося виконати
        raise TTSError(f"Помилка синтезу мовлення: {primary_error}")

    def speak_locally(self, text: str, voice_id: Optional[str] = None):
        """Асинхронно синтезує та відтворює звук на хостовому PipeWire / Bluetooth аудіовиході."""
        def _worker():
            try:
                res = self.synthesize(text, voice_id=voice_id)
                if not res.audio_bytes:
                    return

                # Зберігаємо у тимчасовий файл для системного програвача
                ext = ".wav" if "wav" in res.content_type else ".mp3"
                tmp_file = self.cache.cache_dir / f"local_playback{ext}"
                tmp_file.write_bytes(res.audio_bytes)

                # 1. Програвач PipeWire (pw-play)
                p1 = subprocess.run(["pw-play", str(tmp_file)], capture_output=True, timeout=20)
                if p1.returncode == 0:
                    return

                # 2. GStreamer play
                p2 = subprocess.run(["gst-play-1.0", "--no-interactive", str(tmp_file)], capture_output=True, timeout=20)
                if p2.returncode == 0:
                    return
            except Exception as e:
                logger.warning(f"Помилка локального відтворення TTS: {e}")

            # 3. Аварійний резерв spd-say
            try:
                clean = normalize_ukrainian_text(text, max_length=self.max_text_length)
                subprocess.run(["spd-say", "-l", "uk", "-r", "0", clean], timeout=15)
            except Exception as ex:
                logger.error(f"Fallback spd-say зазнав невдачі: {ex}")

        threading.Thread(target=_worker, daemon=True).start()


# Глобальний екземпляр TTSManager
tts_manager = TTSManager()
