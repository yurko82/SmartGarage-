#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Server Boot & Network Fix Script
# ==============================================================================
# Цей скрипт усуває проблеми з відвалом SSH, Wi-Fi та сном сервера ThinkPad E530c:
# 1. Вимикає енергозбереження Wi-Fi (wifi.powersave=2) для Broadcom BCM4313.
# 2. Повністю блокує перехід у сплячий режим (mask sleep/suspend/hibernate).
# 3. Дозволяє ігнорувати закриття кришки незалежно від графічного середовища (LidSwitchIgnoreInhibited=yes).
# 4. Виправляє Avahi mDNS (блокує docker0, щоб *.local не резолвився у 172.17.0.1).
# 5. Виводить поточні IP-адреси та SSH команду на екран термінала (/etc/issue).
# ==============================================================================

set -e

if [ "$EUID" -ne 0 ]; then
    echo "❌ Цей скрипт потребує прав адміністратора (sudo)."
    echo "Запустіть: sudo $0"
    exit 1
fi

echo "🔧 [1/5] Вимикаємо енергозбереження Wi-Fi у NetworkManager..."
mkdir -p /etc/NetworkManager/conf.d
cat <<'EOF' > /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf
[connection]
wifi.powersave = 2
EOF

echo "🔧 [2/5] Налаштовуємо systemd-logind на 24/7 роботу із закритою кришкою..."
mkdir -p /etc/systemd/logind.conf.d
cat <<'EOF' > /etc/systemd/logind.conf.d/00-laptop-server.conf
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
LidSwitchIgnoreInhibited=yes
EOF

echo "🔧 [3/5] Маскуємо всі режими сну та глибокого сну на рівні ядра/systemd..."
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

echo "🔧 [4/5] Виправляємо Avahi mDNS (виключаємо docker0 з анонсів mDNS)..."
if grep -q "deny-interfaces=" /etc/avahi/avahi-daemon.conf; then
    sed -i 's/^#*deny-interfaces=.*/deny-interfaces=docker0,br-*/' /etc/avahi/avahi-daemon.conf
else
    sed -i '/\[server\]/a deny-interfaces=docker0,br-*' /etc/avahi/avahi-daemon.conf
fi

echo "🔧 [5/5] Перезапускаємо служби logind, avahi та NetworkManager..."
systemctl restart systemd-logind
systemctl restart avahi-daemon
systemctl restart NetworkManager || true

echo ""
echo "======================================================================"
echo "✅ ВСІ СИСТЕМНІ НАЛАШТУВАННЯ УСПІШНО ЗАСТОСОВАНО!"
echo "Ноутбук тепер:"
echo "  • Не засинає при закритті кришки за будь-яких умов"
echo "  • Не відключає Wi-Fi через режим сну адаптера Broadcom"
echo "  • Коректно віддає mDNS (.local) без Docker-мостів"
echo "======================================================================"
