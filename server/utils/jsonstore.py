"""
server/utils/jsonstore.py — Атомарне та безпечне збереження JSON файлів
Захист від пошкодження даних при раптовому вимкненні живлення через os.replace
та створення резервних копій .bak при виявленні пошкоджених файлів.
"""
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("JsonStore")

_FILE_LOCKS: dict[str, threading.RLock] = {}
_REGISTRY_LOCK = threading.RLock()


def _get_lock(path: Path) -> threading.RLock:
    resolved = str(path.resolve())
    with _REGISTRY_LOCK:
        if resolved not in _FILE_LOCKS:
            _FILE_LOCKS[resolved] = threading.RLock()
        return _FILE_LOCKS[resolved]


def atomic_dump(data: Any, target_path: str | Path, backup: bool = True, indent: int = 2) -> None:
    """
    Атомарний запис структури даних у JSON-файл.
    Дані записуються у тимчасовий файл у тому ж каталозі, синхронізуються на диск
    та замінюють цільовий файл атомарною операцією os.replace.
    """
    path = Path(target_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _get_lock(path)

    with lock:
        # Резервна копія перед перезаписом
        if backup and path.exists():
            try:
                bak_path = path.with_suffix(path.suffix + ".bak")
                shutil.copy2(path, bak_path)
            except Exception as e:
                logger.warning(f"Не вдалося створити резервну копію {path}: {e}")

        # Створення тимчасового файлу в тій самій файловій системі
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent)
        )
        tmp_path = Path(tmp_path_str)

        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
                f.flush()
                os.fsync(f.fileno())

            # Атомарне заміщення
            os.replace(tmp_path, path)
        except Exception as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            logger.error(f"Помилка атомарного запису {path}: {e}")
            raise


def atomic_load(target_path: str | Path, default: Any = None) -> Any:
    """
    Безпечне зчитування JSON-файлу.
    Якщо файл пошкоджено, створює аварійний знімок .corrupted і повертає default.
    """
    path = Path(target_path).resolve()
    if not path.exists():
        return default

    lock = _get_lock(path)
    with lock:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Пошкоджений JSON-файл {path}: {e}")
            corrupted_backup = path.with_suffix(f".corrupted.{int(time.time())}.bak")
            try:
                shutil.copy2(path, corrupted_backup)
                logger.info(f"Збережено аварійний знімок: {corrupted_backup}")
            except Exception:
                pass
            return default
        except Exception as e:
            logger.error(f"Помилка зчитування файлу {path}: {e}")
            return default


class JsonStore:
    """Потокобезпечне сховище для конкретного JSON файлу."""

    def __init__(self, file_path: str | Path, default_factory: Callable[[], Any] | None = None):
        self.path = Path(file_path).resolve()
        self.default_factory = default_factory or (lambda: {})

    def load(self) -> Any:
        default_val = self.default_factory()
        res = atomic_load(self.path, default=default_val)
        if res is None:
            return default_val
        return res

    def save(self, data: Any, backup: bool = True) -> None:
        atomic_dump(data, self.path, backup=backup)

    def update(self, mutator: Callable[[Any], None]) -> Any:
        lock = _get_lock(self.path)
        with lock:
            current = self.load()
            mutator(current)
            self.save(current)
            return current
