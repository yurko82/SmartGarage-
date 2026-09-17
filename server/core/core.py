import os
import time
import threading
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

        # Wire proactive presence arrival/departure notifications to Telegram
        _last_owner_greeting_ts = 0.0
        _last_owner_departure_ts = 0.0
        _presence_lock = threading.Lock()

        def _on_presence_event(entry):
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

            # Check device-specific auto_welcome setting if available
            if hasattr(self, "presence") and self.presence and device_id in self.presence.devices:
                dev = self.presence.devices[device_id]
                if not dev.get("auto_welcome", True):
                    return

            now = time.time()

            if event == "ARRIVED":
                if is_owner:
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
                    self.telegram.notify_admin(f"🔔 *Smart Garage:* Помічено прибуття: `{name}` (зона: `{zone}`)")

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
                        if st.get("door") == "open":
                            alerts.append("🚪 Ворота залишилися ВІДЧИНЕНИМИ")
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

        if hasattr(self.presence, "set_event_callback"):
            self.presence.set_event_callback(_on_presence_event)
        elif hasattr(self.presence, "_event_cb"):
            self.presence._event_cb = _on_presence_event

        if start_workers and not os.environ.get("TESTING"):
            self.bt_sensors.start()
            self.presence.start()
            self.telegram.start()

        self.automation = AutomationEngine(self.esp32, self.projector, self.memory, self.logger)
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
                        elif not is_esp_online and fk in floors:
                            floors[fk]["online"] = False

        # Fallback to persistent SQLite latest readings if a floor has no temperature
        if hasattr(self, "telemetry_db") and self.telemetry_db:
            latest_db = self.telemetry_db.get_latest_by_floor()
            for fk, db_val in latest_db.items():
                if fk in floors and floors[fk].get("temperature") is None and db_val.get("temperature") is not None:
                    floors[fk]["temperature"] = db_val["temperature"]
                    floors[fk]["humidity"] = db_val.get("humidity")
                    floors[fk]["battery"] = db_val.get("battery")
                    floors[fk]["last_updated"] = db_val.get("timestamp")
                    floors[fk]["source"] = "db"
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
            door = st.get("door", "зачинено")
            light = "увімкнено" if st.get("light") else "вимкнено"
            fan = "увімкнено" if st.get("fan") else "вимкнено"
            lines.append(f"- Обладнання ESP32-S3: {esp_status} | Ворота: {door} | Світло: {light} | Вентиляція: {fan}")

        # 2. Climate across floors
        floors = self.get_floors_telemetry()
        fb = floors.get("basement", {})
        f2 = floors.get("floor2", {})
        f1 = floors.get("floor1", {})

        b_desc = f"{fb.get('temperature')}°C, вологість {fb.get('humidity')}%, батарея {fb.get('battery')}% (онлайн)" if fb.get("online") and fb.get("temperature") is not None else "офлайн"
        f2_desc = f"{f2.get('temperature')}°C, вологість {f2.get('humidity')}% (онлайн)" if f2.get("online") and f2.get("temperature") is not None else "офлайн"
        f1_desc = f"{f1.get('temperature')}°C" if f1.get("online") and f1.get("temperature") is not None else "очікує встановлення фізичного датчика"

        lines.append(f"- Клімат Підвал (LYWSD03MMC): {b_desc}")
        lines.append(f"- Клімат 2-й поверх (LYWSD03MMC): {f2_desc}")
        lines.append(f"- Клімат 1-й поверх (Гараж): {f1_desc}")

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
            lines.append(f"- Проектор HY350MAX (192.168.100.191): {'онлайн' if proj_online else 'очікування/вимкнено'}")
        if hasattr(self, "speaker") and self.speaker:
            lines.append(f"- BT-колонка JBL Clip 5: {'підключено' if self.speaker.is_connected() else 'не підключено'}")

        return "\n".join(lines)





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
