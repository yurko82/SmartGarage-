import os
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


class SmartGarage:

    def __init__(self, start_workers: bool = True):

        self.logger = Logger()
        self.ai = AIManager()
        self.memory = Memory()
        self.projector = ProjectorController()
        self.esp32 = ESP32Controller()
        self.speaker = BluetoothSpeakerController(logger=self.logger)
        self.presence = PresenceManager(logger=self.logger, presence_config=config.get("presence", {}))
        self.bt_sensors = BluetoothSensorManager()
        self.telegram = TelegramBot(self)

        # Wire presence arrival notifications to Telegram
        def _on_presence_event(entry):
            if entry.get("event") == "ARRIVED":
                name = entry.get("person_name") or entry.get("device_name") or "Пристрій"
                zone = entry.get("proximity", "поруч")
                self.telegram.notify_admin(f"🔔 *Smart Garage:* Помічено прибуття: `{name}` (зона: `{zone}`)")

        if hasattr(self.presence, "set_event_callback"):
            self.presence.set_event_callback(_on_presence_event)
        elif hasattr(self.presence, "_event_cb"):
            self.presence._event_cb = _on_presence_event

        if start_workers and not os.environ.get("TESTING"):
            self.bt_sensors.start()
            self.presence.start()
            self.telegram.start()

        self.automation = AutomationEngine(self.esp32, self.projector, self.memory, self.logger)
        self.commands = CommandProcessor(self.logger, self.memory, self.projector, self.esp32, self.automation, self.bt_sensors, speaker=self.speaker, presence=self.presence)
        self.router = CommandRouter(
            self.commands,
            self.ai
        )





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
