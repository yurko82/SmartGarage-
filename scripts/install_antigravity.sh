#!/bin/bash
set -e

SOURCE_DIR="/home/yurko/Завантажене/Antigravity IDE"
TARGET_DIR="/opt/antigravity-ide"

echo "=== Встановлення Antigravity IDE в $TARGET_DIR ==="

if [ ! -d "$SOURCE_DIR" ]; then
    echo "Помилка: $SOURCE_DIR не знайдено!"
    exit 1
fi

echo "1. Копіювання файлів у $TARGET_DIR..."
mkdir -p "$TARGET_DIR"
cp -a "$SOURCE_DIR"/. "$TARGET_DIR"/
chown -R root:root "$TARGET_DIR"
chmod -R 755 "$TARGET_DIR"

echo "2. Створення системного посилання в /usr/local/bin/antigravity-ide..."
ln -sf "$TARGET_DIR/bin/antigravity-ide" /usr/local/bin/antigravity-ide

echo "3. Оновлення ярлика в меню програм..."
TARGET_USER="${SUDO_USER:-$USER}"
USER_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)

mkdir -p "$USER_HOME/.local/share/applications"
cat << 'EOF' > "$USER_HOME/.local/share/applications/antigravity-ide.desktop"
[Desktop Entry]
Name=Antigravity IDE
Comment=AI-First Code Editor
Exec=/opt/antigravity-ide/antigravity-ide %F
Icon=/usr/share/pixmaps/antigravity.png
Terminal=false
Type=Application
StartupNotify=true
StartupWMClass=Antigravity IDE
Categories=Development;IDE;
MimeType=text/plain;inode/directory;
EOF

chown "$TARGET_USER":"$TARGET_USER" "$USER_HOME/.local/share/applications/antigravity-ide.desktop"

if [ -d "$USER_HOME/.gemini/antigravity-ide/bin" ]; then
    ln -sf "$TARGET_DIR/bin/antigravity-ide" "$USER_HOME/.gemini/antigravity-ide/bin/antigravity-ide"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$USER_HOME/.local/share/applications" 2>/dev/null || true
fi

echo "=== Готово! Antigravity IDE успішно встановлено в $TARGET_DIR ==="
