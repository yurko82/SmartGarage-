"""
Smart Garage - Base TTS Provider Interfaces and Data Structures
----------------------------------------------------------------
Визначає абстрактний інтерфейс TTSProvider, структуру результату TTSResult
та типізовані винятки для модульного синтезу українського мовлення.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Any


class TTSError(Exception):
    """Базовий виняток підсистеми синтезу мовлення (TTS)."""
    pass


class TTSAuthError(TTSError):
    """Помилка автентифікації або відсутність API-ключа провайдера."""
    pass


class TTSRateLimitError(TTSError):
    """Перевищення ліміту частоти запитів до провайдера (429 Too Many Requests)."""
    pass


class TTSServerError(TTSError):
    """Помилка на стороні сервера провайдера TTS (5xx)."""
    pass


class TTSTimeoutError(TTSError):
    """Вичерпано час очікування відповіді від провайдера TTS."""
    pass


class TTSVoiceNotFoundError(TTSError):
    """Вказаний ідентифікатор голосу не знайдено або він не підтримується."""
    pass


class TTSMalformedResponseError(TTSError):
    """Отримано некоректну або пошкоджену відповідь від провайдера TTS."""
    pass


@dataclass
class TTSVoiceInfo:
    """Інформація про доступний голос провайдера."""
    voice_id: str
    name: str
    language: str
    gender: str = "unknown"
    preview_url: Optional[str] = None
    description: Optional[str] = None
    is_default: bool = False


@dataclass
class TTSResult:
    """Результат синтезу мовлення."""
    audio_bytes: bytes
    content_type: str               # "audio/mpeg", "audio/wav" тощо
    provider: str                   # Назва провайдера, що згенерував аудіо
    voice_id: str                   # Використаний ідентифікатор голосу
    cached: bool = False            # Чи повернуто з кешу
    fallback_used: bool = False     # Чи використовувався резервний провайдер
    fallback_reason: Optional[str] = None  # Причина спрацьовування fallback
    duration_seconds: Optional[float] = None


class TTSProvider(ABC):
    """Абстрактний інтерфейс адаптера провайдера TTS."""

    def __init__(self, name: str, timeout: float = 10.0, max_retries: int = 2):
        self.name = name
        self.timeout = timeout
        self.max_retries = max_retries

    @abstractmethod
    def synthesize(self, text: str, voice_id: Optional[str] = None, **kwargs) -> TTSResult:
        """
        Синтезує переданий очищений текст у аудіодані.

        :param text: Нормалізований текст для синтезу (українською мовою).
        :param voice_id: Опціональний ідентифікатор голосу.
        :return: TTSResult з бінарними даними аудіо та метаданими.
        """
        pass

    @abstractmethod
    def get_available_voices(self) -> List[TTSVoiceInfo]:
        """
        Повертає список валідованих українських голосів, доступних у провайдера.
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """
        Перевіряє, чи провайдер належним чином налаштований (наявність ключів тощо).
        """
        pass
