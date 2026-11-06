#!/usr/bin/env python3
"""
Генератор детальної технічної інструкції системи SmartGarage у форматі PDF
та модуль відправки сформованого документу в Telegram адміністратору.
"""

import os
import sys
import subprocess
import requests
from pathlib import Path
from dotenv import load_dotenv

# Завантаження змінних середовища
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

HTML_PATH = ROOT_DIR / "output" / "instruction.html"
PDF_PATH = ROOT_DIR / "output" / "instruction.pdf"
ROOT_PDF_PATH = ROOT_DIR / "instruction.pdf"

CSS_STYLES = """
@page {
    size: A4;
    margin: 18mm 15mm 18mm 15mm;
    @bottom-right {
        content: "Сторінка " counter(page);
        font-size: 9pt;
        color: #64748b;
    }
}

body {
    font-family: 'DejaVu Sans', 'Liberation Sans', 'Helvetica Neue', Arial, sans-serif;
    color: #1e293b;
    line-height: 1.45;
    font-size: 10pt;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
}

h1, h2, h3, h4 {
    color: #0f172a;
    font-weight: 700;
    margin-top: 1.2em;
    margin-bottom: 0.4em;
    page-break-after: avoid;
}

h1 {
    font-size: 20pt;
    color: #0284c7;
    border-bottom: 3px solid #0284c7;
    padding-bottom: 6px;
    margin-top: 0;
}

h2 {
    font-size: 14pt;
    color: #0369a1;
    border-bottom: 1.5px solid #e2e8f0;
    padding-bottom: 4px;
    margin-top: 1.4em;
}

h3 {
    font-size: 11.5pt;
    color: #0f172a;
    margin-top: 1em;
}

p {
    margin: 0.4em 0;
    text-align: justify;
}

ul, ol {
    margin: 0.4em 0 0.6em 1.4em;
    padding: 0;
}

li {
    margin-bottom: 0.25em;
}

code {
    font-family: 'DejaVu Sans Mono', 'Liberation Mono', monospace;
    background-color: #f1f5f9;
    color: #0f766e;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 9pt;
}

pre {
    background-color: #0f172a;
    color: #f8fafc;
    padding: 10px;
    border-radius: 6px;
    font-size: 8.5pt;
    overflow-x: auto;
    page-break-inside: avoid;
    font-family: 'DejaVu Sans Mono', 'Liberation Mono', monospace;
}

.table-wrap {
    width: 100%;
    margin: 10px 0;
    page-break-inside: avoid;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 9pt;
}

th, td {
    border: 1px solid #cbd5e1;
    padding: 6px 8px;
    text-align: left;
    vertical-align: top;
}

th {
    background-color: #f1f5f9;
    color: #0f172a;
    font-weight: 700;
}

tr:nth-child(even) td {
    background-color: #f8fafc;
}

.badge {
    display: inline-block;
    padding: 2px 6px;
    font-size: 8pt;
    font-weight: 700;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.badge-blue { background-color: #e0f2fe; color: #0284c7; }
.badge-green { background-color: #dcfce7; color: #16a34a; }
.badge-amber { background-color: #fef3c7; color: #d97706; }
.badge-red { background-color: #fee2e2; color: #dc2626; }
.badge-purple { background-color: #f3e8ff; color: #9333ea; }

.callout {
    padding: 8px 12px;
    border-left: 4px solid #0284c7;
    background-color: #f0f9ff;
    border-radius: 0 4px 4px 0;
    margin: 8px 0;
    page-break-inside: avoid;
    font-size: 9.5pt;
}

.callout-warning {
    border-left-color: #f59e0b;
    background-color: #fffbeb;
}

.callout-danger {
    border-left-color: #ef4444;
    background-color: #fef2f2;
}

.callout-success {
    border-left-color: #10b981;
    background-color: #f0fdf4;
}

.card-box {
    border: 1px solid #e2e8f0;
    background: #ffffff;
    border-radius: 6px;
    padding: 10px;
    margin-bottom: 10px;
    page-break-inside: avoid;
}

.page-break {
    page-break-before: always;
}

.cover-header {
    text-align: center;
    padding: 20px 0 10px 0;
    border-bottom: 2px solid #0284c7;
    margin-bottom: 20px;
}

.cover-title {
    font-size: 22pt;
    color: #0284c7;
    margin: 0;
    font-weight: 800;
}

.cover-subtitle {
    font-size: 12pt;
    color: #475569;
    margin-top: 6px;
}

.meta-grid {
    display: table;
    width: 100%;
    margin-top: 15px;
    margin-bottom: 15px;
}

.meta-row {
    display: table-row;
}

.meta-cell {
    display: table-cell;
    padding: 4px 8px;
    font-size: 9pt;
}

.meta-label {
    font-weight: 700;
    color: #334155;
    width: 25%;
}
"""

def generate_html_content() -> str:
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <title>SmartGarage — Повна Технічна Інструкція</title>
    <style>
        {CSS_STYLES}
    </style>
