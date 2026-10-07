#!/usr/bin/env bash
# ==============================================================================
# scripts/setup_zram_x413e.sh
# Налаштування ZRAM (zstd, 50% RAM) та відключення дискового swap на ASUS X413E
# Платформа: Linux Mint 22 (база Ubuntu 24.04 Noble Numbat)
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== SmartGarage: Налаштування ZRAM для 8 ГБ RAM (ASUS X413E) ===${NC}"

# Перевірка прав root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Помилка: цей скрипт вимагає прав суперкористувача (root).${NC}" >&2
    echo -e "Будь ласка, запустіть: ${YELLOW}sudo $0${NC}" >&2
    exit 1
fi

# 1. Перевірка дистрибутива
echo -e "\n${BLUE}1. Перевірка операційної системи...${NC}"
OS_NAME="Unknown"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME="${NAME:-Linux} ${VERSION_ID:-}"
fi
echo -e "Виявлено ОС: ${GREEN}${OS_NAME}${NC}"

# 2. Встановлення zram-tools
echo -e "\n${BLUE}2. Встановлення пакету zram-tools...${NC}"
apt-get update -qq
apt-get install -y -qq zram-tools

# 3. Налаштування /etc/default/zramswap
echo -e "\n${BLUE}3. Конфігурація /etc/default/zramswap...${NC}"
if [ -f /etc/default/zramswap ]; then
    cp /etc/default/zramswap /etc/default/zramswap.bak.$(date +%Y%m%d%H%M%S)
fi

cat << 'EOF' > /etc/default/zramswap
# Конфігурація zramswap для SmartGarage на ASUS X413E (8GB RAM)
# Стиснення за алгоритмом zstd (найкращий баланс швидкості та коефіцієнта ~3:1)
ALGO=zstd

# 50% від загального обсягу RAM (для 8 ГБ це ~4 ГБ стисненої RAM = ~12 ГБ віртуальної пам'яті)
PERCENT=50

# Пріоритет вищий за будь-який інший swap
PRIORITY=100
EOF
echo -e "${GREEN}✓ /etc/default/zramswap успішно сконфігуровано (ALGO=zstd, PERCENT=50, PRIORITY=100)${NC}"

# 4. Вимкнення дискового swap на SSD та оновлення /etc/fstab
echo -e "\n${BLUE}4. Вимкнення дискового swap для збереження ресурсу SSD...${NC}"
swapoff -a || true

if [ -f /etc/fstab ]; then
    cp /etc/fstab /etc/fstab.bak.$(date +%Y%m%d%H%M%S)
    # Коментуємо всі активні рядки з типом swap
    sed -i '/swap/ {/^[[:space:]]*#/! s/^/# SmartGarage SSD Protection: /}' /etc/fstab
    echo -e "${GREEN}✓ Дисковий swap закоментовано у /etc/fstab (бекап створено)${NC}"
fi

# 5. Запуск та перезапуск zram-сервісу
echo -e "\n${BLUE}5. Активація та перезапуск служби zramswap...${NC}"
systemctl daemon-reload
systemctl enable zramswap
systemctl restart zramswap

# 6. Перевірка статусу
echo -e "\n${GREEN}=== ПЕРЕВІРКА СТАНУ ZRAM ТА ПАМ'ЯТІ ===${NC}"
echo -e "${BLUE}zramctl:${NC}"
zramctl || true

echo -e "\n${BLUE}free -h:${NC}"
free -h

echo -e "\n${GREEN}✓ Налаштування ZRAM успішно завершено!${NC}"
