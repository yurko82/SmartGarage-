# MQTT Контракт Smart Garage (v1)

Цей документ визначає структуру топіків, JSON-схеми, рівні QoS, політику Retain та LWT для взаємодії між мікроконтролером ESP32-S3, сервером Smart Garage та Home Assistant.

---

## 1. Загальні положення
* **Базовий префікс топіків:** `smartgarage/`
* **Версія протоколу контракту:** `"v": 1`
* **Формат корисного навантаження:** UTF-8 JSON або plain text (для простих прапорів LWT).
* **Сумісність:** Інтеграція з Home Assistant MQTT Discovery (`docs/HOME_ASSISTANT_MQTT.md`) повністю підтримується.

---

## 2. Статус та телеметрія (ESP32 → Сервер / Брокер)

### 2.1. LWT та стан зв'язку
* **Топік:** `smartgarage/esp32/status`
* **QoS:** 1, **Retain:** `true`
* **Повідомлення під час роботи:** `online`
* **LWT (Last Will and Testament):** `offline`

### 2.2. Поточна телеметрія мікроконтролера
* **Топік:** `smartgarage/esp32/telemetry`
* **QoS:** 0, **Retain:** `false`
* **Періодичність:** кожні 10-30 секунд
* **Приклад схеми:**
```json
{
  "v": 1,
  "uptime_ms": 1284500,
  "free_heap": 215420,
  "wifi_rssi": -62,
  "temperature": 18.4,
  "humidity": 55.2,
  "relays": {
    "light": false,
    "gate": false
  },
  "rf_rx_count": 42
}
```

### 2.3. Події радіоприймача 433 МГц (RF RX)
* **Топік:** `smartgarage/esp32/rf/event`
* **QoS:** 1, **Retain:** `false`
* **Приклад схеми:**
```json
{
  "v": 1,
  "timestamp": 1731306000,
  "protocol": 1,
  "bit_length": 24,
  "code": 454523,
  "pulse_length": 350
}
```

### 2.4. BLE Сканування присутності (BLE Beacons)
* **Топік:** `smartgarage/esp32/ble/presence`
* **QoS:** 0, **Retain:** `false`
* **Приклад схеми:**
```json
{
  "v": 1,
  "mac": "AA:BB:CC:DD:EE:FF",
  "rssi": -74,
  "name": "Beacon-Tag",
  "battery": 85
}
```

---

## 3. Команди та керування (Сервер → ESP32)

### 3.1. Керування світлом та воротами
* **Топік команд:** `smartgarage/esp32/cmd/relay`
* **QoS:** 1, **Retain:** `false`
* **Приклад схеми:**
```json
{
  "v": 1,
  "target": "light",
  "action": "toggle",
  "req_id": "req-987654"
}
```

### 3.2. Передача RF-команд 433 МГц (CC1101 TX)
* **Топік команд:** `smartgarage/esp32/cmd/rf_tx`
* **QoS:** 1, **Retain:** `false`
* **Приклад схеми:**
```json
{
  "v": 1,
  "code": 1122334,
  "bit_length": 24,
  "protocol": 1,
  "pulse_length": 350,
  "repeats": 10,
  "req_id": "req-123456"
}
```

### 3.3. Підтвердження виконання (ESP32 → Сервер)
* **Топік:** `smartgarage/esp32/ack`
* **QoS:** 1, **Retain:** `false`
* **Приклад схеми:**
```json
{
  "v": 1,
  "req_id": "req-123456",
  "status": "ok",
  "action": "rf_tx",
  "details": "Transmitted 24-bit code 1122334"
}
```
