#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - AI Resources Monitor & Self-Healing Watchdog
# Path: /usr/local/bin/monitor-ai-resources.sh
# Monitors: antigravity-ai.slice (CPU, Memory, Tasks) via systemd-cgtop & cgroups v2
# Features:
#   - 5-second interval logging to /var/log/antigravity-ai-resources.log
#   - Telegram alert on CPU > 75% for >= 30 seconds
#   - Auto-restart of services exceeding MemoryMax
# ==============================================================================
set -euo pipefail

LOG_FILE="/var/log/antigravity-ai-resources.log"
FALLBACK_LOG="/tmp/antigravity-ai-resources.log"
SLICE_NAME="antigravity-ai.slice"
CGROUP_PATH="/sys/fs/cgroup/${SLICE_NAME}"
PROJECT_ROOT="/home/yurko/AI/SmartGarage"

# Load Telegram credentials from project files
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"

if [ -f "${PROJECT_ROOT}/.env" ]; then
    ENV_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "${PROJECT_ROOT}/.env" | cut -d '=' -f2- | tr -d ' "' || true)
    if [ -n "$ENV_TOKEN" ] && [ -z "$BOT_TOKEN" ]; then
        BOT_TOKEN="$ENV_TOKEN"
    fi
fi

if [ -f "${PROJECT_ROOT}/config/config.yaml" ]; then
    YAML_CHAT_ID=$(grep -E '^\s*admin_chat_id:' "${PROJECT_ROOT}/config/config.yaml" | awk '{print $2}' | tr -d ' "' || true)
    if [ -n "$YAML_CHAT_ID" ] && [ -z "$CHAT_ID" ]; then
        CHAT_ID="$YAML_CHAT_ID"
    fi
fi

# Logging function
log_entry() {
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local line="[$timestamp] $1"
    echo "$line"
    if [ -w "$LOG_FILE" ] || [ -w "$(dirname "$LOG_FILE")" ]; then
        echo "$line" >> "$LOG_FILE" 2>/dev/null || true
    else
        echo "$line" >> "$FALLBACK_LOG" 2>/dev/null || true
    fi
}

