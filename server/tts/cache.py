"""
Smart Garage - Short-Lived TTL Cache for TTS Audio
--------------------------------------------------
Забезпечує тимчасове кешування згенерованого аудіо з обов'язковим
строком життя (TTL) та лімітом кількості файлів. Не зберігає персональні
розмови необмежено й автоматично видаляє застарілі файли.
"""

import os
import time
import hashlib
import logging
import threading
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger("TTSCache")

DEFAULT_CACHE_DIR = Path("/tmp/smartgarage_tts_cache")
DEFAULT_CACHE_TTL = 3600  # 1 година
DEFAULT_MAX_ITEMS = 100


class TTSAudioCache:
    """Кеш аудіофайлів із контролем строку життя (TTL) та обмеженням місткості."""

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        ttl_seconds: int = DEFAULT_CACHE_TTL,
        max_items: int = DEFAULT_MAX_ITEMS
    ):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._lock = threading.Lock()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Виконуємо початкове очищення при старті
        self.cleanup_expired()

    def _get_key(self, provider: str, voice_id: str, text: str, content_type: str) -> str:
        data = f"{provider}:{voice_id}:{content_type}:{text}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def get(self, provider: str, voice_id: str, text: str, content_type: str = "audio/mpeg") -> Optional[bytes]:
        """Отримує аудіобайти з кешу, якщо файл існує і не застарів."""
        ext = "wav" if "wav" in content_type else "mp3"
        key = self._get_key(provider, voice_id, text, content_type)
        file_path = self.cache_dir / f"{key}.{ext}"

        with self._lock:
            if not file_path.exists():
                return None

            try:
                stat = file_path.stat()
                age = time.time() - stat.st_mtime
                if age > self.ttl_seconds:
                    # Застарілий файл — видаляємо
                    file_path.unlink(missing_ok=True)
                    return None

                # Оновлюємо час доступу (mtime)
                file_path.touch()
                return file_path.read_bytes()
            except Exception as e:
                logger.warning(f"Помилка читання TTS кешу {file_path}: {e}")
                return None

    def put(self, provider: str, voice_id: str, text: str, audio_bytes: bytes, content_type: str = "audio/mpeg") -> None:
        """Зберігає аудіобайти в тимчасовий кеш із перевіркою лімітів."""
        if not audio_bytes:
            return

        ext = "wav" if "wav" in content_type else "mp3"
        key = self._get_key(provider, voice_id, text, content_type)
        file_path = self.cache_dir / f"{key}.{ext}"

        with self._lock:
            # Перед збереженням перевіряємо ліміт кількості файлів
            self._enforce_capacity()

            try:
                tmp_path = file_path.with_suffix(".tmp")
                tmp_path.write_bytes(audio_bytes)
                os.replace(tmp_path, file_path)
            except Exception as e:
                logger.warning(f"Помилка запису в TTS кеш {file_path}: {e}")

    def cleanup_expired(self) -> int:
        """Видаляє всі файли, строк життя яких перевищує ttl_seconds."""
        now = time.time()
        removed_count = 0
        with self._lock:
            try:
                for item in self.cache_dir.glob("*.*"):
                    if item.suffix in [".mp3", ".wav", ".tmp"]:
                        try:
                            if now - item.stat().st_mtime > self.ttl_seconds:
                                item.unlink(missing_ok=True)
                                removed_count += 1
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Помилка очищення TTS кешу: {e}")
        return removed_count

    def _enforce_capacity(self) -> None:
        """Якщо кількість файлів перевищує max_items, видаляє найстаріші."""
        try:
            files = list(self.cache_dir.glob("*.*"))
            valid_files = [f for f in files if f.suffix in [".mp3", ".wav"]]
            if len(valid_files) >= self.max_items:
                # Сортуємо за часом модифікації (найстаріші першими)
                valid_files.sort(key=lambda f: f.stat().st_mtime)
                # Видаляємо 20% найстаріших файлів
                to_delete = valid_files[: max(1, len(valid_files) - self.max_items + 10)]
                for f in to_delete:
                    f.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Помилка контролю ліміту місткості TTS кешу: {e}")
