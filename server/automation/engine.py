import time
import threading
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
        self._last_gas_level = 0
        self._last_motion = False

    def evaluate_telemetry(self, telemetry):
        """Called whenever new telemetry arrives from ESP32."""
        if not self.enabled or not isinstance(telemetry, dict):
            return

        with self._lock:
            car_present = telemetry.get("car_present", False)
            gas_ppm = telemetry.get("gas_ppm", 0)
            motion = telemetry.get("motion_detected", False)

            # Auto Safety: Gas/Smoke spike detection
            if gas_ppm > 200 and self._last_gas_level <= 200:
                self.logger.warning(f"⚠️ HIGH GAS DETECTED ({gas_ppm} ppm)! Triggering Emergency Ventilation.")
                self.scenario_gas_alarm()

            self._last_car_present = car_present
            self._last_gas_level = gas_ppm
            self._last_motion = motion

    def scenario_car_arrival(self):
        """Scenario: Vehicle arrives home."""
        self.logger.info("🚗 Executing Scenario: Car Arrival")
        actions = []
        if self.esp32:
            self.esp32.door_open()
            self.esp32.light_on()
            actions.append("Ворота відкрито")
            actions.append("Освітлення увімкнено")

        if self.projector and self.projector.is_reachable():
            self.projector.render_and_send_slide(
                title="Ласкаво просимо додому!",
                subtitle="Сценарій: Прибуття авто",
                details=["Ворота: Відкрито", "Освітлення: 100%", "Паркувальне місце: Готове"]
            )
            actions.append("Слайд привітання на проекторі")

        return True, "🚗 Сценарій 'Прибуття авто' виконано: " + ", ".join(actions)

    def scenario_departure(self):
        """Scenario: Vehicle departs."""
        self.logger.info("🚗 Executing Scenario: Departure")
        actions = []
        if self.esp32:
            self.esp32.door_close()
            self.esp32.light_off()
            actions.append("Ворота закрито")
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
            self.esp32.door_close()
            self.esp32.light_off()
            self.esp32.fan_off()
            actions.append("Ворота надійно зачинено")
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
        """Scenario: Emergency Ventilation & Safety."""
        self.logger.warning("🚨 Executing Scenario: Gas & Smoke Emergency")
        actions = []
        if self.esp32:
            self.esp32.fan_on()
            self.esp32.door_open()
            self.esp32.light_on()
            actions.append("Вентиляцію увімкнено на 100%")
            actions.append("Ворота відкрито для провітрювання")
            actions.append("Освітлення увімкнено для безпеки")

        if self.projector and self.projector.is_reachable():
            self.projector.render_and_send_slide(
                title="⚠️ УВАГА: ЗАГАЗОВАНІСТЬ!",
                subtitle="Активовано аварійне провітрювання",
                details=["Витяжка: 100% потужності", "Ворота: Відкрито", "Зачекайте очищення повітря"]
            )
            actions.append("Тривожне попередження на проекторі")

        return True, "🚨 АВАРІЙНИЙ СЦЕНАРІЙ 'Безпека / Вентиляція': " + ", ".join(actions)

    def list_scenarios(self):
        return """Доступні сценарії автоматизації Smart Garage:
  1. 🚗 'Прибуття авто' (команда: 'я приїхав', 'сценарій прибуття')
  2. 🔒 'Від'їзд' (команда: 'я поїхав', 'сценарій від'їзд')
  3. 🌙 'Нічний режим' (команда: 'добраніч', 'нічний режим')
  4. 🍿 'Кінотеатр у гаражі' (команда: 'кінотеатр', 'режим кіно')
  5. 🚨 'Безпека / Провітрювання' (команда: 'провітрити', 'тривога')"""
