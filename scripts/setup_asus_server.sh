#!/usr/bin/env bash
# ==============================================================================
# Скрипт системної оптимізації та встановлення сервісів 24/7 для ASUS X413E
# SmartGarage Server Infrastructure (Linux Mint 22.x / Ubuntu 24.04 Noble)
# ==============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}🚀 Завершення налаштування Docker та Tailscale на ASUS X413E${NC}"
echo -e "${BLUE}====================================================================${NC}"

# Перевірка запуску з root/sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Будь ласка, запустіть цей скрипт через sudo: sudo $0${NC}"
    exit 1
fi

TARGET_USER="yurko"

# ------------------------------------------------------------------------------
# 1. Налаштування режиму закритої кришки (якщо ще не налаштовано)
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}⚙️  [1/4] Перевірка режиму закритої кришки (Lid Switch)...${NC}"
mkdir -p /etc/systemd/logind.conf.d/
cat << 'EOF' > /etc/systemd/logind.conf.d/00-laptop-server.conf
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
IdleAction=ignore
EOF
systemctl restart systemd-logind

# ------------------------------------------------------------------------------
# 2. Маскування sleep цілей
# ------------------------------------------------------------------------------
echo -e "${YELLOW}🛑 [2/4] Маскування sleep / suspend / hibernate...${NC}"
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || true

# ------------------------------------------------------------------------------
# 3. Встановлення Docker CE для Linux Mint 22 (база Ubuntu noble)
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}🐳 [3/4] Встановлення офіційного Docker Engine (Ubuntu Noble)...${NC}"
# Очищення некоректного Debian trixie репозиторію
rm -f /etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.asc

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

systemctl enable --now docker

# Додавання прав користувачеві
usermod -aG docker "$TARGET_USER" || true
usermod -aG dialout "$TARGET_USER" || true

# ------------------------------------------------------------------------------
# 4. Встановлення Tailscale
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}🌐 [4/4] Встановлення Tailscale...${NC}"
if ! command -v tailscale &> /dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    systemctl enable --now tailscaled
else
    echo "Tailscale вже встановлено."
fi

echo -e "\n${GREEN}====================================================================${NC}"
echo -e "${GREEN}✅ Налаштування Docker та Tailscale успішно завершено!${NC}"
echo -e "${GREEN}====================================================================${NC}"
echo -e "Для підключення Tailscale виконайте: ${BLUE}sudo tailscale up --ssh${NC}"
echo -e "Для застосування групи docker у поточному сеансі виконайте: ${BLUE}newgrp docker${NC}"
