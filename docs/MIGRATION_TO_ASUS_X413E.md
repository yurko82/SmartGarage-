# Покроковий план міграції сервера SmartGarage на ASUS VivoBook 14 X413E

Цей документ містить вичерпну покрокову інструкцію для перенесення інфраструктури сервера **SmartGarage** зі старого ноутбука **Lenovo ThinkPad Edge E530c** (Intel Celeron 1000M) на **ASUS VivoBook 14 X413E** (Intel Core 11-го покоління Tiger Lake).

---

## 1. Порівняння та цілі міграції

| Параметр | Старий сервер (ThinkPad E530c) | Новий сервер (ASUS X413E) |
| :--- | :--- | :--- |
| **Процесор** | Intel Celeron 1000M (2 ядра / 2 потоки, Ivy Bridge 2013, 22 нм) | Intel Core 11-го покоління (Tiger Lake, 10 нм SuperFin) |
| **Інструкції ШІ** | Лише базові (немає навіть AVX2) | AVX2, AVX-512, Intel DL Boost (VNNI) |
| **Bluetooth** | Broadcom BCM20702A0 (BT 4.0, вимагав ручний патч `BCM20702A1...hcd`) | Intel AX201 / MT7921 (BT 5.x, нативна підтримка ядром Linux) |
| **Накопичувач** | SATA SSD (~500 МБ/с) | NVMe M.2 SSD (~2500–3500 МБ/с) |
| **Мережа** | Wi-Fi 802.11n | Wi-Fi 6 (802.11ax) |
| **Живлення** | Постійно від мережі, батарея зношена (19.9 Вт·год) | Постійно від мережі (без потреби в RJ-45) |

---

## 2. Етап 1: Підготовка «заліза» та BIOS (ASUS X413E)

1. **Профілактика системи охолодження:**
   * Очистити вентилятор і радіатор від пилу, замінити термопасту для забезпечення тривалої безперебійної роботи в режимі 24/7.
2. **Налаштування BIOS:**
   * Увійти в BIOS (`F2` або `Del` під час старту ноутбука).
   * Перевірити наявність опції **Restore on AC Power Loss** або **Power On by AC** (автоматичний старт після відновлення живлення).
   * Вимкнути **Fast Boot**.
   * Увімкнути підтримку завантаження з UEFI USB для встановлення системи.

---

## 3. Етап 2: Встановлення та оптимізація ОС під сервер 24/7

### 3.1. Встановлення системи
* Встановити **Ubuntu 24.04 LTS** (Server або Desktop) або **Linux Mint**.
* **Обов'язково створити користувача:** `yurko` (щоб зберегти ідентичність усіх абсолютних шляхів `/home/yurko/...`).

### 3.2. Робота із закритою кришкою та заборона сну
Створити конфігурацію ігнорування кришки:
```bash
sudo mkdir -p /etc/systemd/logind.conf.d/
sudo tee /etc/systemd/logind.conf.d/00-laptop-server.conf << 'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
EOF
sudo systemctl restart systemd-logind
```

Повністю заблокувати перехід у сон/гібернацію:
```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

Увімкнути безперервну роботу користувацьких служб без активної графічної сесії (`user linger`):
```bash
loginctl enable-linger yurko
```

### 3.3. Встановлення базових пакетів
```bash
sudo apt update && sudo apt install -y \
    openssh-server git curl wget rsync jq \
    python3-pip python3-venv \
    mosquitto-clients bluez wireplumber pipewire libglib2.0-dev
```

### 3.4. Встановлення офіційного Docker та Docker Compose
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker yurko
sudo usermod -aG dialout yurko
```

### 3.5. Встановлення Tailscale (для безпечного віддаленого доступу)
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh
```

---

## 4. Етап 3: Створення резервної копії зі старого ThinkPad

На старому сервері перед копіюванням зупинити активні процеси для цілісності баз даних:

```bash
# 1. Зупинити веб-сервер SmartGarage
pkill -f "server.webapp" || true

# 2. Зупинити контейнери n8n та portainer
docker stop n8n portainer 2>/dev/null || true

# 3. Створити директорію для бекапів
mkdir -p ~/migration_backup

# 4. Створити архіви ключових директорій
# Основний проект SmartGarage (бази даних, конфіги, .env)
tar -czvf ~/migration_backup/smartgarage.tar.gz -C /home/yurko/AI SmartGarage

# Робочі процеси та база n8n
tar -czvf ~/migration_backup/n8n_data.tar.gz -C /home/yurko/Docker n8n

