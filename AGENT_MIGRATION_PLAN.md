# AGENT_MIGRATION_PLAN.md — покроковий план міграції SmartGarage (для агента Antigravity)

Станом на 10.11.2026. Доповнює `AGENT_TASK.md` (безпека, гігієна репо) і `AGENT_TASK_ESP32_RF.md` (ESP32 і 433 МГц). Цей файл задає **порядок і межі**: що робити першим, коли зупинятись, як відкотитись.
Репозиторій: `github.com/yurko82/SmartGarage-`. Сервер: `/home/yurko/AI/SmartGarage`.

## 0. Мета і принципи

**Мета.** Перейти від «чотирьох входів у дублюючу логіку + одного циклу прошивки на все» до структури, де:
- один шар команд `DeviceService` обслуговує Web, Telegram, AI та голос;
- ESP32 має один основний транспорт (MQTT), Serial лишається для налагодження;
- стан і дані відокремлені від коду і конфігурації;
- залежності мінімальні, тести герметичні.

**Принципи.**
1. **Не переписувати з нуля.** Міграція за патерном strangler: нова структура росте поруч, функції переїжджають по одній, старий код видаляється лише після підтвердження.
2. **Поведінка не змінюється**, поки крок явно не каже інше. Кожен крок доводиться тестами та golden-знімками відповідей.
3. **Один крок — одна гілка — один PR.** Жодних «мега-PR».
4. **Продакшн-реле й радіо чіпає лише власник** (перепрошивка, перепарювання, фізичні перевірки).
5. **Завжди є відкат** (розділ 4). Крок без відкату не починати.

## 1. Правила роботи

1. Дотримуйся `GEMINI.md`: українська мова (коментарі, UI, логи, звіти), політика автономності.
2. Без запиту: читання, `grep`, тести, лінт, збірка, редагування файлів проєкту, нові гілки та PR.
3. **Тільки з підтвердженням власника:** `rm -rf`, `git push --force`, `git reset --hard`, переписування історії, зміни в `/etc` і `/var`, `pio run -t upload` (прошивка ESP32), заміна/видалення старого venv, зупинка системних сервісів, будь-які дії, що вмикають реле.
4. Перезапуск `smartgarage.service` — лише після злиття PR і лише у вікно, яке підтвердив власник. Перед перезапуском виконати `scripts/smoke.sh` (див. M0.3).
5. Не друкувати й не комітити секрети, MAC-адреси, внутрішні IP, серійні номери пристроїв, `.env`.
6. Керування воротами вимкнено свідомо — не вмикати.
7. Не додавати нових неавторизованих POST-ендпоінтів.
8. Тести ніколи не пишуть у робочі дані (`memory/`, `devices/`, `config/`) і не торкаються заліза, BLE, MQTT-брокера чи платних API.

## 2. Шаблон кожного кроку

```bash
cd /home/yurko/AI/SmartGarage
git switch main && git pull
git switch -c <тип>/<id-кроку>-<коротка-назва>   # приклад: refactor/m2-3-device-service

# ... робота ...

python3 -m compileall server tests scripts
TESTING=true ADMIN_PIN=9876 ESP32_API_KEY=ci_test_esp32_key_12345 OPENROUTER_API_KEY="" PYTHONPATH=. pytest -q tests/
pio run -d esp32          # якщо чіпали прошивку
git status --short        # має бути чисто: тести нічого не змінюють
```

Звіт українською після кроку: гілка і PR; що змінено (3–6 пунктів); результат `pytest` (N пройдено, 0 впало), `git status` чистий; що має зробити власник; що не вдалося перевірити без заліза; як відкотити.

## 3. Карта фаз і залежностей

| Фаза | Зміст | Оцінка | Залежить від |
|---|---|---|---|
| M0 | Страхувальна сітка, залежності, інструменти | 1–2 дні | відкриті гілки з `AGENT_TASK.md` |
| M1 | ESP32: надійність, контракт MQTT, рішення G1 | 1–2 тижні (залежить від заліза) | M0 |
| M2 | Сервер: `DeviceService`, єдиний лінк до ESP32, Blueprints | 2–4 тижні | M0, частково M1 (MQTT-контракт) |
| M3 | Дані, JsonStore, типи, розбиття тестів | 1–2 тижні, паралельно з M2 | M0 |
| M4 | Опційно: Open Interpreter, один UI | за рішенням власника | M2 |

Оцінки орієнтовні й залежать від доступності власника для фізичних перевірок.

---

## Фаза M0 — страхувальна сітка

