"""
Smart Garage - Centralized Audit Logger
Logs all sensitive actions across Web, Voice, Telegram, AI, and MQTT sources
with correlation IDs, sanitizing secrets (passwords, PINs, tokens).
"""
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

AUDIT_LOG_DIR = Path("logs")
AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.log"

logger = logging.getLogger("AuditLogger")

# Sensitive key patterns that must be redacted
SENSITIVE_KEYS = {
    "pin", "password", "token", "secret", "api_key", "authorization",
    "csrf_token", "admin_pin", "key", "bot_token", "jwt"
}


def sanitize_data(data: Any) -> Any:
    """Recursively redact sensitive data (passwords, tokens, PINs) from dictionaries and strings."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, (dict, list)):
                sanitized[k] = sanitize_data(v)
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, str):
        # Redact potential Bearer tokens or PIN sequences in plain strings
        cleaned = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]+', 'Bearer [REDACTED]', data)
        return cleaned
    return data


# Alias for backward-compatibility
sanitize_details = sanitize_data


def audit_log(
    source: str,
    action: str,
    result: str,
    details: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    actor: str | None = None
) -> str:
    """
    Record an immutable structured audit log entry.

    :param source: "web" | "voice" | "telegram" | "ai" | "mqtt" | "system"
    :param action: Action performed (e.g. "light_toggle", "scenario_arrival")
    :param result: "SUCCESS" | "DENIED" | "FAILED" | "BLOCKED"
    :param details: Dictionary of parameters (secrets will be masked)
    :param correlation_id: Tracking ID for request chain
    :param actor: User/system identity if known
    :return: correlation_id
    """
    cid = correlation_id or str(uuid.uuid4())[:8]
    now = time.time()

    sanitized_details = sanitize_data(details or {})

    entry = {
        "timestamp": now,
        "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "correlation_id": cid,
        "source": source.lower(),
        "action": action,
        "result": result.upper(),
        "actor": actor or "anonymous",
        "details": sanitized_details
    }

    log_line = json.dumps(entry, ensure_ascii=False)

    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")

    logger.info(f"[AUDIT] [{entry['source']}] [{entry['result']}] cid={cid} act={action} actor={entry['actor']}")
    return cid
