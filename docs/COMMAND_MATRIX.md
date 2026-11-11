# Матриця можливостей Smart Garage (COMMAND_MATRIX)

| Можливість | Вхід Web / REST | Вхід Processor | Вхід AI Tools | Вхід Telegram | Виконавець (Facade) | Потрібна автентифікація |
|:---|:---|:---|:---|:---|:---|:---|
| **Світло гаража (Light)** | `/api/light`, `/command` | `включи/виключи світло` | `set_light_state` | `/light_on`, `/light_off` | `DeviceService.set_light()` | Так (PIN / Auth Bearer) |
| **Ворота (Gate / Door)** | `/api/door`, `/command` | `відкрий/закрий ворота` | `trigger_garage_door` | `/gate_open`, `/gate_close` | `DeviceService.trigger_door()` | Так (PIN / Auth Bearer) |
| **Зональне світло (Zone Light)** | `/api/zone_light`, `/command` | `підвал/2 поверх світло`| `set_zone_light` | `/zone_light` | `DeviceService.send_rf_code()` | Так (PIN / Auth Bearer) |
| **Проектор (Projector)** | `/api/projector` | `включи/виключи проектор`| `control_projector` | `/projector_power` | `DeviceService.projector_control()` | Так (PIN / Auth Bearer) |
| **Радіо (Radio Stream)** | `/api/speaker/radio` | `включи радіо [назва]` | `play_radio` | `/radio` | `DeviceService.play_radio()` | Так (PIN / Auth Bearer) |
| **Колонка (Speaker TTS / Audio)**| `/api/speaker/play`, `/api/speaker/tts` | `скажи [текст]` | `speaker_play`, `speaker_tts` | `/speak` | `DeviceService.speaker_play()` | Так (PIN / Auth Bearer) |
| **Телеметрія (Telemetry)** | `/api/telemetry`, `/api/telemetry/history` | `яка температура` | `get_telemetry` | `/telemetry`, `/status` | `DeviceService.get_telemetry()` | Ні (Read-only) |
| **BLE Присутність (BLE Scan)** | `/api/presence`, `/api/ble/scan` | `хто в гаражі` | `scan_ble`, `get_presence` | `/presence` | `DeviceService.scan_ble()` | Так (Scan) / Ні (Read) |
| **Голосове керування (Voice)** | `/api/voice/command` | Автоматично через STT | Dispatcher | N/A | `VoiceService.dispatch_command()` | Так (X-Admin-PIN) |
