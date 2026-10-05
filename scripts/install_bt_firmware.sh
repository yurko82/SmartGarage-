#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRMWARE_SRC="$SCRIPT_DIR/BCM20702A1-0a5c-21f4.hcd"

echo "=========================================================="
echo "Встановлення мікропрограми Broadcom BCM20702 & вимкнення USB autosuspend"
echo "=========================================================="

if [ ! -f "$FIRMWARE_SRC" ]; then
    echo "Завантаження BCM20702A1-0a5c-21f4.hcd..."
    curl -fLo "$FIRMWARE_SRC" https://raw.githubusercontent.com/winterheart/broadcom-bt-firmware/master/brcm/BCM20702A1-0a5c-21f4.hcd
fi

echo "1. 📦 Копіювання мікропрограми Broadcom у /lib/firmware/brcm/..."
sudo mkdir -p /lib/firmware/brcm/
sudo cp "$FIRMWARE_SRC" /lib/firmware/brcm/BCM20702A1-0a5c-21f4.hcd
sudo chmod 644 /lib/firmware/brcm/BCM20702A1-0a5c-21f4.hcd

echo "2. ⚙️  Вимкнення USB autosuspend для запобігання link tx timeout..."
echo "options btusb enable_autosuspend=0 reset=1" | sudo tee /etc/modprobe.d/btusb.conf

echo "3. 🔄 Перезапуск драйвера btusb та сервісу bluetooth..."
sudo modprobe -r btusb || true
sleep 1
sudo modprobe btusb
sudo systemctl restart bluetooth
rfkill unblock bluetooth 2>/dev/null || true

# Відключення autosuspend напряму в sysfs, якщо пристрій присутній
for dev in /sys/bus/usb/devices/*/power/control; do
    if [ -f "$dev" ]; then
        echo "on" | sudo tee "$dev" >/dev/null 2>&1 || true
    fi
done

echo "✅ Готово! Перевірка завантаження патчу в ядрі (dmesg):"
dmesg | grep -iE "BCM|firmware" | tail -n 8

echo "=========================================================="
echo "Мікропрограму встановлено, USB autosuspend вимкнено."
