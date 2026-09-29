#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Apply Systemd Slice Isolation for AI Processes
# Path: scripts/apply_systemd_slice.sh
# Configures: antigravity-ai.slice, service overrides, monitor & log rotation
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${PROJECT_ROOT}/config/systemd"

echo "=========================================================="
echo " [SmartGarage] Встановлення systemd slice для AI-процесів"
echo " Slice: antigravity-ai.slice (CPU: 80%, RAM: 4GB, Swap: 0)"
echo "=========================================================="

# 1. Перевірка наявності cgroups v2
if [ "$(stat -fc %T /sys/fs/cgroup/)" != "cgroup2fs" ]; then
    echo "ПОПЕРЕДЖЕННЯ: Ядро не використовує чистий cgroups v2. Деякі ліміти можуть не підтримуватися."
fi

# 2. Копіювання файлу зрізу (antigravity-ai.slice)
echo "==> 1. Встановлення /etc/systemd/system/antigravity-ai.slice..."
sudo cp "${CONFIG_DIR}/antigravity-ai.slice" /etc/systemd/system/antigravity-ai.slice
sudo chmod 644 /etc/systemd/system/antigravity-ai.slice

# 3. Налаштування override для ollama.service
echo "==> 2. Налаштування override для ollama.service (CPU: 40%, RAM: 2GB)..."
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo cp "${CONFIG_DIR}/ollama.service.d/override.conf" /etc/systemd/system/ollama.service.d/override.conf
sudo chmod 644 /etc/systemd/system/ollama.service.d/override.conf

# 4. Налаштування базового сервісу та override для smartgarage.service
echo "==> 3. Налаштування smartgarage.service та override (CPU: 30%, RAM: 2GB)..."
if [ ! -f /etc/systemd/system/smartgarage.service ]; then
    sudo cp "${CONFIG_DIR}/smartgarage.service" /etc/systemd/system/smartgarage.service
    sudo chmod 644 /etc/systemd/system/smartgarage.service
fi

sudo mkdir -p /etc/systemd/system/smartgarage.service.d
sudo cp "${CONFIG_DIR}/smartgarage.service.d/override.conf" /etc/systemd/system/smartgarage.service.d/override.conf
sudo chmod 644 /etc/systemd/system/smartgarage.service.d/override.conf

# 5. Встановлення скрипта моніторингу /usr/local/bin/monitor-ai-resources.sh
echo "==> 4. Встановлення /usr/local/bin/monitor-ai-resources.sh..."
sudo cp "${PROJECT_ROOT}/scripts/monitor-ai-resources.sh" /usr/local/bin/monitor-ai-resources.sh
sudo chmod 755 /usr/local/bin/monitor-ai-resources.sh

# 6. Встановлення cron щотижневого очищення логів та logrotate
echo "==> 5. Встановлення щотижневого cron-завдання та logrotate..."
sudo cp "${CONFIG_DIR}/clean-antigravity-ai-logs" /etc/cron.weekly/clean-antigravity-ai-logs
sudo chmod 755 /etc/cron.weekly/clean-antigravity-ai-logs

sudo cp "${CONFIG_DIR}/antigravity-ai-resources.logrotate" /etc/logrotate.d/antigravity-ai-resources
sudo chmod 644 /etc/logrotate.d/antigravity-ai-resources

# 7. Перезавантаження конфігурацій systemd
echo "==> 6. Перезавантаження конфігурації systemd (daemon-reload)..."
sudo systemctl daemon-reload

# 8. Запуск та активація slice
echo "==> 7. Активація зрізу antigravity-ai.slice..."
sudo systemctl start antigravity-ai.slice

# 9. Перевірка та верифікація параметрів зрізу
echo ""
echo "=========================================================="
echo " [РЕЗУЛЬТАТИ ВЕРИФІКАЦІЇ СИСТЕМНОГО ЗРІЗУ]"
echo "=========================================================="
systemctl show antigravity-ai.slice --property=CPUQuotaPerSecUSec,CPUWeight,MemoryMax,MemoryHigh,MemorySwapMax,TasksMax,IOWeight

echo ""
echo "Служби в override:"
echo -n "• ollama.service: "
systemctl show ollama.service --property=Slice,CPUQuotaPerSecUSec,MemoryMax 2>/dev/null || echo "override встановлено"

echo -n "• smartgarage.service: "
systemctl show smartgarage.service --property=Slice,CPUQuotaPerSecUSec,MemoryMax 2>/dev/null || echo "override встановлено"

echo ""
echo "=========================================================="
echo " [OK] Systemd slice antigravity-ai.slice успішно активовано!"
echo "=========================================================="
