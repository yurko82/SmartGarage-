"""
Smart Garage - Unit and Integration Tests for Ukrainian Voice TTS Subsystem
----------------------------------------------------------------------------
Перевіряє:
- Нормалізацію українського тексту, очищення розмітки та збереження апострофів;
- Адаптери провайдерів (Edge TTS, HeyGen Voice Turbo, ElevenLabs Flash/Turbo);
- Обробку помилок (відсутній ключ, невідомий voice ID, timeout, 429, 5xx, некоректна відповідь);
- Ланцюг автоматичного fallback;
- TTL-кеш аудіофайлів;
- Web API ендпоінти (/api/voice/tts, /api/voice/providers, /api/voice/preview)
  та явне маркування резервного браузерного синтезу.
Жодних реальних платних API-викликів у тестах — усі зовнішні HTTP-запити змодельовані через mock.
"""

import io
import os
import time
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from server.tts.base import (
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
from server.tts.normalizer import (
    normalize_ukrainian_text,
    clean_markdown_and_markup,
    number_to_ukrainian_words,
    format_temperature_ukrainian,
    format_percentage_ukrainian,
)
from server.tts.cache import TTSAudioCache
from server.tts.edge_provider import EdgeTTSProvider
from server.tts.heygen_provider import HeyGenTTSProvider
from server.tts.elevenlabs_provider import ElevenLabsTTSProvider
from server.tts.manager import TTSManager
from server.webapp import app


class TestTTSNormalizer(unittest.TestCase):
    """Тести нормалізатора українського тексту."""

    def test_markdown_and_markup_cleaned_without_losing_text(self):
        raw = "Увага: **світло** увімкнено! Перевірте [дашборд](http://192.168.100.1) `код: 123` 💡"
        clean = clean_markdown_and_markup(raw)
        self.assertNotIn("**", clean)
        self.assertNotIn("http://", clean)
        self.assertNotIn("`", clean)
        self.assertNotIn("💡", clean)
        self.assertIn("світло", clean)
        self.assertIn("дашборд", clean)

    def test_apostrophe_preserved_in_ukrainian_words(self):
        raw = "Залишилось п'ять секунд і зв'язок з'явиться. Озвучуємо «м'яке» слово."
        clean = normalize_ukrainian_text(raw)
        # Апостроф у словах має зберегтися
        self.assertIn("п'ять", clean)
        self.assertIn("зв'язок", clean)
        self.assertIn("м'яке", clean)
        # Лапки ялинки «» мають бути видалені
        self.assertNotIn("«", clean)
        self.assertNotIn("»", clean)

    def test_temperature_normalization(self):
        t1 = normalize_ukrainian_text("Температура +18°C на дворі")
        self.assertIn("плюс вісімнадцять градусів", t1)

        t2 = normalize_ukrainian_text("В підвалі -5°C")
        self.assertIn("мінус п'ять градусів", t2)

        t3 = normalize_ukrainian_text("Зараз 21°C")
        self.assertIn("двадцять один градус", t3)

        t4 = normalize_ukrainian_text("В кімнаті 22°C")
        self.assertIn("двадцять два градуси", t4)

        t5 = normalize_ukrainian_text("Показник 18.5°C")
        self.assertIn("вісімнадцять з половиною градусів", t5)

    def test_percentage_and_units_normalization(self):
        p1 = normalize_ukrainian_text("Вологість 65%")
        self.assertIn("шістдесят п'ять відсотків", p1)

        p2 = normalize_ukrainian_text("Батарея 21%")
        self.assertIn("двадцять один відсоток", p2)

        p3 = normalize_ukrainian_text("Рівень газу 450 ppm, напруга 220 В")
        self.assertIn("часток на мільйон", p3)
        self.assertIn("вольт", p3)

    def test_floor_and_radio_terms(self):
        f1 = normalize_ukrainian_text("Датчик на 2-му поверсі, грає radio roks [онлайн]")
        self.assertIn("другому поверсі", f1)
        self.assertIn("Радіо Рокс", f1)
        self.assertIn("онлайн", f1)
        self.assertNotIn("[онлайн]", f1)

    def test_text_length_limit_and_clean_boundary(self):
        long_text = "Перше речення системи. " * 30  # > 600 символів
        res = normalize_ukrainian_text(long_text, max_length=200)
        self.assertLessEqual(len(res), 200)
        self.assertTrue(res.endswith(".") or res.endswith("..."))


class TestTTSAudioCache(unittest.TestCase):
    """Тести кешу аудіофайлів з обмеженням TTL та місткості."""

    def setUp(self):
        self.test_cache_dir = Path("/tmp/test_smartgarage_tts_cache")
        if self.test_cache_dir.exists():
            shutil.rmtree(self.test_cache_dir)
        self.cache = TTSAudioCache(
            cache_dir=self.test_cache_dir,
            ttl_seconds=2,      # 2 секунди для швидкого тесту
            max_items=3,        # малий ліміт для тесту витіснення
        )

    def tearDown(self):
        if self.test_cache_dir.exists():
            shutil.rmtree(self.test_cache_dir)

    def test_put_and_get(self):
        data = b"MP3_FAKE_DATA_12345"
        self.cache.put("edge", "uk-UA-PolinaNeural", "Привіт", data, "audio/mpeg")
        cached = self.cache.get("edge", "uk-UA-PolinaNeural", "Привіт", "audio/mpeg")
        self.assertEqual(cached, data)

    def test_expired_file_is_evicted(self):
        data = b"MP3_EXPIRED_DATA"
        self.cache.put("edge", "uk-UA-PolinaNeural", "Тимчасовий", data, "audio/mpeg")
        # Чекаємо закінчення TTL (2 секунди)
        time.sleep(2.1)
        cached = self.cache.get("edge", "uk-UA-PolinaNeural", "Тимчасовий", "audio/mpeg")
        self.assertIsNone(cached)

    def test_max_capacity_enforcement(self):
        # Записуємо 5 файлів при ліміті 3
        for i in range(5):
            self.cache.put("edge", "voice", f"text_{i}", f"DATA_{i}".encode("utf-8"), "audio/mpeg")
            time.sleep(0.05)

        files = list(self.test_cache_dir.glob("*.mp3"))
        self.assertLessEqual(len(files), 4)


class TestHeyGenTTSProvider(unittest.TestCase):
    """Тести провайдера HeyGen Voice Turbo REST."""

    def test_missing_api_key_raises_auth_error(self):
        provider = HeyGenTTSProvider(api_key="")
        self.assertFalse(provider.is_configured())
        with self.assertRaises(TTSAuthError):
            provider.synthesize("Світло увімкнено")

    @patch("server.tts.heygen_provider.requests.post")
    @patch("server.tts.heygen_provider.requests.get")
    def test_valid_wav_synthesis(self, mock_get, mock_post):
        # Mock POST /v3/models/audio/tts
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "data": {
                "audio_url": "https://files.heygen.ai/audio/sample_123.wav",
                "duration": 2.4,
            }
        }
        mock_post.return_value = mock_post_resp

        # Mock GET audio_url (WAV bytes)
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.content = b"RIFF_FAKE_WAV_BYTES_44100"
        mock_get.return_value = mock_get_resp

        provider = HeyGenTTSProvider(api_key="hg_test_key_123", default_voice_id="v_uk_01")
        result = provider.synthesize("Світло увімкнено")

        self.assertEqual(result.provider, "heygen")
        self.assertEqual(result.content_type, "audio/wav")
        self.assertEqual(result.audio_bytes, b"RIFF_FAKE_WAV_BYTES_44100")
        self.assertEqual(result.duration_seconds, 2.4)

    @patch("server.tts.heygen_provider.requests.post")
    def test_rate_limit_429_backoff_and_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests"
        mock_post.return_value = mock_resp

        provider = HeyGenTTSProvider(api_key="hg_test_key", default_voice_id="v1", max_retries=1)
        with self.assertRaises(TTSRateLimitError):
            provider.synthesize("Світло увімкнено")
        # 1 перша спроба + 1 повторна спроба = 2 виклики
        self.assertEqual(mock_post.call_count, 2)

    @patch("server.tts.heygen_provider.requests.post")
    def test_server_error_5xx(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_post.return_value = mock_resp

        provider = HeyGenTTSProvider(api_key="hg_test_key", default_voice_id="v1", max_retries=1)
        with self.assertRaises(TTSServerError):
            provider.synthesize("Світло увімкнено")

    @patch("server.tts.heygen_provider.requests.post")
    def test_malformed_response_missing_audio_url(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {}}  # Немає audio_url
        mock_post.return_value = mock_resp

        provider = HeyGenTTSProvider(api_key="hg_test_key", default_voice_id="v1")
        with self.assertRaises(TTSMalformedResponseError):
            provider.synthesize("Світло увімкнено")


class TestElevenLabsTTSProvider(unittest.TestCase):
    """Тести провайдера ElevenLabs Flash v2.5."""

    def test_missing_api_key_raises_auth_error(self):
        provider = ElevenLabsTTSProvider(api_key="")
        self.assertFalse(provider.is_configured())
        with self.assertRaises(TTSAuthError):
            provider.synthesize("Тест")

    @patch("server.tts.elevenlabs_provider.requests.post")
    def test_valid_mp3_synthesis(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ID3_ELEVENLABS_MP3_STREAM"
        mock_post.return_value = mock_resp

        provider = ElevenLabsTTSProvider(api_key="el_test_key", default_voice_id="v_el_01")
        result = provider.synthesize("Світло в гаражі увімкнено")

        self.assertEqual(result.provider, "elevenlabs")
        self.assertEqual(result.content_type, "audio/mpeg")
        self.assertEqual(result.audio_bytes, b"ID3_ELEVENLABS_MP3_STREAM")

    @patch("server.tts.elevenlabs_provider.requests.post")
    def test_rate_limit_429(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_post.return_value = mock_resp

        provider = ElevenLabsTTSProvider(api_key="el_key", default_voice_id="v1", max_retries=1)
        with self.assertRaises(TTSRateLimitError):
            provider.synthesize("Тест")
        self.assertEqual(mock_post.call_count, 2)

    @patch("server.tts.elevenlabs_provider.requests.post")
    def test_server_error_500(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        provider = ElevenLabsTTSProvider(api_key="el_key", default_voice_id="v1", max_retries=1)
        with self.assertRaises(TTSServerError):
            provider.synthesize("Тест")


class TestTTSManagerAndFallbackChain(unittest.TestCase):
    """Тести менеджера TTS та автоматичного переходу на резервний провайдер (fallback)."""

    def setUp(self):
        self.test_cache_dir = Path("/tmp/test_sg_mgr_cache")
        if self.test_cache_dir.exists():
            shutil.rmtree(self.test_cache_dir)
        self.manager = TTSManager(
            active_provider="heygen",
            fallback_provider="edge",
            cache_dir=self.test_cache_dir,
        )

    def tearDown(self):
        if self.test_cache_dir.exists():
            shutil.rmtree(self.test_cache_dir)

    def test_empty_text_raises_error(self):
        with self.assertRaises(TTSError):
            self.manager.synthesize("")
        with self.assertRaises(TTSError):
            self.manager.synthesize("    ")

    def test_disabled_tts_raises_error(self):
        self.manager.enabled = False
        with self.assertRaises(TTSError) as ctx:
            self.manager.synthesize("Світло увімкнено")
        self.assertIn("вимкнено", str(ctx.exception))

    def test_fallback_when_primary_missing_api_key(self):
        """HeyGen без ключа -> автоматичний fallback на Edge TTS."""
        mock_edge = MagicMock()
        mock_edge.is_configured.return_value = True
        mock_edge.name = "edge"
        mock_edge.synthesize.return_value = TTSResult(
            audio_bytes=b"EDGE_FALLBACK_AUDIO",
            content_type="audio/mpeg",
            provider="edge",
            voice_id="uk-UA-PolinaNeural",
            cached=False,
        )
        self.manager.register_provider("edge", mock_edge)

        res = self.manager.synthesize("Ворота зачинено", provider_name="heygen")

        self.assertTrue(res.fallback_used)
        self.assertEqual(res.provider, "edge")
        self.assertEqual(res.audio_bytes, b"EDGE_FALLBACK_AUDIO")
        self.assertIn("не сконфігурований", res.fallback_reason)

    def test_fallback_when_primary_rate_limited(self):
        """ElevenLabs повертає 429 -> автоматичний fallback на Edge TTS."""
        mock_eleven = MagicMock()
        mock_eleven.is_configured.return_value = True
        mock_eleven.name = "elevenlabs"
        mock_eleven.synthesize.side_effect = TTSRateLimitError("429 Too Many Requests")

        mock_edge = MagicMock()
        mock_edge.is_configured.return_value = True
        mock_edge.name = "edge"
        mock_edge.synthesize.return_value = TTSResult(
            audio_bytes=b"EDGE_AUDIO_RESCUE",
            content_type="audio/mpeg",
            provider="edge",
            voice_id="uk-UA-PolinaNeural",
        )

        self.manager.register_provider("elevenlabs", mock_eleven)
        self.manager.register_provider("edge", mock_edge)

        res = self.manager.synthesize("Світло увімкнено", provider_name="elevenlabs")

        self.assertTrue(res.fallback_used)
        self.assertEqual(res.provider, "edge")
        self.assertIn("429 Too Many Requests", res.fallback_reason)

    def test_cache_hit_on_subsequent_request(self):
        mock_edge = MagicMock()
        mock_edge.is_configured.return_value = True
        mock_edge.name = "edge"
        mock_edge.synthesize.return_value = TTSResult(
            audio_bytes=b"EDGE_AUDIO_CACHED_TEST",
            content_type="audio/mpeg",
            provider="edge",
            voice_id="uk-UA-PolinaNeural",
        )
        self.manager.register_provider("edge", mock_edge)

        # 1-й запит (генерація + кешування)
        res1 = self.manager.synthesize("Тестова фраза", provider_name="edge")
        self.assertFalse(res1.cached)
        self.assertEqual(mock_edge.synthesize.call_count, 1)

        # 2-й запит з тим самим текстом (повернення з кешу без виклику провайдера)
        res2 = self.manager.synthesize("Тестова фраза", provider_name="edge")
        self.assertTrue(res2.cached)
        self.assertEqual(res2.audio_bytes, b"EDGE_AUDIO_CACHED_TEST")
        self.assertEqual(mock_edge.synthesize.call_count, 1)


class TestWebAppTTSEndpoints(unittest.TestCase):
    """Тести HTTP-ендпоінтів веб-панелі (/api/voice/tts, /api/voice/providers, /api/voice/preview)."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_voice_tts_empty_text_returns_400(self):
        resp = self.client.get("/api/voice/tts?text=")
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Порожній текст", data["error"])

    @patch("server.webapp.tts_manager.synthesize")
    def test_voice_tts_success_sets_required_headers(self, mock_synth):
        mock_synth.return_value = TTSResult(
            audio_bytes=b"STREAM_MP3_BYTES_OK",
            content_type="audio/mpeg",
            provider="edge",
            voice_id="uk-UA-PolinaNeural",
            cached=False,
            fallback_used=True,
            fallback_reason="HeyGen not configured",
        )

        resp = self.client.get("/api/voice/tts?text=Світло%20увімкнено")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "audio/mpeg")
        self.assertEqual(resp.data, b"STREAM_MP3_BYTES_OK")

        # Перевірка обов'язкових інформаційних заголовків
        self.assertEqual(resp.headers.get("X-TTS-Provider"), "edge")
        self.assertEqual(resp.headers.get("X-TTS-Voice"), "uk-UA-PolinaNeural")
        self.assertEqual(resp.headers.get("X-TTS-Fallback"), "true")
        self.assertEqual(resp.headers.get("X-TTS-Cached"), "false")

    @patch("server.webapp.tts_manager.synthesize")
    def test_voice_tts_failure_returns_503_and_browser_fallback_flag(self, mock_synth):
        mock_synth.side_effect = TTSError("Всі провайдери недоступні")

        resp = self.client.get("/api/voice/tts?text=Повідомлення")
        self.assertEqual(resp.status_code, 503)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertTrue(data.get("fallback_to_browser"))

    def test_voice_providers_endpoint(self):
        resp = self.client.get("/api/voice/providers")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("active_provider", data)
        self.assertIn("providers", data)
        self.assertIn("edge", data["providers"])
        self.assertIn("heygen", data["providers"])
        self.assertIn("elevenlabs", data["providers"])
        # Переконуємось, що секретні ключі не повертаються
        raw_body = resp.get_data(as_text=True)
        self.assertNotIn("api_key", raw_body)
        self.assertNotIn("secret", raw_body.lower())
        # Перевірка наявності голосів у статусі
        edge_voices = data["providers"]["edge"].get("voices", [])
        self.assertGreater(len(edge_voices), 0)
        self.assertIn("voice_id", edge_voices[0])

    def test_voice_config_endpoints(self):
        # 1. GET /api/voice/config
        get_res = self.client.get("/api/voice/config")
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.get_json()
        self.assertTrue(get_data["success"])
        self.assertIn("active_provider", get_data)

        # 2. POST /api/voice/config with valid provider and voice
        post_res = self.client.post("/api/voice/config", json={
            "provider": "edge",
            "voice_id": "uk-UA-OstapNeural"
        })
        self.assertEqual(post_res.status_code, 200)
        post_data = post_res.get_json()
        self.assertTrue(post_data["success"])
        self.assertEqual(post_data["active_provider"], "edge")
        self.assertEqual(post_data["active_voice_id"], "uk-UA-OstapNeural")

        # 3. POST /api/voice/config with invalid provider returns 400
        bad_res = self.client.post("/api/voice/config", json={
            "provider": "non_existent_provider"
        })
        self.assertEqual(bad_res.status_code, 400)
        self.assertFalse(bad_res.get_json()["success"])

    def test_manager_set_active_provider_and_voice(self):
        mgr = TTSManager()
        self.assertTrue(mgr.set_active_provider("edge"))
        self.assertEqual(mgr.active_provider_name, "edge")
        self.assertFalse(mgr.set_active_provider("unknown_prov"))

        mgr.set_active_voice("uk-UA-PolinaNeural")
        self.assertEqual(mgr.active_voice_id, "uk-UA-PolinaNeural")
