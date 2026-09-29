#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Setup Voice Environment (OpenWakeWord + Faster-Whisper + PipeWire)
# Path: scripts/setup_voice_env.sh
# Installs system dependencies, Python packages, configures PipeWire virtual mic,
# and activates antigravity-voice.slice (CPU 15%, RAM 1GB, Swap 0).
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${HOME}/AI/OpenInterpreter/venv/bin/python"
VENV_PIP="${HOME}/AI/OpenInterpreter/venv/bin/pip"
CONFIG_DIR="${PROJECT_ROOT}/config/systemd"
MODELS_DIR="${PROJECT_ROOT}/models/wakeword"

echo "=========================================================="
echo " [SmartGarage] Встановлення оточення голосового інтерфейсу"
echo " Завдання: Wake Word (openwakeword) + STT (faster-whisper)"
echo " Ізоляція: antigravity-voice.slice (CPU: 15%, RAM: 1GB)"
echo " Аудіо:    PipeWire Virtual Source (pipewire-virtual-source)"
echo "=========================================================="

# 1. Створення необхідних директорій
echo "==> 1. Створення каталогу для кастомних моделей wake word..."
mkdir -p "${MODELS_DIR}"
echo "    Каталог: ${MODELS_DIR}"

# 2. Встановлення системних пакетів (FFmpeg, PortAudio, ALSA)
echo "==> 2. Встановлення системних залежностей через apt..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y --no-install-recommends \
        ffmpeg \
        portaudio19-dev \
        libasound2-dev \
        libpulse-dev \
        pulseaudio-utils
    echo "    [OK] Системні аудіопакети встановлено."
else
    echo "    [ПОПЕРЕДЖЕННЯ] apt-get не знайдено. Переконайтеся, що ffmpeg та portaudio встановлені вручну."
fi

# 3. Перевірка Python віртуального оточення
echo "==> 3. Перевірка віртуального середовища Python..."
if [ ! -f "${VENV_PYTHON}" ]; then
    echo "ПОМИЛКА: Не знайдено віртуальне середовище в ${VENV_PYTHON}"
    exit 1
fi

# 4. Встановлення Python бібліотек
echo "==> 4. Встановлення Python-пакетів (openwakeword, faster-whisper, sounddevice, aiohttp)..."
"${VENV_PIP}" install --upgrade \
    openwakeword \
    faster-whisper \
    sounddevice \
    aiohttp \
    scipy \
    numpy

echo "    [OK] Python бібліотеки успішно встановлено."

# 5. Налаштування PipeWire Virtual Source
echo "==> 5. Налаштування віртуального мікрофона PipeWire..."
if command -v pactl >/dev/null 2>&1; then
    if pactl list sources short | grep -q "pipewire-virtual-source"; then
        echo "    [OK] Джерело pipewire-virtual-source вже активне."
    else
        echo "    Створення джерела pipewire-virtual-source через pactl module-remap-source..."
        # Знаходимо активний мікрофон
        MASTER_SOURCE=$(pactl list sources short | awk '$2 ~ /input|mic/ && $2 !~ /monitor/ {print $2; exit}')
        if [ -n "${MASTER_SOURCE}" ]; then
            pactl load-module module-remap-source \
                source_name=pipewire-virtual-source \
                master="${MASTER_SOURCE}" \
                source_properties=device.description=PipeWire-Virtual-Source || true
            echo "    [OK] Віртуальне аудіоджерело підв'язано до ${MASTER_SOURCE}."
        else
            pactl load-module module-remap-source \
                source_name=pipewire-virtual-source \
                source_properties=device.description=PipeWire-Virtual-Source || true
            echo "    [OK] Віртуальне аудіоджерело створено (за замовчуванням)."
        fi
    fi
fi

# 6. Встановлення systemd slice та service
echo "==> 6. Встановлення systemd slice та service..."
if [ -f "${CONFIG_DIR}/antigravity-voice.slice" ]; then
    sudo cp "${CONFIG_DIR}/antigravity-voice.slice" /etc/systemd/system/antigravity-voice.slice
    sudo chmod 644 /etc/systemd/system/antigravity-voice.slice
    echo "    [OK] Встановлено /etc/systemd/system/antigravity-voice.slice"
fi

if [ -f "${CONFIG_DIR}/antigravity-voice.service" ]; then
    sudo cp "${CONFIG_DIR}/antigravity-voice.service" /etc/systemd/system/antigravity-voice.service
    sudo chmod 644 /etc/systemd/system/antigravity-voice.service
    echo "    [OK] Встановлено /etc/systemd/system/antigravity-voice.service"
fi

sudo systemctl daemon-reload
sudo systemctl enable antigravity-voice.slice || true
echo "    [OK] systemd daemon-reload виконано."

# 7. Швидкий тест працездатності компонентів
echo "==> 7. Виконання діагностичного самотесту..."
"${VENV_PYTHON}" -c "
import openwakeword
from openwakeword.model import Model
from faster_whisper import WhisperModel
import sounddevice as sd

print('  • openwakeword:', openwakeword.__version__)
m = Model(wakeword_model_paths=[])
print('  • Wake word моделі:', list(m.models.keys()))
w = WhisperModel('base', device='cpu', compute_type='int8', cpu_threads=1)
print('  • faster-whisper base (int8): успішно ініціалізовано')
print('  • sounddevice: знайдено аудіопристроїв:', len(sd.query_devices()))
"

echo ""
echo "=========================================================="
echo " [УСПІХ] Голосове оточення Smart Garage успішно налаштовано!"
echo " Запуск служби:  sudo systemctl start antigravity-voice.service"
echo " Статус служби:  sudo systemctl status antigravity-voice.service"
echo " Перегляд логів: journalctl -u antigravity-voice.service -f"
echo "=========================================================="
