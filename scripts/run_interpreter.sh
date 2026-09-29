#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Open Interpreter Launcher
# Model: Qwen 2.5 Coder 7B (Ollama)
# Mode: Isolated Docker Container (Default) or Local Host Environment
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${PROJECT_ROOT}/config/interpreter_config.yaml"
SCRATCH_DIR="/tmp/smartgarage_sandbox_scratch"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

# Default mode: docker isolation
MODE="docker"
EXTRA_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --local|--host)
            MODE="local"
            shift
            ;;
        --docker)
            MODE="docker"
            shift
            ;;
        --build)
            echo "==> Збірка Docker образу ізольованого середовища..."
            (cd "${PROJECT_ROOT}" && docker-compose build)
            shift
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "=========================================================="
echo " [SmartGarage] Запуск Open Interpreter"
echo " Модель: Ollama / Qwen 2.5 Coder 7B"
echo " Режим:  ${MODE^^} $([ "$MODE" = "docker" ] && echo "(Ізольований: 2 CPU, 2GB RAM, Read-Only Mount)")"
echo " Конфіг: ${CONFIG_FILE}"
echo "=========================================================="

# 1. Перевірка наявності конфігураційного файлу
if [ ! -f "${CONFIG_FILE}" ]; then
    echo "ПОМИЛКА: Конфігураційний файл не знайдено: ${CONFIG_FILE}"
    exit 1
fi

# 2. Перевірка доступності сервісу Ollama
if ! curl -s -f "${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    echo "ПОПЕРЕДЖЕННЯ: Ollama не відповідає на ${OLLAMA_HOST}."
    echo "Запустіть сервіс Ollama або виконайте scripts/setup_ollama_model.sh"
    read -r -p "Бажаєте запустити скрипт налаштування моделі зараз? [y/N]: " choice
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        "${SCRIPT_DIR}/setup_ollama_model.sh"
    fi
fi

# 3. Підготовка директорії тимчасового буфера (scratchpad)
mkdir -p "${SCRATCH_DIR}"

if [ "${MODE}" = "docker" ]; then
    echo "==> Перевірка наявності Docker образу..."
    if ! docker images -q smartgarage/interpreter-sandbox:latest | grep -q .; then
        echo "--> Збірка образу smartgarage/interpreter-sandbox:latest..."
        (cd "${PROJECT_ROOT}" && docker-compose build)
    fi

    echo "==> Запуск Open Interpreter в ізольованому Docker-контейнері..."
    echo "    - Робоча директорія змонтована як READ-ONLY: /workspace"
    echo "    - Обмеження: 2 CPU ядра, 2GB RAM"
    echo "    - Безпечний режим: safe_mode: true, auto_run: false"
    echo "----------------------------------------------------------"

    # Запуск контейнера з інтерактивним терміналом (TTY)
    (cd "${PROJECT_ROOT}" && docker-compose run --rm \
        interpreter \
        interpreter --profile /workspace/config/interpreter_config.yaml "${EXTRA_ARGS[@]:+${EXTRA_ARGS[@]}}")

elif [ "${MODE}" = "local" ]; then
    echo "==> Підготовка локального середовища Open Interpreter..."
    VENV_PATH="${HOME}/AI/OpenInterpreter/venv"

    if [ ! -f "${VENV_PATH}/bin/interpreter" ]; then
        echo "ПОМИЛКА: Не знайдено віртуальне середовище в ${VENV_PATH}"
        exit 1
    fi

    # Створення профілю у ~/.config/open-interpreter/profiles/
    USER_PROFILES_DIR="${HOME}/.config/open-interpreter/profiles"
    mkdir -p "${USER_PROFILES_DIR}"
    cp "${CONFIG_FILE}" "${USER_PROFILES_DIR}/smartgarage-qwen.yaml"

    echo "==> Запуск локального Open Interpreter з профілем smartgarage-qwen..."
    echo "----------------------------------------------------------"

    source "${VENV_PATH}/bin/activate"
    interpreter --profile smartgarage-qwen "${EXTRA_ARGS[@]:+${EXTRA_ARGS[@]}}"
fi
