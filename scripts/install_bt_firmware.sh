#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRMWARE_SRC="$SCRIPT_DIR/BCM20702A1-0a5c-21f4.hcd"

if [ ! -f "$FIRMWARE_SRC" ]; then
    echo "Завантаження BCM20702A1-0a5c-21f4.hcd..."
    curl -fLo "$FIRMWARE_SRC" https://raw.githubusercontent.com/winterheart/broadcom-bt-firmware/master/brcm/BCM20702A1-0a5c-21f4.hcd
fi

echo "📦 Копіювання мікропрограми Broadcom у /lib/firmware/brcm/..."
sudo cp "$FIRMWARE_SRC" /lib/firmware/brcm/
sudo chmod 644 /lib/firmware/brcm/BCM20702A1-0a5c-21f4.hcd

echo "🔄 Перезапуск драйвера та служби Bluetooth..."
sudo modprobe -r btusb || true
sleep 1
sudo modprobe btusb
sudo systemctl restart bluetooth
rfkill unblock bluetooth 2>/dev/null || true

echo "✅ Готово! Перевірка завантаження патчу в ядрі:"
dmesg | grep -iE "BCM|firmware" | tail -n 6
