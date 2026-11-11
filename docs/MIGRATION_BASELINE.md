# Базові метрики системи SmartGarage (Migration Baseline)

**Дата фіксації:** 11 листопада 2026 р.  
**Хост:** `yurko-VivoBook-ASUSLaptop-X421EAY-X413EA` (ASUS VivoBook 14 X413EA)  
**ОС / Ядро:** Ubuntu 24.04.1 LTS, Linux 7.0.0-42-generic x86_64  
**Цільовий репозиторій:** `yurko82/SmartGarage-` (гілка `main`, хеш `98f2714`)

---

## 1. Стан тестового покриття та час виконання
- **Кількість юніт-тестів:** 220
- **Результат проходження:** 220 passed (100% успішно, 0 помилок, 0 пропущено)
- **Час виконання pytest:** 15.37 с (локально) / 22.37 с (у чистому клоні `/tmp/sg-test`)
- **Компіляція байт-коду (`compileall`):** Успішно, без синтаксичних помилок
- **Компіляція ESP32 (PlatformIO):** Успішно (RAM: 21.3% [69.8 KB], Flash: 46.5% [1.55 MB], час збірки 2.89 с)

---

## 2. Системні ресурси хоста
### Пам'ять (`free -h`)
```text
               total        used        free      shared  buff/cache   available
Mem:           7.5Gi       6.1Gi       231Mi       455Mi       1.9Gi       1.4Gi
Swap:          2.0Gi       2.0Gi       476Ki
```

### Docker-контейнери (`docker ps`)
| Контейнер | Статус | Порти |
|---|---|---|
| `nomad_cyberchef` | Up 2 days | 8100 -> 80/tcp |
| `nomad_qdrant` | Up 2 days | 6333-6334 -> 6333-6334/tcp |
| `nomad_flatnotes` | Up 2 days (healthy) | 8200 -> 8080/tcp |
| `nomad_kiwix_server` | Up 2 days | 8090 -> 8080/tcp |
| `nomad_admin` | Up 2 days (healthy) | 8085 -> 8080/tcp |
| `nomad_redis` | Up 2 days (healthy) | 6379/tcp |
| `nomad_mysql` | Up 2 days (healthy) | 3306/tcp, 33060/tcp |
| `nomad_dozzle` | Up 2 days | 9999 -> 8080/tcp |
| `nomad_disk_collector` | Up 2 days | - |
| `nomad_updater` | Up 2 days | - |
| `ollama` | Up 3 days | 11434 -> 11434/tcp |
| `portainer` | Up 3 days | 9000 -> 9000/tcp, 8000/tcp, 9443/tcp |
| `n8n` | Up 3 days | 5678 -> 5678/tcp |

---

## 3. Python-оточення (вихідний моноліт OpenInterpreter)
- **Шлях:** `/home/yurko/AI/OpenInterpreter/venv`
- **Версія Python:** `3.12.3 (main, Aug 31 2026, 10:18:26) [GCC 13.3.0]`
- **Розмір venv на диску:** `1.4 GB`
- **Загальна кількість встановлених pip-пакетів:** 206
- **Цільовий стан (M0.4):** Створення виділеного компактного `~/AI/sg-venv` (~100-200 MB) з розділеними залежностями:
  - `requirements.txt` (core backend, Flask, SQLite, Bleak, MQTT)
  - `requirements-voice.txt` (sherpa-onnx, pyaudio, soundfile)
  - `requirements-ai.txt` (openrouter, httpx)
  - `requirements-dev.txt` (pytest, ruff, mypy)

---

## 4. Версії системного ПЗ та бібліотек
- **GCC:** `13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1)`
- **SQLite (Python module):** `3.45.1`
- **Mosquitto MQTT:** Системний сервіс `active` (порт 1883)
- **SmartGarage Web Service:** Системний юзер-сервіс `active` (порт 5000)
- **Antigravity Voice Service:** `inactive` (очікує міграції M3)

---

## 5. Безпека та конфіденційність (Sanitization Status)
- Витоків персональних MAC-адрес у Git: **0** (перевірено через `scripts/smoke.sh`).
- Конфігурації пристроїв виносяться в `config/devices.yaml` (ігнорується Git).
- Секрети прошивки ESP32 виносяться в `esp32/src/secrets.h` (ігнорується Git).