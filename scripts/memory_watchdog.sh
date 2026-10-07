#!/usr/bin/env bash
# ==============================================================================
# scripts/memory_watchdog.sh
# Моніторинг та активний захист оперативної пам'яті (RAM Watchdog) на ASUS X413E
# Поріг спрацьовування: доступна RAM < 500 МБ
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Шлях до лог-файлу (системний або локальний fallback)
LOG_FILE="/var/log/antigravity-memory.log"
if [ ! -w "$(dirname "$LOG_FILE")" ] 2>/dev/null && [ "$EUID" -ne 0 ]; then
    mkdir -p "${PROJECT_ROOT}/logs"
    LOG_FILE="${PROJECT_ROOT}/logs/antigravity-memory.log"
fi

THRESHOLD_MB=500

# Функція логування
log_msg() {
    local timestamp
    timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    echo "[$timestamp] $1" | tee -a "$LOG_FILE"
}

# Отримання доступної пам'яті в МБ
get_available_ram_mb() {
    if [ -f /proc/meminfo ]; then
        local mem_avail_kb
        mem_avail_kb=$(grep -i "MemAvailable:" /proc/meminfo | awk '{print $2}')
        if [ -n "$mem_avail_kb" ]; then
            echo "$((mem_avail_kb / 1024))"
            return 0
        fi
    fi
    free -m | awk '/^Mem:/{print $7}'
}

# Отримання налаштувань Telegram
get_telegram_creds() {
    local token=""
    local chat_id=""

    # 1. Спроба з .env
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        token=$(grep -E "^(TELEGRAM_BOT_TOKEN|TG_TOKEN)=" "${PROJECT_ROOT}/.env" | head -n1 | cut -d'=' -f2- | tr -d "'\" " || true)
        chat_id=$(grep -E "^(TELEGRAM_ADMIN_CHAT_ID|TELEGRAM_CHAT_ID)=" "${PROJECT_ROOT}/.env" | head -n1 | cut -d'=' -f2- | tr -d "'\" " || true)
    fi

    # 2. Спроба з config/config.yaml
    if [ -z "$token" ] && [ -f "${PROJECT_ROOT}/config/config.yaml" ]; then
        token=$(grep -E "^[[:space:]]*bot_token:" "${PROJECT_ROOT}/config/config.yaml" | head -n1 | awk '{print $2}' | tr -d "'\" " || true)
    fi
    if [ -z "$chat_id" ] && [ -f "${PROJECT_ROOT}/config/config.yaml" ]; then
        chat_id=$(grep -E "^[[:space:]]*admin_chat_id:" "${PROJECT_ROOT}/config/config.yaml" | head -n1 | awk '{print $2}' | tr -d "'\" " || true)
    fi

    echo "$token|$chat_id"
}

# Відправка сповіщення у Telegram
send_telegram_alert() {
    local text="$1"
    local creds
    creds=$(get_telegram_creds)
    local token="${creds%%|*}"
    local chat_id="${creds##*|}"

    if [ -n "$token" ] && [ -n "$chat_id" ]; then
        curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
            -d "chat_id=${chat_id}" \
            -d "text=${text}" \
            -d "parse_mode=HTML" >/dev/null 2>&1 || true
    fi
}

# Одноразова перевірка стану пам'яті
check_memory() {
    local avail_mb
    avail_mb=$(get_available_ram_mb)

    if [ "$avail_mb" -lt "$THRESHOLD_MB" ]; then
        local alert_text="🚨 <b>SmartGarage Memory Watchdog (ASUS X413E)</b>%0A⚠️ <b>Критично мало RAM:</b> ${avail_mb} МБ (поріг: ${THRESHOLD_MB} МБ)%0A🔄 Виконується очищення кешу пам'яті (drop_caches)..."
        log_msg "УВАГА: Критично низький рівень доступної RAM: ${avail_mb} МБ (< ${THRESHOLD_MB} МБ)."
        send_telegram_alert "$alert_text"

        # 1. Скидання кешів ядра Linux
        if [ "$EUID" -eq 0 ]; then
            log_msg "Виконується sync && echo 3 > /proc/sys/vm/drop_caches..."
            sync
            echo 3 > /proc/sys/vm/drop_caches || true
            sleep 2
        else
            log_msg "Попередження: немає прав root для drop_caches. Запустіть скрипт від root."
        fi

        # 2. Повторна перевірка
        local new_avail_mb
        new_avail_mb=$(get_available_ram_mb)
        log_msg "RAM після drop_caches: ${new_avail_mb} МБ."

        if [ "$new_avail_mb" -lt "$THRESHOLD_MB" ]; then
            log_msg "Очищення кешу не допомогло (RAM: ${new_avail_mb} МБ). Пошук та перезапуск важкого сервісу..."

            local restarted_service="none"
            # Перевіряємо Ollama (системний або Docker)
            if systemctl is-active --quiet ollama 2>/dev/null; then
                log_msg "Перезапуск системного сервісу ollama..."
                systemctl restart ollama || true
                restarted_service="ollama.service"
            elif command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q "^ollama$"; then
                log_msg "Перезапуск Docker-контейнера ollama..."
                docker restart ollama >/dev/null 2>&1 || true
                restarted_service="docker container ollama"
            elif systemctl is-active --quiet smartgarage 2>/dev/null; then
                log_msg "Перезапуск сервісу smartgarage..."
                systemctl restart smartgarage || true
                restarted_service="smartgarage.service"
            fi

            local final_avail_mb
            sleep 2
            final_avail_mb=$(get_available_ram_mb)
            local failover_text="⚠️ <b>Memory Watchdog:</b> Перезапущено сервіс <code>${restarted_service}</code>.%0A✅ Доступна RAM після перезапуску: ${final_avail_mb} МБ."
            log_msg "Сервіс ${restarted_service} перезапущено. Доступно RAM: ${final_avail_mb} МБ."
            send_telegram_alert "$failover_text"
        else
            log_msg "Очищення кешу успішно відновило пам'ять до ${new_avail_mb} МБ."
        fi
    fi
}

# Режим роботи: цикл (кожні 10 сек) або одноразовий запуск
if [ "${1:-}" = "--daemon" ] || [ "${1:-}" = "-d" ] || [ "${1:-}" = "--loop" ]; then
    log_msg "Memory Watchdog запущено у режимі демона (інтервал: 10 секунд)."
    while true; do
        check_memory
        sleep 10
    done
else
    # Одноразовий виклик (наприклад, через systemd timer)
    check_memory
fi
