#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - PipeWire & Bluetooth Audio Real-Time Monitor
# Monitors: XRUNs, buffer underruns/overruns, DSP errors, and quantum status
# ==============================================================================
set -euo pipefail

COLOR_RESET="\033[0m"
COLOR_RED="\033[1;31m"
COLOR_GREEN="\033[1;32m"
COLOR_YELLOW="\033[1;33m"
COLOR_CYAN="\033[1;36m"
COLOR_BOLD="\033[1m"

MODE="${1:---live}"

echo -e "${COLOR_CYAN}==========================================================${COLOR_RESET}"
echo -e "${COLOR_BOLD} [SmartGarage] Моніторинг Аудіосистеми (PipeWire / Bluetooth)${COLOR_RESET}"
echo -e "${COLOR_CYAN}==========================================================${COLOR_RESET}"

case "$MODE" in
    --top|-t)
        echo -e "${COLOR_GREEN}--> Запуск інтерактивного монітора вузлів pw-top...${COLOR_RESET}"
        echo "Зверніть увагу на колонку 'ERR' (кількість xruns)."
        sleep 1
        exec pw-top
        ;;

    --journal|-j)
        echo -e "${COLOR_GREEN}--> Відстеження логів xruns та underrun у реальному часі...${COLOR_RESET}"
        echo "Очікування подій переповнення або спустошення буферів (Ctrl+C для виходу)..."
        exec journalctl --user -u pipewire -u wireplumber -f \
            | grep --line-buffered -i -E "xrun|underrun|overrun|stalled|drop|timeout" \
            | while read -r line; do
                echo -e "${COLOR_RED}[XRUN EVENT]${COLOR_RESET} $line"
            done
        ;;

    --check|-c)
        echo -e "${COLOR_GREEN}--> Перевірка поточної конфігурації кванту та частоти...${COLOR_RESET}"
        pw-cli info 0 | grep -E "default.clock" || true

        echo ""
        echo -e "${COLOR_GREEN}--> Останні помилки та xruns у журналі:${COLOR_RESET}"
        ERRORS=$(journalctl --user -u pipewire -u wireplumber --since "1 hour ago" --no-pager \
            | grep -i -E "xrun|underrun|overrun|stalled" || true)

        if [ -z "$ERRORS" ]; then
            echo -e "${COLOR_GREEN}✓ За останню годину xruns або underruns не зафіксовано.${COLOR_RESET}"
        else
            echo -e "${COLOR_YELLOW}$ERRORS${COLOR_RESET}"
        fi
        ;;

    --live|-l|*)
        echo -e "Режим: ${COLOR_BOLD}Live Diagnostics & XRUN Watcher${COLOR_RESET}"
        echo -e "Для переходу в повноекранний топ запустіть: ${COLOR_CYAN}$0 --top${COLOR_RESET}"
        echo -e "Для постійного журналу запустіть: ${COLOR_CYAN}$0 --journal${COLOR_RESET}"
        echo "----------------------------------------------------------"

        # 1. Поточні параметри тактового генератора PipeWire
        echo -e "${COLOR_BOLD}Поточний статус DSP Clock:${COLOR_RESET}"
        pw-cli info 0 | grep -E "default.clock.(rate|quantum|min-quantum|max-quantum)" | sed 's/^[ \t]*/  /' || true

        echo ""
        # 2. Статус активних аудіопристроїв та кодеків
        echo -e "${COLOR_BOLD}Активні пристрої відтворення (Sinks):${COLOR_RESET}"
        if command -v pactl >/dev/null 2>&1; then
            pactl list sinks | grep -E "(Назва|Name|Опис|Description|bluetooth.codec|Частотна специфікація|Sample Specification)" | sed 's/^[ \t]*/  /' || true
        fi

        echo ""
        echo -e "${COLOR_GREEN}--> Запуск фонового спостереження за xruns (Ctrl+C для завершення)...${COLOR_RESET}"
        journalctl --user -u pipewire -u wireplumber -f -n 0 \
            | grep --line-buffered -i -E "xrun|underrun|overrun|stalled|timeout" \
            | while read -r line; do
                echo -e "${COLOR_RED}[$(date '+%T')] [XRUN/DROP]${COLOR_RESET} $line"
            done
        ;;
esac
