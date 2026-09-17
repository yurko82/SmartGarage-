#!/bin/bash
set -e

FORCE=0
for arg in "$@"; do
    if [ "$arg" = "--force" ] || [ "$arg" = "-f" ]; then
        FORCE=1
    fi
done

if [ "$FORCE" -ne 1 ]; then
    echo "⚠️  УВАГА: цей патч сумісний виключно з ревізією чіпа Broadcom BCM20702 A1."
    echo "На поточному сервері (ThinkPad E530c) встановлено ревізію A0 (bcdDevice 1.12)."
    echo "Встановлення цього патчу СПРИЧИНЯЄ критичне зависання Bluetooth-лінка (link tx timeout)."
    echo "Деталі та аналіз див. у docs/BLUETOOTH_AUDIO_INVESTIGATION.md."
    read -p "Ви дійсно бажаєте примусово продовжити? Введіть 'yes': " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Скасовано користувачем."
        exit 1
    fi
fi


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
