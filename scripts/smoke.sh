#!/usr/bin/env bash
# scripts/smoke.sh — Швидка комплексна перевірка працездатності SmartGarage
set -eo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=================================================="
echo "  SmartGarage Smoke Test & Integrity Check        "
echo "=================================================="

# 1. Визначення Python / Pytest
if [ -n "$VENV_PYTHON" ] && [ -x "$VENV_PYTHON" ]; then
    PY="$VENV_PYTHON"
elif [ -x "$HOME/AI/sg-venv/bin/python" ]; then
    PY="$HOME/AI/sg-venv/bin/python"
elif [ -x "$HOME/AI/OpenInterpreter/venv/bin/python" ]; then
    PY="$HOME/AI/OpenInterpreter/venv/bin/python"
else
    PY="python3"
fi

PYTEST="$(dirname "$PY")/pytest"
if [ ! -x "$PYTEST" ]; then
    PYTEST="pytest"
fi

PIO_BIN="$HOME/.local/bin/pio"
if [ ! -x "$PIO_BIN" ]; then
    PIO_BIN="$(command -v pio || true)"
fi

echo "[1/5] Перевірка компіляції байт-коду Python..."
$PY -m compileall -q server/ tests/ scripts/
echo "  -> Байт-код скомпільовано успішно."

echo "[2/5] Запуск юніт-тестів..."
TESTING=true \
ADMIN_PIN=9876 \
ESP32_API_KEY=ci_test_esp32_key_12345 \
OPENROUTER_API_KEY='' \
PYTHONPATH=. \
$PYTEST -q tests/
echo "  -> Усі тести пройдено успішно."

echo "[3/5] Перевірка відсутності витоку реальних MAC/секретів у git..."
FORBIDDEN_MACS="41:42:62:69:51:9B|F8:5C:7E:EE:7D:CC|A4:C1:38:EC:EC:6C|A4:C1:38:CC:CA:49|B8:7E:39:88:22:9B|A0:62:56:5C:9B:FC"
LEAK_COUNT=$(git grep -iE "$FORBIDDEN_MACS" | wc -l || true)
if [ "$LEAK_COUNT" -ne 0 ]; then
    echo "  [ПОМИЛКА] Знайдено витік персональних MAC-адрес у відстежуваних файлах ($LEAK_COUNT збігів)!"
    git grep -n -iE "$FORBIDDEN_MACS"
    exit 1
fi
echo "  -> Жодних витоків реальних MAC-адрес не виявлено."

echo "[4/5] Перевірка компіляції прошивки ESP32..."
if [ -n "$PIO_BIN" ] && [ -x "$PIO_BIN" ]; then
    if [ ! -f "esp32/src/secrets.h" ] && [ -f "esp32/src/secrets.h.example" ]; then
        cp esp32/src/secrets.h.example esp32/src/secrets.h
    fi
    $PIO_BIN run -d esp32 -s
    echo "  -> Прошивка ESP32 зібрана успішно."
else
    echo "  [ПРОПУЩЕНО] PlatformIO не встановлено або не знайдено в PATH."
fi

echo "[5/5] Перевірка стану локальних сервісів..."
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet mosquitto; then
        echo "  -> Mosquitto MQTT: active"
    else
        echo "  -> Mosquitto MQTT: inactive (або не налаштовано як системний сервіс)"
    fi
    if systemctl --user is-active --quiet smartgarage 2>/dev/null; then
        echo "  -> smartgarage (user service): active"
    elif systemctl is-active --quiet smartgarage 2>/dev/null; then
        echo "  -> smartgarage (system service): active"
    else
        echo "  -> smartgarage: inactive (запущено вручну або зупинено)"
    fi
fi

echo "=================================================="
echo "  Всі smoke-перевірки пройдено успішно (ЗЕЛЕНИЙ СТАН) "
echo "=================================================="