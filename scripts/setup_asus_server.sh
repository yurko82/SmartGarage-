#!/usr/bin/env bash
# ==============================================================================
# Скрипт повної системної оптимізації та встановлення сервісів 24/7 для ASUS X413E
# SmartGarage Server Infrastructure
# ==============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}🚀 Початок налаштування сервера SmartGarage на ASUS VivoBook 14 X413E${NC}"
echo -e "${BLUE}====================================================================${NC}"

# Перевірка запуску з root/sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Будь ласка, запустіть цей скрипт через sudo: sudo $0${NC}"
    exit 1
fi

TARGET_USER="yurko"

# ------------------------------------------------------------------------------
# 1. Налаштування роботи із закритою кришкою та блокування сну
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}⚙️  [1/6] Налаштування режиму закритої кришки (Lid Switch)...${NC}"
mkdir -p /etc/systemd/logind.conf.d/
cat << 'EOF' > /etc/systemd/logind.conf.d/00-laptop-server.conf
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
IdleAction=ignore
EOF

echo "Перезапуск systemd-logind..."
systemctl restart systemd-logind

echo -e "${YELLOW}🛑 [2/6] Маскування sleep / suspend / hibernate цілей...${NC}"
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

# ------------------------------------------------------------------------------
# 2. Встановлення базових пакетів
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}📦 [3/6] Оновлення репозиторіїв та встановлення системних пакетів...${NC}"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    openssh-server \
    git \
    curl \
    wget \
    rsync \
    jq \
    mosquitto \
    mosquitto-clients \
    bluez \
    wireplumber \
    pipewire \
    libglib2.0-dev \
    build-essential \
    lm-sensors

# Активація SSH
systemctl enable --now ssh

# ------------------------------------------------------------------------------
# 3. Налаштування Mosquitto MQTT брокера
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}📡 [4/6] Конфігурація Mosquitto MQTT брокера...${NC}"
mkdir -p /etc/mosquitto/conf.d/
cat << 'EOF' > /etc/mosquitto/conf.d/smartgarage.conf
listener 1883
protocol mqtt
allow_anonymous true

listener 9001
protocol websockets
allow_anonymous true
EOF

systemctl enable mosquitto
systemctl restart mosquitto

# ------------------------------------------------------------------------------
# 4. Встановлення Docker та Docker Compose
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}🐳 [5/6] Встановлення офіційного Docker Engine...${NC}"
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
else
    echo "Docker вже встановлено."
fi

# Додавання користувача yurko до груп docker та dialout (для доступу до ESP32)
usermod -aG docker "$TARGET_USER" || true
usermod -aG dialout "$TARGET_USER" || true

# ------------------------------------------------------------------------------
# 5. Встановлення Tailscale
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}🌐 [6/6] Встановлення Tailscale...${NC}"
if ! command -v tailscale &> /dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    systemctl enable --now tailscaled
else
    echo "Tailscale вже встановлено."
fi

echo -e "\n${GREEN}====================================================================${NC}"
echo -e "${GREEN}✅ Системне налаштування сервера 24/7 успішно завершено!${NC}"
echo -e "${GREEN}====================================================================${NC}"
echo -e "Для підключення Tailscale виконайте: ${BLUE}sudo tailscale up --ssh${NC}"
echo -e "Після додавання до групи docker рекомендується перезайти у термінал або виконати: ${BLUE}newgrp docker${NC}"
