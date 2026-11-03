"""Клієнт OpenRouter з підтримкою виклику інструментів (tools), обмежень витрат,
політики конфіденційності, таймаутів, повторних спроб (backoff) та обліку токенів.
"""
import json
import logging
import os
from pathlib import Path
import re
import time
import uuid
from typing import Dict, Any, List, Optional, Tuple
import requests

from server.config import config

logger = logging.getLogger(__name__)

# Таблиця цін OpenRouter на моделі (USD за 1M токенів)
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # Baseline
    "google/gemini-2.5-flash": {"prompt": 0.30, "completion": 2.50},
    # Швидший та дешевший кандидат
    "google/gemini-2.5-flash-lite": {"prompt": 0.10, "completion": 0.40},
    # Високоточний кандидат для Function Calling
    "openai/gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "openai/gpt-4o-mini-2024-07-18": {"prompt": 0.15, "completion": 0.60},
    # Модель з відкритими вагами
    "meta-llama/llama-3.3-70b-instruct": {"prompt": 0.20, "completion": 0.52},
    # Важковаговик / флагман
    "google/gemini-2.5-pro": {"prompt": 1.25, "completion": 10.00},
    "google/gemini-2.5-pro-preview": {"prompt": 1.25, "completion": 10.00},
    # Інші актуальні моделі
    "deepseek/deepseek-chat": {"prompt": 0.26, "completion": 1.03},
    "qwen/qwen-2.5-72b-instruct": {"prompt": 0.36, "completion": 0.40},
    # За замовчуванням
    "default": {"prompt": 0.30, "completion": 2.50}
}


class OpenRouterError(Exception):
    """Базовий клас помилок OpenRouter."""
    pass


class OpenRouterAuthError(OpenRouterError):
    """Помилка авторизації (401/403)."""
    pass


class OpenRouterRateLimitError(OpenRouterError):
    """Перевищення ліміту частоти запитів (429)."""
    pass


class OpenRouterServerError(OpenRouterError):
    """Помилка серверів OpenRouter (5xx)."""
    pass


class OpenRouterTimeoutError(OpenRouterError):
    """Вичерпано час очікування відповіді (Timeout)."""
    pass


class OpenRouterPrivacyError(OpenRouterError):
    """Запит відхилено провайдером через обмеження data_collection."""
    pass


class OpenRouterBudgetExceededError(OpenRouterError):
    """Перевищено встановлений ліміт щоденних витрат."""
    pass


class OpenRouterConnectionError(OpenRouterError):
    """Помилка мережевого з'єднання з API."""
    pass


def sanitize_context_snapshot(snapshot: str) -> str:
    """Видаляє чутливі локальні IP-адреси, MAC-адреси та паролі з контексту телеметрії перед надсиланням у LLM."""
    if not snapshot or not isinstance(snapshot, str):
        return ""
    # Очищення MAC-адрес (XX:XX:XX:XX:XX:XX)
    text = re.sub(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b", "[MAC]", snapshot)
    # Очищення локальних IPv4 адрес (192.168.x.x, 10.x.x.x)
    text = re.sub(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1]))\.\d{1,3}\.\d{1,3}\b", "[LAN]", text)
    # Очищення можливих секретів або токенів
    text = re.sub(r"(?i)(?:key|token|secret|password|pin)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{8,}['\"]?", "[REDACTED]", text)
    return text