# Telegram notification function
send_telegram_alert() {
    local message="$1"
    if [ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
        curl -s -m 5 -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${CHAT_ID}" \
            -d "text=${message}" \
            -d "parse_mode=HTML" >/dev/null 2>&1 || true
    fi
}

log_entry "=========================================================="
log_entry "Запуск моніторингу AI-ресурсів для ${SLICE_NAME}"
log_entry "Інтервал: 5 сек | Поріг CPU: 75% за 30 сек | MemoryMax Guard: Active"
log_entry "Telegram сповіщення: $([ -n "$BOT_TOKEN" ] && echo "Налаштовано (Chat: $CHAT_ID)" || echo "Вимкнено (немає токена)")"
log_entry "=========================================================="

# State tracking variables
CPU_HIGH_COUNT=0
ALERT_COOLDOWN=0
LAST_USAGE_USEC=0
LAST_CHECK_TIME=0

# Max memory limits in bytes (2GB = 2147483648 bytes, 4GB = 4294967296 bytes)
MAX_SERVICE_MEM_BYTES=$((2 * 1024 * 1024 * 1024))
MAX_SLICE_MEM_BYTES=$((4 * 1024 * 1024 * 1024))

while true; do
    CURRENT_TIME=$(date +%s%N) # nanoseconds

    # 1. Отримання метрик з cgroups v2
    CURRENT_MEM_BYTES=0
    CURRENT_TASKS=0
    CPU_USAGE_PERCENT="0.0"

    if [ -d "$CGROUP_PATH" ]; then
        # Читання поточної пам'яті
        if [ -f "${CGROUP_PATH}/memory.current" ]; then
            CURRENT_MEM_BYTES=$(cat "${CGROUP_PATH}/memory.current" 2>/dev/null || echo 0)
        fi

        # Читання кількості задач
        if [ -f "${CGROUP_PATH}/pids.current" ]; then
            CURRENT_TASKS=$(cat "${CGROUP_PATH}/pids.current" 2>/dev/null || echo 0)
        elif [ -f "${CGROUP_PATH}/cgroup.procs" ]; then
            CURRENT_TASKS=$(wc -l < "${CGROUP_PATH}/cgroup.procs" 2>/dev/null || echo 0)
        fi

        # Розрахунок реального CPU % за дельтою usage_usec
        if [ -f "${CGROUP_PATH}/cpu.stat" ]; then
            USAGE_USEC=$(grep "^usage_usec" "${CGROUP_PATH}/cpu.stat" | awk '{print $2}' || echo 0)

            if [ "$LAST_CHECK_TIME" -gt 0 ] && [ "$LAST_USAGE_USEC" -gt 0 ]; then
                DELTA_TIME_USEC=$(( (CURRENT_TIME - LAST_CHECK_TIME) / 1000 ))
                DELTA_USAGE_USEC=$(( USAGE_USEC - LAST_USAGE_USEC ))

                if [ "$DELTA_TIME_USEC" -gt 0 ] && [ "$DELTA_USAGE_USEC" -ge 0 ]; then
                    # Розрахунок % CPU: (delta_usage / delta_time) * 100
                    CPU_USAGE_PERCENT=$(awk "BEGIN {printf \"%.1f\", ($DELTA_USAGE_USEC / $DELTA_TIME_USEC) * 100}")
                fi
            fi

            LAST_USAGE_USEC="$USAGE_USEC"
            LAST_CHECK_TIME="$CURRENT_TIME"
        fi
    fi

    # Переведення пам'яті в МБ
    CURRENT_MEM_MB=$(( CURRENT_MEM_BYTES / 1024 / 1024 ))

    # 2. Знімок із systemd-cgtop
    CGTOP_SNAPSHOT=$(systemd-cgtop -b -n 1 2>/dev/null | grep -E "antigravity-ai|smartgarage|ollama|CGroup" | head -n 5 || true)

    # 3. Логування у файл
    STATUS_LINE="Slice: ${SLICE_NAME} | CPU: ${CPU_USAGE_PERCENT}% | Mem: ${CURRENT_MEM_MB}MB/4096MB | Tasks: ${CURRENT_TASKS}"
    log_entry "$STATUS_LINE"

    if [ -n "$CGTOP_SNAPSHOT" ]; then
        echo "$CGTOP_SNAPSHOT" | while read -r line; do
            log_entry "  [cgtop] $line"
        done
    fi

    # 4. Перевірка CPU порогу (> 75% протягом 30 секунд = 6 перевірок по 5с)
    # Перевірка числа через awk
    IS_HIGH_CPU=$(awk "BEGIN {print ($CPU_USAGE_PERCENT > 75.0) ? 1 : 0}")

    if [ "$IS_HIGH_CPU" -eq 1 ]; then
        CPU_HIGH_COUNT=$((CPU_HIGH_COUNT + 1))
        log_entry "  [WARN] CPU ${CPU_USAGE_PERCENT}% > 75% (тривалість: $((CPU_HIGH_COUNT * 5))с / 30с)"

        if [ "$CPU_HIGH_COUNT" -ge 6 ]; then
            # Перевірка кулдауну сповіщень (не частіше ніж раз на 5 хвилин = 60 циклів)
            if [ "$ALERT_COOLDOWN" -le 0 ]; then
                ALERT_MSG="⚠️ <b>[SmartGarage Alert] Високе навантаження CPU в AI Slice!</b>%0A%0A"
                ALERT_MSG+="• <b>Slice:</b> <code>${SLICE_NAME}</code>%0A"
                ALERT_MSG+="• <b>Поточний CPU:</b> <b>${CPU_USAGE_PERCENT}%</b> (поріг > 75%)%0A"
                ALERT_MSG+="• <b>Тривалість:</b> 30+ секунд%0A"
                ALERT_MSG+="• <b>Пам'ять зрізу:</b> ${CURRENT_MEM_MB} MB / 4096 MB%0A"
                ALERT_MSG+="• <b>Активних задач:</b> ${CURRENT_TASKS}%0A"
                ALERT_MSG+="<i>Ресурсні квоти cgroup захищають хост від деградації.</i>"

                send_telegram_alert "$ALERT_MSG"
                log_entry "  [ALERT] Telegram сповіщення про перевантаження CPU відправлено."
                ALERT_COOLDOWN=60 # 60 * 5s = 300 секунд кулдаун
            fi
        fi
    else
        CPU_HIGH_COUNT=0
    fi

    if [ "$ALERT_COOLDOWN" -gt 0 ]; then
        ALERT_COOLDOWN=$((ALERT_COOLDOWN - 1))
    fi

    # 5. Автоматичний перезапуск сервісів у разі перевищення MemoryMax
    CHECK_SERVICES=("smartgarage.service" "ollama.service")

    for SVC in "${CHECK_SERVICES[@]}"; do
        SVC_CGROUP="${CGROUP_PATH}/${SVC}"
        RESTART_NEEDED=false
        REASON=""

        if [ -d "$SVC_CGROUP" ]; then
            # Перевірка поточного споживання пам'яті сервісу
            if [ -f "${SVC_CGROUP}/memory.current" ]; then
                SVC_MEM=$(cat "${SVC_CGROUP}/memory.current" 2>/dev/null || echo 0)
                if [ "$SVC_MEM" -gt "$MAX_SERVICE_MEM_BYTES" ]; then
                    RESTART_NEEDED=true
                    REASON="Використання пам'яті ($((SVC_MEM / 1024 / 1024))MB) перевищило MemoryMax (2048MB)"
                fi
            fi

            # Перевірка подій memory.events (OOM або MAX)
            if [ -f "${SVC_CGROUP}/memory.events" ]; then
                MAX_EVENTS=$(grep "^max" "${SVC_CGROUP}/memory.events" | awk '{print $2}' || echo 0)
                OOM_EVENTS=$(grep "^oom_kill" "${SVC_CGROUP}/memory.events" | awk '{print $2}' || echo 0)

                if [ "$OOM_EVENTS" -gt 0 ]; then
                    RESTART_NEEDED=true
                    REASON="Зафіксовано OOM Kill події (кількість: $OOM_EVENTS)"
                elif [ "$MAX_EVENTS" -gt 5 ]; then
                    RESTART_NEEDED=true
                    REASON="Регулярне перевищення MemoryMax ліміту ($MAX_EVENTS подій)"
                fi
            fi
        fi

        # Виконання перезапуску за потреби
        if [ "$RESTART_NEEDED" = true ]; then
            log_entry "  [RECOVERY] 🚨 Перезапуск ${SVC}: ${REASON}"

            # Спроба перезапуску через systemctl (system або user)
            if systemctl is-active --quiet "$SVC" 2>/dev/null; then
                systemctl restart "$SVC" 2>/dev/null || true
            elif systemctl --user is-active --quiet "$SVC" 2>/dev/null; then
                systemctl --user restart "$SVC" 2>/dev/null || true
            fi

            RESTART_MSG="🚨 <b>[SmartGarage Self-Healing] Автоперезапуск сервісу!</b>%0A%0A"
            RESTART_MSG+="• <b>Сервіс:</b> <code>${SVC}</code>%0A"
            RESTART_MSG+="• <b>Причина:</b> ${REASON}%0A"
            RESTART_MSG+="• <b>Час:</b> $(date '+%Y-%m-%d %H:%M:%S')%0A"
            RESTART_MSG+="<i>Сервіс автоматично відновлено в межах квот пам'яті.</i>"

            send_telegram_alert "$RESTART_MSG"
            log_entry "  [RECOVERY] Сповіщення про перезапуск надіслано в Telegram."
            sleep 2
        fi
    done

    sleep 5
done
