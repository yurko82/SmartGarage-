import os
import time
import threading
from datetime import datetime
from server.config import config
from server.ai.manager import AIManager
from server.memory.memory import Memory
from server.logger.logger import Logger
from server.commands.processor import CommandProcessor
from server.devices.projector import ProjectorController
from server.devices.esp32 import ESP32Controller
from server.devices.bluetooth_sensor import BluetoothSensorManager
from server.devices.bluetooth_speaker import BluetoothSpeakerController
from server.devices.presence import PresenceManager
from server.automation.engine import AutomationEngine
from server.utils.files import FileManager
from server.services.telegram_bot import TelegramBot
from server.router.router import CommandRouter
from server.storage.telemetry_db import TelemetryDB
from server.ai.tools import ToolDispatcher
from server.services.voice_queue import voice_command_queue, VoiceCommandQueue


class SmartGarage:

    def __init__(self, start_workers: bool = True):

        self.logger = Logger()
        self.ai = AIManager()
        self.memory = Memory()
        self.telemetry_db = TelemetryDB()
        self.projector = ProjectorController()
        self.esp32 = ESP32Controller()
        self.speaker = BluetoothSpeakerController(logger=self.logger)
        self.presence = PresenceManager(logger=self.logger, presence_config=config.get("presence", {}))
        self.bt_sensors = BluetoothSensorManager(telemetry_db=self.telemetry_db)
        self.telegram = TelegramBot(self)

        # Wire proactive presence arrival/departure notifications to Telegram & TTS
        _last_owner_greeting_ts = 0.0
        _last_owner_departure_ts = 0.0
        _presence_lock = threading.Lock()
        _guest_alerts_ts = {}
        _guest_alert_lock = threading.Lock()

        def _handle_presence_event_async(entry):
            nonlocal _last_owner_greeting_ts, _last_owner_departure_ts
            event = entry.get("event")
            name = entry.get("person_name") or entry.get("device_name") or "Пристрій"
            role = str(entry.get("role") or "").lower()
            zone = entry.get("proximity", "поруч")
            source = str(entry.get("source") or "")
            device_id = str(entry.get("device_id") or "")
            is_owner = ("owner" in role) or ("власник" in name.lower()) or ("юрій" in name.lower())

            # Ignore secondary paired accessory arrivals (e.g. watch paired to phone)
            if source == "paired_with_owner":
                return

            # Check device-specific settings if available
            dev = {}
            if hasattr(self, "presence") and self.presence and device_id in self.presence.devices:
                dev = self.presence.devices[device_id]

            now = time.time()
            time_str = datetime.fromtimestamp(now).strftime("%H:%M")

            if event == "ARRIVED":
                if is_owner:
                    # Opt-in check for automatic welcome greeting
                    if not bool(dev.get("auto_welcome", False) and dev.get("opt_in", False)):
                        return

                    with _presence_lock:
                        # Debounce owner greetings to at most once every 10 minutes (600s)
                        if now - _last_owner_greeting_ts < 600:
                            return
                        _last_owner_greeting_ts = now

                    try:
                        greeting_prompt = (
                            f"Власник Юрій щойно прибув у гараж (зона: {zone}). "
                            f"Сформулюй коротке, ввічливе та технологічне привітання від імені Smart Garage (1-2 речення). "
                            f"Згадай один найважливіший факт про поточний стан (клімат підвалу або готовність гаража)."
                        )
                        ai_greeting = self.ai.chat(greeting_prompt, context_info=self.get_context_snapshot())
                        self.telegram.notify_admin(f"👋 {ai_greeting}")
                    except Exception:
                        self.telegram.notify_admin(f"🔔 *Smart Garage:* Помічено прибуття: `{name}` (зона: `{zone}`)")
                else:
                    # Guest arrival: notifications and automations disabled by default (opt-in required)
                    if not bool(dev.get("opt_in", False) and dev.get("notify_owner", False)):
                        return

                    with _guest_alert_lock:
                        last_guest_ts = _guest_alerts_ts.get(device_id, 0.0)
                        if now - last_guest_ts < 300:  # Debounce to max 1 alert per 5 minutes per device
                            return
                        _guest_alerts_ts[device_id] = now

                    # Neutral Telegram notification to owner (never announce absence to visitor or play absence audio)
                    self.telegram.notify_admin(
                        f"👋 *Smart Garage:* До гаража наблизився пристрій: *{name}* (виявлено о {time_str}, зона: {zone})."
                    )

            elif event == "DEPARTED":
                if is_owner:
                    with _presence_lock:
                        # Debounce owner departures to at most once every 10 minutes (600s)
                        if now - _last_owner_departure_ts < 600:
                            return
                        _last_owner_departure_ts = now

                    alerts = []
                    if hasattr(self, "esp32") and self.esp32:
                        st = self.esp32.get_telemetry()
                        if st.get("light"):
                            alerts.append("💡 Світло залишилося УВІМКНЕНИМ")

                    if alerts:
                        alert_text = "\n".join(f"• {a}" for a in alerts)
                        self.telegram.notify_admin(
                            f"⚠️ *Увага, Юрію! Ви залишили гараж, але:*\n{alert_text}\n\n"
                            f"Надішліть «закрий ворота» чи «вимкни світло» для виправлення."
                        )
                    else:
                        self.telegram.notify_admin("🚗 *Smart Garage:* Власник залишив зону гаража. Безпека в нормі.")

        def _on_presence_event(entry):
            if os.environ.get("TESTING"):
                _handle_presence_event_async(entry)
                return
            # Dispatch to background thread so presence monitor and locks are NEVER blocked
            try:
                threading.Thread(
                    target=_handle_presence_event_async,
                    args=(dict(entry),),
                    daemon=True,
                    name="PresenceEventHandler"
                ).start()
            except Exception as e:
                self.logger.error(f"Error starting presence event handler thread: {e}")

        if hasattr(self.presence, "set_event_callback"):
            self.presence.set_event_callback(_on_presence_event)
        elif hasattr(self.presence, "_event_cb"):
            self.presence._event_cb = _on_presence_event

        self.voice_queue = voice_command_queue
        self._voice_worker_thread = None

        if start_workers and not os.environ.get("TESTING"):
            self.bt_sensors.start()
            self.presence.start()
            self.telegram.start()
            self._start_voice_worker()

        self.automation = AutomationEngine(self.esp32, self.projector, self.memory, self.logger)

        def _on_esp32_telemetry(data):
            if hasattr(self, "automation") and self.automation:
                self.automation.evaluate_telemetry(data)
            if "floors" in data and hasattr(self, "bt_sensors") and self.bt_sensors:
                with self.bt_sensors._lock:
                    for fk, fval in data["floors"].items():
                        mac = fval.get("mac")
                        if mac and mac in self.bt_sensors.sensors:
                            s = self.bt_sensors.sensors[mac]
                            if fval.get("temperature") is not None:
                                s["temperature"] = fval["temperature"]
                            if fval.get("humidity") is not None:
                                s["humidity"] = fval["humidity"]
                            if fval.get("battery") is not None:
                                s["battery"] = fval["battery"]
                            s["online"] = fval.get("online", True)
                            s["last_updated"] = time.time()
                self.bt_sensors._save_cache()
            if hasattr(self, "telemetry_db") and self.telemetry_db and "floors" in data:
                for fk, fval in data["floors"].items():
                    if isinstance(fval, dict) and fval.get("temperature") is not None:
                        self.telemetry_db.record(
                            floor=fk,
                            temperature=fval["temperature"],
                            humidity=fval.get("humidity"),
                            battery=fval.get("battery"),
                            mac=fval.get("mac"),
                            sensor_name=fval.get("name")
                        )

        self.esp32.on_telemetry_callback = _on_esp32_telemetry

        self.commands = CommandProcessor(self.logger, self.memory, self.projector, self.esp32, self.automation, self.bt_sensors, speaker=self.speaker, presence=self.presence, telemetry_db=self.telemetry_db)
        self.tool_dispatcher = ToolDispatcher(self)
        if hasattr(self.ai, "set_tool_dispatcher"):
            self.ai.set_tool_dispatcher(self.tool_dispatcher)

        self.router = CommandRouter(
            self.commands,
            self.ai,
            context_provider=self.get_context_snapshot
        )

    def get_floors_telemetry(self) -> dict:
        """Returns unified floor telemetry merged from BluetoothSensorManager (host) and ESP32."""
        floors = {}
        if hasattr(self, "bt_sensors") and self.bt_sensors:
            t = self.bt_sensors.get_telemetry()
            floors = dict(t.get("floors", {}))

        if hasattr(self, "esp32") and self.esp32:
            st = self.esp32.get_telemetry()
            esp_floors = st.get("floors", {})
            if isinstance(esp_floors, dict):
                for fk, fval in esp_floors.items():
                    if isinstance(fval, dict) and fval.get("mac"):
                        is_esp_online = bool(fval.get("online", False))
                        if is_esp_online and fval.get("temperature") is not None:
                            if fk not in floors:
                                floors[fk] = dict(fval)
                            else:
                                floors[fk] = dict(floors[fk])
                                floors[fk]["temperature"] = fval["temperature"]
                                floors[fk]["humidity"] = fval.get("humidity", floors[fk].get("humidity"))
                                floors[fk]["battery"] = fval.get("battery", floors[fk].get("battery"))
                                floors[fk]["online"] = True
                            floors[fk]["last_updated"] = fval.get("last_updated") or time.time()
                            floors[fk]["source"] = "esp32"
                        elif fk in floors and fval.get("temperature") is not None:
                            # Зберігаємо останні дійсні виміри температури навіть якщо миттєвий прапорець не активний
                            if floors[fk].get("temperature") is None:
                                floors[fk]["temperature"] = fval["temperature"]
                                floors[fk]["humidity"] = fval.get("humidity", floors[fk].get("humidity"))
        return floors

    def get_context_snapshot(self) -> str:
        """Builds an informative, compact text snapshot of the garage's real-time state for AI."""
        import time
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"- Дата та час: {now_str}"]

        # 1. Hardware / ESP32
        if hasattr(self, "esp32") and self.esp32:
            st = self.esp32.get_telemetry()
            esp_status = "онлайн (USB-Serial)" if st.get("online") else "офлайн"
            relays_installed = st.get("relays_installed", False)
            if not relays_installed:
                lines.append(f"- Обладнання ESP32-S3: {esp_status}")
            else:
                light = "увімкнено" if st.get("light") else "вимкнено"
                fan = "увімкнено" if st.get("fan") else "вимкнено"
                lines.append(f"- Обладнання ESP32-S3: {esp_status} | Світло: {light} | Вентиляція: {fan}")

        # 2. Climate across floors
        floors = self.get_floors_telemetry()
        fb = floors.get("basement", {})
        f2 = floors.get("floor2", {})
        f1 = floors.get("floor1", {})

        def _fmt_desc(f_data, default_text="немає даних"):
            temp = f_data.get("temperature") if f_data.get("temperature") is not None else f_data.get("last_known_temperature")
            hum = f_data.get("humidity") if f_data.get("humidity") is not None else f_data.get("last_known_humidity")
            if temp is not None:
                hum_str = f", вологість {hum}%" if hum is not None else ""
                return f"{temp}°C{hum_str}"
            if not f_data.get("mac") or not f_data.get("installed", True):
                return "очікує встановлення фізичного датчика"
            return default_text

        b_desc = _fmt_desc(fb, "офлайн")
        f2_desc = _fmt_desc(f2, "офлайн")
        f1_desc = _fmt_desc(f1, "очікує встановлення фізичного датчика")

        lines.append(f"- Клімат 1-й поверх (гараж): {f1_desc}")
        lines.append(f"- Клімат Підвал: {b_desc}")
        lines.append(f"- Клімат 2-й поверх: {f2_desc}")
        lines.append(f"- Загальна температура в гаражі: на 1-му поверсі {f1_desc}, у підвалі {b_desc}, на 2-му поверсі {f2_desc}")

        # 3. Presence
        if hasattr(self, "presence") and self.presence:
            p_status = self.presence.get_status()
            present = p_status.get("present_now", [])
            if present:
                names = [f"{d.get('name')} ({d.get('role', 'гість')}, зона: {d.get('proximity', 'поруч')})" for d in present]
                lines.append(f"- Присутність: виявлено поруч: {', '.join(names)}")
            else:
                lines.append("- Присутність: біля гаража наразі нікого не виявлено (власник відсутній)")

        # 4. Multimedia & Audio
        if hasattr(self, "projector") and self.projector:
            proj_online = self.projector.is_reachable()
            lines.append(f"- Проектор HY350MAX: {'онлайн' if proj_online else 'очікування/вимкнено'}")
        if hasattr(self, "speaker") and self.speaker:
            try:
                st = self.speaker.get_status()
                active_name = st.get("name", "Bluetooth-колонка")
                is_conn = st.get("connected", False)
                is_play = st.get("playing", False)
                is_paused = st.get("paused", False)
                vol = st.get("volume", 0)
                track = st.get("current_track") or "радіо/аудіо"

                spk_parts = []
                for s in st.get("speakers", []):
                    s_name = s.get("name")
                    s_state = "підключено" if s.get("connected") else "відключено/офлайн"
                    if s.get("active"):
                        s_state += ", АКТИВНА"
                    spk_parts.append(f"{s_name} ({s_state})")
                spk_summary = "; ".join(spk_parts) if spk_parts else f"{active_name} ({'підключено' if is_conn else 'офлайн'})"

                if is_play:
                    play_desc = f"Транслюється: '{track}' на активну колонку '{active_name}' (гучність {vol}%)"
                elif is_paused:
                    play_desc = f"На паузі: '{track}' на колонці '{active_name}' (гучність {vol}%)"
                else:
                    play_desc = "Зупинено / нічого не транслюється"

                lines.append(f"- Мультимедіа/Аудіо: {play_desc} | Колонки: {spk_summary}")
            except Exception as e:
                lines.append(f"- Мультимедіа/Аудіо: помилка отримання статусу ({e})")

        return "\n".join(lines)

    def process_voice_command(self, text: str, source: str = "voice") -> str:
        """
        Processes a voice command with top priority (source: 'voice') through the router / AI pipeline.
        Notifies Telegram admin and returns the AI response.
        """
        text = text.strip()
        if not text:
            return ""

        self.logger.info(f"[Voice AI] Received command with high priority (source='{source}'): «{text}»")
        # Enqueue with metadata marked as executed to maintain audit log and stats
        self.voice_queue.put_sync(text, source=source, priority=1, metadata={"executed": True})

        reply = self.router.execute(text, session_id="voice")

        # Notify Telegram admin if configured
        if hasattr(self, "telegram") and self.telegram and getattr(self.telegram, "admin_chat_id", None):
            try:
                self.telegram.send_message(
                    self.telegram.admin_chat_id,
                    f"🎙️ *Голосова команда:* «{text}»\n🤖 {reply or 'Команду виконано.'}"
                )
            except Exception as e:
                self.logger.debug(f"Failed to send Telegram voice notification: {e}")

        return reply or "Команду виконано."

    def _start_voice_worker(self):
        """Starts asynchronous background consumer for the voice message queue."""
        import asyncio

        def _loop_runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _consumer():
                while True:
                    try:
                        cmd = await self.voice_queue.get()
                        if cmd.metadata and cmd.metadata.get("executed"):
                            continue
                        self.logger.info(f"[VoiceQueueWorker] Processing async command (source={cmd.source}): «{cmd.text}»")
                        reply = self.router.execute(cmd.text, session_id="voice")
                        if hasattr(self, "telegram") and self.telegram and getattr(self.telegram, "admin_chat_id", None):
                            try:
                                self.telegram.send_message(
                                    self.telegram.admin_chat_id,
                                    f"🎙️ *Голосова команда:* «{cmd.text}»\n🤖 {reply or 'Команду виконано.'}"
                                )
                            except Exception:
                                pass
                    except Exception as e:
                        self.logger.error(f"[VoiceQueueWorker] Error in queue consumer: {e}")
                        await asyncio.sleep(1.0)

            loop.run_until_complete(_consumer())

        self._voice_worker_thread = threading.Thread(target=_loop_runner, daemon=True, name="VoiceQueueWorker")
        self._voice_worker_thread.start()
        self.logger.info("VoiceQueueWorker thread initialized.")

    def turn_off_light_zone(self, zone: str) -> bool:
        """Гарантоване вимкнення світла для окремої зони (basement_light, floor2_light, main_light)."""
        if hasattr(self, "esp32") and self.esp32:
            return self.esp32.light_off_zone(zone)
        return False

    def start(self):

        self.logger.info("Starting Smart Garage...")

        self.ai.info()

        data = self.memory.load()
        self.logger.info(f"Memory: {data}")

        self.logger.info("System ready.")

        text = FileManager.read("README.md")

        if text:
            self.logger.info("README loaded successfully.")
        else:
            self.logger.error("README not found.")

        result = self.commands.execute("status")
        self.logger.info(result)