class CostTracker:
    """Облік використання токенів та витрат (USD) у розрізі днів із захистом від перевищення бюджету."""

    def __init__(self, storage_path: Optional[Path] = None):
        if storage_path is not None:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = Path(__file__).resolve().parent.parent.parent / "memory" / "openrouter_usage.json"
        self._load()

    def _today_key(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _load(self):
        self._data: Dict[str, Any] = {}
        if self.storage_path.exists():
            try:
                content = self.storage_path.read_text(encoding="utf-8").strip()
                if content:
                    self._data = json.loads(content)
            except Exception as e:
                logger.warning(f"Не вдалося завантажити історію витрат: {e}")

    def _save(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.storage_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.storage_path)
        except Exception as e:
            logger.debug(f"Помилка збереження історії витрат: {e}")

    def add_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Розраховує вартість запиту, додає до денного обліку та повертає вартість у USD."""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        p_cost = (prompt_tokens / 1_000_000.0) * pricing["prompt"]
        c_cost = (completion_tokens / 1_000_000.0) * pricing["completion"]
        req_cost = round(p_cost + c_cost, 6)

        today = self._today_key()
        if today not in self._data:
            self._data[today] = {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0
            }

        rec = self._data[today]
        rec["requests"] += 1
        rec["prompt_tokens"] += prompt_tokens
        rec["completion_tokens"] += completion_tokens
        rec["total_tokens"] += (prompt_tokens + completion_tokens)
        rec["total_cost_usd"] = round(rec["total_cost_usd"] + req_cost, 6)

        self._save()
        return req_cost

    def is_budget_exceeded(self, daily_budget_usd: float) -> bool:
        """Перевіряє, чи не перевищено денний ліміт витрат."""
        if daily_budget_usd <= 0:
            return False
        today = self._today_key()
        spent = self._data.get(today, {}).get("total_cost_usd", 0.0)
        return spent >= daily_budget_usd

    def get_today_cost(self) -> float:
        today = self._today_key()
        return float(self._data.get(today, {}).get("total_cost_usd", 0.0))

    def get_today_stats(self) -> Dict[str, Any]:
        today = self._today_key()
        return dict(self._data.get(today, {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0
        }))


class OpenRouterClient:
    """Надійний клієнт OpenRouter із захистом конфіденційності, таймаутами та повторними спробами."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_backoff: Optional[float] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        daily_budget_usd: Optional[float] = None,
        provider_preferences: Optional[Dict[str, Any]] = None,
        cost_tracker: Optional[CostTracker] = None
    ):
        llm_cfg = config.get("llm", {}) if isinstance(config, dict) else {}

        # 1. API-ключ (ніколи не зберігається в YAML чи клієнті)
        self.api_key = (
            api_key
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("LLM_API_KEY")
            or llm_cfg.get("api_key")
            or ""
        ).strip()

        # 2. Модель: за замовчуванням baseline google/gemini-2.5-flash
        self.model = (
            model
            or os.getenv("OPENROUTER_MODEL")
            or llm_cfg.get("model")
            or "google/gemini-2.5-flash"
        ).strip().replace("openrouter/", "")

        # 3. Базовий URL
        self.api_base = (
            api_base
            or llm_cfg.get("api_base")
            or "https://openrouter.ai/api/v1"
        ).rstrip("/")

        # 4. Мережеві параметри та повторні спроби
        self.timeout = float(timeout or os.getenv("OPENROUTER_TIMEOUT") or llm_cfg.get("timeout", 8.0))
        self.max_retries = int(max_retries or os.getenv("OPENROUTER_MAX_RETRIES") or llm_cfg.get("max_retries", 2))
        self.retry_backoff = float(retry_backoff or llm_cfg.get("retry_backoff", 1.0))
        self.max_tokens = int(max_tokens or os.getenv("OPENROUTER_MAX_TOKENS") or llm_cfg.get("max_tokens", 400))
        self.temperature = float(temperature if temperature is not None else llm_cfg.get("temperature", 0.0))

        # 5. Обмеження витрат
        self.daily_budget_usd = float(
            daily_budget_usd
            if daily_budget_usd is not None
            else os.getenv("OPENROUTER_DAILY_BUDGET")
            or llm_cfg.get("daily_budget_usd", 1.00)
        )

        # 6. Політика конфіденційності провайдера
        cfg_pref = llm_cfg.get("provider_preferences", {})
        env_data_col = os.getenv("OPENROUTER_DATA_COLLECTION")
        default_pref = {"data_collection": "deny", "allow_fallbacks": True}
        if isinstance(cfg_pref, dict):
            default_pref.update(cfg_pref)
        if env_data_col:
            default_pref["data_collection"] = env_data_col.strip()
        self.provider_preferences = provider_preferences or default_pref

        # 7. Трекер витрат
        self.cost_tracker = cost_tracker or CostTracker()

    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def send_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Надсилає запит chat/completions з автоматичним retry/backoff для 429/5xx,
        контролем конфіденційності та безпечним структурованим логуванням.
        """
        if not self.has_api_key():
            raise OpenRouterAuthError("Відсутній ключ авторизації OPENROUTER_API_KEY у .env.")

        # Перевірка бюджету
        if self.cost_tracker.is_budget_exceeded(self.daily_budget_usd):
            spent = self.cost_tracker.get_today_cost()
            raise OpenRouterBudgetExceededError(
                f"⚠️ Досягнуто денного ліміту витрат на AI (${self.daily_budget_usd:.2f} USD, витрачено ${spent:.4f}). "
                "Запити тимчасово призупинено для захисту балансу."
            )

        req_id = f"gen_{uuid.uuid4().hex[:10]}"
        req_timeout = timeout or self.timeout

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "provider": self.provider_preferences
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://smartgarage.local",
            "X-Title": "SmartGarage-AI",
            "X-Request-ID": req_id
        }

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            t0 = time.time()
            try:
                resp = requests.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=req_timeout
                )
                latency_ms = int((time.time() - t0) * 1000)

                # 1. Успіх
                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usage", {})
                    p_tok = int(usage.get("prompt_tokens", 0))
                    c_tok = int(usage.get("completion_tokens", 0))
                    cost = self.cost_tracker.add_usage(self.model, p_tok, c_tok)

                    # Структурований лог без витоку промпту чи ключів
                    logger.info(
                        f"[OpenRouter] req_id={req_id} model={self.model} status=200 "
                        f"latency={latency_ms}ms prompt_tokens={p_tok} completion_tokens={c_tok} "
                        f"cost_usd=${cost:.6f}"
                    )
                    return data

                # 2. Rate limit (429)
                if resp.status_code == 429:
                    logger.warning(
                        f"[OpenRouter] req_id={req_id} model={self.model} status=429 (RateLimit) "
                        f"attempt={attempt + 1}/{self.max_retries + 1} latency={latency_ms}ms"
                    )
                    if attempt < self.max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        wait_sec = self.retry_backoff * (2 ** attempt)
                        if retry_after:
                            try:
                                wait_sec = min(float(retry_after), 5.0)
                            except ValueError:
                                pass
                        time.sleep(wait_sec)
                        continue
                    raise OpenRouterRateLimitError(
                        "⚠️ Перевищено ліміт частоти запитів до OpenRouter (Rate Limit / 429). "
                        "Будь ласка, зачекайте декілька секунд."
                    )

                # 3. Серверні помилки (500, 502, 503, 504)
                if resp.status_code in (500, 502, 503, 504):
                    logger.warning(
                        f"[OpenRouter] req_id={req_id} model={self.model} status={resp.status_code} "
                        f"attempt={attempt + 1}/{self.max_retries + 1} latency={latency_ms}ms"
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_backoff * (2 ** attempt))
                        continue
                    raise OpenRouterServerError(
                        f"⚠️ Сервіс OpenRouter тимчасово недоступний (помилка сервера {resp.status_code}). "
                        "Спробуйте пізніше."
                    )

                # 4. Помилки авторизації (401, 403)
                if resp.status_code in (401, 403):
                    logger.error(f"[OpenRouter] req_id={req_id} model={self.model} status={resp.status_code} (AuthError)")
                    raise OpenRouterAuthError(
                        "⚠️ Помилка авторизації в OpenRouter: недійсний або заблокований API-ключ у .env."
                    )

                # 5. Помилка обмеження конфіденційності (data_collection: deny)
                resp_text = resp.text
                if resp.status_code in (400, 404) and any(k in resp_text.lower() for k in ("data_collection", "privacy", "provider requirements", "no available provider")):
                    logger.warning(f"[OpenRouter] req_id={req_id} PrivacyRequirementRejected: {resp_text[:120]}")
                    raise OpenRouterPrivacyError(
                        "⚠️ Провайдер відхилив запит через обмеження конфіденційності (data_collection: deny). "
                        "Моделі, що вимагають збереження даних, заблоковані."
                    )

                # 6. Інші помилки API
                err_msg = ""
                try:
                    err_msg = resp.json().get("error", {}).get("message", "")
                except Exception:
                    pass
                if not err_msg:
                    err_msg = resp_text[:120]

                logger.error(f"[OpenRouter] req_id={req_id} status={resp.status_code} error={err_msg}")
                raise OpenRouterError(f"⚠️ Помилка OpenRouter API ({resp.status_code}): {err_msg}")

            except requests.exceptions.Timeout as e:
                latency_ms = int((time.time() - t0) * 1000)
                logger.warning(
                    f"[OpenRouter] req_id={req_id} model={self.model} Timeout "
                    f"attempt={attempt + 1}/{self.max_retries + 1} latency={latency_ms}ms"
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff)
                    continue
                raise OpenRouterTimeoutError(
                    "⚠️ Час очікування відповіді від OpenRouter вичерпано (Timeout). Перевірте інтернет або повторіть запит."
                )

            except (OpenRouterError, OpenRouterRateLimitError, OpenRouterServerError, OpenRouterAuthError, OpenRouterPrivacyError, OpenRouterBudgetExceededError):
                raise

            except requests.exceptions.RequestException as re_err:
                logger.warning(f"[OpenRouter] req_id={req_id} NetworkException: {re_err}")
                last_error = re_err
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff)
                    continue

        if last_error:
            raise OpenRouterConnectionError(f"⚠️ Тимчасова помилка зв'язку з сервером OpenRouter: {last_error}")

        raise OpenRouterError("⚠️ Не вдалося отримати відповідь від OpenRouter.")


# Глобальний екземпляр
openrouter_client = OpenRouterClient()
