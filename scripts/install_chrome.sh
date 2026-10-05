#!/usr/bin/env bash
# ==============================================================================
# Встановлення Google Chrome та налаштування його як основного браузера
# ==============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}🌐 Встановлення Google Chrome на ASUS VivoBook 14 X413E${NC}"
echo -e "${BLUE}====================================================================${NC}"

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Запустіть скрипт через sudo: sudo $0${NC}"
    exit 1
fi

TARGET_USER="yurko"
DEB_PATH="/tmp/google-chrome-stable_current_amd64.deb"

# 1. Завантаження якщо файл відсутній або пошкоджений
if [ ! -s "$DEB_PATH" ]; then
    echo -e "${YELLOW}📥 [1/3] Завантаження офіційного пакету Google Chrome...${NC}"
    curl -fsSL "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" -o "$DEB_PATH"
else
    echo -e "${GREEN}📦 [1/3] Використовується завантажений пакет: ${DEB_PATH}${NC}"
fi

# 2. Встановлення пакунка через apt
echo -e "${YELLOW}⚙️  [2/3] Встановлення Google Chrome та залежностей...${NC}"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y "$DEB_PATH"

# 3. Налаштування як основного браузера в системі
echo -e "${YELLOW}⭐ [3/3] Налаштування Google Chrome як браузера за замовчуванням...${NC}"
update-alternatives --install /usr/bin/x-www-browser x-www-browser /usr/bin/google-chrome-stable 200 || true
update-alternatives --set x-www-browser /usr/bin/google-chrome-stable || true

update-alternatives --install /usr/bin/gnome-www-browser gnome-www-browser /usr/bin/google-chrome-stable 200 || true
update-alternatives --set gnome-www-browser /usr/bin/google-chrome-stable || true

# Налаштування для сеансу користувача (xdg-mime, xdg-settings)
USER_HOME="/home/${TARGET_USER}"
if [ -d "$USER_HOME" ]; then
    sudo -u "$TARGET_USER" xdg-settings set default-web-browser google-chrome.desktop 2>/dev/null || true
    sudo -u "$TARGET_USER" xdg-mime default google-chrome.desktop x-scheme-handler/http 2>/dev/null || true
    sudo -u "$TARGET_USER" xdg-mime default google-chrome.desktop x-scheme-handler/https 2>/dev/null || true
    sudo -u "$TARGET_USER" xdg-mime default google-chrome.desktop text/html 2>/dev/null || true
    sudo -u "$TARGET_USER" xdg-mime default google-chrome.desktop application/xhtml+xml 2>/dev/null || true

    # Гарантований запис у mimeapps.list користувача
    MIMEAPPS="${USER_HOME}/.config/mimeapps.list"
    mkdir -p "${USER_HOME}/.config"
    if [ ! -f "$MIMEAPPS" ]; then
        touch "$MIMEAPPS"
        chown "${TARGET_USER}:${TARGET_USER}" "$MIMEAPPS"
    fi

    # Оновлення секції [Default Applications]
    if ! grep -q "\[Default Applications\]" "$MIMEAPPS" 2>/dev/null; then
        echo -e "\n[Default Applications]" >> "$MIMEAPPS"
    fi
    for proto in "x-scheme-handler/http" "x-scheme-handler/https" "text/html" "application/xhtml+xml" "text/xml" "x-scheme-handler/about" "x-scheme-handler/unknown"; do
        sed -i "/^${proto}=/d" "$MIMEAPPS" 2>/dev/null || true
        echo "${proto}=google-chrome.desktop" >> "$MIMEAPPS"
    done
    chown -R "${TARGET_USER}:${TARGET_USER}" "${USER_HOME}/.config"
fi

echo -e "\n${GREEN}====================================================================${NC}"
echo -e "${GREEN}✅ Google Chrome успішно встановлено та призначено основним браузером!${NC}"
echo -e "${GREEN}====================================================================${NC}"
google-chrome --version || true