### M0.1 Тег і резервна копія (до будь-яких змін)

```bash
cd /home/yurko/AI/SmartGarage
git tag -a pre-migration -m "Стан перед міграцією 10.11.2026"
git push origin pre-migration

mkdir -p ~/backups/smartgarage-$(date +%Y%m%d)
tar czf ~/backups/smartgarage-$(date +%Y%m%d)/data.tar.gz memory devices config/rf_mappings.json config/config.yaml .env telemetry.db 2>/dev/null
ls -lh ~/backups/smartgarage-$(date +%Y%m%d)/
```

`.env` у архіві — лише локальна копія на сервері, не пушити й не показувати.

**Готово, коли:** тег `pre-migration` є на GitHub, архів створено, розмір ненульовий.
**Відкат:** розпакувати архів у корінь проєкту, `git checkout pre-migration`.

### M0.2 Закрити зауваження до відкритих гілок

Це блокер для злиття `chore/untrack-personal-files` (див. `AGENT_TASK.md`, P0-1) та `fix/esp32-rf-diagnostics`:

1. Тести `TestBleScanFiltering::test_get_bound_macs` і `test_scan_all_ble_filters_bound_devices` залежать від прибраного `devices/bluetooth_devices.json`. Перевести на тимчасовий файл у `tmp_path` з фейковими MAC (`00:11:22:33:44:55`).
2. Реальні MAC лишились у ~19 відстежуваних файлах (`server/ai/tools.py`, `commands/processor.py`, `bluetooth_sensor.py`, `bluetooth_speaker.py`, `dashboard.js`, `app.js`, шаблони, скрипти, `esp32/src/main.cpp`, документація, CHANGELOG, тести). Винести в конфіг поза git (`config/devices.yaml`, шаблон `config/devices.yaml.example`), у коді — читання з конфігу, у документації та тестах — фейкові значення.
3. Додати в `tests/conftest.py` автофікстуру, яка переспрямовує `memory/`, `devices/` і `config/rf_mappings.json` у `tmp_path` (змінна `SMARTGARAGE_DATA_DIR`). Тест, що змінює робочий файл, має падати.
4. Звіт `docs/ESP32_RF_DIAGNOSTICS.md`: прибрати внутрішній IP сервера та серійний номер USB-пристрою; формулювання «Підтверджено» замінити на «підтверджено кодом» або «підтверджено виміром» (де є вивід `journalctl`/`mosquitto_sub`).
5. Повторно запустити повний `pytest` у чистій копії (`git clone` у `/tmp`), переконатись: 0 впало, `git status` чистий.