# Додаткова серверна структура (сайти, зворотний проксі тощо)
if [ -d "/home/yurko/server" ]; then
    tar -czvf ~/migration_backup/server_dir.tar.gz -C /home/yurko server
fi

# Налаштування WirePlumber для аудіо (A2DP)
mkdir -p ~/migration_backup/configs
cp -r ~/.config/wireplumber ~/migration_backup/configs/ 2>/dev/null || true
```

---

## 5. Етап 4: Перенесення даних та розгортання оточення на ASUS

### 5.1. Розпакування архівів на новому ноутбуці
Скопіювати архіви з `~/migration_backup/` на ASUS (через scp, rsync або зовнішній накопичувач):
```bash
# Створити цільові каталоги
mkdir -p /home/yurko/AI /home/yurko/Docker

# Розпакувати дані
tar -xzvf smartgarage.tar.gz -C /home/yurko/AI/
tar -xzvf n8n_data.tar.gz -C /home/yurko/Docker/
[ -f server_dir.tar.gz ] && tar -xzvf server_dir.tar.gz -C /home/yurko/

# Відновити налаштування WirePlumber
mkdir -p ~/.config
cp -r ~/migration_backup/configs/wireplumber ~/.config/ 2>/dev/null || true
```

### 5.2. Створення віртуального оточення Python 3.12
```bash
mkdir -p /home/yurko/AI/OpenInterpreter
python3 -m venv /home/yurko/AI/OpenInterpreter/venv

# Активація та встановлення залежностей з requirements.txt
source /home/yurko/AI/OpenInterpreter/venv/bin/activate
pip install --upgrade pip
pip install -r /home/yurko/AI/SmartGarage/requirements.txt
```

### 5.3. Налаштування та активація автозапуску SmartGarage
```bash
mkdir -p ~/.config/systemd/user/
cp /home/yurko/AI/SmartGarage/smartgarage.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable smartgarage.service
```

### 5.4. Запуск Docker-контейнерів
```bash
# Запуск n8n з існуючими збереженими даними
docker run -d \
  --name n8n \
  -p 5678:5678 \
  -v /home/yurko/Docker/n8n/data:/home/node/.n8n \
  --restart unless-stopped \
  docker.n8n.io/n8nio/n8n:latest

# Запуск Portainer
docker volume create portainer_data
docker run -d \
  -p 9000:9000 \
  --name portainer \
  --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest
```

---

## 6. Етап 5: Підключення периферії та Bluetooth

1. **Bluetooth зв'язок (BLE клімат-датчики та акустика):**
   * Модуль Intel нативно працює в ядрі Linux. Додаткові прошивки Broadcom непотрібні.
   * Підключити аудіосистему та колонку через утиліту `bluetoothctl`:
     ```bash
     bluetoothctl
     # Усередині консолі bluetoothctl:
     power on
     agent on
     default-agent
     scan on
     
     # Після виявлення MAC-адрес (наприклад, JBL Clip 5 / JX-BT):
     pair <MAC_ADDRESS>
     trust <MAC_ADDRESS>
     connect <MAC_ADDRESS>
     exit
     ```
   * Перевірити, що WirePlumber підтримує A2DP stereo:
     ```bash
     wpctl status
     ```

2. **Підключення ESP32 через USB:**
   * Під'єднати USB-кабель мікроконтролера ESP32 до будь-якого USB-порту ASUS.
   * Перевірити виявлення пристрою:
     ```bash
     ls -la /dev/ttyUSB* /dev/ttyACM*
     ```
   * Переконатися, що користувач `yurko` має доступ до послідовного порту (`sudo usermod -aG dialout yurko`).

---

## 7. Етап 6: Запуск та тестування системи

1. **Запуск SmartGarage сервісу:**
   ```bash
   systemctl --user start smartgarage.service
   systemctl --user status smartgarage.service
   ```

2. **Контрольна перевірка функцій:**
   * **Веб-панель гаража:** Відкрити у браузері `http://<IP_ASUS>:5000`
   * **Автоматизація n8n:** Відкрити у браузері `http://<IP_ASUS>:5678`
   * **Кліматичні датчики:** Зачекати 5–10 хвилин і перевірити надходження оновлених значень:
     ```bash
     cat /home/yurko/AI/SmartGarage/devices/sensor_cache.json
     ```
   * **Логи сервісу:**
     ```bash
     journalctl --user -u smartgarage.service -f -n 50
     ```

3. **Завершення міграції:**
   * Після підтвердження стабільної роботи SmartGarage та n8n вимкнути старий ThinkPad Edge E530c.
