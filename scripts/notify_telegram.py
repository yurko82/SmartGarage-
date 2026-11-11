#!/usr/bin/env python3
import sys
import os
from pathlib import Path

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
        
    ok = bot.send_message(bot.admin_chat_id, text)
    if ok:
        print("OK")
    else:
        print("FAIL", file=sys.stderr)
        sys.exit(4)

if __name__ == "__main__":
    main()
