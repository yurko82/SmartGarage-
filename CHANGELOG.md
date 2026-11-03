# Changelog

All notable changes to the Smart Garage Infrastructure project will be documented in this file.

## [0.6.0] - 2026-11-03

### Tests, CI & Legacy Infrastructure Consolidation
- **Reproducible Testing & CI Pipeline**:
  - Створено пайплайн GitHub Actions [`.github/workflows/ci.yml`](file:///home/yurko/AI/SmartGarage/.github/workflows/ci.yml) з перевіркою синтаксису (`compileall`), запуском 181 тесту (`pytest`) та збіркою прошивки ESP32-S3 (`pio run -d esp32`) без потреби в секретах або апаратному забезпеченні.
  - Створено [`requirements-dev.txt`](file:///home/yurko/AI/SmartGarage/requirements-dev.txt) для відтворюваного встановлення залежностей розробки та тестування.
  - Створено [`pytest.ini`](file:///home/yurko/AI/SmartGarage/pytest.ini) із маркуванням `mock` для повної ізоляції від фізичного обладнання та хмарних платних API.
  - Усі 181 тест виконуються без реальних спрацьовувань реле, BLE-сканувань чи платних зовнішніх викликів.
- **Canonical Firmware Source of Truth (PlatformIO)**:
  - Підтверджено та протестовано канонічне джерело істини прошивки: [`esp32/src/main.cpp`](file:///home/yurko/AI/SmartGarage/esp32/src/main.cpp), що збирається через PlatformIO ([`esp32/platformio.ini`](file:///home/yurko/AI/SmartGarage/esp32/platformio.ini)).
  - Проведено чисту тестову збірку: `RAM 20.6%`, `Flash 45.2%`, успішно зібрано бінарний образ `firmware.bin`.
  - Усі застарілі та надлишкові скетчі Arduino IDE (`smart_garage_esp32.ino`, директорію `smart_garage_esp32/`) переміщено в архівну директорію [`esp32/legacy/`](file:///home/yurko/AI/SmartGarage/esp32/legacy/) із пояснювальною документацією [`esp32/legacy/README.md`](file:///home/yurko/AI/SmartGarage/esp32/legacy/README.md).
- **Service Retention & Docker Compose Profiles**:
  - Збережено Mosquitto MQTT брокер як базовий сервіс для зв'язку з ESP32.
  - Додано профіль `cache` для Redis у [`docker-compose.yml`](file:///home/yurko/AI/SmartGarage/docker-compose.yml) із підтримкою автоматичного fallback на локальну пам'ять при відсутності контейнера.
  - Додано профіль `automation` для n8n та профіль `dev` для ізольованої пісочниці Open Interpreter.
  - Підтверджено активну роль TelegramBot для сповіщень про присутність власника та безпеку гаража.
- **Truthful Documentation Alignment**:
  - Повністю оновлено [`README.md`](file:///home/yurko/AI/SmartGarage/README.md): чесно задекларовано, що фізичний привід воріт не встановлено (заблоковано), датчик газу не змонтовано, застарілі сенсори відображаються як історичні, а хмарні TTS-провайдери потребують ключів у `.env`.
  - Оновлено [`.env.example`](file:///home/yurko/AI/SmartGarage/.env.example) актуальними змінними OpenRouter, TTS та безпеки.
  - Оновлено [`SERVER_STATUS.md`](file:///home/yurko/AI/SmartGarage/SERVER_STATUS.md) із зазначенням статусу всіх підсистем.

## [0.5.0] - 2026-11-03

### Ukrainian Voice Text-To-Speech (TTS) Architecture
- **Provider Adapter Interface & Modular Subsystem**:
  - Створено модульну підсистему [`server/tts/`](file:///home/yurko/AI/SmartGarage/server/tts/) з чітким розділенням інтерфейсу провайдерів (`TTSProvider`), результатів (`TTSResult`) та типізованих винятків (`TTSAuthError`, `TTSRateLimitError`, `TTSServerError`, `TTSTimeoutError`, `TTSVoiceNotFoundError`, `TTSMalformedResponseError`).
  - Підсистема повністю автономна та відокремлена від AI/чат-моделей.
- **Configurable Providers & Fallback Orchestration**:
  - Підтримка трьох провайдерів:
    1. **Microsoft Edge Neural TTS** ([`server/tts/edge_provider.py`](file:///home/yurko/AI/SmartGarage/server/tts/edge_provider.py)): локальний безкоштовний провайдер на базі `uk-UA-PolinaNeural` та `uk-UA-OstapNeural`, що не потребує API-ключа та слугує стабільним baseline і надійним резервом (оновлено пакет `edge-tts` до 7.3.1).
    2. **HeyGen Voice Turbo REST** ([`server/tts/heygen_provider.py`](file:///home/yurko/AI/SmartGarage/server/tts/heygen_provider.py)): інтеграція офіційного endpoint `POST /v3/models/audio/tts` (WAV 44.1 kHz) та динамічного отримання переліку голосів `GET /v3/voices` без фіктивних voice_id. Враховано обмеження черги Turbo Free (спільна потужність, термін дії пропозиції до 30.11.2026) без клонування чи завантаження користувацьких голосів.
    3. **ElevenLabs Flash v2.5** ([`server/tts/elevenlabs_provider.py`](file:///home/yurko/AI/SmartGarage/server/tts/elevenlabs_provider.py)): інтеграція моделі `eleven_flash_v2_5` з наднизькою затримкою (~150ms) за тарифом ~$0.04/1 000 символів з підтримкою української мови.
  - Конфігурація у [`config/config.yaml`](file:///home/yurko/AI/SmartGarage/config/config.yaml) та [`server/config.py`](file:///home/yurko/AI/SmartGarage/server/config.py) через `TTS_PROVIDER`, `TTS_MODEL`, `TTS_VOICE_ID`, `TTS_FALLBACK_PROVIDER`, `TTS_TIMEOUT`, `TTS_MAX_TEXT_LENGTH`.
  - API-ключі (`HEYGEN_API_KEY`, `ELEVENLABS_API_KEY`) зчитуються виключно із серверного середовища `.env` і ніколи не передаються в браузер, логи чи Git.
- **Ukrainian Text Normalizer & Length Limiting**:
  - Розроблено модуль [`server/tts/normalizer.py`](file:///home/yurko/AI/SmartGarage/server/tts/normalizer.py):
    - Очищення Markdown, URL, коду, емодзі, тегів HTML.
    - Збереження апострофів в українських словах (`п'ять`, `зв'язок`, `м'яке`) при акуратному видаленні лапок (`«»`, `""`).
    - Граматичне розгортання температур (`+18°C` -> `плюс вісімнадцять градусів`, `-5°C` -> `мінус п'ять градусів`, `21°C` -> `двадцять один градус`, `22°C` -> `двадцять два градуси`, `18.5°C` -> `вісімнадцять з половиною градусів`).
    - Розгортання відсотків (`65%` -> `шістдесят п'ять відсотків`, `21%` -> `двадцять один відсоток`).
    - Розгортання поверхів (`1-й поверх` -> `перший поверх`, `2-му поверсі` -> `другому поверсі`) та технічних одиниць (`ppm`, `В`, `кВт`, `хв`, `сек`).
    - Обмеження максимальної довжини тексту (500 символів) з акуратним завершенням на межі речень.
- **Short-Lived TTL Audio Cache**:
  - Впроваджено [`server/tts/cache.py`](file:///home/yurko/AI/SmartGarage/server/tts/cache.py): кеш аудіофайлів з обов'язковим TTL (1 година), автоматичним вилученням застарілих записів та обмеженням місткості (до 100 файлів). Особисті діалоги не зберігаються необмежено на диску.
- **Unified Web Endpoints & Explicit Browser Fallback**:
  - Оновлено ендпоінти у [`server/webapp.py`](file:///home/yurko/AI/SmartGarage/server/webapp.py):
    - `GET /api/voice/tts` та `POST /api/voice/tts` повертають аудіопотік з обов'язковими інформаційними заголовками: `X-TTS-Provider`, `X-TTS-Voice`, `X-TTS-Fallback`, `X-TTS-Cached`.
    - `GET /api/voice/providers` повертає статус провайдерів та доступних голосів без витоку ключів.
    - `POST /api/voice/preview` для тестового прослуховування розробником.
  - Оновлено клієнтський JavaScript у [`server/static/js/app.js`](file:///home/yurko/AI/SmartGarage/server/static/js/app.js) та [`server/static/js/dashboard.js`](file:///home/yurko/AI/SmartGarage/server/static/js/dashboard.js):
    - Пріоритетне серверне відтворення через `fetch('/api/voice/tts')`.
    - Якщо серверний TTS недоступний або повертає помилку, браузерний `speechSynthesis` запускається ВИКЛЮЧНО як явно позначений резерв із візуальним сповіщенням: `⚠️ Серверний TTS недоступний. Задіяно резервний браузерний синтез (Web Speech API)` (без мовчазної підміни голосу).
    - Кнопки увімкнення/вимкнення озвучення коректно зупиняють відтворення.
- **Developer A/B Evaluation & Benchmark Suite**:
  - Створено інструмент [`scripts/evaluate_tts_providers.py`](file:///home/yurko/AI/SmartGarage/scripts/evaluate_tts_providers.py) зі стандартизованим набором українських фраз (системне сповіщення, клімат/сенсори, follow-up).
  - Підтримка прапорця `--generate` для контрольованого створення тестових MP3/WAV файлів без масової генерації.
  - Безпечна робота при відсутності ключів (виведення чітких інструкцій без вигадування результатів).
- **Test Suite**:
  - Створено тестовий набір [`tests/test_tts.py`](file:///home/yurko/AI/SmartGarage/tests/test_tts.py) з 27 всебічними тестами (нормалізація, збереження апострофів, кеш, таймаути, 429 backoff, 5xx, моки WAV/MP3, fallback, вимкнене TTS, заголовки).
  - Загальна кількість тестів проекту досягла **181 тесту**, усі проходять успішно (181/181 passed, 100%).

## [0.4.0] - 2026-11-03

### OpenRouter Integration, AI Routing & Model Evaluation Architecture
- **Dedicated OpenRouter Client Architecture**:
  - Створено автономний клієнт [`server/ai/openrouter_client.py`](file:///home/yurko/AI/SmartGarage/server/ai/openrouter_client.py) із підтримкою Function Calling, контролем лімітів витрат, структурованим логуванням та обробкою помилок.
  - Повна типізація виняткових ситуацій: `OpenRouterAuthError`, `OpenRouterRateLimitError`, `OpenRouterServerError`, `OpenRouterTimeoutError`, `OpenRouterPrivacyError`, `OpenRouterBudgetExceededError`, `OpenRouterConnectionError`.
  - Усі помилки клієнта повертають користувачеві вичерпні, зрозумілі повідомлення українською мовою без розкриття технічних ключів чи аварійного скидання в незахищений інтерпретатор.
- **Configurable Model & Environment Isolation**:
  - Підтримка налаштування моделі через змінну оточення `OPENROUTER_MODEL` (Baseline: `google/gemini-2.5-flash`), `OPENROUTER_TIMEOUT` (за замовчуванням 30.0s), `OPENROUTER_MAX_TOKENS` (800) та `OPENROUTER_DAILY_BUDGET` ($1.00/день).
  - Конфігурація у [`server/config.py`](file:///home/yurko/AI/SmartGarage/server/config.py) та [`config/config.yaml`](file:///home/yurko/AI/SmartGarage/config/config.yaml).
  - API-ключ завантажується виключно з безпечного оточення (`.env`), ніколи не зберігається в YAML, системі контролю версій чи на стороні браузера.
- **Provider Privacy & Telemetry Sanitization**:
  - Налаштування приватності провайдера OpenRouter: `provider: {"data_collection": "deny"}`.
  - Функція `sanitize_context_snapshot()` видаляє локальні IP-адреси (`192.168.x.x`, `10.x.x.x`), MAC-адреси пристроїв та сенсорів, паролі, токени та конфіденційні хеші перед відправкою до моделі.
  - Жорстка заборона мовчазного скасування обмежень приватності: якщо маршрут вимагає дозволу на збір даних, запит переривається винятком `OpenRouterPrivacyError` без прихованого переходу на публічний збір даних.
- **Resilience, Retry & Budget Enforcement**:
  - Експоненційний retry/backoff для статусів 429 (Rate Limit) та 5xx (Server Error) з налаштовуваним числом спроб (за замовчуванням 2).
  - Щоденний облік витрат у [`memory/openrouter_usage.json`](file:///home/yurko/AI/SmartGarage/memory/openrouter_usage.json): підрахунок prompt/completion токенів і реальної суми у USD із блокуванням перевищення добового бюджету (`OpenRouterBudgetExceededError`).
  - Безпека виконання: збій OpenRouter ніколи не призводить до автоматичного запуску стороннього довільного коду (OpenInterpreter відключено як fallback).
- **Controlled A/B Evaluation Suite**:
  - Розроблено та протестовано комплексний набір із 8 сценаріїв у [`tests/test_openrouter_ab.py`](file:///home/yurko/AI/SmartGarage/tests/test_openrouter_ab.py):
    1. Звичайний діалог (українська ввічливість і граматика).
    2. Музичний пошук і відтворення (виклик tool з верифікацією програвача).
    3. Follow-up «спробуй ще раз» (автоматичне збереження запиту невдалої дії).
    4. Неоднозначний запит (постановка уточнювального запитання перед дією).
    5. Невідомий/офлайн стан сенсора (правдивість, відсутність галюцинацій).
    6. Відхилена заборонена дія (суворе дотримання фізичної безпеки воріт).
    7. Помилковий результат tool (повідомлення про невдачу без хибного звітування про успіх).
    8. Timeout та Rate Limit (коректний backoff та зрозуміле українське сповіщення).
- **Comparative Analysis & Model Recommendations**:
  - Створено аналітичний скрипт [`scripts/evaluate_models_ab.py`](file:///home/yurko/AI/SmartGarage/scripts/evaluate_models_ab.py) з розрахунком припущень для гаража (30 запитів/день, ~900/міс):
    - **Baseline** (`google/gemini-2.5-flash`): ~$0.347/міс, контекст 1M токенів, TTFT ~0.65s, відмінне володіння українською мовою та висока надійність tools. Збережено за замовчуванням.
    - **Економічний кандидат** (`google/gemini-2.5-flash-lite`): ~$0.088/міс (-74% вартості), TTFT ~0.42s (+35% швидкості), рекомендовано для оптимізації витрат.
    - **Альтернативний кандидат** (`openai/gpt-4o-mini`): ~$0.132/міс (-63% вартості), TTFT ~0.55s, еталонна строгість JSON схем.
    - **Преміум кандидат** (`google/gemini-2.5-pro`): ~$1.417/міс (+300% вартості), надлишковий для повсякденних команд гаража.
- **Testing Integrity**:
  - 15 нових тестів у `tests/test_openrouter_ab.py` (15/15 passed).
  - Загальний набір тестів проекту зріс до 154 тестів, усі проходять успішно (154/154 passed, 100%).

## [0.3.1] - 2026-11-03

### Web Dialogue, Context Retention & Controlled Follow-Up Architecture
- **Stable, Isolated & Secure Web Session IDs**:
  - Створено централізований менеджер сесій [`server/ai/session_manager.py`](file:///home/yurko/AI/SmartGarage/server/ai/session_manager.py) з повною ізоляцією браузерних та API сесій.
  - Повністю ліквідовано використання глобального ідентифікатора `web_console`.
  - Серверна перевірка та генерація захищених сесійних ідентифікаторів у [`server/webapp.py`](file:///home/yurko/AI/SmartGarage/server/webapp.py): для браузерних сесій використовується криптографічно підписаний `session["dialog_session_id"]`, спроби клієнта підставити чужий ID блокуються з кодом 403.
  - Сувора валідація формату `is_safe_session_id`: заборона персональних імен (yurko, admin, yuri тощо), IP-адрес, email-адрес та MAC-адрес сенсорів у session ID.
- **Valid OpenRouter Tool-Call Message Cycles**:
  - Реалізовано збереження повного циклу виклику інструментів у буфері повідомлень: повідомлення `assistant` із `tool_calls`, окремі повідомлення `tool` для кожного `tool_call_id` з результатами, і фінальна текстова відповідь `assistant`.
  - Виправлено обрізку контексту: історія зберігається та обрізається атомарними раундами (turns), що унеможливлює появу осиротілих `tool` повідомлень без відповідного `tool_calls`.
  - Запобігання галюцинаціям: модель більше ніколи не зберігає «Команду виконано», якщо інструмент насправді повернув помилку чи статус `success: False`.
  - Додано функцію `validate_openrouter_messages()`, що перевіряє сумісність послідовності повідомлень зі специфікаціями актуальних моделей OpenRouter (Google Gemini 2.5 Flash, Anthropic Claude 3.5, OpenAI GPT-4o).
- **Controlled Follow-Up & Short-Term Pending Actions**:
  - Впроваджено механізм `PendingAction` для фіксації останньої дії та її результату для кожної сесії з TTL 300 секунд.
  - Розпізнавання намірів повторення («спробуй ще раз», «повтори», «так само», «не вийшло» тощо) через `is_retry_intent()` та контролер `handle_retry_followup()`.
  - Якщо дія вже успішна: система не повторює побічну дію сліпо, а повідомляє про вже досягнутий результат або просить уточнити намір.
  - Якщо дія завершилася невдачею: повторна спроба автоматично використовує параметри (назву пісні/радіостанції, пристрій) з попереднього запиту без потреби повторного опису користувачем.
- **Truthful Music & Audio Status Reporting**:
  - В інструментах `play_song` та `play_radio` у [`server/ai/tools.py`](file:///home/yurko/AI/SmartGarage/server/ai/tools.py) додано точну типізацію статусів: `playback_started`, `device_unavailable`, `ytmusic_error`, `playback_failed`, `not_found`, `blocked`.
  - Збереження початкового запиту користувача (`initial_query` та `query`).
  - Система ніколи не стверджує, що трек грає, доки програвач не підтвердив успішний старт.
- **Safety Boundaries & Taboo Enforcement on Follow-Up**:
  - Намір у попередньому повідомленні не є дозволом на заборонену фізичну дію: заблоковані команди (наприклад, керування приводом воріт `control_device(door)` або несанкціоновані інструменти) неможливо обійти формулюванням «спробуй ще раз» чи «повтори».
  - Жорстке табу на російськомовний контент: відхилені запити російською мовою не можуть бути повторно активовані через механізм повтору.
- **Session Persistence Across Restarts**:
  - Сесії та pending actions автоматично зберігаються на диску в [`memory/dialog_sessions.json`](file:///home/yurko/AI/SmartGarage/memory/dialog_sessions.json) та відновлюються після перезапуску сервера.
- **Comprehensive Test Suite**:
  - Створено тестовий набір [`tests/test_webdialog_context.py`](file:///home/yurko/AI/SmartGarage/tests/test_webdialog_context.py) з 12 вичерпними тестами (ізоляція сесій, підміна session ID, відсутність персональних даних, збереження після рестарту, повтор музики, блокування заборонених дій, багатокрокові tool calls, валідатор OpenRouter).
  - Усі 139 тестів бекенду виконано успішно (139/139 passed, 100%).

## [0.3.0] - 2026-11-03

### Sensors & Telemetry Authenticity (Truth Architecture)
- **Unified Freshness & Telemetry Truth Engine**:
  - Створено модуль [`server/sensors/freshness.py`](file:///home/yurko/AI/SmartGarage/server/sensors/freshness.py) із централізованими константами опитування (`SENSOR_POLL_INTERVAL_SECONDS = 900` / 15 хв) та єдиним порогом свіжості (`SENSOR_FRESHNESS_THRESHOLD_SECONDS = 1200` / 20 хв).
  - Чітка типізація станів сенсорів: `online`, `stale`, `offline`, `not_installed`, `never_seen`.
  - Для кожного виміру гарантовано повернення: джерела даних (`ble_direct`, `esp32_ble_bridge`, `sqlite_history`, `cache`), часу останнього успішного виміру в ISO-8601 із timezone offset (`last_updated_iso`, `last_successful_iso`), відносного часу українською (`last_updated_relative`), статусу свіжості та рівня батареї.
  - Жодне застаріле чи офлайн показання більше не видається як поточне: `current_temperature: None` та `temperature: None`, при цьому історичне значення зберігається в окремому полі `last_known_temperature` із зазначенням віку даних.
- **Multi-Source Consolidation & Conflict Merging**:
  - Впроваджено функцію `get_consolidated_floors_telemetry()` у [`server/webapp.py`](file:///home/yurko/AI/SmartGarage/server/webapp.py) та алгоритм `merge_sensor_readings()`, що об'єднує прямий хостовий BLE-зв'язок (Bleak), міст ESP32 BLE та історичну базу SQLite.
  - Гарантія збереження свіжих даних: невдале або застаріле опитування ESP32 ніколи не перезаписує актуальні дані прямого BLE (і навпаки).
  - Чітке розмежування поверхів: 1-й поверх (Гараж, без датчика температури) зафіксовано як `installed: False` зі статусом `not_installed`; виключено підтягування випадкових значень з SQLite або підміну середнім чи значеннями з інших поверхів.
- **Frontend UI Truth & Reliability**:
  - Оновлено логіку рендерингу в [`server/static/js/app.js`](file:///home/yurko/AI/SmartGarage/server/static/js/app.js) та [`server/static/js/dashboard.js`](file:///home/yurko/AI/SmartGarage/server/static/js/dashboard.js):
    - Числова температура відображається ВИКЛЮЧНО коли датчик онлайн і вимір свіжий.
    - Якщо датчик офлайн або дані застаріли, відображається `-- °C` (або `--`), а останнє відоме значення виводиться в підписі: «Актуально», «Офлайн — останній вимір …», «Дані застаріли …» або «Датчик не встановлено».
    - Підказки (tooltips) детально повідомляють точне джерело та час зняття показника.
- **Owner Constraints & Safety Integrity**:
  - Повна безпека за відсутності датчика газу: `gas_ppm = None` не викликає `TypeError` в оцінці телеметрії чи сценаріях, сценарій `scenario_gas_alarm()` коректно повертає повідомлення про недоступність функції.
- **Comprehensive Regression Tests**:
  - У [`tests/test_backend.py`](file:///home/yurko/AI/SmartGarage/tests/test_backend.py) додано тестовий набір `TestSensorFreshnessAndTelemetryTruth`, який на 100% покриває 8 ключових сценаріїв:
    1. Новий вимір онлайн (`test_1_new_measurement_online`)
    2. Відключення датчика / офлайн (`test_2_sensor_goes_offline`)
    3. Кеш старший за поріг 1200с (`test_3_cache_older_than_threshold`)
    4. SQLite містить лише старе значення (`test_4_sqlite_fallback_only_old_value`)
    5. Неналаштований датчик 1-го поверху (`test_5_sensor_not_configured`)
    6. Конфліктні мітки часу BLE та ESP32 (`test_6_conflicting_timestamps_ble_and_esp32_merging`)
    7. Безпека `gas_ppm = None` (`test_7_gas_ppm_none_safety`)
    8. Відсутній primary sensor при офлайні всіх датчиків (`test_8_missing_primary_sensor_when_all_offline`)
  - Усі 127 тестів пройдено успішно (127/127 passed, 100%).

## [0.2.9] - 2026-11-03

### Security Hardening & Zero-Trust Architecture
- **Unified Server-Side Authentication & Session Security**:
  - Впроваджено модуль [`server/security/auth.py`](file:///home/yurko/AI/SmartGarage/server/security/auth.py) та універсальний декоратор `@require_auth` для всіх мутуючих ендпоінтів Flask (пристрої, сценарії, медіа, проектор, Bluetooth-колонка, радіо, YT Music, BLE сканування, присутність).
  - Підтримка Direct API авторизації через заголовки `X-Admin-PIN` або `Authorization: Bearer <pin>`.
  - Захищені HTTP-only cookie-сесії з атрибутами `SameSite=Lax`, лімітом 12 годин та захистом від CSRF через `X-CSRF-Token`.
  - Захист від brute-force підбору PIN-коду: ковзне вікно `LoginRateLimiter` (максимум 5 спроб за 300 секунд, блокування з HTTP 429).
  - Безпечне порівняння PIN-кодів у константному часі через `hmac.compare_digest`.
  - Frontend оновлено: автоматичне перехоплення `fetch` запитів для додавання `X-CSRF-Token`, динамічна генерація унікального `session_id` для збереження контексту діалогу в AI чаті.
- **Centralized Audit Logging & Secret Sanitization**:
  - Створено модуль [`server/security/audit.py`](file:///home/yurko/AI/SmartGarage/server/security/audit.py) для запису структурованого аудиту всіх дій (`web`, `voice`, `telegram`, `ai`, `mqtt`) у файл `logs/audit.log`.
  - Автоматична санітизація та маскування (`[REDACTED]`) чутливих полів (паролі, PIN-коди, токени, ключі API).
  - Прив'язка кожного виклику до унікального кореляційного ID (`correlation_id`).
- **Elimination of Arbitrary Code Execution (Open Interpreter Lockdown)**:
  - OpenInterpreter вимкнено за замовчуванням у production (`ENABLE_OPEN_INTERPRETER=false`).
  - Усунено фоллбек на довільне виконання коду (`interpreter.chat`) з `auto_run=True` та `safe_mode="off"`.
  - Усі локальні та віддалені запити до AI виконуються строго через `ToolDispatcher` з allowlist дозволених операцій.
- **Network & Docker Hardening**:
  - `docker-compose.yml`: порти Redis (`6379`) та Mosquitto (`1883`, `9001`) обмежено локальним приватним інтерфейсом `127.0.0.1`.
  - Контейнер `interpreter` виділено у профіль для розробки (`profiles: ["dev"]`).
  - Mosquitto MQTT: вимкнено анонімний доступ (`allow_anonymous false`), налаштовано захист паролем та обмеження доступу до топіків через ACL ([`config/mosquitto/mosquitto.acl`](file:///home/yurko/AI/SmartGarage/config/mosquitto/mosquitto.acl)).
- **ESP32 Firmware & OTA Hardening**:
  - У прошивці ESP32 ([`esp32/src/main.cpp`](file:///home/yurko/AI/SmartGarage/esp32/src/main.cpp)) вимкнено незахищене Web OTA (`ENABLE_WEB_OTA = 0`, повертає HTTP 403 Forbidden).
  - Додано перевірку API токена (`X-API-Key` / `key`) для локальних керувальних HTTP-ендпоінтів.
  - Вилучено відкриті облікові дані Wi-Fi та MQTT з усіх файлів прошивки (`main.cpp`, `smart_garage_esp32.ino`), замінено на безпечні плейсхолдери.
- **Owner Constraints Compliance**:
  - **Gas Sensor Deactivation (Constraint #1)**: деактивовано логіку та сценарії MQ2, повертається `gas_ppm: null`, `gas_installed: false`, `gas_status: "not_installed"`.
  - **Garage Door Control Block (Constraint #2)**: повне блокування відкриття/закриття воріт на всіх рівнях, стан read-only `unknown`.
- **Secret Hygiene & Documentation**:
  - Вичищено плейсхолдери паролів у `config/config.yaml` та `config/mosquitto/password.txt`.
  - Оновлено [`.env.example`](file:///home/yurko/AI/SmartGarage/.env.example) з інструкціями щодо змінних середовища та необхідності ротації паролів.
  - Розширено тестовий набір `TestOwnerSecurityConstraints` у [`tests/test_backend.py`](file:///home/yurko/AI/SmartGarage/tests/test_backend.py). 119 тестів успішно пройдено (100%).

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
