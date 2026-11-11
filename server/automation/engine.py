import threading
import time

from server.logger.logger import Logger


class AutomationEngine:

    def __init__(self, esp32=None, projector=None, memory=None, logger=None):
        self.esp32 = esp32
        self.projector = projector
        self.memory = memory
        self.logger = logger or Logger()
        self.enabled = True
        self._lock = threading.Lock()

        # Track previous states to trigger edge-based automations
        self._last_car_present = False
        self._last_motion = False

    def evaluate_telemetry(self, telemetry):
        """Called whenever new telemetry arrives from ESP32."""
        if not self.enabled or not isinstance(telemetry, dict):
            return

        with self._lock:
            car_present = bool(telemetry.get("car_present"))
            motion = bool(telemetry.get("motion_detected"))

            self._last_car_present = car_present
            self._last_motion = motion

    def scenario_car_arrival(self):
        """Scenario: Vehicle arrives home."""
        self.logger.info("🚗 Executing Scenario: Car Arrival")
        actions = []
        if self.esp32:
            self.esp32.light_on()
            actions.append("Освітлення увімкнено")

        if self.projector and self.projector.is_reachable():
            self.projector.render_and_send_slide(
                title="Ласкаво просимо додому!",
                subtitle="Сценарій: Прибуття авто",
                details=["Освітлення: 100%", "Паркувальне місце: Готове"]
            )
            actions.append("Слайд привітання на проекторі")

        return True, "🚗 Сценарій 'Прибуття авто' виконано: " + ", ".join(actions)

    def scenario_departure(self):
        """Scenario: Vehicle departs."""
        self.logger.info("🚗 Executing Scenario: Departure")
        actions = []
        if self.esp32:
            self.esp32.light_off()
            actions.append("Освітлення вимкнено")

        if self.projector:
            self.projector.stop_mirroring()
            self.projector.stop_video()
            actions.append("Проектор переведено в режим очікування")

        return True, "🔒 Сценарій 'Від'їзд' виконано: " + ", ".join(actions)

    def scenario_night_mode(self):
        """Scenario: Night Security Auto-Lock."""
        self.logger.info("🌙 Executing Scenario: Night Security Mode")
        actions = []
        if self.esp32:
            self.esp32.light_off()
            self.esp32.fan_off()
            actions.append("Всі прилади та освітлення знеструмлено")

        if self.projector:
            self.projector.stop_mirroring()
            self.projector.stop_video()
            actions.append("Проектор вимкнено")

        return True, "🌙 Сценарій 'Нічний режим' активовано: " + ", ".join(actions)

    def scenario_cinema_mode(self):
        """Scenario: Garage Cinema / Media Lounge."""
        self.logger.info("🍿 Executing Scenario: Garage Cinema")
        actions = []
        if self.esp32:
            self.esp32.light_off()
            self.esp32.fan_off()
            actions.append("Освітлення вимкнено")

        if self.projector and self.projector.is_reachable():
            self.projector.render_and_send_slide(
                title="Smart Garage Cinema",
                subtitle="Режим кінотеатру активовано",
                details=["Головне світло: Вимкнено", "Екран: HY350MAX Full HD", "Очікування вибору медіа..."]
            )
            actions.append("Проектор HY350MAX активовано")

        return True, "🍿 Сценарій 'Кінотеатр у гаражі' активовано: " + ", ".join(actions)

    def scenario_gas_alarm(self):
        """Scenario: Emergency Ventilation & Safety (Disabled: gas sensor not installed)."""
        self.logger.info("Сценарій аварійного газу відхилено: газовий датчик не встановлений.")
        return False, "⚠️ Функція недоступна: газовий датчик не встановлений."

    def list_scenarios(self):
        return """Доступні сценарії автоматизації Smart Garage:
  1. 🚗 'Прибуття авто' (команда: 'я приїхав', 'сценарій прибуття')
  2. 🔒 'Від'їзд' (команда: 'я поїхав', 'сценарій від'їзд')
  3. 🌙 'Нічний режим' (команда: 'добраніч', 'нічний режим')
  4. 🍿 'Кінотеатр у гаражі' (команда: 'кінотеатр', 'режим кіно')"""
