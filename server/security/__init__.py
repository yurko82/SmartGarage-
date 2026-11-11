"""
Smart Garage Security Module
"""
from server.security.audit import audit_log, sanitize_data, sanitize_details
from server.security.auth import (
    FORBIDDEN_DEFAULT_PINS,
    command_rate_limiter,
    generate_csrf_token,
    get_client_ip,
    get_expected_esp32_key,
    get_trusted_proxies,
    init_session_security,
    rate_limiter,
    require_auth,
    telemetry_rate_limiter,
    tts_rate_limiter,
    verify_esp32_auth,
    verify_pin_secure,
)

__all__ = [
    "audit_log",
    "sanitize_data",
    "require_auth",
    "verify_pin_secure",
    "rate_limiter",
    "tts_rate_limiter",
    "command_rate_limiter",
    "telemetry_rate_limiter",
    "init_session_security",
    "generate_csrf_token",
    "get_client_ip",
    "get_trusted_proxies",
    "FORBIDDEN_DEFAULT_PINS",
    "get_expected_esp32_key",
    "verify_esp32_auth"
]
