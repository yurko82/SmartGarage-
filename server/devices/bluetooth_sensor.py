import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from bleak import BleakScanner, BleakClient
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False

from server.storage.telemetry_db import TelemetryDB

logger = logging.getLogger(__name__)

CHAR_DATA_NOTIFY = "ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6"
CHAR_BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"


class BluetoothSensorManager:
    """Manages Bluetooth LE sensor devices (temperature, humidity, battery, etc.)."""

    def __init__(self, config_path: Optional[str] = None, telemetry_db: Optional[TelemetryDB] = None):
        if config_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            self.config_path = base_dir / "devices" / "bluetooth_devices.json"
        else:
            self.config_path = Path(config_path)

        self.telemetry_db = telemetry_db or TelemetryDB()
        self.cache_path = self.config_path.parent / "sensor_cache.json"
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Cached sensor states keyed by MAC address (uppercase)
        self.sensors: Dict[str, Dict[str, Any]] = {}
        self.primary_mac: Optional[str] = None

        self._load_config()
        self._load_cache()

    def _load_config(self):
        """Load configured devices from bluetooth_devices.json."""
        if not self.config_path.exists():
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            with self._lock:
                for mac_raw, info in data.items():
                    mac = mac_raw.upper().strip()
                    floor_val = info.get("floor", "")
                    if not floor_val:
                        alias_lower = (info.get("alias") or "").lower()
                        if "підвал" in alias_lower or "basement" in alias_lower:
                            floor_val = "basement"
                        elif "1" in alias_lower or "перш" in alias_lower:
                            floor_val = "floor1"
                        elif "2" in alias_lower or "друг" in alias_lower:
                            floor_val = "floor2"

                    if mac not in self.sensors:
                        self.sensors[mac] = {
                            "mac": mac,
                            "name": info.get("name", "Unknown"),
                            "alias": info.get("alias", ""),
                            "floor": floor_val,
                            "in_garage": info.get("in_garage", True),
                            "temperature": None,
                            "humidity": None,
                            "battery": None,
                            "rssi": None,
                            "online": False,
                            "last_updated": None,
                            "type": info.get("type", "temperature_sensor")
                        }
                    else:
                        self.sensors[mac]["name"] = info.get("name", self.sensors[mac]["name"])
                        self.sensors[mac]["alias"] = info.get("alias", self.sensors[mac]["alias"])
                        self.sensors[mac]["floor"] = floor_val or self.sensors[mac].get("floor", "")
                        self.sensors[mac]["in_garage"] = info.get("in_garage", self.sensors[mac]["in_garage"])
                        if "type" in info:
                            self.sensors[mac]["type"] = info["type"]

                    # Set primary sensor (prefer real temperature sensor on 1st floor, fallback to 2nd floor or basement)
                    if info.get("type") != "speaker":
                        if floor_val == "floor1" and "00:00:01" not in mac:
                            self.primary_mac = mac
                        elif not self.primary_mac and (floor_val == "floor2" or mac == "A4:C1:38:EC:EC:6C"):
                            self.primary_mac = mac
                        elif not self.primary_mac and (floor_val == "basement" or mac == "A4:C1:38:CC:CA:49"):
                            self.primary_mac = mac

        except Exception as e:
            logger.error(f"Error loading bluetooth devices config: {e}")

    def _load_cache(self):
        """Load latest persistent sensor readings from cache file."""
        if not self.cache_path.exists():
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            with self._lock:
                for mac, vals in cached.items():
                    mac_u = mac.upper().strip()
                    if mac_u in self.sensors:
                        for k, v in vals.items():
                            if v is not None:
                                self.sensors[mac_u][k] = v
        except Exception as e:
            logger.error(f"Error loading sensor cache: {e}")

    def _save_cache(self):
        """Save latest persistent sensor readings to cache file."""
        try:
            data = {}
            with self._lock:
                for mac, s in self.sensors.items():
                    data[mac] = {
                        "temperature": s.get("temperature"),
                        "humidity": s.get("humidity"),
                        "battery": s.get("battery"),
                        "online": s.get("online"),
                        "last_updated": s.get("last_updated")
                    }
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving sensor cache: {e}")

    def start(self, interval_seconds: int = 900):
        """Initialize sensor manager with 15-minute background polling cycle."""
        self._load_config()
        self._load_cache()
        if not self._running:
            self._running = True
            self.poll_interval = interval_seconds
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="BluetoothSensorWorker")
            self._thread.start()
            logger.info(f"BluetoothSensorManager started with {interval_seconds}s (15 min) periodic cycle.")

    def stop(self):
        """Stop background worker if active."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("BluetoothSensorManager stopped.")

    def poll_on_demand(self, mac: Optional[str] = None):
        """Trigger an on-demand background poll of sensors without blocking the caller."""
        if not BLEAK_AVAILABLE:
            return

        def _run_poll():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self._load_config()
                if mac:
                    loop.run_until_complete(self._read_sensor_data(mac))
                else:
                    loop.run_until_complete(self._poll_all_sensors())
            except Exception as e:
                logger.error(f"Error during on-demand sensor poll: {e}")
            finally:
                loop.close()

        t = threading.Thread(target=_run_poll, daemon=True, name="SensorOnDemandPoll")
        t.start()
        return t

    def _worker_loop(self):
        """Worker loop polling sensors every 15 minutes."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        time.sleep(3)
        while self._running:
            try:
                self._load_config()
                loop.run_until_complete(self._poll_all_sensors())
            except Exception as e:
                logger.error(f"Error in Bluetooth sensor polling cycle: {e}")
            interval = getattr(self, "poll_interval", 900)
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)
        loop.close()

    async def _poll_all_sensors(self):
        """Poll all recognized temperature sensors."""
        with self._lock:
            macs_to_poll = [
                mac for mac, s in self.sensors.items()
                if "LYWSD03MMC" in (s.get("name") or "").upper() or s.get("type") == "temperature_sensor" or mac == "A4:C1:38:EC:EC:6C"
            ]

        for mac in macs_to_poll:
            if not self._running:
                break
            try:
                await self._read_sensor_data(mac)
            except Exception as e:
                logger.warning(f"Failed to read BLE sensor {mac}: {e}")

    async def _read_sensor_data(self, mac: str):
        """Connect to sensor and retrieve temperature, humidity, and battery."""
        logger.debug(f"Scanning for BLE sensor {mac}...")
        device = await BleakScanner.find_device_by_address(mac, timeout=25.0)
        if not device:
            logger.debug(f"Sensor {mac} not found in 25s discovery window.")
            with self._lock:
                if mac in self.sensors:
                    last = self.sensors[mac].get("last_updated")
                    if last and (time.time() - last > 300):
                        self.sensors[mac]["online"] = False
            return

        temp_found = None
        hum_found = None
        battery_found = None

        def handle_notification(sender, data: bytearray):
            nonlocal temp_found, hum_found
            if len(data) >= 3:
                temp_raw = int.from_bytes(data[0:2], byteorder="little", signed=True)
                temp_found = round(temp_raw / 100.0, 1)
                hum_found = int(data[2])

        try:
            async with BleakClient(device, timeout=20.0) as client:
                if client.is_connected:
                    # 1. Battery
                    try:
                        bat_raw = await client.read_gatt_char(CHAR_BATTERY)
                        if bat_raw:
                            battery_found = int(bat_raw[0])
                    except Exception:
                        pass

                    # 2. Temperature & Humidity (Direct Read)
                    try:
                        raw_data = await client.read_gatt_char(CHAR_DATA_NOTIFY)
                        if raw_data and len(raw_data) >= 3:
                            temp_raw = int.from_bytes(raw_data[0:2], byteorder="little", signed=True)
                            temp_found = round(temp_raw / 100.0, 1)
                            hum_found = int(raw_data[2])
                    except Exception as e:
                        logger.debug(f"Direct read on {CHAR_DATA_NOTIFY} failed: {e}")

                    # Fallback to notifications if direct read failed
                    if temp_found is None or hum_found is None:
                        try:
                            await client.start_notify(CHAR_DATA_NOTIFY, handle_notification)
                            await asyncio.sleep(3.0)
                            await client.stop_notify(CHAR_DATA_NOTIFY)
                        except Exception as e:
                            logger.debug(f"Error subscribing to notify on {mac}: {e}")

            # Update cache if valid values obtained
            updated = False
            with self._lock:
                if mac in self.sensors:
                    s = self.sensors[mac]
                    if temp_found is not None:
                        s["temperature"] = temp_found
                        updated = True
                    if hum_found is not None:
                        s["humidity"] = hum_found
                        updated = True
                    if battery_found is not None:
                        s["battery"] = battery_found
                        updated = True
                    if temp_found is not None or battery_found is not None:
                        s["online"] = True
                        s["last_updated"] = time.time()
                        logger.info(f"Updated BLE sensor {mac}: Temp={s['temperature']}°C, Hum={s['humidity']}%, Bat={s['battery']}%")

            if updated:
                self._save_cache()
                if hasattr(self, "telemetry_db") and self.telemetry_db:
                    try:
                        f_k = self.sensors.get(mac, {}).get("floor") or "garage"
                        name_s = self.sensors.get(mac, {}).get("alias") or self.sensors.get(mac, {}).get("name")
                        self.telemetry_db.record(
                            floor=f_k,
                            temperature=temp_found,
                            humidity=hum_found,
                            battery=battery_found,
                            mac=mac,
                            sensor_name=name_s
                        )
                    except Exception as edb:
                        logger.debug(f"TelemetryDB recording error for {mac}: {edb}")

        except Exception as e:
            logger.debug(f"Exception connecting to sensor {mac}: {e}")

    def get_telemetry(self) -> Dict[str, Any]:
        """Return thread-safe snapshot of all sensor data, primary values, and floor climate."""
        with self._lock:
            device_list = list(self.sensors.values())
            primary = None

            # Floor dictionary
            floors = {
                "floor1": {"name": "1-й поверх", "floor": "floor1", "temperature": None, "humidity": None, "battery": None, "online": False, "mac": None},
                "floor2": {"name": "2-й поверх", "floor": "floor2", "temperature": None, "humidity": None, "battery": None, "online": False, "mac": None},
                "basement": {"name": "Підвал", "floor": "basement", "temperature": None, "humidity": None, "battery": None, "online": False, "mac": None}
            }

            for s in device_list:
                if s.get("type") == "speaker":
                    continue
                f_key = s.get("floor")
                if not f_key:
                    alias_lower = (s.get("alias") or "").lower()
                    if "підвал" in alias_lower or "basement" in alias_lower:
                        f_key = "basement"
                    elif "1" in alias_lower or "перш" in alias_lower:
                        f_key = "floor1"
                    elif "2" in alias_lower or "друг" in alias_lower:
                        f_key = "floor2"

                if f_key in floors:
                    is_online = bool(s.get("online", False))
                    floors[f_key] = {
                        "name": s.get("alias") or floors[f_key]["name"],
                        "floor": f_key,
                        "temperature": s.get("temperature"),
                        "humidity": s.get("humidity"),
                        "battery": s.get("battery"),
                        "online": is_online,
                        "mac": s.get("mac"),
                        "last_updated": s.get("last_updated")
                    }

            # Primary sensor resolution
            if self.primary_mac and self.primary_mac in self.sensors:
                primary = self.sensors[self.primary_mac]
            elif floors["floor1"]["temperature"] is not None:
                primary = floors["floor1"]
            elif floors["floor2"]["temperature"] is not None:
                primary = floors["floor2"]
            elif device_list:
                for s in device_list:
                    if s.get("temperature") is not None:
                        primary = s
                        break
                if not primary and device_list:
                    primary = device_list[0]

            return {
                "devices": [dict(d) for d in device_list],
                "floors": floors,
                "primary_mac": self.primary_mac,
                "primary_temperature": primary.get("temperature") if primary else None,
                "primary_humidity": primary.get("humidity") if primary else None,
                "primary_battery": primary.get("battery") if primary else None,
                "primary_name": (primary.get("alias") or primary.get("name")) if primary else "1-й поверх",
                "primary_online": primary.get("online", False) if primary else False,
            }

    def bind_sensor(self, floor_key: str, new_mac: str, alias: Optional[str] = None) -> bool:
        """Bind or update the MAC address of a floor sensor."""
        floor_key = floor_key.lower().strip()
        if floor_key in ("1", "first", "floor_1", "1-й поверх", "перший поверх"):
            floor_key = "floor1"
        elif floor_key in ("2", "second", "floor_2", "2-й поверх", "другий поверх"):
            floor_key = "floor2"
        elif floor_key in ("0", "basement", "підвал", "цоколь"):
            floor_key = "basement"

        new_mac_clean = new_mac.upper().strip()
        default_names = {
            "floor1": "1-й поверх",
            "floor2": "2-й поверх",
            "basement": "Підвал"
        }
        sensor_alias = alias or default_names.get(floor_key, floor_key)

        try:
            # Read existing config
            cfg_data = {}
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)

            # Remove old placeholder for this floor if MAC changed
            to_remove = []
            for mac, info in cfg_data.items():
                if info.get("floor") == floor_key and mac != new_mac_clean:
                    to_remove.append(mac)
            for m in to_remove:
                del cfg_data[m]

            cfg_data[new_mac_clean] = {
                "name": "LYWSD03MMC",
                "in_garage": (floor_key != "floor2"),
                "alias": sensor_alias,
                "floor": floor_key,
                "type": "temperature_sensor"
            }

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg_data, f, indent=4)

            self._load_config()
            return True
        except Exception as e:
            logger.error(f"Failed to bind sensor MAC {new_mac_clean} to floor {floor_key}: {e}")
            return False
