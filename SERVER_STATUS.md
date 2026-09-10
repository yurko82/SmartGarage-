# SERVER_STATUS: Домашній сервер Lenovo ThinkPad E530c

> Документ створено автоматично після завершення налаштування системи для режиму 24/7.

---

## 1. Апаратні характеристики та ОС

- **Модель ноутбука:** Lenovo ThinkPad Edge E530c (Type 33664LG)
- **Процесор (CPU):** Intel Celeron 1000M @ 1.80GHz (2 ядра / 2 потоки, x86_64)
- **Оперативна пам'ять (RAM):** 7.6 GiB (доступно ~4.7 GiB, Swap: 7.6 GiB)
- **Накопичувач (SSD/HDD):** 223.6 GB
  - `/` (корінь): 73 GB (використано 16 GB, вільно 54 GB)
  - `/home`: 138 GB (використано 6.0 GB, вільно 125 GB)
- **Операційна система:** Linux Mint 22.3 (Zena) / база Ubuntu 24.04 LTS (noble)
- **Ядро (Kernel):** Linux 7.0.0-30-generic
- **Температурний режим:** ~55°C – 63°C (критичний ліміт 105°C)

---

## 2. Мережева конфігурація

- **Локальна мережа (Wi-Fi `wlp3s0b1`):** `10.112.49.31/24` (шлюз: `10.112.49.97`)
- **Ethernet (`enp12s0`):** Gigabit LAN (резервний, готовий до кабельного підключення)
- **Tailscale Mesh IP (IPv4):** `100.122.57.39`
- **Tailscale Mesh IP (IPv6):** `fd7a:115c:a1e0::7a01:39ca`
- **Tailscale Hostname:** `yurko-thinkpad-edge-e530c`
- **Docker Networks:** `172.17.0.1/16` (bridge), `172.18.0.1/16` (`n8n_default`)

---

## 3. Встановлені компоненти та версії

- **OpenSSH Server:** OpenSSH 9.6p1 (активний, systemd `ssh.service` enabled)
- **Tailscale:** 1.102.3 (активний, systemd `tailscaled.service` enabled, з підтримкою `--ssh`)
- **Docker:** 29.1.3 (активний, systemd `docker.service` enabled)
- **Docker Compose:** 1.29.2
- **Python:** 3.12.3 (pip 24.0)
- **Node.js:** v18.19.1 (npm 9.2.0)
- **Git:** 2.43.0
- **Antigravity CLI (`agy`):** 1.1.19 (розташовано у `/home/yurko/.local/bin/agy`, додано у PATH)

---

## 4. Активні сервіси та карта портів

| Порт | Протокол | Сервіс | Тип запуску | Призначення |
| :--- | :--- | :--- | :--- | :--- |
| **22** | TCP | OpenSSH Server | systemd (`ssh.service`) | Віддалене керування терміналом |
| **1883** | TCP | Mosquitto MQTT | systemd (`mosquitto.service`) | Брокер повідомлень IoT/SmartGarage |
| **5000** | TCP | SmartGarage WebApp | systemd user (`smartgarage.service`) | Веб-інтерфейс та API гаража |
| **5678** | TCP | n8n Automation | Docker container (`n8n`) | Автоматизація робочих процесів |
| **9000** | TCP | Portainer CE | Docker container (`portainer`) | Веб-панель керування Docker |
| **631** | TCP | CUPS | systemd (`cups.service`) | Сервер друку |

---

## 5. Розташування проєктів та структура файлової системи

- **`/home/yurko/AI/SmartGarage`** — проект Smart Garage (Flask/FastAPI сервіс, веб-інтерфейс, ESP32 код, тести).
- **`/home/yurko/AI/OpenInterpreter`** — віртуальне середовище Python `venv` та конфіги.
- **`/home/yurko/Docker/n8n`** — робочі процеси та база даних n8n (`docker-compose.yml`, `./data`).
- **`/home/yurko/Docker/portainer`** — конфігурації Portainer.
- **`/home/yurko/server/`** — нова ізольована структура для майбутніх сервісів:
  - `sites/` — веб-сайти (HTML, PHP, Node.js, Python тощо).
  - `services/` — зворотні проксі (Nginx Proxy шаблон у `services/proxy/`), API, боти.
  - `databases/` — бази даних (PostgreSQL, MySQL, Redis шаблони).
  - `monitoring/` — моніторинг (Uptime Kuma, Netdata).
  - `backups/` — резервні копії.

---

## 6. Корисні команди для керування сервером

### Підключення через SSH (з будь-якої точки світу через Tailscale):
```bash
ssh yurko@100.122.57.39
# або за Tailscale ім'ям:
ssh yurko@yurko-thinkpad-edge-e530c
```

### Перевірка стану ключових сервісів:
```bash
# Статус Tailscale
tailscale status

# Статус SSH
systemctl status ssh

# Статус Docker-контейнерів
docker ps

# Статус SmartGarage
systemctl --user status smartgarage.service

# Моніторинг температури та навантаження
sensors
uptime
```

### Керування n8n (Docker):
```bash
cd /home/yurko/Docker/n8n
docker compose restart
```

---

## 7. Журнал змін (Що було змінено і що НЕ змінювалося)

### Що БУЛО змінено/налаштовано:
1. **Кришка ноутбука (Lid Action):**
   - Створено конфігурацію `/etc/systemd/logind.conf.d/00-laptop-server.conf` (`HandleLidSwitch=ignore`, `HandleLidSwitchExternalPower=ignore`). Ноутбук працює безперервно 24/7 при закритій кришці.
2. **Встановлено OpenSSH Server:**
   - Встановлено пакунок `openssh-server`, активовано та увімкнено автозапуск.
3. **Встановлено та підключено Tailscale:**
   - Встановлено офіційний Tailscale 1.102.3, пристрій авторизовано в мережі користувача з IP `100.122.57.39`.
4. **Створено модульну структуру `~/server`:**
   - Підготовлено каталоги `sites/`, `services/`, `databases/`, `monitoring/`, `backups/` з готовими прикладами docker-compose.
5. **Активовано User Linger:**
   - Перевірено та підтверджено `loginctl enable-linger yurko`, що гарантує автозапуск користувацьких systemd-сервісів (`smartgarage.service`) після рестарту навіть без входу в графічний сеанс.

### Що НЕ змінювалося (збережено в оригінальному стані):
- Жоден існуючий Docker-контейнер, образ чи volume не видалявся.
- Конфігурація та база даних n8n у `/home/yurko/Docker/n8n/data` не модифікувалися.
- Проекти SmartGarage та віртуальне середовище OpenInterpreter залишилися без змін.
- Мережеві налаштування роутера не змінювалися (порти назовні не відкривалися, доступ захищено через Tailscale).
