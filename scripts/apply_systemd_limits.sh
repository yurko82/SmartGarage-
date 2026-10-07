#!/usr/bin/env bash
# ==============================================================================
# scripts/apply_systemd_limits.sh
# Встановлення systemd override конфігурацій для лімітування пам'яті та процесора
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OVERRIDES_DIR="${PROJECT_ROOT}/systemd/overrides"

echo -e "${BLUE}=== SmartGarage: Встановлення systemd override лімітів ===${NC}"

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Помилка: для копіювання в /etc/systemd потрібні права root (sudo).${NC}" >&2
    echo -e "Будь ласка, виконайте: ${YELLOW}sudo $0${NC}" >&2
    exit 1
fi

SYSTEM_DIR="/etc/systemd/system"
USER_DIR="/etc/systemd/user"
mkdir -p "$SYSTEM_DIR" "$USER_DIR"

# 1. ollama.service
echo -e "Встановлення лімітів для ollama.service..."
mkdir -p "${SYSTEM_DIR}/ollama.service.d"
cp "${OVERRIDES_DIR}/ollama.service.d/override.conf" "${SYSTEM_DIR}/ollama.service.d/override.conf"

# 2. smartgarage.service
echo -e "Встановлення лімітів для smartgarage.service..."
mkdir -p "${SYSTEM_DIR}/smartgarage.service.d"
cp "${OVERRIDES_DIR}/smartgarage.service.d/override.conf" "${SYSTEM_DIR}/smartgarage.service.d/override.conf"

# 3. antigravity-voice.service
echo -e "Встановлення лімітів для antigravity-voice.service..."
mkdir -p "${SYSTEM_DIR}/antigravity-voice.service.d"
cp "${OVERRIDES_DIR}/antigravity-voice.service.d/override.conf" "${SYSTEM_DIR}/antigravity-voice.service.d/override.conf"

# 4. docker.service
echo -e "Встановлення лімітів для docker.service..."
mkdir -p "${SYSTEM_DIR}/docker.service.d"
cp "${OVERRIDES_DIR}/docker.service.d/override.conf" "${SYSTEM_DIR}/docker.service.d/override.conf"

# 5. wireplumber.service (як системний, так і користувацький рівень)
echo -e "Встановлення захисту від OOM killer для wireplumber.service..."
mkdir -p "${SYSTEM_DIR}/wireplumber.service.d" "${USER_DIR}/wireplumber.service.d"
cp "${OVERRIDES_DIR}/wireplumber.service.d/override.conf" "${SYSTEM_DIR}/wireplumber.service.d/override.conf"
cp "${OVERRIDES_DIR}/wireplumber.service.d/override.conf" "${USER_DIR}/wireplumber.service.d/override.conf"

# Перезавантаження конфігурації systemd
echo -e "\n${BLUE}Перезавантаження демона systemd...${NC}"
systemctl daemon-reload

echo -e "${GREEN}✓ Усі ліміти успішно встановлено та застосовано!${NC}"
echo -e "Перевірити накладені параметри можна командою:"
echo -e "${YELLOW}systemctl show <сервіс> -p MemoryMax,MemorySwapMax,CPUQuota,MemoryMin${NC}"
