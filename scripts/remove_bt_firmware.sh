#!/bin/bash
set -e

echo "🗑️ Видалення стороннього патчу BCM20702A1..."
sudo rm -f /lib/firmware/brcm/BCM20702A1-0a5c-21f4.hcd

echo "🔄 Перезапуск драйвера та служби Bluetooth..."
sudo modprobe -r btusb || true
sleep 1
sudo modprobe btusb
sudo systemctl restart bluetooth
rfkill unblock bluetooth 2>/dev/null || true

echo "✅ Готово! Перевірка dmesg:"
dmesg | grep -iE "BCM|firmware|timeout" | tail -n 5
