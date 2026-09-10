#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Server Info & Status
# ==============================================================================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}======================================================================${NC}"
echo -e "${GREEN} 🚗 Smart Garage Server — Поточний стан та підключення${NC}"
echo -e "${CYAN}======================================================================${NC}"

# Get IPs
ETH_IP=$(ip -4 addr show dev enx0259055e3065 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || true)
WIFI_IP=$(ip -4 addr show dev wlp3s0b1 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || true)
LAN_IP=$(ip -4 addr show dev enp12s0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || true)
TS_IP=$(tailscale ip -4 2>/dev/null || true)

echo -e "${YELLOW}📡 Мережеві адреси для підключення:${NC}"
if [ -n "$ETH_IP" ]; then
    echo -e "  • USB Модем (Ethernet): ${GREEN}${ETH_IP}${NC}"
fi
if [ -n "$WIFI_IP" ]; then
    echo -e "  • Локальний Wi-Fi:       ${GREEN}${WIFI_IP}${NC}"
fi
if [ -n "$LAN_IP" ]; then
    echo -e "  • Кабельний LAN:        ${GREEN}${LAN_IP}${NC}"
fi
if [ -n "$TS_IP" ]; then
    echo -e "  • Tailscale VPN IP:     ${GREEN}${TS_IP}${NC} (доступ звідусіль)"
    echo -e "  • Tailscale Hostname:   ${GREEN}yurko-thinkpad-edge-e530c${NC}"
fi
echo -e "  • mDNS (локальна назва): ${GREEN}yurko-thinkpad-edge-e530c.local${NC}"

echo ""
echo -e "${YELLOW}🔑 Команди для входу через SSH:${NC}"
if [ -n "$TS_IP" ]; then
    echo -e "  ${BLUE}ssh yurko@${TS_IP}${NC}              # через Tailscale (з телефону / ПК)"
fi
if [ -n "$ETH_IP" ]; then
    echo -e "  ${BLUE}ssh yurko@${ETH_IP}${NC}           # через USB модем"
fi
if [ -n "$WIFI_IP" ]; then
    echo -e "  ${BLUE}ssh yurko@${WIFI_IP}${NC}          # через локальний Wi-Fi"
fi
echo -e "  ${BLUE}ssh yurko@yurko-thinkpad-edge-e530c.local${NC} # за ім'ям хоста в локальній мережі"

echo ""
echo -e "${YELLOW}🌐 Веб-сервіси:${NC}"
TARGET_IP="${ETH_IP:-${WIFI_IP:-${TS_IP:-localhost}}}"
echo -e "  • SmartGarage WebApp:  ${CYAN}http://${TARGET_IP}:5000${NC} (або http://localhost:5000)"
echo -e "  • Portainer (Docker):  ${CYAN}http://${TARGET_IP}:9000${NC}"
echo -e "  • n8n Автоматизація:   ${CYAN}http://${TARGET_IP}:5678${NC}"

echo ""
echo -e "${YELLOW}⚙️ Стан сервісів:${NC}"
systemctl is-active --quiet ssh && echo -e "  • SSH Server:       ${GREEN}АКТИВНИЙ${NC}" || echo -e "  • SSH Server:       ${YELLOW}НЕ АКТИВНИЙ${NC}"
systemctl is-active --quiet tailscaled && echo -e "  • Tailscale:        ${GREEN}АКТИВНИЙ${NC}" || echo -e "  • Tailscale:        ${YELLOW}НЕ АКТИВНИЙ${NC}"
systemctl is-active --quiet mosquitto && echo -e "  • Mosquitto MQTT:   ${GREEN}АКТИВНИЙ${NC}" || echo -e "  • Mosquitto MQTT:   ${YELLOW}НЕ АКТИВНИЙ${NC}"
systemctl is-active --quiet docker && echo -e "  • Docker:           ${GREEN}АКТИВНИЙ${NC}" || echo -e "  • Docker:           ${YELLOW}НЕ АКТИВНИЙ${NC}"
systemctl --user is-active --quiet smartgarage.service && echo -e "  • SmartGarage App:  ${GREEN}АКТИВНИЙ${NC}" || echo -e "  • SmartGarage App:  ${YELLOW}НЕ АКТИВНИЙ${NC}"

echo -e "${CYAN}======================================================================${NC}"
