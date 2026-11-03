# Архів застарілих скетчів Arduino IDE (Legacy Firmware Archive)

Ця директорія містить застарілі файли скетчів для Arduino IDE:
- `smart_garage_esp32.ino`
- `smart_garage_esp32/smart_garage_esp32.ino`

## ⚠️ Джерело істини прошивки (Single Source of Truth)
Активною, канонічною та єдиною робочою прошивкою проекту є:
**`esp32/src/main.cpp`**, яка збирається за допомогою **PlatformIO** (`esp32/platformio.ini`).

Вона містить:
- Підтримку BLE-опитування кліматичних сенсорів Xiaomi LYWSD03MMC;
- Підтримку MQTT-зв'язку (`PubSubClient`);
- Дуальний зв'язок (USB Serial CDC + Wi-Fi HTTP API);
- Апаратні конфігурації для ESP32-S3 (WROOM-1 / DevKitC-1);
- Захищене відключення небезпечних/невстановлених приводів воріт та датчиків газу.

Ці файли переміщено сюди для уникнення дублювання та конфліктів під час збірки.