**Дія власника:** змінити пароль Mosquitto, вирішити щодо видимості репо (приватний або `git filter-repo`).
**Готово, коли:** обидві гілки зелені в CI і злиті (або об'єднані в одну).

### M0.3 Smoke-скрипт і базові метрики

Створити `scripts/smoke.sh` (без актуації, лише читання):

```bash
#!/usr/bin/env bash
set -u
SG_URL="${SG_URL:-http://127.0.0.1:5000}"   # перевір порт у config.yaml
ok=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "OK   $1"; ok=$((ok+1)); else echo "FAIL $1 (отримано $2, очікувалось $3)"; fail=$((fail+1)); fi; }

check "health"                 "$(curl -s -o /dev/null -w '%{http_code}' "$SG_URL/health")" 200
check "esp32 status (публічний)" "$(curl -s -o /dev/null -w '%{http_code}' "$SG_URL/api/esp32/status")" 200
check "захищений POST без авторизації" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$SG_URL/api/device/light/toggle")" 401
check "/command без авторизації"       "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$SG_URL/command")" 401
echo "Підсумок: OK=$ok FAIL=$fail"; [ "$fail" -eq 0 ]
```

(Остання перевірка очікує 401 лише після P0-2; до того вона має падати — це нормально.)

Записати базові метрики в `docs/MIGRATION_BASELINE.md` (без секретів): кількість тестів, час `pytest`, `free -h`, `systemctl status smartgarage.service`, список активних контейнерів `docker ps`, розмір venv (`du -sh <venv>`), кількість пакетів (`pip list | wc -l`).

**Готово, коли:** `smoke.sh` запускається, метрики записані.

### M0.4 Розділити залежності (новий venv, старий не чіпати)

Проблема: `requirements.txt` — це freeze усього venv (201 пакет), напряму імпортується ~22.

1. Порахувати реальні імпорти (AST-скрипт, збережений як `scripts/audit_imports.py`):

```bash
python3 - <<'EOF'
import ast, pathlib, sys
std = set(sys.stdlib_module_names)
used = {}
for root in ['server', 'scripts', 'tests', 'training']:
    for p in pathlib.Path(root).rglob('*.py'):
        try:
            t = ast.parse(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        for n in ast.walk(t):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name.split('.')[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods = [n.module.split('.')[0]]
            for m in mods:
                if m not in std and m not in ('server', 'tests', 'scripts'):
                    used.setdefault(m, set()).add(root)
for k, v in sorted(used.items()):
    print(f"{k:22s} {'/'.join(sorted(v))}")
EOF
```

2. Розкласти на файли:
   - `requirements.txt` — ядро (за результатом аудиту, очікувано: Flask, Flask-SocketIO, python-socketio, simple-websocket, paho-mqtt, pyserial, requests, PyYAML, python-dotenv, psutil, Pillow, matplotlib, numpy, bleak, aiohttp, edge-tts, prometheus-client);
   - `requirements-voice.txt` — `faster-whisper`, `onnxruntime`, `openwakeword`, `sounddevice` (використовує `server/services/voice_listener.py`);
   - `requirements-ai.txt` — `open-interpreter` (опційно, див. M4.1);
   - `requirements-dev.txt` — вже є (pytest і CI), перевірити;
   - `training/requirements.txt` — `torch`, `transformers`, `trl`, `unsloth`, `datasets` (використовує лише `training/`).
3. Знайти й вирішити конфлікти (кожен — окремий коміт з обґрунтуванням):
   - `asyncio_mqtt` і `aiomqtt` імпортуються обидва → залишити один (`grep -rn "asyncio_mqtt\|aiomqtt" server`);
   - `server/api/telemetry.py` використовує FastAPI, решта — Flask → з'ясувати, чи змонтований цей модуль; якщо ні, видалити або перенести на Flask Blueprint і прибрати `fastapi`/`uvicorn`/`starlette`;
   - `redis` використовується лише з профілем `cache` → винести в опційні.
4. Створити новий venv **поруч** зі старим:

```bash
python3 -m venv ~/AI/sg-venv
~/AI/sg-venv/bin/pip install --upgrade pip
~/AI/sg-venv/bin/pip install -r requirements.txt -r requirements-dev.txt
TESTING=true ADMIN_PIN=9876 ESP32_API_KEY=ci_test_esp32_key_12345 OPENROUTER_API_KEY="" PYTHONPATH=. ~/AI/sg-venv/bin/pytest -q tests/
~/AI/sg-venv/bin/pip freeze > constraints.txt
```

5. Модулі, що імпортують `interpreter`, мають працювати без нього (`server/ai/manager.py`, `server/ai/chat.py`): обгорнути імпорт у `try/except ImportError` з ясним логом і відключенням цієї гілки.
6. Перемикання на сервері (**з підтвердженням власника**): змінна `VENV_PYTHON` у `scripts/run_server.sh` / юніті; `systemctl cat smartgarage.service` покаже, який варіант реально встановлено. Старий venv не видаляти 14 днів.

**Готово, коли:** `pytest` зелений у новому venv, сервер стартує з ним, `scripts/smoke.sh` проходить, кількість пакетів у `pip list` суттєво менша.
**Відкат:** повернути `VENV_PYTHON` на старий шлях і перезапустити сервіс.

### M0.5 Інструменти якості (спочатку без блокування)

1. `pyproject.toml` з конфігом `ruff` (lint і format) та `mypy` для `server/devices`, `server/core`, `server/security`.
2. У `.github/workflows/ci.yml` додати кроки `ruff check` і `mypy` з `continue-on-error: true`. Блокуючими вони стануть у M3.4.
3. Нічого масово не переформатовувати в цьому кроці.

### M0.6 Правила для агентів (`GEMINI.md`)

Додати розділ «Архітектурні правила»: файл не більший за ~500 рядків; нова команда пристрою — лише через `DeviceService` (після M2.3); нова залежність — з обґрунтуванням у PR; тести герметичні (фікстури `tmp_path`); жодних захардкоджених MAC/IP/шляхів; робочі дані не потрапляють у git.

## 6. Контрольний список прогресу

- [ ] M0.1 Тег і резервна копія
- [ ] M0.2 Зауваження до відкритих гілок закриті
- [ ] M0.3 `smoke.sh` і базові метрики
- [ ] M0.4 Залежності розділені, новий venv
- [ ] M0.5 ruff і mypy у CI (не блокують)
- [ ] M0.6 Правила в `GEMINI.md`
