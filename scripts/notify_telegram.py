#!/usr/bin/env python3
import sys
import os
from pathlib import Path
import requests

# Ensure repo root is in sys.path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from server.services.telegram_bot import TelegramBot

def main():
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = sys.stdin.read().strip()
    
    if not text:
        print("No text provided", file=sys.stderr)
        sys.exit(1)
        
    bot = TelegramBot(None)
    if not bot.enabled:
        print("Telegram bot is disabled", file=sys.stderr)
        sys.exit(2)
    if not bot.token or not bot.admin_chat_id:
        print("Telegram token or admin_chat_id missing", file=sys.stderr)
        sys.exit(3)
        
    url = f"{bot.api_base}/sendMessage"
    # Try sending with HTML or plain text fallback to avoid Markdown entity parse errors
    r = requests.post(url, json={"chat_id": bot.admin_chat_id, "text": text}, timeout=10)
    if r.status_code == 200:
        print("OK")
        sys.exit(0)
    else:
        print(f"FAIL: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(4)

if __name__ == "__main__":
    main()
