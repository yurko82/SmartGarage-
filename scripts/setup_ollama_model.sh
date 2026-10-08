#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Ollama Qwen 2.5 Coder 1.5B Setup Script (8GB RAM Optimized)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODELFILE_PATH="${PROJECT_ROOT}/config/Modelfile.qwen2.5-coder"
MODEL_NAME="qwen2.5-coder:1.5b"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

echo "=========================================================="
echo " [SmartGarage] Ollama Model Provisioning: ${MODEL_NAME}"
echo "=========================================================="

# 1. Check if Ollama service is reachable
check_ollama_service() {
    if curl -s -f "${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

echo -n "==> Перевірка доступності сервісу Ollama (${OLLAMA_HOST})... "
if ! check_ollama_service; then
    echo "НЕАКТИВНИЙ"
    echo "--> Сервіс Ollama не відповідає на ${OLLAMA_HOST}."

    # Перевірка чи встановлено CLI ollama
    if command -v ollama >/dev/null 2>&1; then
        echo "--> Спроба запуску фонового сервісу ollama serve..."
        ollama serve >/dev/null 2>&1 &
        sleep 3
    elif docker ps -a --format '{{.Names}}' | grep -q "^ollama$"; then
        echo "--> Виявлено Docker-контейнер 'ollama'. Запуск контейнера..."
        docker start ollama >/dev/null
        sleep 3
    fi

    if ! check_ollama_service; then
        echo ""
        echo "ПОМИЛКА: Не вдалося з'єднатися з Ollama."
        echo "Будь ласка, запустіть Ollama одним із способів:"
        echo "  1) Встановити та запустити локально: curl -fsSL https://ollama.com/install.sh | sh && ollama serve"
        echo "  2) Або запустити через Docker: docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama"
        exit 1
    fi
fi
echo "OK"

# 2. Check if the model already exists in Ollama
echo -n "==> Перевірка наявності моделі '${MODEL_NAME}'... "
MODEL_EXISTS=false

if command -v ollama >/dev/null 2>&1; then
    if ollama list | awk '{print $1}' | grep -q "^${MODEL_NAME}$"; then
        MODEL_EXISTS=true
    fi
elif docker ps --format '{{.Names}}' | grep -q "^ollama$"; then
    if docker exec ollama ollama list | awk '{print $1}' | grep -q "^${MODEL_NAME}$"; then
        MODEL_EXISTS=true
    fi
else
    # Fallback checking via REST API
    TAGS_JSON=$(curl -s "${OLLAMA_HOST}/api/tags" || echo "{}")
    if echo "${TAGS_JSON}" | grep -q "\"${MODEL_NAME}\""; then
        MODEL_EXISTS=true
    fi
fi

if [ "${MODEL_EXISTS}" = true ]; then
    echo "ЗНАЙДЕНО"
    echo "--> Модель ${MODEL_NAME} вже завантажена в Ollama."
else
    echo "НЕ ЗНАЙДЕНО"
    echo "==> Завантаження базової моделі ${MODEL_NAME} (це може зайняти деякий час)..."
    if command -v ollama >/dev/null 2>&1; then
        ollama pull "${MODEL_NAME}"
    elif docker ps --format '{{.Names}}' | grep -q "^ollama$"; then
        echo "--> Завантаження через docker exec ollama..."
        docker exec ollama ollama pull "${MODEL_NAME}"
    else
        echo "--> Завантаження через REST API..."
        curl -X POST "${OLLAMA_HOST}/api/pull" -d "{\"name\": \"${MODEL_NAME}\", \"stream\": false}"
    fi
    echo "--> Завантаження ${MODEL_NAME} успішно завершено."
fi

# 3. Apply custom Modelfile parameters (num_ctx, temperature, top_p, repeat_penalty)
if [ ! -f "${MODELFILE_PATH}" ]; then
    echo "ПОМИЛКА: Файл Modelfile не знайдено за шляхом: ${MODELFILE_PATH}"
    exit 1
fi

echo "==> Застосування кастомних параметрів з Modelfile..."
echo "    - num_ctx: 4096"
echo "    - temperature: 0.1"
echo "    - top_p: 0.9"
echo "    - repeat_penalty: 1.1"

if command -v ollama >/dev/null 2>&1; then
    ollama create "${MODEL_NAME}" -f "${MODELFILE_PATH}"
else
    # Create via Docker or REST API if ollama CLI is in container
    if docker ps --format '{{.Names}}' | grep -q "^ollama$"; then
        docker cp "${MODELFILE_PATH}" ollama:/tmp/Modelfile
        docker exec ollama ollama create "${MODEL_NAME}" -f /tmp/Modelfile
    else
        echo "--> Створення через Ollama REST API..."
        MODELFILE_CONTENT=$(cat "${MODELFILE_PATH}")
        # Build JSON payload using jq if available or python
        PAYLOAD=$(python3 -c "import json; print(json.dumps({'name': '${MODEL_NAME}', 'modelfile': '''${MODELFILE_CONTENT}''', 'stream': False}))")
        curl -s -X POST "${OLLAMA_HOST}/api/create" -H "Content-Type: application/json" -d "${PAYLOAD}" >/dev/null
    fi
fi

# 4. Verify configuration
echo "==> Перевірка конфігурації моделі ${MODEL_NAME}:"
if command -v ollama >/dev/null 2>&1; then
    ollama show "${MODEL_NAME}" --parameters || true
elif docker ps --format '{{.Names}}' | grep -q "^ollama$"; then
    docker exec ollama ollama show "${MODEL_NAME}" --parameters || true
else
    curl -s "${OLLAMA_HOST}/api/show" -d "{\"name\": \"${MODEL_NAME}\"}" | jq '.parameters // .' 2>/dev/null || true
fi

echo ""
echo "=========================================================="
echo " [OK] Модель ${MODEL_NAME} успішно підготовлена до роботи!"
echo "=========================================================="
