"""
server/services/device_service.py — Єдиний фасад апаратного рівня (DeviceService)
Централізує взаємодію з фізичними пристроями: ESP32, BLE-сенсорами, RF 433 МГц,
подвійною аудіосистемою (JBL + JX-BT), проєктором та системою присутності.
"""
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("DeviceService")


class DeviceService:
    """Єдиний сервіс доступу до апаратного забезпечення гаража."""

    def __init__(
        self,
        esp32=None,
        bt_sensors=None,
        speaker=None,
        rf_manager=None,
        projector=None,
        presence=None,
        telemetry_db=None,
    ):
        self._esp32 = esp32
        self._bt_sensors = bt_sensors
        self._speaker = speaker
        self._rf_manager = rf_manager
        self._projector = projector
        self._presence = presence
        self._telemetry_db = telemetry_db

    # --- Ледачі властивості для підсистем ---

    @property
    def esp32(self):
        if self._esp32 is None:
            try:
                from server.devices.esp32 import ESP32Controller
                self._esp32 = ESP32Controller()
            except Exception as e:
                logger.error(f"Не вдалося ініціалізувати ESP32Controller: {e}")
        return self._esp32

    @property
    def bt_sensors(self):
        if self._bt_sensors is None:
            try:
                from server.devices.bluetooth_sensor import BluetoothSensorManager
                self._bt_sensors = BluetoothSensorManager(telemetry_db=self.telemetry_db)
            except Exception as e:
                logger.error(f"Не вдалося ініціалізувати BluetoothSensorManager: {e}")
        return self._bt_sensors

    @property
    def speaker(self):
        if self._speaker is None:
            try:
                from server.devices.bluetooth_speaker import BluetoothSpeakerController
                self._speaker = BluetoothSpeakerController()
            except Exception as e:
                logger.error(f"Не вдалося ініціалізувати BluetoothSpeakerController: {e}")
        return self._speaker

    @property
    def rf_manager(self):
        if self._rf_manager is None:
            try:
                from server.devices.rf_manager import RfManager
                self._rf_manager = RfManager()
            except Exception as e:
                logger.error(f"Не вдалося ініціалізувати RfManager: {e}")
        return self._rf_manager

    @property
    def projector(self):
        if self._projector is None:
            try:
                from server.devices.projector import ProjectorController
                self._projector = ProjectorController()
            except Exception as e:
                logger.error(f"Не вдалося ініціалізувати ProjectorController: {e}")
        return self._projector

    @property
    def presence(self):
        if self._presence is None:
            try:
                from server.devices.presence import PresenceManager
                self._presence = PresenceManager()
            except Exception as e:
                logger.error(f"Не вдалося ініціалізувати PresenceManager: {e}")
        return self._presence

    @property
    def telemetry_db(self):
        if self._telemetry_db is None:
            try:
                from server.storage.telemetry_db import TelemetryDB
                self._telemetry_db = TelemetryDB()
            except Exception as e:
                logger.error(f"Не вдалося ініціалізувати TelemetryDB: {e}")
        return self._telemetry_db

    # --- Публічне API апаратного рівня ---

    def get_telemetry(self) -> dict[str, Any]:
        """Отримати зведену телеметрію з ESP32, BLE-датчиків та локальної бази даних."""
        result: dict[str, Any] = {
            "online": False,
            "light": False,
            "fan": False,
            "temperature": None,
            "humidity": None,
            "floors": {},
            "source": "fallback",
        }

        # 1. Спроба отримати свіжі дані від ESP32
        if self.esp32:
            try:
                esp_data = self.esp32.get_status()
                if esp_data and isinstance(esp_data, dict):
                    result.update(esp_data)
                    result["online"] = True
                    result["source"] = "esp32"
            except Exception as e:
                logger.warning(f"Помилка опитування ESP32: {e}")

        # 2. Доповнення/оновлення даними BLE датчиків, якщо доступні
        if self.bt_sensors:
            try:
                sensor_data = self.bt_sensors.get_latest_data()
                if sensor_data:
                    if "floors" not in result or not result["floors"]:
                        result["floors"] = {}
                    for k, v in sensor_data.items():
                        if k not in result["floors"] or not result["floors"][k].get("online"):
                            result["floors"][k] = v
            except Exception as e:
                logger.debug(f"Помилка отримання даних BluetoothSensorManager: {e}")

        # 3. Fallback до останніх записів у TelemetryDB, якщо показники температури відсутні
        if result.get("temperature") is None and self.telemetry_db:
            try:
                latest = self.telemetry_db.get_latest_by_floor()
                if latest:
                    if "floors" not in result:
                        result["floors"] = {}
                    for floor_key, rec in latest.items():
                        if floor_key not in result["floors"]:
                            result["floors"][floor_key] = rec
                    if "floor1" in latest and latest["floor1"].get("temperature") is not None:
                        result["temperature"] = latest["floor1"]["temperature"]
                        result["humidity"] = latest["floor1"].get("humidity")
            except Exception as e:
                logger.debug(f"Помилка читання TelemetryDB fallback: {e}")

        return result

    def trigger_door(self) -> bool:
        """Подати імпульс на реле відкриття/закриття гаражних воріт."""
        if not self.esp32:
            logger.error("ESP32 недоступний для команди trigger_door")
            return False
        try:
            return bool(self.esp32.trigger_door())
        except Exception as e:
            logger.error(f"Помилка виконання trigger_door: {e}")
            return False

    def set_light(self, state: bool, zone: str = "main") -> bool:
        """Керування освітленням (підтримка зони main через реле ESP32, або RF зон floor2/basement)."""
        zone_lower = (zone or "main").lower().strip()

        # Зони радіореле 433 МГц
        if zone_lower in ("floor2", "basement", "2nd_floor", "підвал", "2-й поверх"):
            target_zone = "floor2" if ("2" in zone_lower or "поверх" in zone_lower) else "basement"
            if self.esp32 and hasattr(self.esp32, "control_relay_zone"):
                return bool(self.esp32.control_relay_zone(target_zone, "on" if state else "off"))
            if self.esp32:
                cmd = f"LIGHT:{target_zone.upper()}:{'ON' if state else 'OFF'}"
                res = self.esp32.send_command(cmd)
                return bool(res and res.get("status") == "ok")
            return False

        # Основна зона (main relay на ESP32)
        if self.esp32:
            try:
                res = self.esp32.set_light(state)
                return bool(res)
            except Exception as e:
                logger.error(f"Помилка ввімкнення світла: {e}")
                return False

        return False

    def set_fan(self, state: bool) -> bool:
        """Керування витяжним вентилятором гаража."""
        if not self.esp32:
            return False
        try:
            return bool(self.esp32.set_fan(state))
        except Exception as e:
            logger.error(f"Помилка керування вентилятором: {e}")
            return False

    def send_rf_code(self, code: int, protocol: int = 1) -> bool:
        """Відправити довільний 24-бітний радіокод 433 МГц."""
        if self.esp32:
            if hasattr(self.esp32, "rf_transmit"):
                return bool(self.esp32.rf_transmit(code))
            res = self.esp32.send_command(f"RF_SEND:{code}")
            return bool(res and (res.get("status") == "ok" or "rf_sent" in res))
        return False

    def get_rf_diagnostics(self) -> dict[str, Any]:
        """Отримати діагностику радіотракту CC1101 (MARC стан, RSSI, версія чіпа)."""
        if self.esp32:
            try:
                diag = self.esp32.get_rf_diagnostics()
                if diag and isinstance(diag, dict):
                    return diag
            except Exception as e:
                logger.warning(f"Помилка отримання RF-діагностики: {e}")
        return {"status": "error", "error": "ESP32 CC1101 unavailable"}

    def scan_ble(self, duration: int = 15, only_new: bool = True) -> list[dict[str, Any]]:
        """Сканування BLE пристроїв у зоні гаража з фільтрацією прив'язаної інфраструктури."""
        if self.esp32:
            try:
                res = self.esp32.scan_ble(duration=duration)
                if isinstance(res, list):
                    return res
                if isinstance(res, dict) and "devices" in res:
                    return res["devices"]
            except Exception as e:
                logger.warning(f"Помилка сканування BLE через ESP32: {e}")
        return []

    def speaker_play(self, source: str, device: str = "jbl", title: str = "") -> bool:
        """Відтворення аудіо на вибраній колонці ('jbl' — гараж, 'jxbt' / 'floor1' — 1-й поверх)."""
        if not self.speaker:
            logger.error("Підсистема динаміків недоступна")
            return False
        try:
            dev_target = (device or "jbl").lower().strip()
            # Маршрутизація на конкретний пристрій або дефолтний
            if dev_target in ("jxbt", "jx-bt", "floor1", "1-й поверх"):
                return bool(self.speaker.play_on_speaker("floor1", source, track_title=title))
            return bool(self.speaker.play_file(source, track_title=title))
        except Exception as e:
            logger.error(f"Помилка відтворення аудіо: {e}")
            return False

    def speaker_stop(self, device: str | None = None) -> bool:
        """Зупинити відтворення на колонках."""
        if not self.speaker:
            return False
        try:
            return bool(self.speaker.stop())
        except Exception as e:
            logger.error(f"Помилка зупинки аудіо: {e}")
            return False

    def get_presence_status(self) -> dict[str, Any]:
        """Отримати поточний статус присутності власника, сім'ї та гостей."""
        if not self.presence:
            return {"status": "unavailable", "devices": {}}
        try:
            with self.presence._lock:
                return {
                    "status": "active",
                    "devices": dict(self.presence.devices),
                    "total_devices": len(self.presence.devices),
                }
        except Exception as e:
            logger.error(f"Помилка читання статусу присутності: {e}")
            return {"status": "error", "error": str(e), "devices": {}}

    def projector_control(self, action: str) -> bool:
        """Керування проєктором гаража (on, off, toggle, status)."""
        if not self.projector:
            return False
        try:
            act = action.lower().strip()
            if act == "on":
                return bool(self.projector.turn_on())
            elif act == "off":
                return bool(self.projector.turn_off())
            elif act == "toggle":
                return bool(self.projector.toggle())
            return False
        except Exception as e:
            logger.error(f"Помилка керування проєктором: {e}")
            return False
