# Changelog

All notable changes to the Smart Garage Infrastructure project will be documented in this file.

## [0.2.8] - 2026-09-17

### UI/UX & Accessibility
- **Unified Design System Tokens (`theme.css`)**:
  - Створено єдиний файл дизайн-токенів [`server/static/css/theme.css`](file:///home/yurko/AI/SmartGarage/server/static/css/theme.css) для консолі AI (`index.html`) та сенсорного дашборду 1-го поверху (`dashboard.html`).
  - Уніфіковано колірну палітру (`--bg-main: #0f172a`, `--bg-surface: #1e293b`, `--text-main: #f8fafc`, `--text-muted: #94a3b8`, `--accent: #38bdf8`), шкалу заокруглень (`--radius-sm/md/lg/full`), семантичні кольори та підсвічування стану (`--glow-danger/success/warning/info`).
  - Усунено дублювання змінних `:root` у [`server/static/css/style.css`](file:///home/yurko/AI/SmartGarage/server/static/css/style.css) та [`server/static/css/dashboard.css`](file:///home/yurko/AI/SmartGarage/server/static/css/dashboard.css), узгоджено фон та інтенсивність неонового підсвічування.
- **Accessibility & Screen Reader Compliance (a11y)**:
  - 100% покриття інтерактивних елементів зрозумілими україномовними атрибутами `aria-label` для кнопок-іконок, повзунків, інпутів та інтерактивних плашок в обох шаблонах (`index.html` та `dashboard.html`).
  - Додано повну підтримку клавіатурної навігації (Enter / Space, `role="button"`, `tabindex="0"`) для інтерактивних елементів: радіочіпів, плиток поверху та швидких дій.
  - Виправлено дубльований HTML-атрибут `class="active"` на кнопці голосового асистента `#btnTts`.
  - Забезпечено семантичну структуру заголовків в [`server/templates/index.html`](file:///home/yurko/AI/SmartGarage/server/templates/index.html) (`<h1 class="brand-title">Smart Garage</h1>`).
- **Telemetry Usability & Responsive Breakpoints**:
  - Дозволено виділення та копіювання числових і текстових даних сенсорів/телеметрії в дашборді (`user-select: text` для значень температури, вологості, тиску, годинника, радіостанцій та індикатора воріт).
  - Додано адаптивні `@media` брейкпоінти (1024px планшет та 640px мобільний) для інтерфейсу AI-консолі, що оптимізують розміри сайдбару, шапки та сітки карток.
  - Додано легкий SVG data-URI фавікон (гараж / дім) до обох веб-інтерфейсів.

## [0.2.7] - 2026-09-17

### Security & Hardening
- **Audit #3 Corrective Actions**:
  - **Script Safety & Broadcom Hardware Revision Guard**: скрипт [`scripts/install_bt_firmware.sh`](file:///home/yurko/AI/SmartGarage/scripts/install_bt_firmware.sh) доповнено попередженням про несумісність стороннього HCD-патчу з ревізією чіпа Broadcom BCM20702 A0 та інтерактивним підтвердженням / прапорцем `--force`.
  - **Audio Stream URL Scheme Allow-list**: ендпоінт `/api/radio/play` та метод `BluetoothSpeakerController.play_stream` валідують URL-схеми, дозволяючи лише `http://` та `https://` та відхиляючи небезпечні схеми (зокрема `file://`) з кодом HTTP 400.
  - **Media Path Traversal Hardening**: ендпоінт `/api/media/delete` посилено перевіркою `str(target).startswith(media_dir_resolved + "/") and target.is_file()`, запобігаючи несанкціонованому виходу за межі каталогу `media/`.
  - **Documentation & Checklist Validation**: у [`docs/BLUETOOTH_AUDIO_INVESTIGATION.md`](file:///home/yurko/AI/SmartGarage/docs/BLUETOOTH_AUDIO_INVESTIGATION.md) оновлено чек-лист з фактичними статусами (відкат прошивки виконано, захист API покрито тестами, тест локальним звуком та перевірка JX-BT / JBL Clip 5 готові до запуску).
  - **Repository Hygiene**: динамічний лог присутності `devices/presence_log.json` вилучено з індексу Git і додано до `.gitignore`. Додано [`memory/README.md`](file:///home/yurko/AI/SmartGarage/memory/README.md) з обґрунтуванням збереження `memory/memory.json` у Git як персистентної бази знань між сесіями.
  - **Unit Testing**: додано тестовий клас `TestAudioAndRadio` в [`tests/test_backend.py`](file:///home/yurko/AI/SmartGarage/tests/test_backend.py) (RadioService fallback дзеркал, валідація схем відтворення стрімів, захист від path traversal під час видалення медіа; 71 тест успішно пройдено).

## [0.2.6] - 2026-09-17

### Added & Fixed
- **Bluetooth Speaker `JX-BT` (1-й поверх) & Internet Radio Streaming**:
  - Інтегровано підтримку другого Bluetooth-аудіопристрою `JX-BT` (`41:42:62:69:51:9B`) на 1-му поверсі поруч із JBL Clip 5.
  - Оновлено тач-дашборд: динамічне відображення активної колонки, вибір радіостанцій в один клік, керування гучністю та трансляцією онлайн-потоків (Kiss FM, Hit FM, Radio ROKS тощо).
  - Виправлено конфлікт маршрутизації команд у `server/commands/processor.py`: запити *«включи радіо...»* тепер спрямовуються на онлайн-радіопотік, а не на завантаження відео з YouTube.
- **PipeWire Native Audio Output & Bluetooth Optimization**:
  - Переведено вивід плеєра в [`server/devices/bluetooth_speaker.py`](file:///home/yurko/AI/SmartGarage/server/devices/bluetooth_speaker.py) із застарілого `pulsesink` на рідний `pipewiresink target-object=...` з прямою синхронізацією системного годинника.
  - Створено конфігурацію WirePlumber `~/.config/wireplumber/bluetooth.lua.d/51-bluez-a2dp-only.lua`, яка вимикає низькоякісний телефонний профіль гарнітури HSP/HFP (8kHz mono CVSD) та блокує аудіо виключно у високоякісному A2DP-стерео.
  - Виявлено несумісність стороннього патчу `BCM20702A1-0a5c-21f4.hcd` з апаратною ревізією Broadcom BCM20702A0 (`bcdDevice 1.12`), що викликала зависання `link tx timeout`. Чіп надійно функціонує на базовому ROM-коді за наявності A2DP-фіксації.

## [0.2.5] - 2026-09-09

### Added
- **High-Speed AI Engine (Gemini 2.5 Flash via OpenRouter)**:
  - Інтегровано пряме швидкісне API-підключення до моделі `google/gemini-2.5-flash` через OpenRouter.
  - Зменшено час генерації відповідей AI-помічника з 3–5 секунд до менше ніж 1 секунди (~0.85 с).
  - Збережено резервний автоматичний fallback на повний агент `OpenInterpreter` у разі потреби виконання коду.
- **Telegram Bot Remote Control & Notifications (`TelegramBot`)**:
  - Створено автономний Telegram-сервіс [`TelegramBot`](file:///home/yurko/AI/SmartGarage/server/services/telegram_bot.py) без додаткових важких залежностей (використовує `requests` long-polling).
  - Підтримка інтерактивного меню (кнопки: *Статус гаража*, *Клімат*, *Присутність*, *Ворота*, *Світло*, *Вентиляція*).
  - Розумна прив'язка власника за PIN-кодом (`7777`).
  - Підтримка текстових і голосових повідомлень (з транскрипцією аудіо).
  - Автоматичні Push-сповіщення при виявленні прибуття власника/гостей (`PresenceManager`).

## [0.2.4] - 2026-09-07

### Added
- **Hardware BLE Air Scanning on ESP32-S3**:
  - Реалізовано апаратне BLE-сканування з 99% робочим циклом у прошивці [`esp32/src/main.cpp`](file:///home/yurko/AI/SmartGarage/esp32/src/main.cpp).
  - Додано обробку команд `CMD:SCAN_BLE:<duration>` та REST API ендпоінт `GET /api/esp32/scan_ble`.
- **Presence & Visitor Registry System (`PresenceManager`)**:
  - Створено модульний реєстр пристроїв та відвідувачів [`PresenceManager`](file:///home/yurko/AI/SmartGarage/server/devices/presence.py).
  - База збереження пристроїв [`devices/presence_devices.json`](file:///home/yurko/AI/SmartGarage/devices/presence_devices.json) та хронологічний журнал подій [`devices/presence_log.json`](file:///home/yurko/AI/SmartGarage/devices/presence_log.json).
  - Автоматичне розпізнавання власника (смартфон Motorola Edge 50 Pro, смарт-годинник) за комбінацією Classic BT MAC, BLE Service UUIDs та RPA.
  - Розрахунок зон наближення за рівнем RSSI: `<2м` (*дуже близько*), `2–6м` (*поруч*), `>6м` (*на підході*).
  - REST API: `GET /api/presence/status`, `GET /api/presence/log`, `POST /api/presence/devices`, `DELETE /api/presence/devices/<id>`, `POST /api/presence/scan`.
  - Голосові та консольні команди AI: *«хто в гаражі»*, *«хто тут»*, *«присутність»*, *«журнал відвідувань»*, *«хто приходив»*.

## [0.2.3] - 2026-08-27

### Added
- **Bluetooth Audio & JBL Clip 5 Integration**:
  - Створено повнофункціональний контролер [`BluetoothSpeakerController`](file:///home/yurko/AI/SmartGarage/server/devices/bluetooth_speaker.py) для аудіосистеми JBL Clip 5 (`F8:5C:7E:EE:7D:CC`).
  - **Тач-Дашборд 1-го поверху (`/dashboard`):** додано спеціалізовану картку аудіосистеми з кнопками «🔗 З'єднати» / «🔌 Відключити», слайдером гучності (0–100%), статусом «Зараз відтворюється», кнопками керування плеєром (Пауза/Продовжити/Стоп) та швидким пошуком пісень.
  - **Класична консоль (`/`):** додано статус колонки в сайдбар та віджет керування у вкладку «🎬 Медіахаб».
  - **API аудіосистеми:** реалізовано ендпоінти `GET /api/speaker/status`, `POST /api/speaker/connect`, `POST /api/speaker/disconnect`, `POST /api/speaker/volume`, `POST /api/speaker/play`, `POST /api/speaker/control`.
  - **Розумна маршрутизація команд AI:** голосові та текстові запити (*«включи пісню на jbl»*, *«гучність колонки 80»*, *«підключи колонку»*, *«зупини музику»*) автоматично транслюються на Bluetooth-колонку або виступають fallback-варіантом у разі офлайн-статусу проектора.


### Added
- **3-Floor Multi-Zone Climate System (Підвал, 1-й поверх, 2-й поверх)**:
  - Додано підтримку трьох Bluetooth LE датчиків Xiaomi LYWSD03MMC з прив'язкою по поверхах:
    - 🏢 **2-й поверх:** поточний датчик `A4:C1:38:EC:EC:6C`.
    - 🏠 **1-й поверх:** датчик `A4:C1:38:00:00:01` (з можливістю швидкої зміни MAC).
    - ⚓ **Підвал:** датчик `A4:C1:38:00:00:02` (з можливістю швидкої зміни MAC).
  - **Тач-інтерфейс Дашборду 1-го поверху:** додано 3-секційну плитку клімату з окремою температурою, вологістю та зарядом батареї для кожного поверху.
  - **Голосове опитування поверхів:** AI помічник розуміє запити українською мовою для кожного приміщення окремо (*«яка температура в підвалі»*, *«клімат 2 поверх»*, *«стан датчиків на 1 поверсі»*, *«покажи всі датчики»*).
  - **API керування датчиками:** додано `GET /api/sensors/floors` та `POST /api/sensors/bind` для швидкої прив'язки реальних MAC-адрес нових датчиків.

## [0.2.1] - 2026-08-25

### Added
- **1st Floor Touch & Tablet Dashboard (`/dashboard`, `/floor1`)**:
  - Створено спеціалізований тач-інтерфейс (PWA / Kiosk Mode) для планшета на стіні та смартфона.
  - **Керування освітленням та виконавчими пристроями:** великі тач-плитки для світла (з неоновим підсвічуванням стану), витяжки/вентиляції та воріт/замка, кнопки швидкого ввімкнення/вимкнення всього освітлення.
  - **Моніторинг мікроклімату та датчиків:** температура, вологість, якість повітря (MQ2 сенсор газу), заряд батареї BLE термометра та статус ESP32.
  - **Інтерактивний голосовий помічник:** велика кнопка мікрофона з анімацією хвиль, розпізнавання української/англійської мов (Web Speech API) та голосове озвучення відповідей AI (TTS).
  - **Медіахаб та пульт проектора:** статус проектора HY350MAX, кнопки пауза/продовжити/зупинити/трансляція екрану, поле онлайн-стрімінгу YouTube та швидкий запуск із локальної медіатеки.
  - **Діагностика сервера 24/7:** температура CPU ноутбука ThinkPad, навантаження, використання RAM, час безперервної роботи (Uptime) та IP-адреси мережі.
  - **Kiosk & PWA інтеграція:** великий віджет годинника і дати, підтримка Screen Wake Lock API (екран планшета не згасає), повноекранний режим та маніфест для встановлення як додаток на робочий стіл.

## [0.2.0] - 2026-08-25

### Added
- **4G Modem & Router Integration**:
  - Інтегровано 4G USB-модем Qualcomm з локальною мережею `192.168.100.x` та доступом до адмін-панелі.
  - Налаштовано захищене Wi-Fi з'єднання для периферійних пристроїв.
- **ESP32-S3 Firmware & Hardware Flashing**:
  - Створено PlatformIO середовище з підтримкою плати ESP32-S3 (16MB Flash, CDC USB).
  - Прошито дуальну прошивку (`smart_garage_esp32`), що підтримує зв'язок по Wi-Fi (`192.168.100.222`) та по прямому USB Serial CDC (`/dev/ttyACM0`).
- **Dual-Channel Transport in ESP32Controller**:
  - Реалізовано автоматичний вибір каналу (USB Serial або HTTP REST / Webhooks).
  - Фоновий потік `_serial_worker` для прийому телеметрії та відправки апаратних команд (`CMD:DOOR_OPEN`, `CMD:LIGHT_ON`, `CMD:FAN_ON` тощо).

## [0.1.9] - 2026-08-24

### Added
- **Web Dashboard Multi-Tab Interface**:
  - Розділення вебінтерфейсу на три спеціалізовані панелі: `💬 Консоль AI`, `📈 Графіки та Датчики`, `🎬 Медіахаб & Проектор`.
- **Real-Time Telemetry Graphing & History API**:
  - Додано потоковий буфер історії телеметрії `TelemetryHistory` та ендпоінт `GET /api/telemetry/history`.
  - Інтегровано динамічні інтерактивні графіки температури та вологості (Chart.js) в реальному часі.
- **Interactive Media Hub**:
  - Каталог файлів із папки `media/` з можливістю запуску на проектор HY350MAX в один клік (`GET /api/media/list`, `POST /api/media/play`).
  - Віджет керування проектором (пауза, продовження, зупинка, трансляція екрану).
  - Стрімінг онлайн відео (YouTube та direct link) через веб-форму.

## [0.1.8] - 2026-08-23

### Added
- **Self-Healing Dynamic Projector Discovery**:
  - Реалізовано автоматичне виявлення нової IP-адреси та порту проектора HY350MAX через широкомовний протокол SSDP UPnP (`M-SEARCH` `ssdp:all`).
  - Додано динамічне визначення поточної IP-адреси ноутбука (`get_local_ip()`) для генерування правильних локальних медіа-посилань.
  - Автоматичне відновлення зв'язку при зміні мережі або перезавантаженні роутера/проектора без ручного втручання.
  - Оновлено робочу адресу проектора: `10.228.30.59` (DLNA порт `36887`, AirPlay `32017`).

## [0.1.7] - 2026-08-23
- Systemd Autostart & Background Daemon: `smartgarage.service`, автозапуск при завантаженні комп'ютера з підтримкою `Linger=yes`.

## [0.1.6] - 2026-08-22
- Сценарії автоматизації (Stage G), голосовий ввід та виведення медіа виключно на проектор.
