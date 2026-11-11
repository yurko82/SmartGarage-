import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

CONFIG_PATH = BASE_DIR / "config" / "config.yaml"

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}

# Support environment variables for sensitive tokens and OpenRouter config
if "llm" in config:
    env_llm_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY")
    if env_llm_key:
        config["llm"]["api_key"] = env_llm_key.strip()

    env_model = os.getenv("OPENROUTER_MODEL")
    if env_model:
        config["llm"]["model"] = env_model.strip()

    env_timeout = os.getenv("OPENROUTER_TIMEOUT")
    if env_timeout:
        try:
            config["llm"]["timeout"] = float(env_timeout)
        except ValueError:
            pass

    env_max_tokens = os.getenv("OPENROUTER_MAX_TOKENS")
    if env_max_tokens:
        try:
            config["llm"]["max_tokens"] = int(env_max_tokens)
        except ValueError:
            pass

    env_daily_budget = os.getenv("OPENROUTER_DAILY_BUDGET") or os.getenv("OPENROUTER_MAX_DAILY_COST")
    if env_daily_budget:
        try:
            config["llm"]["daily_budget_usd"] = float(env_daily_budget)
        except ValueError:
            pass

    env_data_col = os.getenv("OPENROUTER_DATA_COLLECTION")
    if env_data_col:
        if "provider_preferences" not in config["llm"]:
            config["llm"]["provider_preferences"] = {}
        config["llm"]["provider_preferences"]["data_collection"] = env_data_col.strip()

if "telegram" in config:
    env_tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if env_tg_token:
        config["telegram"]["bot_token"] = env_tg_token

# TTS Configuration & Environment Overrides
if "tts" not in config:
    config["tts"] = {}

env_tts_provider = os.getenv("TTS_PROVIDER")
if env_tts_provider:
    config["tts"]["provider"] = env_tts_provider.strip().lower()

env_tts_model = os.getenv("TTS_MODEL")
if env_tts_model:
    config["tts"]["model"] = env_tts_model.strip()

env_tts_voice_id = os.getenv("TTS_VOICE_ID")
if env_tts_voice_id:
    config["tts"]["voice_id"] = env_tts_voice_id.strip()

env_tts_timeout = os.getenv("TTS_TIMEOUT")
if env_tts_timeout:
    try:
        config["tts"]["timeout_seconds"] = float(env_tts_timeout)
    except ValueError:
        pass

env_tts_max_len = os.getenv("TTS_MAX_TEXT_LENGTH")
if env_tts_max_len:
    try:
        config["tts"]["max_text_length"] = int(env_tts_max_len)
    except ValueError:
        pass

env_tts_fallback = os.getenv("TTS_FALLBACK_PROVIDER")
if env_tts_fallback:
    config["tts"]["fallback_provider"] = env_tts_fallback.strip().lower()

env_tts_enabled = os.getenv("TTS_ENABLED")
if env_tts_enabled is not None:
    config["tts"]["enabled"] = env_tts_enabled.strip().lower() in ("1", "true", "yes")

