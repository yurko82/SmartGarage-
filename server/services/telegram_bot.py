import base64
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram Bot for remote SmartGarage monitoring, notifications, and control."""

    def __init__(self, garage, config_path: str | None = None):
        self.garage = garage
        self.config_path = Path(config_path) if config_path else Path(__file__).resolve().parent.parent.parent / "config" / "config.yaml"
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_update_id = 0
        self._load_config()

    def _load_config(self):
        from server.config import config
        tg_cfg = config.get("telegram", {}) if isinstance(config, dict) else {}
        self.enabled = tg_cfg.get("enabled", True)
        self.token = tg_cfg.get("bot_token", "").strip()
        self.admin_chat_id = tg_cfg.get("admin_chat_id")
        self.admin_pin = str(tg_cfg.get("admin_pin", "7777")).strip()
        self.notify_presence = tg_cfg.get("notify_presence", True)
        self.notify_door = tg_cfg.get("notify_door", True)
        self.api_base = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    def _save_admin_chat_id(self, chat_id: int):
        self.admin_chat_id = chat_id
        try:
            import yaml
            if self.config_path.exists():
                with open(self.config_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if "telegram" not in data:
                    data["telegram"] = {}
                data["telegram"]["admin_chat_id"] = chat_id
                with open(self.config_path, "w", encoding="utf-8") as f:
                    yaml.dump(data, f, allow_unicode=True, sort_keys=False)
                logger.info(f"Saved Telegram admin_chat_id {chat_id} to config.")
        except Exception as e:
            logger.error(f"Failed to save admin_chat_id to config: {e}")

    def start(self):
        self._load_config()
        if not self.enabled:
            logger.info("Telegram Bot is disabled in config.")
            return

        if not self.token:
            logger.warning("Telegram Bot token is empty. Bot worker will wait for token in config/config.yaml.")
            return

        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="TelegramBotWorker")
            self._thread.start()
            logger.info("Telegram Bot worker started.")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Telegram Bot worker stopped.")

    def _worker_loop(self):
        logger.info("Telegram polling worker initialized.")
        while self._running:
            try:
                if not self.token:
                    time.sleep(10)
                    self._load_config()
                    continue

                updates = self._get_updates(offset=self._last_update_id + 1, timeout=20)
                if updates and isinstance(updates, list):
                    for u in updates:
                        up_id = u.get("update_id")
                        if up_id:
                            self._last_update_id = max(self._last_update_id, up_id)
                        self._process_update(u)
            except Exception as e:
                logger.debug(f"Telegram polling exception: {e}")
                time.sleep(3)

    def _get_updates(self, offset: int = 0, timeout: int = 20) -> list:
        try:
            url = f"{self.api_base}/getUpdates"
            params = {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]}
            r = requests.get(url, params=params, timeout=timeout + 5)
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    return data.get("result", [])
        except Exception:
            pass
        return []

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
        if not self.token:
            return False
        try:
            url = f"{self.api_base}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            r = requests.post(url, json=payload, timeout=6)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False

    def edit_message(self, chat_id: int, message_id: int, text: str, reply_markup: dict | None = None) -> bool:
        if not self.token:
            return False
        try:
            url = f"{self.api_base}/editMessageText"
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "Markdown",
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            r = requests.post(url, json=payload, timeout=6)
            if r.status_code == 200:
                return True
            return self.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as e:
            logger.debug(f"Error editing Telegram message: {e}")
            return self.send_message(chat_id, text, reply_markup=reply_markup)

    def edit_photo_message(self, chat_id: int, message_id: int, photo_bytes: bytes, caption: str | None = None, reply_markup: dict | None = None) -> bool:
        """Edit an existing photo message in-place using editMessageMedia."""
        if not self.token:
            return False
        try:
            url = f"{self.api_base}/editMessageMedia"
            media_obj = {
                "type": "photo",
                "media": "attach://photo_file",
            }
            if caption:
                media_obj["caption"] = caption
                media_obj["parse_mode"] = "Markdown"

            data = {
                "chat_id": chat_id,
                "message_id": message_id,
                "media": json.dumps(media_obj)
            }
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)

            files = {"photo_file": ("chart.png", photo_bytes, "image/png")}
            r = requests.post(url, data=data, files=files, timeout=12)
            if r.status_code == 200:
                return True
            logger.debug(f"editMessageMedia returned {r.status_code}: {r.text}")
            return self.send_photo(chat_id, photo_bytes, caption=caption, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error editing photo message: {e}")
            return self.send_photo(chat_id, photo_bytes, caption=caption, reply_markup=reply_markup)

    def send_photo(self, chat_id: int, photo_bytes: bytes, caption: str | None = None, reply_markup: dict | None = None) -> bool:
        if not self.token:
            return False
        try:
            url = f"{self.api_base}/sendPhoto"
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
                data["parse_mode"] = "Markdown"
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            files = {
                "photo": ("climate_chart.png", photo_bytes, "image/png")
            }
            r = requests.post(url, data=data, files=files, timeout=12)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Error sending Telegram photo: {e}")
            return False

    def send_climate_chart(self, chat_id: int, floor: str = "basement", hours: float = 24.0, message_id: int | None = None) -> bool:
        """Render and send a dual-axis climate history chart with interactive range buttons."""
        try:
            from server.storage.chart_renderer import generate_climate_chart
            if not hasattr(self.garage, "telemetry_db") or not self.garage.telemetry_db:
                self.send_message(chat_id, "⚠️ База даних телеметрії недоступна для побудови графіка.")
                return False

            hours_int = int(hours) if hours in (24, 48, 168) else int(hours)
            query_floor = floor
            floor_titles = {
                "basement": "Підвал",
                "floor2": "2-й поверх",
                "floor1": "1-й поверх (Гараж)"
            }

            res = self.garage.telemetry_db.get_history(floor=query_floor, hours=hours, limit=100)
            points = res.get("points", [])
            stats = res.get("stats", {})

            fallback = False
            if (not points or floor == "floor1") and floor != "basement":
                res_b = self.garage.telemetry_db.get_history(floor="basement", hours=hours, limit=100)
                if res_b.get("points"):
                    points = res_b.get("points", [])
                    stats = res_b.get("stats", {})
                    query_floor = "basement"
                    fallback = True

            floor_title = floor_titles.get(query_floor, query_floor)
            img_bytes = generate_climate_chart(points, stats, floor_title=floor_title, hours=hours)
            if not img_bytes:
                self.send_message(chat_id, f"⚠️ Немає збережених кліматичних даних для приміщення '{floor}' за обраний період.")
                return False

            cur_t = stats.get("current_temp", "--")
            min_t = stats.get("min_temp", "--")
            max_t = stats.get("max_temp", "--")
            cur_h = stats.get("current_hum", "--")

            caption = (
                f"📈 *Графік клімату: {floor_title}*\n"
                f"⏱️ Період: *{hours_int} год*\n"
                f"🌡️ Зараз: `{cur_t}°C` (мін: `{min_t}°C`, макс: `{max_t}°C`)\n"
                f"💧 Вологість: `{cur_h}%`"
            )
            if fallback:
                caption += "\n\nℹ️ _Датчик у гаражі (1-й поверх) ще очікує підключення, тому відображено активний датчик підвалу._"

            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": f"{'🔘 ' if hours_int==24 else ''}24 год", "callback_data": f"chart_{query_floor}_24"},
                        {"text": f"{'🔘 ' if hours_int==48 else ''}48 год", "callback_data": f"chart_{query_floor}_48"},
                        {"text": f"{'🔘 ' if hours_int==168 else ''}7 днів", "callback_data": f"chart_{query_floor}_168"}
                    ],
                    [
                        {"text": f"{'🔘 ' if query_floor=='basement' else ''}⚓ Підвал", "callback_data": f"chart_basement_{hours_int}"},
                        {"text": f"{'🔘 ' if query_floor=='floor2' else ''}🏢 2-й поверх", "callback_data": f"chart_floor2_{hours_int}"}
                    ],
                    [
                        {"text": "🔙 До меню температури", "callback_data": "clim_menu"}
                    ]
                ]
            }

            if message_id:
                return self.edit_photo_message(chat_id, message_id, img_bytes, caption=caption, reply_markup=reply_markup)
            return self.send_photo(chat_id, img_bytes, caption=caption, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error in send_climate_chart: {e}")
            self.send_message(chat_id, f"⚠️ Помилка побудови графіка: {e}")
            return False

    def notify_admin(self, text: str):
        """Send proactive notification to admin if registered."""
        if self.admin_chat_id:
            self.send_message(self.admin_chat_id, text)

    def _get_main_keyboard(self) -> dict:
        return {
            "keyboard": [
                [{"text": "📊 Статус гаража"}, {"text": "🌡️ Температура"}],
                [{"text": "💡 Світло"}, {"text": "💨 Вентиляція"}],
                [{"text": "👥 Присутність"}, {"text": "📌 Розпіновка"}]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": False
        }

    def _process_update(self, update: dict):
        # 1. Handle Callback Queries (Inline buttons)
        cb = update.get("callback_query")
        if cb:
            self._handle_callback_query(cb)
            return

        # 2. Handle Messages
        msg = update.get("message")
        if not msg:
            return

        chat_id = msg.get("chat", {}).get("id")
        user = msg.get("from", {})
        text = (msg.get("text") or "").strip()
        voice = msg.get("voice")
        logger.info(f"Telegram message from {user.get('username') or user.get('first_name')} (chat_id={chat_id}): '{text}'")

        # Automatically save admin_chat_id if not set yet
        if not self.admin_chat_id and chat_id:
            self._save_admin_chat_id(chat_id)

        # Public info commands (pinout is always accessible)
        low = text.lower()
        if low in ("/pinout", "розпіновка", "піни", "підключення", "схема", "📌 розпіновка", "скинь розпіновку"):
            self._send_pinout(chat_id)
            return

        if low in ("/rf", "/sniffer", "сніфер", "радіокод", "код", "📡 радіокод"):
            self._send_rf_sniffer(chat_id)
            return

        # Authorization check
        is_admin = (self.admin_chat_id is not None and str(chat_id) == str(self.admin_chat_id))

        # Check PIN authorization
        if not is_admin:
            clean_text = text.replace("/start", "").strip()
            if clean_text == self.admin_pin:
                self._save_admin_chat_id(chat_id)
                welcome = (
                    f"🎉 *Вітаю, {user.get('first_name', 'Власнику')}!*\n\n"
                    f"✅ Ви успішно авторизувалися як головний адміністратор **Smart Garage**.\n"
                    f"Тепер ви можете повністю керувати системою, отримувати сповіщення та ставити будь-які запитання."
                )
                self.send_message(chat_id, welcome, reply_markup=self._get_main_keyboard())
                self._send_pinout(chat_id)
                return
            else:
                self.send_message(
                    chat_id,
                    "🔒 *Smart Garage Bot*\n\nВведіть PIN-код адміністратора (наприклад: `7777`), щоб отримати доступ до керування гаражем.\n\n📌 Щоб переглянути схему підключення плати, натисніть /pinout."
                )
                return

        # Authorized Admin Processing:
        # Handle Voice message
        if voice:
            self._handle_voice_message(chat_id, voice)
            return

        # Handle Text commands
        if not text:
            return

        low = text.lower()
        if low in ("/start", "/help"):
            help_text = (
                "🤖 *Smart Garage AI — Пульт керування*\n\n"
                "Оберіть кнопку в меню або надішліть будь-яке запитання/голосове повідомлення:\n\n"
                "• 📊 *Статус гаража* — поточний огляд системи\n"
                "• 🌡️ *Температура* — підменю (1-й поверх, 2-й поверх, підвал, вулиця, графік)\n"
                "• 👥 *Присутність* — хто зараз біля гаража\n"
                "• 💡 *Світло* — вмикання/вимикання світла\n"
                "• 💨 *Вентиляція* — витяжка"
            )
            self.send_message(chat_id, help_text, reply_markup=self._get_main_keyboard())

        elif low in ("📊 статус гаража", "/status", "статус"):
            self._send_status(chat_id)

        elif low in ("🌡️ температура", "🌡️ клімат", "/temp", "/climate", "клімат", "температура"):
            self._send_climate_menu(chat_id)

        elif low in ("1 поверх", "1-й поверх", "перший поверх", "гараж"):
            self._send_floor1_details(chat_id)

        elif low in ("2 поверх", "2-й поверх", "другий поверх"):
            self._send_floor2_details(chat_id)

        elif low in ("підвал", "підвал температура"):
            self._send_basement_details(chat_id)

        elif low in ("вулиця", "вулична температура", "погода"):
            self._send_outdoor_details(chat_id)

        elif low in ("📈 графік", "/chart", "графік", "графік клімату", "графік температур", "покажи графік"):
            self.send_climate_chart(chat_id, floor="basement", hours=24.0)

        elif low in ("👥 присутність", "/presence", "присутність", "хто в гаражі", "хто тут"):
            self._send_presence(chat_id)

        elif low in ("🚪 ворота", "/door", "ворота"):
            self._send_door_menu(chat_id)

        elif low in ("💡 світло", "/light", "світло"):
            self._send_light_menu(chat_id)

        elif low in ("💨 вентиляція", "/fan", "вентиляція"):
            self._send_fan_menu(chat_id)

        elif low in ("/pinout", "розпіновка", "піни", "підключення", "схема"):
            self._send_pinout(chat_id)

        elif low in ("/pair", "сполучення", "навчання", "прив'язка", "режим сполучення", "📡 сполучення", "прив'язати реле"):
            self._start_rf_pairing(chat_id)

        elif low in ("/rf", "/sniffer", "сніфер", "радіокод", "код", "📡 радіокод"):
            self._send_rf_sniffer(chat_id)

        else:
            # Route to Smart Garage AI Router (Fast Gemini 2.5 Flash / Commands)
            try:
                res = self.garage.router.execute(text, session_id=f"tg_{chat_id}")
                if not res:
                    res = "Команду виконано."
                self.send_message(chat_id, res)
            except Exception as e:
                self.send_message(chat_id, f"⚠️ Помилка обробки: {e}")

    def _get_floors(self) -> dict:
        if hasattr(self.garage, "get_floors_telemetry"):
            return self.garage.get_floors_telemetry()
        bt = self.garage.bt_sensors.get_telemetry() if hasattr(self.garage, "bt_sensors") and self.garage.bt_sensors else {}
        return bt.get("floors", {})

    def _start_rf_pairing(self, chat_id: int):
        esp = getattr(self.garage, "esp32", None)
        if esp:
            esp.rf_pair(30)
            text = (
                "📡 *Режим безперервного сполучення 433 МГц запущено на 30 секунд!*\n\n"
                "🟣 *Світлодіод на ESP32 блимає фіолетовим* — радіомодуль CC1101 кожні 120 мс транслює код керування світлом `0xF1A101`.\n\n"
                "👉 *Ваші дії прямо зараз:*\n"
                "1. Підійдіть до блоку 4-канального реле 12V.\n"
                "2. Натисніть кнопку навчання на платі реле **2 рази** (для режиму Toggle / самоблокування).\n"
                "3. Світлодіод на реле засвітиться, отримає постійний сигнал від ESP32, кілька разів моргне і згасне.\n\n"
                "✅ Після цього реле збереже код і світло буде вмикатися та вимикатися кнопкою у додатку!"
            )
            self.send_message(chat_id, text)
        else:
            self.send_message(chat_id, "⚠️ ESP32 не підключено або недоступний.")

    def _send_pinout(self, chat_id: int):
        pinout_text = (
            "📌 *Апаратна розпіновка Smart Garage (CC1101 + AHT10 + ESP32-S3)*\n\n"
            "🔍 *Зверніть увагу на плату ESP32-S3 DevKitC-1:*\n"
            "Усі піни підключення розташовані на **лівому роз'ємі (Header J1)**, якщо тримати плату мікросхемою та антеною догори, а портами USB вниз:\n\n"
            "📡 *Радіомодуль CC1101 → ESP32-S3:*\n"
            "• Пін 1 (GND) ───► `GND` (нижній пін 22 на лівій гребінці або будь-який GND)\n"
            "• Пін 2 (VCC) ───► `3V3` (верхній пін 1 або 2 на лівій гребінці. ⚠️ *Тільки 3.3V! Не 5V!*)\n"
            "• Пін 3 (GDO0) ──► `7` (7-й зверху пін на лівій гребінці, напис '7')\n"
            "• Пін 4 (CSN) ───► `10` (16-й зверху пін, напис '10')\n"
            "• Пін 5 (SCK) ───► `12` (18-й зверху пін, напис '12')\n"
            "• Пін 6 (MOSI) ──► `11` (17-й зверху пін, напис '11')\n"
            "• Пін 7 (MISO) ──► `13` (19-й зверху пін, напис '13')\n"
            "• Пін 8 (GDO2) ──► *НЕ ПІДКЛЮЧАТИ* (залишається вільним)\n\n"
            "🌡️ *Кліматичний датчик AHT10 (I2C) → ESP32-S3:*\n"
            "• Пін VIN ───────► `3V3` (3.3V)\n"
            "• Пін GND ───────► `GND`\n"
            "• Пін SCL ───────► `9` (15-й зверху пін, напис '9')\n"
            "• Пін SDA ───────► `8` (12-й зверху пін, напис '8')\n\n"
            "💡 *Команди для перевірки:*\n"
            "• /pair — запустити трансляцію коду для навчання реле на 30 сек\n"
            "• /rf — подивитися перехоплені радіокоди"
        )
        self.send_message(chat_id, pinout_text)

    def _send_rf_sniffer(self, chat_id: int):
        esp = getattr(self.garage, "esp32", None)
        last_rf = esp.state.get("last_rf_sniffed") if esp else None
        if not last_rf:
            self.send_message(
                chat_id,
                "📡 *433 МГц Радіосніфер ESP32 (CC1101)*\n\n"
                "ℹ️ Перехоплених сигналів поки немає.\n\n"
                "👉 Натисніть клавішу на настінному вимикачі чи пульті поруч із гаражем / ESP32. "
                "Модуль CC1101 зафіксує радіокод у пам'яті, після чого введіть /rf для перегляду!"
            )
            return

        from server.sensors.freshness import format_relative_time_ua
        ts_rel = format_relative_time_ua(last_rf.get("timestamp"))
        text = (
            "📡 *Останній перехоплений 433 МГц радіосигнал:*\n\n"
            f"• 🔢 *Десятковий код:* `{last_rf.get('code')}`\n"
            f"• 🏷️ *Шістнадцятковий (HEX):* `{last_rf.get('hex')}`\n"
            f"• ⏱️ *Розрядність:* `{last_rf.get('bits')}` біт\n"
            f"• ⚙️ *Протокол:* `{last_rf.get('protocol')}`\n"
            f"• ⏳ *Затримка пульсу:* `{last_rf.get('delay')} мкс`\n"
            f"• 🕒 *Час перехоплення:* {ts_rel}\n\n"
            "💡 _Цей код зчитано безпосередньо з вимикача без необхідності натискати кнопку на реле! "
            "ESP32 тепер може транслювати цей самий код для керування освітленням._"
        )
        self.send_message(chat_id, text)

    def _send_status(self, chat_id: int):
        try:
            state = self.garage.esp32.get_telemetry()
            floors = self._get_floors()
            fb = floors.get("basement", {})
            f2 = floors.get("floor2", {})
            f1 = floors.get("floor1", {})

            esp_online = "🟢 Онлайн (USB Serial)" if state.get("online") else "🔴 Офлайн"
            temp_str = f"{fb.get('temperature', '--')}°C" if fb.get("temperature") is not None else "--"
            hum_str = f"{fb.get('humidity', '--')}%" if fb.get("humidity") is not None else "--"

            temp_f2_str = f"{f2.get('temperature', '--')}°C" if f2.get("temperature") is not None else "--"
            hum_f2_str = f"{f2.get('humidity', '--')}%" if f2.get("humidity") is not None else "--"
            f2_online_mark = "🟢" if f2.get("online") else "🔴"
            f2_status_desc = f"{f2_online_mark} `{temp_f2_str}` (Вологість: `{hum_f2_str}`)" if f2.get("online") and f2.get("temperature") is not None else f"🔴 `{temp_f2_str}` (Офлайн)"

            temp_f1_str = f"{f1.get('temperature', '--')}°C" if f1.get("temperature") is not None else "--"
            hum_f1_str = f"{f1.get('humidity', '--')}%" if f1.get("humidity") is not None else "--"
            f1_online_mark = "🟢" if f1.get("online") else "🔴"
            f1_status_desc = f"{f1_online_mark} `{temp_f1_str}` (Вологість: `{hum_f1_str}`)" if f1.get("online") and f1.get("temperature") is not None else f"🔴 `{temp_f1_str}` (Офлайн)"

            light_status = "🟢 Увімкнено" if state.get("light") else "⚪ Вимкнено"
            fan_status = "🟢 Увімкнено" if state.get("fan") else "⚪ Вимкнено"

            text = (
                f"📊 *Стан Smart Garage:*\n\n"
                f"• 📡 *ESP32-S3:* {esp_online}\n"
                f"• 🏠 *1-й поверх (AHT10):* {f1_status_desc}\n"
                f"• ⚓ *Підвал (LYWSD03MMC):* `{temp_str}` (Вологість: `{hum_str}`)\n"
                f"• 🏢 *2-й поверх (LYWSD03MMC):* {f2_status_desc}\n"
                f"• 💡 *Світло:* {light_status}\n"
                f"• 💨 *Вентиляція:* {fan_status}\n"
            )
            self.send_message(chat_id, text, reply_markup=self._get_main_keyboard())
        except Exception as e:
            self.send_message(chat_id, f"Помилка отримання статусу: {e}", reply_markup=self._get_main_keyboard())

    def _send_climate_menu(self, chat_id: int, message_id: int | None = None):
        try:
            floors = self._get_floors()
            fb = floors.get("basement", {})
            f2 = floors.get("floor2", {})
            f1 = floors.get("floor1", {})

            tb = f"{fb.get('temperature')}°C" if fb.get('temperature') is not None else "--"
            hb = f"{fb.get('humidity')}%" if fb.get('humidity') is not None else "--"
            stat_b = "🟢 Онлайн" if fb.get("online") else "⚪ В базі"

            t2 = f"{f2.get('temperature')}°C" if f2.get('temperature') is not None else "--"
            stat_2 = "🟢 Онлайн" if f2.get("online") else "🔴 Офлайн"

            t1 = f"{f1.get('temperature')}°C" if f1.get('temperature') is not None else "Очікує датчик"
            stat_1 = "🟢 Онлайн" if f1.get("online") else "⏳ Очікує підключення"

            msg = (
                "🌡️ *Клімат та температура Smart Garage*\n\n"
                f"• 🏠 *1-й поверх (Гараж):* `{t1}` ({stat_1})\n"
                f"• 🏢 *2-й поверх:* `{t2}` ({stat_2})\n"
                f"• ⚓ *Підвал:* `{tb}` (вологість: `{hb}`, {stat_b})\n"
                f"• 🌳 *Вулиця:* `Очікує датчик` (⏳ Не встановлено)\n\n"
                "👇 _Оберіть локацію для детальної інформації або перегляду графіка:_"
            )

            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "🏠 1-й поверх", "callback_data": "clim_floor1"},
                        {"text": "🏢 2-й поверх", "callback_data": "clim_floor2"}
                    ],
                    [
                        {"text": "⚓ Підвал", "callback_data": "clim_basement"},
                        {"text": "🌳 Вулиця", "callback_data": "clim_outdoor"}
                    ],
                    [
                        {"text": "📈 Графік зміни температур", "callback_data": "chart_basement_24"}
                    ]
                ]
            }

            if message_id:
                self.edit_message(chat_id, message_id, msg, reply_markup=reply_markup)
            else:
                self.send_message(chat_id, msg, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error showing climate menu: {e}")
            self.send_message(chat_id, f"Помилка даних клімату: {e}")

    def _send_floor1_details(self, chat_id: int, message_id: int | None = None):
        floors = self._get_floors()
        f1 = floors.get("floor1", {})
        temp = f1.get("temperature") if f1.get("temperature") is not None else f1.get("last_known_temperature")
        hum = f1.get("humidity") if f1.get("humidity") is not None else f1.get("last_known_humidity")
        is_online = f1.get("online", False) and temp is not None
        status_mark = "🟢 Актуально" if is_online else "🔴 Офлайн"

        temp_str = f"{temp}°C" if temp is not None else "--"
        hum_str = f"{hum}%" if hum is not None else "--"

        msg = (
            f"🏠 *1-й поверх (Гараж)*\n\n"
            f"• Датчик: `AHT10 (ESP32 I2C)`\n"
            f"• Стан: {status_mark}\n"
            f"• Температура: `{temp_str}`\n"
            f"• Вологість: `{hum_str}`\n"
        )
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📈 Графік (1-й поверх)", "callback_data": "chart_floor1_24"}],
                [{"text": "🔙 До меню температури", "callback_data": "clim_menu"}]
            ]
        }
        if message_id:
            self.edit_message(chat_id, message_id, msg, reply_markup=reply_markup)
        else:
            self.send_message(chat_id, msg, reply_markup=reply_markup)

    def _send_floor2_details(self, chat_id: int, message_id: int | None = None):
        floors = self._get_floors()
        f2 = floors.get("floor2", {})
        t2 = f"{f2.get('temperature')}°C" if f2.get('temperature') is not None else "--"
        h2 = f"{f2.get('humidity')}%" if f2.get('humidity') is not None else "--"
        online2 = "🟢 Онлайн" if f2.get("online") else "🔴 Офлайн (останні збережені дані)"

        msg = (
            "🏢 *2-й поверх (Житлове приміщення)*\n\n"
            "• Датчик: `Xiaomi Mijia LYWSD03MMC` (BLE)\n"
            f"• Температура: `{t2}`\n"
            f"• Вологість: `{h2}`\n"
            f"• Стан зв'язку: {online2}"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "📈 Графік 2-го поверху", "callback_data": "chart_floor2_24"},
                    {"text": "📈 Графік підвалу", "callback_data": "chart_basement_24"}
                ],
                [{"text": "🔙 До меню температури", "callback_data": "clim_menu"}]
            ]
        }
        if message_id:
            self.edit_message(chat_id, message_id, msg, reply_markup=reply_markup)
        else:
            self.send_message(chat_id, msg, reply_markup=reply_markup)

    def _send_basement_details(self, chat_id: int, message_id: int | None = None):
        floors = self._get_floors()
        fb = floors.get("basement", {})
        tb = f"{fb.get('temperature')}°C" if fb.get('temperature') is not None else "--"
        hb = f"{fb.get('humidity')}%" if fb.get('humidity') is not None else "--"
        online_b = "🟢 Онлайн" if fb.get("online") else "⚪ В базі даних"

        msg = (
            "⚓ *Підвал (Основний кліматичний вузол)*\n\n"
            "• Датчик: `Xiaomi Mijia LYWSD03MMC` (BLE)\n"
            f"• Температура: `{tb}`\n"
            f"• Вологість: `{hb}`\n"
            f"• Стан зв'язку: {online_b}"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "📈 Графік 24г", "callback_data": "chart_basement_24"},
                    {"text": "📈 Графік 48г", "callback_data": "chart_basement_48"},
                    {"text": "📈 Графік 7д", "callback_data": "chart_basement_168"}
                ],
                [{"text": "🔙 До меню температури", "callback_data": "clim_menu"}]
            ]
        }
        if message_id:
            self.edit_message(chat_id, message_id, msg, reply_markup=reply_markup)
        else:
            self.send_message(chat_id, msg, reply_markup=reply_markup)

    def _send_outdoor_details(self, chat_id: int, message_id: int | None = None):
        msg = (
            "🌳 *Вулиця (Зовнішній клімат)*\n\n"
            "• Стан: ⏳ Фізичний вуличний датчик ще не встановлений.\n"
            "• Поточна температура: `--`\n"
            "• Вологість: `--`\n\n"
            "ℹ️ _Після підключення вуличного датчика тут відображатиметься актуальна температура на подвір'ї та графік коливань._"
        )
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📈 Графік підвалу", "callback_data": "chart_basement_24"}],
                [{"text": "🔙 До меню температури", "callback_data": "clim_menu"}]
            ]
        }
        if message_id:
            self.edit_message(chat_id, message_id, msg, reply_markup=reply_markup)
        else:
            self.send_message(chat_id, msg, reply_markup=reply_markup)

    def _send_presence(self, chat_id: int):
        try:
            p_status = self.garage.presence.get_status() if hasattr(self.garage, "presence") else {}
            visitors = p_status.get("visitors_in_garage", [])
            active = p_status.get("active_devices", [])

            if not active and not visitors:
                self.send_message(chat_id, "👥 *У гаражі та поруч наразі нікого не виявлено.*")
                return

            msg = "👥 *Виявлені пристрої та відвідувачі:*\n\n"
            for d in active:
                alias = d.get("alias") or d.get("name") or "Невідомий пристрій"
                owner = f" ({d.get('owner')})" if d.get('owner') else ""
                zone = d.get("zone", "поруч")
                rssi = d.get("rssi", "--")
                msg += f"• 📱 *{alias}{owner}* — зона: `{zone}` (RSSI: `{rssi} dBm`)\n"

            self.send_message(chat_id, msg)
        except Exception as e:
            self.send_message(chat_id, f"Помилка перевірки присутності: {e}")

    def _send_door_menu(self, chat_id: int):
        self.send_message(
            chat_id,
            "🚪 *Гаражні ворота:* Керування вимкнено (привід воріт не планується / не встановлений).\nСтан: *Невідомо (unknown)*."
        )

    def _send_light_menu(self, chat_id: int):
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "💡 Увімкнути світло", "callback_data": "light_on"},
                    {"text": "🌑 Вимкнути світло", "callback_data": "light_off"}
                ]
            ]
        }
        self.send_message(chat_id, "💡 *Керування освітленням:* (Очікує фізичного підключення реле)", reply_markup=reply_markup)

    def _send_fan_menu(self, chat_id: int):
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "💨 Увімкнути вентиляцію", "callback_data": "fan_on"},
                    {"text": "🛑 Вимкнути вентиляцію", "callback_data": "fan_off"}
                ]
            ]
        }
        self.send_message(chat_id, "💨 *Керування вентиляцією:* (Очікує фізичного підключення реле)", reply_markup=reply_markup)

    def _handle_callback_query(self, cb: dict):
        cb_id = cb.get("id")
        data = cb.get("data")
        msg = cb.get("message", {})
        chat_id = msg.get("chat", {}).get("id")

        # Answer callback to remove loading icon
        try:
            requests.post(f"{self.api_base}/answerCallbackQuery", json={"callback_query_id": cb_id}, timeout=3)
        except Exception:
            pass

        if data in ("door_open", "door_close"):
            self.send_message(chat_id, "⚠️ Керування воротами вимкнено: привід воріт не планується / не встановлений.")
        elif data == "light_on":
            self.garage.esp32.light_on()
            self.send_message(chat_id, "💡 Світло увімкнено.")
        elif data == "light_off":
            self.garage.esp32.light_off()
            self.send_message(chat_id, "🌑 Світло вимкнено.")
        elif data == "fan_on":
            self.garage.esp32.fan_on()
            self.send_message(chat_id, "💨 Вентиляцію увімкнено.")
        elif data == "fan_off":
            self.garage.esp32.fan_off()
            self.send_message(chat_id, "🛑 Вентиляцію вимкнено.")
        elif data == "clim_menu":
            self._send_climate_menu(chat_id, message_id=msg.get("message_id"))
        elif data == "clim_floor1":
            self._send_floor1_details(chat_id, message_id=msg.get("message_id"))
        elif data == "clim_floor2":
            self._send_floor2_details(chat_id, message_id=msg.get("message_id"))
        elif data == "clim_basement":
            self._send_basement_details(chat_id, message_id=msg.get("message_id"))
        elif data == "clim_outdoor":
            self._send_outdoor_details(chat_id, message_id=msg.get("message_id"))
        elif data and data.startswith("chart_"):
            parts = data.split("_")
            if len(parts) == 3:
                _, c_floor, c_hours = parts
                try:
                    self.send_climate_chart(chat_id, floor=c_floor, hours=float(c_hours), message_id=msg.get("message_id"))
                except Exception as ec:
                    logger.error(f"Failed handling chart callback: {ec}")

    def _handle_voice_message(self, chat_id: int, voice: dict):
        file_id = voice.get("file_id")
        if not file_id:
            return

        self.send_message(chat_id, "🎙️ *Слухаю голосове повідомлення...*")

        try:
            # 1. Get file path from Telegram
            r = requests.get(f"{self.api_base}/getFile", params={"file_id": file_id}, timeout=5)
            if r.status_code != 200:
                self.send_message(chat_id, "⚠️ Не вдалося завантажити голосовий файл.")
                return

            file_path = r.json().get("result", {}).get("file_path")
            download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            audio_data = requests.get(download_url, timeout=10).content

            # 2. Transcribe via Gemini 2.5 Flash on OpenRouter
            from server.config import config
            api_key = config.get("llm", {}).get("api_key")
            api_base = config.get("llm", {}).get("api_base", "https://openrouter.ai/api/v1")

            b64_audio = base64.b64encode(audio_data).decode("utf-8")
            payload = {
                "model": "google/gemini-2.5-flash",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Розпізнай текст цього короткого голосового повідомлення українською мовою. Поверни ТІЛЬКИ розпізнаний текст без лапок і коментарів."},
                            {"type": "input_audio", "input_audio": {"data": b64_audio, "format": "ogg"}}
                        ]
                    }
                ],
                "max_tokens": 100
            }
            resp = requests.post(f"{api_base.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload, timeout=12)

            transcript = ""
            if resp.status_code == 200:
                transcript = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()

            if not transcript:
                self.send_message(chat_id, "⚠️ Не вдалося розпізнати слова в аудіо.")
                return

            self.send_message(chat_id, f"🗣️ *Ви сказали:* «{transcript}»")

            # Execute command
            reply = self.garage.router.execute(transcript, session_id=f"tg_{chat_id}")
            self.send_message(chat_id, reply or "Команду виконано.")

        except Exception as e:
            logger.error(f"Voice message handling error: {e}")
            self.send_message(chat_id, f"⚠️ Помилка обробки голосового повідомлення: {e}")
