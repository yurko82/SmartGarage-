# Home Assistant MQTT Integration — Smart Garage Antigravity

Цей документ описує підключення Smart Garage до Home Assistant через MQTT з підтримкою **MQTT Auto-Discovery** та приклад конфігурації для ручного налаштування (`configuration.yaml`).

---

## 1. Автоматичне виявлення (MQTT Discovery)

Smart Garage автоматично публікує конфігурації пристроїв у топіки `homeassistant/...` з флагом `retain: true`.
Усі сутності автоматично групуються під єдиним пристроєм **«Smart Garage Antigravity»** (`smartgarage_antigravity_core`).

### Створені сутності:
1. **Ворота (Cover):** `cover.vorota_garazha`
   - Команди: `OPEN`, `CLOSE`, `STOP` у топік `smartgarage/door/set`
   - Стан: `open`, `closed` з топіка `smartgarage/door/state`
2. **Датчик воріт (Binary Sensor):** `binary_sensor.vorota_datchik_gerkona`
   - Стан: `open` / `closed`
3. **Освітлення (Switch):** `switch.osvitlennya_garazha`
   - Команди: `ON`, `OFF` у топік `smartgarage/light/set`
   - Стан: `ON`, `OFF` з топіка `smartgarage/light/state`
4. **Вентиляція (Switch):** `switch.ventilyatsiya_garazha`
   - Команди: `ON`, `OFF` у топік `smartgarage/fan/set`
   - Стан: `ON`, `OFF` з топіка `smartgarage/fan/state`
5. **Клімат Підвалу:**
   - Температура: `sensor.pidval_temperatura` (`°C`)
   - Вологість: `sensor.pidval_vologist` (`%`)
6. **Клімат 2-го поверху:**
   - Температура: `sensor_2_y_poverkh_temperatura` (`°C`)
   - Вологість: `sensor_2_y_poverkh_vologist` (`%`)
7. **Датчик Газу MQ2:** `sensor.gaz_mq2_dim` (`ppm`)
8. **Статус AI Antigravity:** `sensor.status_ai_antigravity` (`idle` / `processing`)
9. **Остання відповідь AI:** `sensor.ostannya_vidpovid_ai`

---

## 2. Ручне налаштування (Manual `configuration.yaml` для Home Assistant)

Якщо ви віддаєте перевагу ручному опису сутностей у Home Assistant замість або на додаток до Auto-Discovery, додайте наступні секції до вашого файлу `configuration.yaml`:

```yaml
mqtt:
  # 🚪 Ворота гаража
  cover:
    - name: "Ворота Гаража (Smart Garage)"
      unique_id: "manual_smartgarage_door_cover"
      device_class: garage
      command_topic: "smartgarage/door/set"
      state_topic: "smartgarage/door/state"
      payload_open: "OPEN"
      payload_close: "CLOSE"
      payload_stop: "STOP"
      state_open: "open"
      state_closed: "closed"
      availability_topic: "smartgarage/bridge/status"
      payload_available: "online"
      payload_not_available: "offline"

  # 🧲 Фізичний геркон воріт
  binary_sensor:
    - name: "Ворота (Геркон)"
      unique_id: "manual_smartgarage_door_sensor"
      device_class: garage_door
      state_topic: "smartgarage/door/state"
      payload_on: "open"
      payload_off: "closed"
      availability_topic: "smartgarage/bridge/status"

  # 💡 Освітлення та 💨 Вентиляція
  switch:
    - name: "Освітлення Гаража"
      unique_id: "manual_smartgarage_light"
      command_topic: "smartgarage/light/set"
      state_topic: "smartgarage/light/state"
      payload_on: "ON"
      payload_off: "OFF"
      state_on: "ON"
      state_off: "OFF"
      icon: "mdi:lightbulb"
      availability_topic: "smartgarage/bridge/status"

    - name: "Вентиляція Гаража"
      unique_id: "manual_smartgarage_fan"
      command_topic: "smartgarage/fan/set"
      state_topic: "smartgarage/fan/state"
      payload_on: "ON"
      payload_off: "OFF"
      state_on: "ON"
      state_off: "OFF"
      icon: "mdi:fan"
      availability_topic: "smartgarage/bridge/status"

  # 🌡️ Кліматичні сенсори та статус AI
  sensor:
    - name: "Підвал Температура"
      unique_id: "manual_smartgarage_basement_temp"
      state_topic: "smartgarage/telemetry"
      value_template: "{{ value_json.floors.basement.temperature }}"
      unit_of_measurement: "°C"
      device_class: temperature
      state_class: measurement
      availability_topic: "smartgarage/bridge/status"

    - name: "Підвал Вологість"
      unique_id: "manual_smartgarage_basement_hum"
      state_topic: "smartgarage/telemetry"
      value_template: "{{ value_json.floors.basement.humidity }}"
      unit_of_measurement: "%"
      device_class: humidity
      state_class: measurement
      availability_topic: "smartgarage/bridge/status"

    - name: "2-й поверх Температура"
      unique_id: "manual_smartgarage_floor2_temp"
      state_topic: "smartgarage/telemetry"
      value_template: "{{ value_json.floors.floor2.temperature }}"
      unit_of_measurement: "°C"
      device_class: temperature
      state_class: measurement
      availability_topic: "smartgarage/bridge/status"

    - name: "2-й поверх Вологість"
      unique_id: "manual_smartgarage_floor2_hum"
      state_topic: "smartgarage/telemetry"
      value_template: "{{ value_json.floors.floor2.humidity }}"
      unit_of_measurement: "%"
      device_class: humidity
      state_class: measurement
      availability_topic: "smartgarage/bridge/status"

    - name: "Газ MQ2 (Дим)"
      unique_id: "manual_smartgarage_gas"
      state_topic: "smartgarage/telemetry"
      value_template: "{{ value_json.gas_ppm }}"
      unit_of_measurement: "ppm"
      icon: "mdi:molecule-co2"
      availability_topic: "smartgarage/bridge/status"

    - name: "Статус AI Antigravity"
      unique_id: "manual_smartgarage_ai_status"
      state_topic: "smartgarage/ai/status"
      icon: "mdi:robot"
      availability_topic: "smartgarage/bridge/status"

    - name: "Остання відповідь AI"
      unique_id: "manual_smartgarage_ai_response"
      state_topic: "smartgarage/ai/response"
      icon: "mdi:chat-processing"
      availability_topic: "smartgarage/bridge/status"
```

---

## 3. Надсилання довільних AI-команд з Home Assistant
Ви можете надіслати будь-яку текстову команду AI-помічнику з автоматизації або скрипта Home Assistant через дію `mqtt.publish`:

```yaml
service: mqtt.publish
data:
  topic: "smartgarage/ai/command"
  payload: "Юрій приїхав у гараж, провітри підвал і підготуй освітлення"
```
Відповідь штучного інтелекту буде опубліковано в топік `smartgarage/ai/response`.
