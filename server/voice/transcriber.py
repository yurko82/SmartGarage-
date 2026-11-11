"""
server/voice/transcriber.py — Локальне розпізнавання мови (Speech-to-Text)
Використовує Faster-Whisper з квантуванням INT8 для швидкого декодування без перевантаження процесора.
"""

import logging
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("VoiceListener.Transcriber")


class SpeechTranscriber:
    """Розпізнавач мови на базі Faster-Whisper."""

    def __init__(self, model_size: str = "base", language: str = "uk", cpu_threads: int = 1):
        self.model_size = model_size
        self.language = language
        self.cpu_threads = cpu_threads
        self.model = None
        self._load_model()

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel

            logger.info(f"Завантаження faster-whisper '{self.model_size}' (int8, threads={self.cpu_threads})...")
            t0 = time.time()
            self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8", cpu_threads=self.cpu_threads)
            logger.info(f"Модель faster-whisper завантажено за {time.time() - t0:.2f}с.")
        except ImportError:
            logger.warning("Бібліотеку faster_whisper не встановлено. STT працюватиме в режимі заглушки.")
        except Exception as e:
            logger.error(f"Помилка завантаження Faster-Whisper: {e}")

    def transcribe(self, audio_data: np.ndarray) -> str:
        """
        Транскрибування 16 кГц float32 аудіо-масиву.
        Повертає розпізнаний текст.
        """
        if self.model is None or len(audio_data) < 4000:
            return ""

        try:
            t0 = time.time()
            segments, info = self.model.transcribe(
                audio_data,
                language=self.language,
                beam_size=1,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            elapsed = time.time() - t0
            logger.info(f"Розпізнавання завершено за {elapsed:.2f}с: «{text}»")
            return text
        except Exception as e:
            logger.error(f"Помилка транскрибування: {e}")
            return ""


# Аліас для збереження сумісності
LowCpuSpeechTranscriber = SpeechTranscriber
