#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Audio System Stabilization Automated Setup Script
# Applies PipeWire, WirePlumber, BlueZ, and Udev optimizations
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${PROJECT_ROOT}/config/audio"

echo "=========================================================="
echo " [SmartGarage] Стабілізація аудіосистеми (PipeWire + BT)"
echo "=========================================================="

# 1. Застосування користувацьких конфігурацій (User Level, без sudo)
echo "==> 1. Налаштування користувацьких сервісів PipeWire та WirePlumber..."

# 1.1 WirePlumber override
WP_OVERRIDE_DIR="${HOME}/.config/systemd/user/wireplumber.service.d"
mkdir -p "${WP_OVERRIDE_DIR}"
cp "${CONFIG_DIR}/wireplumber_override.conf" "${WP_OVERRIDE_DIR}/override.conf"
echo "    [✓] Встановлено ${WP_OVERRIDE_DIR}/override.conf"

# 1.2 PipeWire config
PW_CONFIG_DIR="${HOME}/.config/pipewire"
mkdir -p "${PW_CONFIG_DIR}"
cp "${CONFIG_DIR}/pipewire.conf" "${PW_CONFIG_DIR}/pipewire.conf"
echo "    [✓] Встановлено ${PW_CONFIG_DIR}/pipewire.conf"

# 2. Застосування системних конфігурацій (System Level, потребує sudo)
echo ""
echo "==> 2. Застосування системних налаштувань (/etc та /usr/local/bin)..."
echo "    (За потреби введіть пароль sudo для застосування системних файлів)"

# 2.1 Налаштування PAM / security limits для real-time аудіо
echo "    --> Встановлення /etc/security/limits.d/99-realtime-audio.conf..."
sudo cp "${CONFIG_DIR}/99-realtime-audio.conf" /etc/security/limits.d/99-realtime-audio.conf
sudo chmod 644 /etc/security/limits.d/99-realtime-audio.conf
echo "    [✓] Ліміти real-time (rtprio 95, memlock unlimited) активовано."

# 2.2 Модифікація /etc/bluetooth/main.conf
echo "    --> Оновлення /etc/bluetooth/main.conf..."
if [ -f /etc/bluetooth/main.conf ]; then
    sudo cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.bak."$(date +%Y%m%d%H%M%S)"
fi

# Інтеграція секцій у main.conf
sudo python3 -c "
import re

conf_path = '/etc/bluetooth/main.conf'
with open(conf_path, 'r') as f:
    content = f.read()

# 1. Перевірка або додавання Enable/Disable у [General]
if '[General]' in content:
    # Заміна або додавання Enable
    if re.search(r'^\s*Enable\s*=', content, re.MULTILINE):
        content = re.sub(r'^\s*Enable\s*=.*$', 'Enable = Source,Sink,Media,Socket', content, flags=re.MULTILINE)
    else:
        content = re.sub(r'(\[General\])', r'\1\nEnable = Source,Sink,Media,Socket', content)

    # Заміна або додавання Disable
    if re.search(r'^\s*Disable\s*=', content, re.MULTILINE):
        content = re.sub(r'^\s*Disable\s*=.*$', 'Disable = HeadsetGateway,mSBC', content, flags=re.MULTILINE)
    else:
        content = re.sub(r'(\[General\])', r'\1\nDisable = HeadsetGateway,mSBC', content)

# 2. Перевірка або додавання [CodecConfig]
codec_section = '''
[CodecConfig]
SBCSources=1
A2DPSources=1
SBCXQSources=1
'''

if '[CodecConfig]' in content:
    content = re.sub(r'\[CodecConfig\][^\[]*', codec_section.strip() + '\n\n', content)
else:
    content += '\n' + codec_section

with open(conf_path, 'w') as f:
    f.write(content)
"
sudo chmod 644 /etc/bluetooth/main.conf
echo "    [✓] /etc/bluetooth/main.conf успішно оновлено (SBC-XQ, A2DP, заборона mSBC/CVSD)."

# 2.3 Правило udev для заборони USB autosuspend
echo "    --> Встановлення udev-правила для Broadcom BCM20702A0..."
sudo cp "${CONFIG_DIR}/99-bluetooth-no-autosuspend.rules" /etc/udev/rules.d/99-bluetooth-no-autosuspend.rules
sudo chmod 644 /etc/udev/rules.d/99-bluetooth-no-autosuspend.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb

# Примусове вимкнення autosuspend для поточного пристрою Broadcom прямо зараз
for dev in /sys/bus/usb/devices/*; do
    if [ -f "$dev/idVendor" ] && [ "$(cat "$dev/idVendor" 2>/dev/null)" = "0a5c" ]; then
        if [ -f "$dev/power/control" ]; then
            echo on | sudo tee "$dev/power/control" >/dev/null || true
            echo "    [✓] USB autosuspend вимкнено для $dev (0a5c:$(cat "$dev/idProduct" 2>/dev/null))."
        fi
    fi
done

# 2.4 Встановлення /usr/local/bin/bluetooth-audio-fix.sh
echo "    --> Встановлення /usr/local/bin/bluetooth-audio-fix.sh..."
sudo cp "${PROJECT_ROOT}/scripts/bluetooth-audio-fix.sh" /usr/local/bin/bluetooth-audio-fix.sh
sudo chmod 755 /usr/local/bin/bluetooth-audio-fix.sh
echo "    [✓] /usr/local/bin/bluetooth-audio-fix.sh встановлено."

# 3. Перезавантаження сервісів без reboot
echo ""
echo "==> 3. Перезавантаження аудіосервісів та Bluetooth (без reboot)..."
sudo systemctl restart bluetooth
systemctl --user daemon-reload
systemctl --user restart pipewire pipewire-pulse wireplumber
sleep 2

# 4. Верифікація результатів
echo ""
echo "=========================================================="
echo " [РЕЗУЛЬТАТИ ВЕРИФІКАЦІЇ]"
echo "=========================================================="
echo -n "Статус служби Bluetooth: "
systemctl is-active bluetooth

echo -n "Статус PipeWire: "
systemctl --user is-active pipewire

echo -n "Статус WirePlumber: "
systemctl --user is-active wireplumber

echo ""
echo "Конфігурація тактового генератора PipeWire:"
pw-cli info 0 | grep -E "default.clock.(rate|quantum|min-quantum|max-quantum)" | sed 's/^[ \t]*/  /'

echo ""
echo "=========================================================="
echo " [OK] Стабілізацію аудіосистеми успішно застосовано!"
echo "=========================================================="
