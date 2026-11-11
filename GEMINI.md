# Project Agent Rules & Execution Policy

## Autonomy & Command Execution Policy
- **Automatic Execution**: Execute all standard, non-destructive commands (such as reading files, grep/search, running tests, linting, building, starting/stopping local dev servers within the workspace, git status, git diff, editing project files) immediately without asking for user confirmation.
- **Critical & Dangerous Actions Confirmation**: ONLY pause and prompt the user for explicit confirmation before executing potentially destructive or critical actions, including:
  - Recursive file/directory deletion (`rm -rf`, deleting entire modules or root directories).
  - Force operations in Git (`git push --force`, `git reset --hard` that could drop uncommitted work).
  - Dropping databases or truncating production/critical data stores.
  - Modifying system-wide files outside the workspace (e.g. `/etc`, `/usr`, `/var`) or killing system critical processes.
  - Executing unknown or unverified external binary downloads (`curl ... | bash`).

## Мовна політика та абсолютна заборона російської мови (ЖОРСТКЕ ТАБУ)
- **Виключно українська мова**: Спілкування з користувачем, інтерфейс веб-сайту, тексти сповіщень (Telegram, голос, логи, MQTT) мають бути ВИКЛЮЧНО українською мовою (допускається англійська лише для технічного коду, бібліотек, API та конфігурацій).
- **Категоричне табу на російську мову**: Ніякої російської мови ні в діалогах, ні в коментарях, ні в коді, ні на сайті. Жодних винятків.
- **Повна заборона російськомовного контенту та музики**: Категорично заборонено шукати, відтворювати чи транслювати музику, треки, радіостанції чи відео російською мовою. Будь-які подібні запити негайно блокуються та відхиляються українською мовою.

## Архітектурні принципи та правила розробки (Architecture & Quality Gate)
1. **Заборона хардкоду MAC-адрес та секретів**:
   - Будь-які апаратні MAC-адреси (Bluetooth, BLE, Wi-Fi BSSID), паролі та токени виносяться виключно у `config/devices.yaml` або `.env` (які ігноруються Git).
   - У репозиторії зберігаються лише `config/devices.yaml.example` та `esp32/src/secrets.h.example` із фіктивними MAC-адресами (`00:11:22:33:44:xx`).
   - Будь-який коміт, що містить реальні MAC-адреси або персональні дані, суворо блокується.

2. **Підтримка подвійної аудіосистеми (Dual Speaker Setup)**:
   - Гараж має два незалежних аудіопристрої: `JX-BT` (1-й поверх) та `JBL Clip 5` (гараж).
   - Обидва пристрої мають повноцінну підтримку в конфігурації, веб-інтерфейсі та маршрутизаторі команд.

3. **Модульне розділення сервісів**:
   - `DeviceService` / ESP32: фізичний рівень (реле, ворота, сенсори, CC1101 433 МГц).
   - `Core / Automation`: бізнес-логіка, сценарії, правила присутності, база телеметрії `TelemetryDB`.
   - `Voice`: голосовий асистент `voice_listener` на базі OpenWakeWord + Faster-Whisper.
   - `Web / UI`: легкий веб-інтерфейс Flask + WebSockets/SSE для керування та графіків.

4. **Контракт ESP32 (Single Source of Truth)**:
   - ESP32 є єдиним джерелом правди про стан фізичних контактів (кінцевики воріт, стан реле світла).
   - Серверний бекенд не має права емулювати успішне перемикання реле, якщо ESP32 повернув помилку або офлайн.
   - Обов'язкова валідація payload та перевірка API ключа `X-ESP32-Key` для всіх запитів від мікроконтролера.

5. **Герметичність та ізоляція тестів (Test Hermeticity)**:
   - Жоден юніт-тест не має права змінювати або створювати файли у виробничих директоріях `memory/`, `devices/` або `config/`.
   - Всі операції запису в тестах перенаправляються в `tmp_path` за допомогою фікстури `tests/conftest.py` та змінної `SMARTGARAGE_DATA_DIR`.
   - Тести мають успішно проходити в чистому клонованому репозиторії без локальних файлів конфігурації.