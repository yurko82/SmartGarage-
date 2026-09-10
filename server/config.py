import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

CONFIG_PATH = BASE_DIR / "config" / "config.yaml"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}

# Support environment variables for sensitive tokens
if "llm" in config:
    env_llm_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY")
    if env_llm_key:
        config["llm"]["api_key"] = env_llm_key

if "telegram" in config:
    env_tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if env_tg_token:
        config["telegram"]["bot_token"] = env_tg_token
