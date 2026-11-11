"""
server/voice/service.py — Сервіс локального голосового керування Smart Garage
Координує захоплення аудіо через PipeWire, детекцію Wake Word (OpenWakeWord),
розпізнавання мови (Faster-Whisper) та диспетчеризацію команд у ядро системи.
"""

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from server.voice.listener import WakeWordDetector
from server.voice.synthesizer import VoiceSynthesizer
from server.voice.transcriber import SpeechTranscriber

logger = logging.getLogger("VoiceService")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


class PipeWireAudioCapture:
    """
    Керує захопленням аудіо через PipeWire virtual source
    з автоматичним перепідключенням при збоях.
    """

    def __init__(
        self,
        virtual_source_name: str = "pipewire-virtual-source",
        sample_rate: int = 16000,
        chunk_size: int = 1280,
    ):
        self.virtual_source_name = virtual_source_name
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size  # 80ms при 16000Hz
        self.stream: Any = None
        self._sd = None
        self._ensure_pipewire_virtual_source()

    def _ensure_pipewire_virtual_source(self) -> bool:
        """Перевірка наявності віртуального джерела PipeWire або його створення."""
        try:
            res = subprocess.run(
                ["pactl", "list", "sources", "short"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            if self.virtual_source_name in res.stdout:
                logger.info(f"PipeWire віртуальне джерело '{self.virtual_source_name}' вже активне.")
                return True

            logger.info(f"Створення PipeWire віртуального джерела '{self.virtual_source_name}'...")
            master_source = None
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[1]
                    if ("input" in name or "mic" in name) and not name.endswith(".monitor"):
                        master_source = name
                        break

            cmd = [
                "pactl",
                "load-module",
                "module-remap-source",
                f"source_name={self.virtual_source_name}",
                "source_properties=device.description=PipeWire-Virtual-Source",
            ]
            if master_source:
                cmd.append(f"master={master_source}")
                logger.info(f"Мапування віртуального джерела на фізичний мікрофон: {master_source}")

            create_res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
            if create_res.returncode == 0:
                logger.info("Віртуальне джерело PipeWire успішно завантажено.")
                return True
            else:
                logger.warning(f"Не вдалося завантажити module-remap-source: {create_res.stderr.strip()}")
        except Exception as e:
            logger.warning(f"Попередження PipeWire: {e}. Використовуватиметься стандартне джерело.")
        return False

    def open_stream(self):
        """Відкриття аудіопотоку через sounddevice."""
        try:
            import sounddevice as sd

            self._sd = sd
        except ImportError:
            logger.error("Пакет sounddevice не знайдено.")
            raise

        os.environ["PULSE_SOURCE"] = self.virtual_source_name

        device_index = None
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            dname = dev.get("name", "").lower()
            if self.virtual_source_name.lower() in dname:
                device_index = idx
                logger.info(f"Знайдено віртуальне джерело (індекс {idx}): {dev.get('name')}")
                break

        self.stream = sd.InputStream(
            device=device_index,
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size,
        )
        self.stream.start()
        logger.info(f"Аудіопотік відкрито ({self.sample_rate}Hz, 16-bit PCM, chunk={self.chunk_size}).")

    def read_chunk(self) -> np.ndarray:
        """Зчитування одного чанку аудіо з потоку."""
        if not self.stream or not self.stream.active:
            raise OSError("Аудіопотік не активний.")
        data, overflowed = self.stream.read(self.chunk_size)
        if overflowed:
            logger.debug("Переповнення аудіобуфера (пропущено).")
        return data.flatten()

    def close(self):
        """Закриття аудіопотоку."""
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            logger.info("Аудіопотік зупинено.")


class VoiceService:
    """
    Головний сервіс голосової взаємодії.
    Координує прослуховування, розпізнавання Wake Word, запис команди та передачу в API.
    """

    def __init__(
        self,
        wake_word: str = "hey_jarvis",
        wake_word_threshold: float = 0.55,
        whisper_model: str = "base",
        whisper_lang: str = "uk",
        api_url: str = "http://127.0.0.1:5000/api/voice/command",
        max_record_sec: float = 8.0,
        silence_timeout_sec: float = 1.3,
        audio_capture: PipeWireAudioCapture | None = None,
        detector: WakeWordDetector | None = None,
        transcriber: SpeechTranscriber | None = None,
        synthesizer: VoiceSynthesizer | None = None,
    ):
        self.wake_word = wake_word
        self.wake_word_threshold = wake_word_threshold
        self.whisper_model_name = whisper_model
        self.whisper_lang = whisper_lang
        self.api_url = api_url
        self.max_record_sec = max_record_sec
        self.silence_timeout_sec = silence_timeout_sec

        self.running = False
        self.audio = audio_capture or PipeWireAudioCapture()
        self.detector = detector
        self.transcriber = transcriber
        self.synthesizer = synthesizer or VoiceSynthesizer()
        self.queue: Any = None

        # Черга голосових команд для ядра системи
        try:
            from server.services.voice_queue import voice_command_queue

            self.queue = voice_command_queue
        except ImportError:
            self.queue = None

        self._debounce_until = 0.0

    def init_engines(self):
        """Ініціалізація моделей штучного інтелекту."""
        if self.detector is None:
            self.detector = WakeWordDetector(
                model_name_or_path=self.wake_word,
                threshold=self.wake_word_threshold,
            )
        if self.transcriber is None:
            self.transcriber = SpeechTranscriber(
                model_size=self.whisper_model_name,
                language=self.whisper_lang,
                cpu_threads=1,
            )

    def record_speech_after_wakeword(self) -> np.ndarray:
        """
        Запис аудіо після детекції Wake Word до паузи у мовленні
        або досягнення max_record_sec.
        """
        logger.info("🎙️ Активаційне слово виявлено! Запис голосової команди...")
        recorded_chunks = []
        silence_start = None
        speech_started = False
        start_time = time.time()
        speech_energy_threshold = 220

        while time.time() - start_time < self.max_record_sec:
            try:
                chunk = self.audio.read_chunk()
                recorded_chunks.append(chunk)
                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

                if rms > speech_energy_threshold:
                    speech_started = True
                    silence_start = None
                else:
                    if speech_started:
                        if silence_start is None:
                            silence_start = time.time()
                        elif time.time() - silence_start >= self.silence_timeout_sec:
                            logger.info(f"Тиша після команди ({time.time() - silence_start:.2f}с). Завершення запису.")
                            break
                    else:
                        if time.time() - start_time > 2.5:
                            logger.info("Мовлення не зафіксовано після активації.")
                            break
            except Exception as e:
                logger.warning(f"Помилка зчитування аудіо: {e}")
                break

        if not recorded_chunks:
            return np.array([], dtype=np.float32)

        full_pcm = np.concatenate(recorded_chunks, axis=0)
        return full_pcm.astype(np.float32) / 32768.0

    # Зворотна сумісність імені методу
    _record_speech_after_wakeword = record_speech_after_wakeword

    async def dispatch_command(self, text: str) -> str | None:
        """Відправка розпізнаної команди в чергу та на HTTP API."""
        if not text:
            return None

        if self.queue:
            try:
                await self.queue.put(text=text, source="voice", priority=1)
            except Exception as e:
                logger.warning(f"Не вдалося додати в чергу: {e}")

        response_text = None
        try:
            import aiohttp

            admin_pin = os.getenv("ADMIN_PIN") or "7777"
            headers = {
                "X-Admin-PIN": admin_pin,
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as session:
                payload = {"command": text, "text": text, "source": "voice"}
                async with session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=6.0),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        response_text = data.get("response") or "Виконано"
                        logger.info(f"✅ Відповідь AI: «{response_text}»")
                    else:
                        logger.warning(f"Сервер повернув HTTP {resp.status} для команди.")
        except Exception as e:
            logger.warning(f"Не вдалося надіслати команду до {self.api_url}: {e}")

        return response_text

    # Зворотна сумісність імені методу
    _dispatch_command = dispatch_command

    async def run_loop(self):
        """Головний асинхронний цикл обробки аудіо."""
        self.running = True
        logger.info("Запуск основного циклу голосового сервісу...")
        backoff_sec = 1.0

        while self.running:
            try:
                if not self.audio.stream or not self.audio.stream.active:
                    logger.info("Підключення до аудіопотоку PipeWire...")
                    self.audio.open_stream()
                    backoff_sec = 1.0

                chunk = self.audio.read_chunk()

                if time.time() < self._debounce_until:
                    await asyncio.sleep(0.01)
                    continue

                if self.detector:
                    detected, score, model_name = self.detector.process_chunk(chunk)
                    if detected:
                        logger.info(f"⚡ Активація! ('{model_name}', впевненість={score:.2f})")
                        self._debounce_until = time.time() + 2.5

                        speech_audio = self.record_speech_after_wakeword()
                        if len(speech_audio) > 0 and self.transcriber:
                            transcript = self.transcriber.transcribe(speech_audio)
                            if transcript:
                                await self.dispatch_command(transcript)

                        self.detector.reset()

                await asyncio.sleep(0.005)

            except (OSError, Exception) as e:
                logger.error(f"Помилка аудіопотоку: {e}. Перепідключення через {backoff_sec:.1f}с...")
                self.audio.close()
                await asyncio.sleep(backoff_sec)
                backoff_sec = min(backoff_sec * 2.0, 10.0)

        self.audio.close()
        logger.info("Голосовий сервіс зупинено.")

    def stop(self):
        """Зупинка сервісу."""
        self.running = False


# Аліас для зворотної сумісності
VoiceListenerService = VoiceService


def load_config() -> dict[str, Any]:
    """Завантаження налаштувань із config/config.yaml."""
    cfg: dict[str, Any] = {}
    if DEFAULT_CONFIG_PATH.exists():
        try:
            import yaml

            with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Не вдалося завантажити конфіг: {e}")
    return cfg


def main():
    parser = argparse.ArgumentParser(description="Smart Garage Voice Service")
    parser.add_argument("--wake-word", type=str, default="hey_jarvis", help="Назва або шлях до моделі Wake Word")
    parser.add_argument("--threshold", type=float, default=0.55, help="Поріг спрацьовування Wake Word")
    parser.add_argument("--whisper-model", type=str, default="base", help="Модель faster-whisper (tiny, base, small)")
    parser.add_argument("--lang", type=str, default="uk", help="Код мови Whisper (типово: uk)")
    parser.add_argument("--api-url", type=str, default="http://127.0.0.1:5000/api/voice/command", help="Endpoint API")
    args = parser.parse_args()

    cfg = load_config()
    voice_cfg = cfg.get("voice", {})
    wake_word = voice_cfg.get("wake_word", args.wake_word)
    threshold = float(voice_cfg.get("wake_word_threshold", args.threshold))
    whisper_model = voice_cfg.get("whisper_model", args.whisper_model)
    whisper_lang = voice_cfg.get("whisper_language", args.lang)
    api_url = voice_cfg.get("api_endpoint", args.api_url)

    service = VoiceService(
        wake_word=wake_word,
        wake_word_threshold=threshold,
        whisper_model=whisper_model,
        whisper_lang=whisper_lang,
        api_url=api_url,
    )
    service.init_engines()

    def _sig_handler(sig, frame):
        logger.info(f"Отримано сигнал виходу ({sig}). Зупинка сервісу...")
        service.stop()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        asyncio.run(service.run_loop())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Вихід за перериванням клавіатури.")


if __name__ == "__main__":
    main()
