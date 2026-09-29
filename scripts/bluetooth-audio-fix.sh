#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Bluetooth Audio Reset & Recovery Tool
# Path: /usr/local/bin/bluetooth-audio-fix.sh
# ==============================================================================
set -euo pipefail

LOG_FILE="/var/log/bluetooth-audio-fix.log"
FALLBACK_LOG="/tmp/bluetooth-audio-fix.log"

# Target Known Bluetooth Speakers in Smart Garage:
# 1) JX-BT (1st floor): 41:42:62:69:51:9B
# 2) JBL Clip 5 (Garage): F8:5C:7E:EE:7D:CC
DEFAULT_DEVICES=("41:42:62:69:51:9B" "F8:5C:7E:EE:7D:CC")
TARGET_MAC="${1:-${DEFAULT_DEVICES[0]}}"

# Logging helper
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg"
    if [ -w "$LOG_FILE" ] || [ -w "$(dirname "$LOG_FILE")" ]; then
        echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
    else
        echo "$msg" >> "$FALLBACK_LOG" 2>/dev/null || true
    fi
}

log "=========================================================="
log "Початок виконання bluetooth-audio-fix"
log "Цільовий Bluetooth пристрій: ${TARGET_MAC}"

# 1. Перезапуск сервісів аудіосистеми (PipeWire, WirePlumber, PulseAudio)
log "1. Перезавантаження аудіосервісів..."
if systemctl --user is-active --quiet pipewire 2>/dev/null; then
    systemctl --user restart pipewire pipewire-pulse wireplumber 2>/dev/null || true
    log "--> pipewire, pipewire-pulse, wireplumber перезапущено успішно."
else
    # Fallback якщо викликано з root контексту без поточної сесії користувача
    if [ -n "${SUDO_USER:-}" ]; then
        USER_UID=$(id -u "$SUDO_USER")
        export XDG_RUNTIME_DIR="/run/user/${USER_UID}"
        sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" systemctl --user restart pipewire pipewire-pulse wireplumber || true
        log "--> Сервіси перезапущено від імені користувача $SUDO_USER."
    else
        log "--> УВАГА: Не вдалося визначити активну сесію PipeWire користувача."
    fi
fi

# Дати час сервісам на ініціалізацію
sleep 2

# 2. Перепідключення Bluetooth пристрою
log "2. Перепідключення Bluetooth пристрою ${TARGET_MAC}..."
# Перевірка живлення адаптера
if command -v bluetoothctl >/dev/null 2>&1; then
    bluetoothctl power on >/dev/null 2>&1 || true
    bluetoothctl disconnect "${TARGET_MAC}" >/dev/null 2>&1 || true
    sleep 1

    log "--> Спроба з'єднання з ${TARGET_MAC}..."
    CONNECT_OUTPUT=$(bluetoothctl connect "${TARGET_MAC}" 2>&1 || true)
    log "--> Результат bluetoothctl connect: ${CONNECT_OUTPUT}"
    sleep 2
else
    log "ПОМИЛКА: bluetoothctl не знайдено."
fi

# 3. Перевірка статусу кодека та аудіовиходу через pactl list sinks
log "3. Перевірка статусу кодека через pactl list sinks..."
CODEC_FOUND="unknown"
SINK_FOUND=false

if command -v pactl >/dev/null 2>&1; then
    SINKS_DUMP=$(pactl list sinks 2>/dev/null || true)

    if echo "$SINKS_DUMP" | grep -q -i "bluez"; then
        SINK_FOUND=true
        # Пошук кодека серед властивостей bluetooth
        CODEC_INFO=$(echo "$SINKS_DUMP" | grep -E "bluetooth.codec|api.bluez5.codec" | head -n 1 | tr -d '\t" ' || true)
        if [ -n "$CODEC_INFO" ]; then
            CODEC_FOUND="$CODEC_INFO"
        fi

        DEVICE_DESC=$(echo "$SINKS_DUMP" | grep -A 2 -i "bluez" | grep "Опис:\|Description:" | head -n 1 | sed 's/^[ \t]*//' || true)
        log "--> Знайдено Bluetooth Sink: ${DEVICE_DESC}"
        log "--> Активний кодек: ${CODEC_FOUND}"

        # Фіксація гучності на 80% для запобігання спрацьовування апаратного шумодаву (noise gate)
        BT_SINK_NAME=$(echo "$SINKS_DUMP" | grep "Назва:\|Name:" | grep "bluez" | head -n 1 | awk '{print $2}')
        if [ -n "$BT_SINK_NAME" ]; then
            pactl set-sink-volume "$BT_SINK_NAME" 80% 2>/dev/null || true
            pactl set-sink-mute "$BT_SINK_NAME" 0 2>/dev/null || true
            log "--> Гучність $BT_SINK_NAME встановлено на 80% (noise gate bypass)."
        fi
    else
        log "--> ПОПЕРЕДЖЕННЯ: Bluetooth audio sink поки що не зареєстровано в PipeWire."
    fi
fi

log "Статус завершення: SinkFound=${SINK_FOUND}, Codec=${CODEC_FOUND}"
log "=========================================================="
echo "bluetooth-audio-fix виконано. Деталі у лозі: ${LOG_FILE}"