</head>
<body>

    <div class="cover-header">
        <div class="cover-title">SMART GARAGE — ПОВНА СИСТЕМНА ІНСТРУКЦІЯ</div>
        <div class="cover-subtitle">Детальний опис обладнання, датчиків, моделей штучного інтелекту, логіки роботи та вебінтерфейсу</div>
    </div>

    <div class="meta-grid">
        <div class="meta-row">
            <div class="meta-cell meta-label">Проєкт:</div>
            <div class="meta-cell">Smart Garage Autonomous AI Infrastructure</div>
            <div class="meta-cell meta-label">Версія системи:</div>
            <div class="meta-cell"><span class="badge badge-blue">v0.2.0</span> / Core Python 3.12</div>
        </div>
        <div class="meta-row">
            <div class="meta-cell meta-label">Головний сервер:</div>
            <div class="meta-cell">Сервер Linux Mint (24/7 Host, IP: 192.0.2.10)</div>
            <div class="meta-cell meta-label">Мікроконтролер:</div>
            <div class="meta-cell">ESP32-S3 (IP: 192.0.2.20, HTTP + MQTT + Serial)</div>
        </div>
        <div class="meta-row">
            <div class="meta-cell meta-label">Базовий ШІ:</div>
            <div class="meta-cell">OpenRouter (google/gemini-2.5-flash)</div>
            <div class="meta-cell meta-label">Дата генерації:</div>
            <div class="meta-cell">Листопад 2026 року</div>
        </div>
    </div>

    <div class="callout callout-success">
        <b>Цільове призначення документа:</b> Цей посібник містить вичерпну та достовірну технічну інформацію про повний апаратний та програмний комплекс розумного гаража. Він охоплює датчики, актуатори, ШІ-моделі (LLM, STT, TTS), внутрішні пайплайни взаємодії, захищені канали зв'язку та детальний розбір усіх елементів вебінтерфейсу.
    </div>

    <!-- РОЗДІЛ 1 -->
    <h2>1. Архітектурний огляд та фундаментальні принципи</h2>
    <p>
        Система <b>SmartGarage</b> є багаторівневим програмно-апаратним комплексом автономного моніторингу та керування, побудованим на базі сучасних інженерних стандартів:
    </p>
    <ul>
        <li><b>Апаратний рівень (Field Devices):</b> Мікроконтролер <b>ESP32-S3</b>, сенсори мікроклімату <b>Xiaomi LYWSD03MMC</b> (Bluetooth Low Energy), силові реле освітлення та витяжки, мультимедійна аудіосистема (акустика <b>JX-BT</b> на 1-му поверсі та портативна <b>JBL Clip 5</b> у гаражі), а також проектор <b>HY350MAX</b>.</li>
        <li><b>Серверний рівень (Edge Server):</b> Захищений 24/7 хост на ноутбуку ThinkPad під керуванням Linux Mint. Ядро написано на Python 3.12 (Flask, WebSockets, PipeWire/PulseAudio, SQLite Telemetry DB, Paho-MQTT, Bleak).</li>
        <li><b>Хмарний та AI рівень:</b> Мультимодальна мовна модель <b>Gemini 2.5 Flash</b> через шлюз OpenRouter для міркувань та Tool Calling, нейронний голосовий синтез <b>Microsoft Edge Neural TTS</b> (Поліна/Остап), <b>ElevenLabs Flash v2.5</b>, <b>HeyGen Turbo</b>, а також локальний офлайн-бекграунд <b>Ollama (Qwen 2.5 Coder)</b>.</li>
        <li><b>Інтерфейси користувача:</b> Сенсорний Touch-Дашборд (<code>/dashboard</code>), інженерна Консоль AI (<code>/</code>), персональний Telegram-бот <b>@SmartGarageYurkoBot</b>, голосовий інтерфейс мікрофона («hey_jarvis»).</li>
    </ul>

    <div class="callout callout-warning">
        <b>Принцип правдивості телеметрії (Telemetry Truth Architecture):</b>
        Система категорично забороняє генерацію фіктивних показників або підміну відсутніх датчиків усередненими числами. Якщо сенсор не змонтований або дані застаріли (понад 20 хвилин), система чесно маркує стан як <code>not_installed</code>, <code>stale</code> або <code>offline</code>.
    </div>

    <!-- РОЗДІЛ 2 -->
    <h2>2. Сенсорна карта та апаратне обладнання</h2>
    <p>
        Усі датчики та виконавчі пристрої розподілені за функціональними зонами гаражного комплексу:
    </p>

    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th style="width: 18%;">Вузол / Локація</th>
                    <th style="width: 20%;">Модель та MAC / IP</th>
                    <th style="width: 15%;">Протокол</th>
                    <th style="width: 25%;">Параметри вимірювання</th>
                    <th style="width: 22%;">Роль та статус</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><b>2-й поверх</b></td>
                    <td>Xiaomi LYWSD03MMC<br><code>A4:C1:38:EC:EC:6C</code></td>
                    <td>BLE (Bluetooth Low Energy)</td>
                    <td>Температура (°C), Відносна вологість (%), Заряд батарейки (%)</td>
                    <td><span class="badge badge-green">Встановлено</span><br>Опитується ESP32 що 2 хв та Bleak сервером. Запис у SQLite.</td>
                </tr>
                <tr>
                    <td><b>Підвал (Сховище)</b></td>
                    <td>Xiaomi LYWSD03MMC<br><code>A4:C1:38:CC:CA:49</code></td>
                    <td>BLE (Bluetooth Low Energy)</td>
                    <td>Температура (°C), Відносна вологість (%), Заряд батарейки (%)</td>
                    <td><span class="badge badge-green">Встановлено</span><br>Контроль вогкості та замерзання, моніторинг сховища, графіки.</td>
                </tr>
                <tr>
                    <td><b>1-й поверх (Гараж)</b></td>
                    <td>Кліматичний сенсор відсутній</td>
                    <td>—</td>
                    <td>Температура: <code>null</code><br>Вологість: <code>null</code></td>
                    <td><span class="badge badge-amber">Не змонтовано</span><br>Чесний статус <code>not_installed</code>. Жодних вигаданих значень!</td>
                </tr>
                <tr>
                    <td><b>Датчик газу / диму</b></td>
                    <td>MQ Gas/Smoke Sensor</td>
                    <td>—</td>
                    <td>Концентрація CO / газу</td>
                    <td><span class="badge badge-amber">Не змонтовано</span><br>Фізично відсутній, аварійні сценарії не симулюються.</td>
                </tr>
                <tr>
                    <td><b>Реле освітлення</b></td>
                    <td>ESP32-S3 GPIO 5<br>(Relay Light)</td>
                    <td>HTTP REST / MQTT / Serial</td>
                    <td>Стан силового кола: <code>on / off</code></td>
                    <td><span class="badge badge-green">Активно</span><br>Керування головним світлом 1-го поверху через вебінтерфейс, голос, Telegram.</td>
                </tr>
                <tr>
                    <td><b>Реле вентиляції</b></td>
                    <td>ESP32-S3 GPIO 6<br>(Relay Fan)</td>
                    <td>HTTP REST / MQTT / Serial</td>
                    <td>Стан витяжки: <code>on / off</code></td>
                    <td><span class="badge badge-green">Активно</span><br>Примусове або автоматичне провітрювання приміщення гаража.</td>
                </tr>
                <tr>
                    <td><b>Привід воріт</b></td>
                    <td>ESP32-S3 GPIO 4<br>(Door Pulse)</td>
                    <td>Апаратне блокування</td>
                    <td>Стан: суворо <code>CLOSED</code></td>
                    <td><span class="badge badge-red">Блоковано назавжди</span><br>Електропривід фізично відсутній. Будь-які запити блокуються з помилкою безпеки.</td>
                </tr>
                <tr>
                    <td><b>Presence Radar (Власник)</b></td>
                    <td>Motorola Edge 50 Pro<br><code>B8:7E:39:88:22:9B</code></td>
                    <td>Classic BT + BLE RPA Rotation</td>
                    <td>RSSI (дБм), наближення: <code>immediate / near / away</code></td>
                    <td><span class="badge badge-purple">Відстеження</span><br>Автоматичне привітання Юрія, сценарії «Прибуття / Від'їзд».</td>
                </tr>
                <tr>
                    <td><b>Акустика 1-й поверх</b></td>
                    <td>JX-BT Audio<br><code>41:42:62:69:51:9B</code></td>
                    <td>Bluetooth Audio (PipeWire)</td>
                    <td>Потік аудіо, гучність 0-100%</td>
                    <td><span class="badge badge-blue">Медіа</span><br>Основна колонка для озвучення відповідей AI та музики.</td>
                </tr>
                <tr>
                    <td><b>Акустика Гараж</b></td>
                    <td>JBL Clip 5<br><code>F8:5C:7E:EE:7D:CC</code></td>
                    <td>Bluetooth Audio (PipeWire)</td>
                    <td>Потік аудіо, гучність 0-100%</td>
                    <td><span class="badge badge-blue">Медіа</span><br>Портативна акустична колонка для робочої зони.</td>
                </tr>
                <tr>
                    <td><b>Проектор</b></td>
                    <td>HY350MAX<br>IP: <code>192.0.2.30</code></td>
                    <td>AirPlay (57000), REST (8899), DLNA</td>
                    <td>Живлення, Screen Mirroring, HDMI</td>
                    <td><span class="badge badge-blue">Медіа</span><br>Трансляція екрану та медіафайлів на великий екран.</td>
                </tr>
            </tbody>
        </table>
    </div>

    <!-- РОЗДІЛ 3 -->
    <div class="page-break"></div>
    <h2>3. Моделі штучного інтелекту (ШІ) та принципи їхньої роботи</h2>
    <p>
        У системі SmartGarage задіяна каскадна екосистема нейромереж, яка забезпечує осмислення команд, автономне прийняття рішень, високоякісний голос та локальну стійкість:
    </p>

    <div class="card-box">
        <h3>3.1. Основна LLM: Google Gemini 2.5 Flash (через OpenRouter)</h3>
        <p><b>Роль у системі:</b> Центральний інтелект SmartGarage. Здійснює аналіз команд природною українською мовою, зіставлення контексту стану гаража, виклик функціональних інструментів (Function Calling / Tools) та генерацію зрозумілих відповідей.</p>
        <ul>
            <li><b>Економічна ефективність:</b> $0.30 за 1M вхідних та $2.50 за 1M вихідних токенів. При 30 запитах на добу місячні витрати становлять лише <b>~$0.35</b>.</li>
            <li><b>Швидкість реакції (TTFT):</b> Середній час початку генерації першого токена — лише <b>0.65 секунди</b>.</li>
            <li><b>Надійність виклику інструментів (Tools Reliability):</b> Оцінка 4.8/5. Модель стабільно повертає валідні аргументи JSON для виклику пристроїв.</li>
            <li><b>Санітизація телеметрії (Privacy Protection):</b> Перед надсиланням у хмару модуль <code>server/ai/openrouter_client.py</code> маскує внутрішні IP (<code>192.168.x.x</code>), MAC-адреси сенсорів, токени та паролі плейсхолдерами. Передається заголовок заборони збору даних <code>provider_preferences: {{data_collection: "deny"}}</code>.</li>
            <li><b>Контроль бюджету (CostTracker):</b> Жорсткий добовий ліміт <b>$1.00</b> (параметр <code>OPENROUTER_DAILY_BUDGET</code>). У разі вичерпання ліміту платні запити миттєво блокуються із захисним сповіщенням.</li>
            <li><b>Суворе дотримання циклу діалогу:</b> Повна відповідність стандарту OpenRouter: повідомлення <code>assistant</code> з <code>tool_calls</code> &rarr; повідомлення <code>tool</code> з результатом виконання кожного <code>tool_call_id</code> &rarr; фінальна відповідь <code>assistant</code>.</li>
            <li><b>Підтримка намірів Follow-Up:</b> Запити «повтори», «спробуй ще раз», «так само» відновлюють параметри останньої дії (назву пісні чи радіо) без потреби повторного уточнення у власника.</li>
        </ul>
    </div>

    <div class="card-box">
        <h3>3.2. Локальна резервна модель: Ollama (Qwen 2.5 Coder 1.5B)</h3>
        <p><b>Роль у системі:</b> Повна автономність у разі зникнення Інтернету або відсутності ключа OpenRouter.</p>
        <ul>
            <li>Працює локально на хості ThinkPad через локальний API <code>http://localhost:11434</code>.</li>
            <li>Використовує кастомний конфіг <code>config/Modelfile.qwen2.5-coder</code> з системним україномовним промтом.</li>
            <li>Швидко виконує базові команди комутації світла, вентиляції та опитування локальних сенсорів.</li>
        </ul>
    </div>

    <div class="card-box">
        <h3>3.3. Розпізнавання мовлення (STT): OpenWakeWord + Faster-Whisper</h3>
        <p><b>Роль у системі:</b> Постійний моніторинг аудіопотоку та голосове керування без рук (Hands-Free).</p>
        <ul>
            <li><b>Детектор активаційної фрази:</b> <code>openwakeword</code> з моделлю активації <b>«hey_jarvis»</b> (чутливість 0.55). Споживає менше 2% CPU в режимі спокою.</li>
            <li><b>Аудіозахоплення:</b> Працює через віртуальне аудіоджерело PipeWire (<code>pipewire-virtual-source</code>).</li>
            <li><b>Транскрипція мовлення:</b> <code>faster-whisper</code> (модель <code>base</code>, мова <code>uk</code>, квантування <code>int8</code>). Забезпечує миттєву транскрипцію української мови.</li>
            <li><b>Пріоритезація черги:</b> Голосові команди отримують вищий пріоритет (<code>priority=1</code>) у <code>VoiceCommandQueue</code> і обробляються першочергово.</li>
        </ul>
    </div>

    <div class="card-box">
        <h3>3.4. Український голосовий синтез (Neural TTS)</h3>
        <p><b>Роль у системі:</b> Природне озвучення відповідей AI та системних сповіщень через Bluetooth-акустику.</p>
        <ul>
            <li><b>Microsoft Edge Neural TTS (Базовий):</b> Повністю безкоштовний високоякісний синтез (голоси <code>uk-UA-PolinaNeural</code> та <code>uk-UA-OstapNeural</code>). Не потребує жодних платних підписок чи API-ключів.</li>
            <li><b>ElevenLabs Flash v2.5 (Преміум):</b> Хмарний адаптер із рекордно низькою затримкою ~150 мс.</li>
            <li><b>HeyGen Voice Turbo REST:</b> Хмарний генератор 44.1 kHz WAV (безкоштовна квота до 30.11.2026).</li>
            <li><b>Web Speech API (Browser Fallback):</b> Якщо серверний синтез недоступний, браузер автоматично озвучує відповідь своїм голосом із позначкою у вебі.</li>
            <li><b>Нормалізація українського тексту (<code>server/tts/normalizer.py</code>):</b> Автоматично перетворює цифри на числівники у відповідних відмінках (1 поверх, 2 поверхи, 5 поверхів), правильно озвучує температуру («дванадцять градусів тепла»), зберігає апострофи (п'ять, об'єкт) та очищає текст від технічних емодзі перед відправкою до синтезатора.</li>
        </ul>
    </div>

    <div class="card-box">
        <h3>3.5. Доступні інструменти ШІ (Function Calling Tools — 16 інструментів)</h3>
        <p>Модуль <code>server/ai/tools.py</code> надає моделі суворо типізовані маніпулятори станом гаража:</p>
        <div class="table-wrap">
            <table>
                <tr>
                    <th>Назва інструменту</th>
                    <th>Опис дії</th>
                    <th>Цільовий модуль</th>
                </tr>
                <tr><td><code>control_device</code></td><td>Увімкнення/вимкнення світла чи вентиляції</td><td><code>server/devices/esp32.py</code></td></tr>
                <tr><td><code>play_song</code></td><td>Пошук та старт пісні на YouTube Music</td><td><code>server/services/ytmusic_service.py</code></td></tr>
                <tr><td><code>play_user_playlist</code></td><td>Запуск улюблених треків або плейлиста Юрія</td><td><code>server/services/ytmusic_service.py</code></td></tr>
                <tr><td><code>list_user_playlists</code></td><td>Перегляд доступних персональних списків</td><td><code>server/services/ytmusic_service.py</code></td></tr>
                <tr><td><code>next_music_track / prev_music_track</code></td><td>Перемикання треків у черзі</td><td><code>server/devices/bluetooth_speaker.py</code></td></tr>
                <tr><td><code>seek_music_track</code></td><td>Перемотування аудіо за таймкодом</td><td><code>server/devices/bluetooth_speaker.py</code></td></tr>
                <tr><td><code>speaker_control</code></td><td>Вибір активної колонки (JBL чи JX-BT) та гучності</td><td><code>server/devices/bluetooth_speaker.py</code></td></tr>
                <tr><td><code>play_radio / stop_radio</code></td><td>Керування стрімом українського онлайн-радіо</td><td><code>server/services/radio_service.py</code></td></tr>
                <tr><td><code>get_climate_history</code></td><td>Отримання числових показників за обраний період</td><td><code>server/storage/telemetry_db.py</code></td></tr>
                <tr><td><code>show_climate_chart</code></td><td>Рендеринг двовісного графіка мікроклімату</td><td><code>server/storage/chart_renderer.py</code></td></tr>
                <tr><td><code>run_scenario</code></td><td>Виконання комплексних макросів автоматизації</td><td><code>server/automation/engine.py</code></td></tr>
                <tr><td><code>play_media / stop_media</code></td><td>Керування локальними файлами та проектором</td><td><code>server/devices/projector.py</code></td></tr>
            </table>
        </div>
    </div>

    <!-- РОЗДІЛ 4 -->
    <div class="page-break"></div>
    <h2>4. Логіка роботи всієї системи: що за чим виконується</h2>
    <p>
        Робота SmartGarage організована у вигляді чітких, взаємопов'язаних контурів реального часу:
    </p>

    <h3>4.1. Послідовність старту системи (Boot Sequence)</h3>
    <ol>
        <li><b>Завантаження середовища:</b> Читання конфігураційного файлу <code>config/config.yaml</code> та накладання секретів із <code>.env</code> (токени, паролі, PIN).</li>
        <li><b>Ініціалізація сховища:</b> Підключення до бази даних SQLite <code>devices/telemetry.db</code> у високоефективному режимі WAL (Write-Ahead Logging).</li>
        <li><b>Створення контролерів пристроїв:</b> Ініціалізація екземплярів <code>ESP32Controller</code>, <code>BluetoothSensorManager</code>, <code>BluetoothSpeakerController</code>, <code>ProjectorController</code>, <code>PresenceManager</code>.</li>
        <li><b>Запуск фонових сервісів:</b>
            <ul>
                <li>Запуск воркера опитування Bluetooth BLE датчиків (фоновий потік Bleak).</li>
                <li>Запуск монітора присутності (BLE/Classic BT Presence Worker).</li>
                <li>Запуск воркера Telegram-бота з механізмом довгих опитувань (Long Polling).</li>
                <li>Запуск асинхронного споживача голосової черги <code>VoiceQueueWorker</code>.</li>
                <li>Старт вебсервера Flask на порту 8000/5000 та запуск сервісу <code>mqtt_bridge.py</code>.</li>
            </ul>
        </li>
    </ol>

    <h3>4.2. Цикл збору телеметрії та оновлення мікроклімату</h3>
    <ol>
        <li>Мікроконтролер <b>ESP32-S3</b> раз на 10 секунд формує JSON-пакет стану реле і відправляє його через HTTP POST на <code>/api/esp32/telemetry</code> та публікує в MQTT топік <code>smartgarage/esp32/telemetry</code>.</li>
        <li>Раз на 2 хвилини ESP32-S3 сканує радіоефір BLE, зчитує характеристики <code>ebe0ccc1...</code> (клімат) та <code>0x2a19</code> (батарея) з сенсорів 2-го поверху та підвалу, після чого передає їх на сервер.</li>
        <li>Паралельно серверний модуль <code>BluetoothSensorManager</code> виконує пряме зчитування через хост-адаптер Bleak.</li>
        <li>Сервер порівнює джерела даних, відсікає застарілі заміри, зберігає новий запис у таблицю <code>climate_history</code> бази <code>telemetry.db</code> та оновлює кеш у <code>devices/sensor_cache.json</code>.</li>
        <li>Оновлені показники негайно стають доступними вебпанелі, системі автоматизації та Telegram-боту.</li>
    </ol>

    <h3>4.3. Пайплайн виконання команд (Голос / Веб-чат / Telegram)</h3>
    <ol>
        <li><b>Вхід команди:</b> Голос із мікрофона гаража, повідомлення з вебінтерфейсу або команда від Юрія з Telegram.</li>
        <li><b>Автокорекція розкладки:</b> Якщо команду випадково введено англійськими літерами (наприклад, <code>cdsnkj dbrk</code>), функція <code>convert_qwerty_to_ua</code> автоматично перетворює її на коректну українську фразу <code>світло викл</code>.</li>
        <li><b>Швидка статична диспетчеризація:</b> Модуль <code>CommandProcessor</code> перевіряє команду на відповідність типовим патернам. Якщо збіг знайдено — дія виконується миттєво (за 0.05с) без витрачання токенів ШІ.</li>
        <li><b>Маршрутизація до AI Core:</b> Якщо команда складна або діалогова, вона потрапляє до <code>AIManager.chat()</code>:
            <ul>
                <li>Сервер збирає свіжий санітизований зріз стану гаража через <code>get_context_snapshot()</code>.</li>
                <li>Формується запит до OpenRouter із переліком 16 інструментів (GARAGE_TOOLS).</li>
                <li>Модель приймає рішення: відповісти текстом або викликати інструмент (наприклад, <code>play_song(query="Океан Ельзи")</code> чи <code>control_device(device="fan", action="on")</code>).</li>
                <li>Інструмент виконується на контролері, результат передається назад моделі, яка генерує лаконічну українську відповідь.</li>
            </ul>
        </li>
        <li><b>Озвучення та зворотний зв'язок:</b> Відповідь передається в <code>TTSManager</code>, нормалізується українською мовою, синтезується в аудіопотік через Edge Neural TTS та відтворюється на активній Bluetooth-колонці, а також виводиться в чат.</li>
    </ol>

    <h3>4.4. Життєвий цикл присутності (Arrival / Departure Lifecycle)</h3>
    <ol>
        <li><b>Прибуття власника (ARRIVED):</b>
            <ul>
                <li>Радар присутності фіксує смартфон Юрія (Motorola Edge 50 Pro) поруч із гаражем.</li>
                <li>Вмикається дебаунс (щоб не вітатися частіше ніж раз на 10 хвилин).</li>
                <li>ШІ генерує персоналізоване технологічне привітання з урахуванням температури підвалу та готовності систем.</li>
                <li>Привітання звучить через акустику і надсилається в Telegram. Сценарій «Прибуття» вмикає світло.</li>
            </ul>
        </li>
        <li><b>Від'їзд власника (DEPARTED):</b>
            <ul>
                <li>Пристрій зникає з зони дії понад 90 секунд.</li>
                <li>Система перевіряє стан реле: якщо світло або вентиляцію залишено увімкненими — надсилається термінове попередження Юрію в Telegram з кнопками швидкого вимкнення.</li>
            </ul>
        </li>
    </ol>

    <!-- РОЗДІЛ 5 -->
    <div class="page-break"></div>
    <h2>5. Детальний прохід по Вебпанелі: що відображається, звідки береться і які файли відповідають</h2>
    <p>
        Вебінтерфейс SmartGarage складається з двох основних частин: сенсорного Touch-Дашборду 1-го поверху (<code>/dashboard</code>) та інженерної Консолі AI (<code>/</code>). Нижче наведено детальний огляд кожного окремого блоку:
    </p>

    <div class="card-box">
        <h3>5.1. Верхній рядок стану (Top Bar)</h3>
        <div class="table-wrap">
            <table>
                <tr>
                    <th style="width: 25%;">Елемент інтерфейсу</th>
                    <th style="width: 25%;">Що відображає</th>
                    <th style="width: 25%;">Звідки береться (Ендпоінт / Джерело)</th>
                    <th style="width: 25%;">Відповідальні файли та модулі</th>
                </tr>
                <tr>
                    <td><b>Логотип та Годинник</b></td>
                    <td>Час у реальному часі (HH:MM:SS) та назва хабу.</td>
                    <td>Локальний таймер JavaScript (оновлення щосекунди).</td>
                    <td><code>server/templates/dashboard.html</code><br><code>server/static/js/dashboard.js</code></td>
                </tr>
                <tr>
                    <td><b>Бейдж ESP32 (Індикатор зв'язку)</b></td>
                    <td>Статус контролера: «Онлайн (12ms)» або «Офлайн». Клік відкриває діагностичне вікно.</td>
                    <td><code>GET /api/esp32/status</code><br>Перевірка стану пінг/HTTP мікроконтролера.</td>
                    <td><code>server/webapp.py</code> (функція <code>esp32_status</code>)<br><code>server/devices/esp32.py</code></td>
                </tr>
                <tr>
                    <td><b>Кнопка «Ворота блоковано»</b></td>
                    <td>Червоний щит із попередженням: «Електропривід не встановлено».</td>
                    <td>Статична політика безпеки бекенду. Будь-який запит повертає помилку блокування.</td>
                    <td><code>server/templates/dashboard.html</code><br><code>server/webapp.py</code> (маршрут <code>/api/device/door/toggle</code>)</td>
                </tr>
                <tr>
                    <td><b>Кнопка замка (Адмін-авторизація)</b></td>
                    <td>Іконка замка 🔒/🔓. Відкриває модальне вікно вводу PIN-коду адміністратора.</td>
                    <td><code>POST /api/admin/verify</code><br>Видає підписаний токен сесії.</td>
                    <td><code>server/security/auth.py</code><br><code>server/webapp.py</code></td>
                </tr>
            </table>
        </div>
    </div>

    <div class="card-box">
        <h3>5.2. Картка «💡 Освітлення та Керування»</h3>
        <div class="table-wrap">
            <table>
                <tr>
                    <th style="width: 25%;">Елемент інтерфейсу</th>
                    <th style="width: 25%;">Що відображає</th>
                    <th style="width: 25%;">Звідки береться (Ендпоінт / Джерело)</th>
                    <th style="width: 25%;">Відповідальні файли та модулі</th>
                </tr>
                <tr>
                    <td><b>Кнопка «Головне світло»</b></td>
                    <td>Стан освітлення (Увімк/Вимк), колір підсвічування та перемикач.</td>
                    <td><code>POST /api/device/light/toggle</code><br>Стан зчитується з <code>/api/garage/state</code>.</td>
                    <td><code>server/webapp.py</code><br><code>server/devices/esp32.py</code> (GPIO 5)</td>
                </tr>
                <tr>
                    <td><b>Кнопка «Витяжна вентиляція»</b></td>
                    <td>Стан витяжного вентилятора (Працює/Зупинено).</td>
                    <td><code>POST /api/device/fan/toggle</code><br>Стан зчитується з <code>/api/garage/state</code>.</td>
                    <td><code>server/webapp.py</code><br><code>server/devices/esp32.py</code> (GPIO 6)</td>
                </tr>
                <tr>
                    <td><b>Кнопка воріт</b></td>
                    <td>Сіра неактивна плашка «Привід не змонтовано».</td>
                    <td>Апаратна конфігурація.</td>
                    <td><code>server/templates/dashboard.html</code></td>
                </tr>
                <tr>
                    <td><b>Швидкі сценарії</b></td>
                    <td>4 кнопки: «Прибуття», «Від'їзд», «Ніч», «Провітрювання».</td>
                    <td><code>POST /api/scenarios/&lt;name&gt;</code><br>Автоматизоване виконання ланцюжків команд.</td>
                    <td><code>server/automation/engine.py</code><br><code>server/webapp.py</code></td>
                </tr>
            </table>
        </div>
    </div>

    <div class="card-box">
        <h3>5.3. Картка «📊 Мікроклімат і Датчики»</h3>
        <div class="table-wrap">
            <table>
                <tr>
                    <th style="width: 25%;">Елемент інтерфейсу</th>
                    <th style="width: 25%;">Що відображає</th>
                    <th style="width: 25%;">Звідки береться (Ендпоінт / Джерело)</th>
                    <th style="width: 25%;">Відповідальні файли та модулі</th>
                </tr>
                <tr>
                    <td><b>Картка «1-й поверх (Гараж)»</b></td>
                    <td>Позначка «Не змонтовано», статус «Очікує монтажу сенсора». Жодних фіктивних чисел!</td>
                    <td><code>GET /api/sensors/floors</code> (об'єкт <code>floor1</code> з параметром <code>installed: false</code>).</td>
                    <td><code>server/sensors/freshness.py</code><br><code>server/webapp.py</code></td>
                </tr>
                <tr>
                    <td><b>Картка «2-й поверх»</b></td>
                    <td>Поточна температура (°C), вологість (%), батарейка, бейдж давності («Свіжі» / «Застарілі»).</td>
                    <td><code>GET /api/sensors/floors</code> (сенсор <code>A4:C1:38:EC:EC:6C</code>).</td>
                    <td><code>server/devices/bluetooth_sensor.py</code><br><code>server/sensors/freshness.py</code></td>
                </tr>
                <tr>
                    <td><b>Картка «Підвал (Сховище)»</b></td>
                    <td>Поточна температура (°C), вологість (%), батарейка, бейдж давності.</td>
                    <td><code>GET /api/sensors/floors</code> (сенсор <code>A4:C1:38:CC:CA:49</code>).</td>
                    <td><code>server/devices/bluetooth_sensor.py</code><br><code>server/storage/telemetry_db.py</code></td>
                </tr>
                <tr>
                    <td><b>Модальне вікно графіка (клік по картці)</b></td>
                    <td>Інтерактивний графік Chart.js з вибором діапазону (24 год / 48 год / 7 днів) та розрахунком мін/макс/середнього.</td>
                    <td><code>GET /api/telemetry/history?floor=...&hours=...</code></td>
                    <td><code>server/storage/telemetry_db.py</code><br><code>server/static/js/chart.min.js</code><br><code>server/static/js/dashboard.js</code></td>
                </tr>
            </table>
        </div>
    </div>

    <div class="card-box">
        <h3>5.4. Картка «🎙️ Голосовий помічник AI»</h3>
        <div class="table-wrap">
            <table>
                <tr>
                    <th style="width: 25%;">Елемент інтерфейсу</th>
                    <th style="width: 25%;">Що відображає</th>
                    <th style="width: 25%;">Звідки береться (Ендпоінт / Джерело)</th>
                    <th style="width: 25%;">Відповідальні файли та модулі</th>
                </tr>
                <tr>
                    <td><b>Кнопка мікрофона</b></td>
                    <td>Анімація прослуховування голосу в браузері.</td>
                    <td>Браузерний Web Speech API або надсилання аудіо на <code>POST /api/voice/command</code>.</td>
                    <td><code>server/static/js/dashboard.js</code><br><code>server/services/voice_listener.py</code></td>
                </tr>
                <tr>
                    <td><b>Поле вводу та кнопка «Надіслати»</b></td>
                    <td>Рядок для текстового запиту та історія відповідей асистента.</td>
                    <td><code>POST /command</code><br>Передає запит у ядро SmartGarage.</td>
                    <td><code>server/router/router.py</code><br><code>server/ai/manager.py</code></td>
                </tr>
                <tr>
                    <td><b>Кнопка налаштування «⚙️ TTS»</b></td>
                    <td>Відображає активного провайдера та голос (наприклад: <code>Edge: Поліна</code>).</td>
                    <td><code>GET /api/voice/providers</code> та <code>GET /api/voice/config</code>.</td>
                    <td><code>server/tts/manager.py</code><br><code>server/webapp.py</code></td>
                </tr>
                <tr>
                    <td><b>Модальне вікно конфігурації TTS</b></td>
                    <td>Вибір Edge / ElevenLabs / HeyGen, вибір голосу, кнопка тестового прослуховування («▶ Прослухати»).</td>
                    <td><code>POST /api/voice/preview</code> та <code>POST /api/voice/config</code>.</td>
                    <td><code>server/tts/edge_provider.py</code><br><code>server/tts/elevenlabs_provider.py</code><br><code>server/tts/heygen_provider.py</code></td>
                </tr>
            </table>
        </div>
    </div>

    <div class="card-box">
        <h3>5.5. Картка «🎬 Медіацентр & Проектор HY350MAX»</h3>
        <div class="table-wrap">
            <table>
                <tr>
                    <th style="width: 25%;">Елемент інтерфейсу</th>
                    <th style="width: 25%;">Що відображає</th>
                    <th style="width: 25%;">Звідки береться (Ендпоінт / Джерело)</th>
                    <th style="width: 25%;">Відповідальні файли та модулі</th>
                </tr>
                <tr>
                    <td><b>Бейдж статусу проектора</b></td>
                    <td>«Онлайн» або «Вимкнено» (перевірка IP <code>192.0.2.30</code>).</td>
                    <td><code>GET /api/projector/status</code></td>
                    <td><code>server/devices/projector.py</code></td>
                </tr>
                <tr>
                    <td><b>Кнопка «Трансляція екрану»</b></td>
                    <td>Запуск віддзеркалення робочого столу на великий екран проектора.</td>
                    <td><code>POST /api/projector/mirror</code> (протокол AirPlay, порт 57000).</td>
                    <td><code>server/devices/projector.py</code></td>
                </tr>
                <tr>
                    <td><b>Кнопка живлення проектора</b></td>
                    <td>Дистанційне вимкнення пристрою.</td>
                    <td>REST API проектора на порт 8899.</td>
                    <td><code>server/devices/projector.py</code></td>
                </tr>
            </table>
        </div>
    </div>

    <div class="card-box">
        <h3>5.6. Картка «🔊 Bluetooth Колонка & Музичний хаб»</h3>
        <div class="table-wrap">
            <table>
                <tr>
                    <th style="width: 25%;">Елемент інтерфейсу</th>
                    <th style="width: 25%;">Що відображає</th>
                    <th style="width: 25%;">Звідки береться (Ендпоінт / Джерело)</th>
                    <th style="width: 25%;">Відповідальні файли та модулі</th>
                </tr>
                <tr>
                    <td><b>Селектор акустики</b></td>
                    <td>Вибір між «JX-BT (1-й поверх)» та «JBL Clip 5 (Гараж)».</td>
                    <td><code>POST /api/speaker/switch</code> (перемикання PipeWire audio sink).</td>
                    <td><code>server/devices/bluetooth_speaker.py</code></td>
                </tr>
                <tr>
                    <td><b>Повзунок гучності</b></td>
                    <td>Рівень гучності у відсотках (0-100%).</td>
                    <td><code>POST /api/speaker/volume</code></td>
                    <td><code>server/devices/bluetooth_speaker.py</code></td>
                </tr>
                <tr>
                    <td><b>Плеєр YouTube Music</b></td>
                    <td>Назва поточного треку, виконавець, статус Play/Pause, кнопки перемотування, прогрес-бар.</td>
                    <td><code>GET /api/ytmusic/status</code>, виклики <code>/api/ytmusic/play</code>, <code>/next</code>, <code>/prev</code>.</td>
                    <td><code>server/services/ytmusic_service.py</code><br><code>server/devices/bluetooth_speaker.py</code></td>
                </tr>
                <tr>
                    <td><b>Селектор онлайн-радіо</b></td>
                    <td>Список станцій (Хіт FM, Radio ROKS, Kiss FM, Lounge FM, Байрактар).</td>
                    <td><code>GET /api/radio/stations</code> та запуск через <code>POST /api/radio/play</code>.</td>
                    <td><code>server/services/radio_service.py</code></td>
                </tr>
                <tr>
                    <td><b>Персональні плейлисти</b></td>
                    <td>Випадаючий список списків відтворення Юрія з YouTube Music.</td>
                    <td><code>GET /api/ytmusic/playlists</code> (збережено в <code>devices/ytmusic_playlists.json</code>).</td>
                    <td><code>server/services/ytmusic_service.py</code></td>
                </tr>
            </table>
        </div>
    </div>

    <div class="card-box">
        <h3>5.7. Картка «💻 Сервер ThinkPad 24/7» (Системний моніторинг)</h3>
        <div class="table-wrap">
            <table>
                <tr>
                    <th style="width: 25%;">Елемент інтерфейсу</th>
                    <th style="width: 25%;">Що відображає</th>
                    <th style="width: 25%;">Звідки береться (Ендпоінт / Джерело)</th>
                    <th style="width: 25%;">Відповідальні файли та модулі</th>
                </tr>
                <tr>
                    <td><b>Навантаження CPU</b></td>
                    <td>Завантаженість процесора ThinkPad у відсотках.</td>
                    <td><code>GET /api/system/stats</code> (модуль <code>psutil.cpu_percent</code>).</td>
                    <td><code>server/webapp.py</code> (функція <code>get_system_stats</code>)</td>
                </tr>
                <tr>
                    <td><b>Температура CPU</b></td>
                    <td>Температура ядер процесора в °C.</td>
                    <td><code>GET /api/system/stats</code> (зчитування <code>/sys/class/thermal</code>).</td>
                    <td><code>server/webapp.py</code></td>
                </tr>
                <tr>
                    <td><b>Пам'ять RAM</b></td>
                    <td>Відсоток зайнятої оперативної пам'яті.</td>
                    <td><code>GET /api/system/stats</code> (модуль <code>psutil.virtual_memory</code>).</td>
                    <td><code>server/webapp.py</code></td>
                </tr>
                <tr>
                    <td><b>Батарея ThinkPad</b></td>
                    <td>Рівень заряду вбудованого акумулятора ноутбука.</td>
                    <td><code>GET /api/system/stats</code> (модуль <code>psutil.sensors_battery</code>).</td>
                    <td><code>server/webapp.py</code></td>
                </tr>
                <tr>
                    <td><b>Час роботи (Uptime)</b></td>
                    <td>Тривалість безперервної роботи сервера з моменту запуску.</td>
                    <td><code>GET /api/system/stats</code> (розрахунок від <code>psutil.boot_time</code>).</td>
                    <td><code>server/webapp.py</code></td>
                </tr>
                <tr>
                    <td><b>Мережеві IP-адреси</b></td>
                    <td>Локальний IP (<code>192.0.2.10</code>) та безпечний Mesh IP Tailscale.</td>
                    <td><code>GET /api/system/stats</code> (системні інтерфейси <code>wlan0</code> / <code>tailscale0</code>).</td>
                    <td><code>server/webapp.py</code></td>
                </tr>
            </table>
        </div>
    </div>

    <!-- РОЗДІЛ 6 -->
    <div class="page-break"></div>
    <h2>6. Безпека, відмовостійкість та політика захисту даних</h2>
    <p>
        Комплекс SmartGarage побудовано на основі ешелонованої оборони (Defense in Depth):
    </p>
    <ul>
        <li><b>Апаратне блокування приводу воріт (Gate Safety Protection):</b> Навіть якщо користувач у чаті просить «відкрий ворота», модель та бекенд миттєво відхиляють дію з повідомленням про фізичну відсутність приводу. Жодні спроби переконати чи обдурити ШІ не здатні обійти цю заборону.</li>
        <li><b>Захист від підбору PIN-коду (Sliding-window Rate Limiter):</b> Дозволено не більше 5 невдалих спроб введення PIN за 5 хвилин. При перевищенні ліміту IP-адреса блокується із затримкою (модуль <code>server/security/auth.py</code>).</li>
        <li><b>Централізований аудит безпеки (<code>logs/audit.log</code>):</b> Усі чутливі події (входи, зміна стану реле, команди адміністратора) записуються в журнал із маскуванням паролів, токенів та PIN-кодів (функція <code>sanitize_data</code>).</li>
        <li><b>Повна ізоляція від довільного виконання коду:</b> Інструмент OpenInterpreter повністю вимкнено за замовчуванням (<code>ENABLE_OPEN_INTERPRETER=false</code>), щоб запобігти будь-якому несанкціонованому виконанню системних команд.</li>
        <li><b>Захист від фінансових перевитрат на ШІ:</b> Добовий ліміт OpenRouter ($1.00/добу) гарантує, що неконтрольований потік запитів або циклічні збої не призведуть до фінансових втрат.</li>
        <li><b>Категоричне табу на російську мову та контент:</b> Система блокує будь-які запити на пошук чи відтворення російськомовних пісень або радіостанцій (фільтри в <code>ytmusic_service.py</code> та системні промти). Усі комунікації, логи та сповіщення ведуться виключно солов'їною українською мовою.</li>
    </ul>

    <!-- РОЗДІЛ 7 -->
    <h2>7. Зведена таблиця файлової структури та модулів</h2>
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th style="width: 30%;">Шлях до файлу / директорії</th>
                    <th style="width: 35%;">Основний клас / сервіс</th>
                    <th style="width: 35%;">Функціональне призначення</th>
                </tr>
            </thead>
            <tbody>
                <tr><td><code>server/main.py</code></td><td>Консольний запуск</td><td>Точка входу запуску CLI інтерфейсу</td></tr>
                <tr><td><code>server/webapp.py</code></td><td>Flask WebApp</td><td>Головний вебсервер, обробка всіх 45+ API роутів</td></tr>
                <tr><td><code>server/core/core.py</code></td><td><code>SmartGarage</code></td><td>Головний оркестратор життєвого циклу гаража</td></tr>
                <tr><td><code>server/config.py</code></td><td><code>config</code></td><td>Завантаження конфігурацій та перекриття з .env</td></tr>
                <tr><td><code>server/ai/openrouter_client.py</code></td><td><code>OpenRouterClient</code></td><td>Зв'язок із моделлю Gemini, санітизація, облік витрат</td></tr>
                <tr><td><code>server/ai/manager.py</code></td><td><code>AIManager</code></td><td>Контекст розмов, управління сесіями та запитами</td></tr>
                <tr><td><code>server/ai/tools.py</code></td><td><code>GARAGE_TOOLS</code></td><td>16 декларацій функцій для виклику нейромережею</td></tr>
                <tr><td><code>server/tts/manager.py</code></td><td><code>TTSManager</code></td><td>Маршрутизація голосу (Edge, ElevenLabs, HeyGen)</td></tr>
                <tr><td><code>server/tts/normalizer.py</code></td><td><code>UkrainianTextNormalizer</code></td><td>Відмінювання чисел, одиниць, збереження апострофів</td></tr>
                <tr><td><code>server/devices/esp32.py</code></td><td><code>ESP32Controller</code></td><td>Управління реле світла, вентиляції через HTTP/Serial</td></tr>
                <tr><td><code>server/devices/bluetooth_sensor.py</code></td><td><code>BluetoothSensorManager</code></td><td>Пряме зчитування датчиків через Bleak</td></tr>
                <tr><td><code>server/devices/bluetooth_speaker.py</code></td><td><code>BluetoothSpeakerController</code></td><td>Керування PipeWire, гучність, черга треків</td></tr>
                <tr><td><code>server/devices/presence.py</code></td><td><code>PresenceManager</code></td><td>5-рівневий радар присутності Юрія та гостей</td></tr>
                <tr><td><code>server/devices/projector.py</code></td><td><code>ProjectorController</code></td><td>AirPlay дзеркалювання, живлення проектора HY350MAX</td></tr>
                <tr><td><code>server/services/telegram_bot.py</code></td><td><code>TelegramBot</code></td><td>Воркер бота @SmartGarageYurkoBot, інлайн-кнопки, пуші</td></tr>
                <tr><td><code>server/services/voice_listener.py</code></td><td><code>VoiceListener</code></td><td>Слухач «hey_jarvis» через OpenWakeWord + Whisper</td></tr>
                <tr><td><code>server/services/ytmusic_service.py</code></td><td><code>YTMusicService</code></td><td>Інтеграція плейлистів та треків YouTube Music</td></tr>
                <tr><td><code>server/services/radio_service.py</code></td><td><code>RadioService</code></td><td>Потокове мовлення українських радіостанцій</td></tr>
                <tr><td><code>server/services/mqtt_bridge.py</code></td><td><code>MQTTBridge</code></td><td>Міст між ESP32, сервером та Home Assistant</td></tr>
                <tr><td><code>server/storage/telemetry_db.py</code></td><td><code>TelemetryDB</code></td><td>База даних SQLite для збереження клімату поверхів</td></tr>
                <tr><td><code>server/storage/chart_renderer.py</code></td><td><code>generate_climate_chart</code></td><td>Рендеринг зображень графіків для Telegram чату</td></tr>
                <tr><td><code>server/templates/dashboard.html</code></td><td>HTML5 / CSS3</td><td>Touch-інтерфейс швидкого керування 1-го поверху</td></tr>
                <tr><td><code>server/templates/index.html</code></td><td>HTML5 / CSS3</td><td>Повна інженерна консоль AI та вкладка адмінки</td></tr>
                <tr><td><code>esp32/src/main.cpp</code></td><td>PlatformIO C++</td><td>Прошивка мікроконтролера ESP32-S3</td></tr>
            </tbody>
        </table>
    </div>

    <div style="margin-top: 30px; text-align: center; color: #64748b; font-size: 8.5pt; border-top: 1px solid #e2e8f0; padding-top: 10px;">
        Smart Garage Autonomous Infrastructure • Розроблено для Юрія Савчука • 2026 • Слава Україні! 🇺🇦
    </div>

</body>
</html>
"""

def compile_pdf() -> bool:
    print(f"[1/4] Створення директорій...")
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"[2/4] Генерація структурованого HTML-документа: {HTML_PATH}")
    html_content = generate_html_content()
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"[3/4] Компіляція HTML у PDF через LibreOffice...")
    cmd = [
        "libreoffice",
        "--headless",
        "--convert-to", "pdf",
        str(HTML_PATH),
        "--outdir", str(PDF_PATH.parent)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Помилка компіляції PDF: {res.stderr}")
        return False
    
    # Також копіюємо в корінь як instruction.pdf
    if PDF_PATH.exists():
        import shutil
        shutil.copyfile(PDF_PATH, ROOT_PDF_PATH)
        print(f"PDF успішно створено: {PDF_PATH} ({PDF_PATH.stat().st_size} байт)")
        print(f"Також скопійовано в: {ROOT_PDF_PATH}")
        return True
    else:
        print("Помилка: файл PDF не знайдено після компіляції.")
        return False

def send_to_telegram() -> bool:
    print(f"[4/4] Відправка PDF інструкції в Telegram...")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
    
    if not token or not admin_chat_id:
        print("Повідомлення: TELEGRAM_BOT_TOKEN або TELEGRAM_ADMIN_CHAT_ID не задано. Відправка пропущена.")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    caption = (
        "📘 *Повна технічна інструкція SmartGarage*\n\n"
        "У документі детально описано:\n"
        "• Встановлені датчики, актуатори та їхні ролі;\n"
        "• Моделі ШІ (Gemini 2.5 Flash, Ollama, Whisper, Edge TTS);\n"
        "• Повна логіка та пайплайни системи реального часу;\n"
        "• Детальний розбір усіх блоків вебінтерфейсу;\n"
        "• Політика безпеки, аудит та файлова структура.\n\n"
        "Файл скомпільовано у високій якості (PDF)."
    )
    
    with open(ROOT_PDF_PATH, "rb") as f:
        files = {
            "document": ("SmartGarage_System_Instruction.pdf", f, "application/pdf")
        }
        data = {
            "chat_id": admin_chat_id,
            "caption": caption,
            "parse_mode": "Markdown"
        }
        r = requests.post(url, data=data, files=files, timeout=40)
        
    if r.status_code == 200 and r.json().get("ok"):
        print(f"✅ Документ успішно доставлено в Telegram користувачу (Chat ID: {admin_chat_id})!")
        return True
    else:
        print(f"❌ Помилка Telegram API: {r.status_code} - {r.text}")
        return False

if __name__ == "__main__":
    success = compile_pdf()
    if success:
        send_to_telegram()
    else:
        sys.exit(1)
