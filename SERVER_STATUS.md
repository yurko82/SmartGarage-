# SERVER_STATUS: Домашній сервер ASUS VivoBook 14 X413E

> Документ оновлено автоматично після успішної міграції сервера SmartGarage зі старого ThinkPad E530c на новий ASUS X413E.

---

## 1. Апаратні характеристики та ОС

- **Модель ноутбука:** ASUS VivoBook 14 X413E (X421EAY-X413EA)
- **Процесор (CPU):** 11th Gen Intel(R) Core(TM) i5-1135G7 @ 2.40GHz (4 ядра / 8 потоків, Tiger Lake 10 нм SuperFin)
- **Інструкції ШІ:** AVX2, AVX-512, Intel DL Boost (VNNI)
- **Оперативна пам'ять (RAM):** 7.6 GiB DDR4
- **Накопичувач (SSD):** 1 ТБ NVMe M.2 SSD (`nvme0n1p2`, 931 GB)
- **Операційна система:** Linux Mint 22.3 (Zena) / база Ubuntu 24.04 LTS (noble)
- **Ядро (Kernel):** Linux 6.14.0-37-generic
- **Bluetooth:** Вбудований Intel AX201 / MT7921 (BT 5.x, нативна підтримка ядром Linux)
- **Температурний режим:** ~45°C – 54°C (активне охолодження)

---

## 2. Мережева конфігурація

- **Локальна мережа (Wi-Fi `wlo1`):** `192.0.2.100/24` (Documentation IP / LAN DHCP)
- **Tailscale Mesh IP (IPv4):** `100.64.0.1` (CGNAT / Tailscale documentation placeholder)
- **Tailscale Mesh IP (IPv6):** `fd7a:115c:a1e0::xxxx:xxxx`
- **Tailscale Hostname:** `smartgarage-server`
- **Docker Networks:** `172.17.0.1/16` (bridge), `172.18.0.1/16` (`n8n_default`)

---

## 3. Встановлені компоненти та версії

- **OpenSSH Server:** OpenSSH 9.6p1 (активний, systemd `ssh.service` enabled)
- **Tailscale:** 1.102.4 (активний, systemd `tailscaled.service` enabled, з підтримкою `--ssh`)
- **Docker Engine:** 29.8.2 (активний, systemd `docker.service` enabled)
- **Docker Compose:** v5.6.0 (офіційний docker-compose-plugin)
- **Python:** 3.12.3 у `~/AI/OpenInterpreter/venv`
- **Mosquitto MQTT:** 2.0.18 (активний, systemd `mosquitto.service`, порти 1883 та 9001 WebSockets)
- **WirePlumber & PipeWire:** нативна аудіопідсистема, профіль `51-bluez-a2dp-only.lua`

---

## 4. Активні сервіси та карта портів

| Порт | Протокол | Сервіс | Тип запуску | Призначення |
| :--- | :--- | :--- | :--- | :--- |
| **22** | TCP | OpenSSH Server | systemd (`ssh.service`) | Віддалене керування терміналом |
| **1883** | TCP | Mosquitto MQTT | systemd (`mosquitto.service`) | Брокер повідомлень IoT/ESP32/HA |
| **5000** | TCP | SmartGarage WebApp | systemd user (`smartgarage.service`) | Веб-інтерфейс та API гаража |
| **5678** | TCP | n8n Automation | Docker container (`n8n`) | Автоматизація робочих процесів |
| **9000** | TCP | Portainer CE | Docker container (`portainer`) | Веб-панель керування Docker |
| **9001** | TCP | Mosquitto WebSockets | systemd (`mosquitto.service`) | WebSockets для веб-панелей |
| **631** | TCP | CUPS | systemd (`cups.service`) | Сервер друку |

---

## 4.1. Статус підсистем SmartGarage (Перевірено 03.11.2026)

- **Прошивка ESP32-S3:** Канонічне джерело істини — `esp32/src/main.cpp` (PlatformIO збірка успішна, застарілі Arduino скетчі архівовано в `esp32/legacy/`).
- **Сенсори та Клімат:** Датчик 1-го поверху чесно зафіксовано як не встановлений (`not_installed`). Датчики 2-го поверху та підвалу мають поріг свіжості 20 хв; застарілі дані позначаються як історичні (`stale`/`offline`).
- **Безпека воріт та газу:** Привід воріт заблоковано (`Door drive not installed`), датчик газу не змонтовано.
- **AI-маршрутизація:** OpenRouter (`google/gemini-2.5-flash`), очищення телеметрії від LAN IP/MAC-адрес, трекінг щоденного бюджету, відключено виконання довільного коду (OpenInterpreter).
- **Голосовий TTS:** Модульна система (`server/tts/`), baseline — безкоштовний Edge TTS (Поліна), підтримка ElevenLabs Flash v2.5 та HeyGen Turbo REST, явне сповіщення про резервний браузерний Web Speech API.
- **Тестування та CI:** 181 тест пройдено (100% success), нуль фізичних або платних викликів під час тестів, налаштовано GitHub Actions (`.github/workflows/ci.yml`).


---

## 5. Розташування проєктів та структура файлової системи

- **`~/AI/SmartGarage`** — проєкт Smart Garage (Flask/FastAPI, веб-інтерфейс, ESP32, тести).
- **`~/AI/OpenInterpreter`** — віртуальне середовище Python 3.12 (`venv`) та конфігурації.
- **`~/Docker/n8n`** — мігровані робочі процеси та база даних n8n (`docker-compose.yml`, `./data`).
- **`~/Docker/portainer`** — дані та volume Portainer CE (`portainer_data`).
- **`~/server/`** — модульна серверна інфраструктура:
  - `sites/` — веб-сайти.
  - `services/` — зворотні проксі (Nginx/Traefik).
  - `databases/` — шаблони баз даних.
  - `monitoring/` — моніторинг.
  - `backups/` — бекапи.

---

## 6. Корисні команди для керування сервером

### Підключення через SSH (з будь-якої точки світу через Tailscale):
```bash
ssh user@100.64.0.1
# або за Tailscale ім'ям:
ssh user@smartgarage-server
```

### Перевірка стану ключових сервісів:
```bash
# Статус Tailscale
tailscale status

# Статус Docker-контейнерів
docker ps

# Статус SmartGarage
systemctl --user status smartgarage.service

# Логи SmartGarage
journalctl --user -u smartgarage.service -f -n 50
```

### Керування n8n (Docker):
```bash
cd ~/Docker/n8n
docker compose restart
```

---

## 7. Журнал міграції

1. **Залізо та BIOS:** ASUS VivoBook 14 X413E з процесором i5-1135G7 та NVMe SSD 1 ТБ підготовлено.
2. **ОС 24/7:** Linux Mint 22.3 налаштовано із закритою кришкою (`HandleLidSwitch=ignore`), sleep targets замасковано, `user linger` увімкнено.
3. **Пакетне середовище:** Встановлено Docker CE, Tailscale, Mosquitto MQTT, WirePlumber, SSH.
4. **Міграція даних:** Базу SQLite та налаштування n8n перенесено з ThinkPad E530c через захищений Tailscale тунель без втрати даних.
5. **Сервіси:** n8n та Portainer успішно запущені в Docker, SmartGarage WebApp працює під systemd user.
