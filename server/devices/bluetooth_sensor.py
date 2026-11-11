import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from bleak import BleakClient, BleakScanner
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False

from server.sensors.freshness import (
    SENSOR_FRESHNESS_THRESHOLD_SECONDS,
    SENSOR_POLL_INTERVAL_SECONDS,
    SOURCE_BLE_DIRECT,
    SOURCE_CACHE,
    SOURCE_ESP32_BRIDGE,
    SOURCE_NONE,
    SOURCE_SQLITE_HISTORY,
    STATUS_NEVER_SEEN,
    STATUS_NOT_INSTALLED,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_STALE,
    build_sensor_payload,
    format_iso_timestamp,
    format_relative_time_ua,
)
from server.storage.telemetry_db import TelemetryDB

logger = logging.getLogger(__name__)

CHAR_DATA_NOTIFY = "ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6"
CHAR_BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"


class BluetoothSensorManager:
    def _get_floor2_mac(self) -> str:
        try:
            from server.devices_config import get_sensor_config
            return (get_sensor_config("floor2").get("mac") or "").upper().strip()
        except Exception:
            return ""

    def _get_basement_mac(self) -> str:
        try:
            from server.devices_config import get_sensor_config
            return (get_sensor_config("basement").get("mac") or "").upper().strip()
        except Exception:
            return ""

    """Manages Bluetooth LE sensor devices (temperature, humidity, battery, etc.)."""

    @property
    def config_path(self) -> Path:
        if getattr(self, "_custom_config_path", None):
            return self._custom_config_path
        from server.utils.paths import get_devices_dir
        return get_devices_dir() / "bluetooth_devices.json"

    @config_path.setter
    def config_path(self, val):
        self._custom_config_path = Path(val) if val else None

    @property
    def cache_path(self) -> Path:
        return self.config_path.parent / "sensor_cache.json"

    @cache_path.setter
    def cache_path(self, val):
        pass

    def __init__(self, config_path: str | None = None, telemetry_db: TelemetryDB | None = None):
        self._custom_config_path = Path(config_path) if config_path else None
        self.telemetry_db = telemetry_db or TelemetryDB()
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None

        # Cached sensor states keyed by MAC address (uppercase)
        self.sensors: dict[str, dict[str, Any]] = {}
        self.primary_mac: str | None = None

        self._load_config()
        self._load_cache()

    def _load_config(self):
        """Load configured devices from bluetooth_devices.json."""
        if not self.config_path.exists():
            return

        try:
            with open(self.config_path, encoding="utf-8") as f:
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
                            "source": SOURCE_NONE,
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
                        elif not self.primary_mac and (floor_val == "floor2" or (self._get_floor2_mac() and mac == self._get_floor2_mac())):
                            self.primary_mac = mac
                        elif not self.primary_mac and (floor_val == "basement" or (self._get_basement_mac() and mac == self._get_basement_mac())):
                            self.primary_mac = mac

        except Exception as e:
            logger.error(f"Error loading bluetooth devices config: {e}")

    def _load_cache(self):
        """Load latest persistent sensor readings from cache file."""
        if not self.cache_path.exists():
            return
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            with self._lock:
                for mac, vals in cached.items():
                    mac_u = mac.upper().strip()
                    if mac_u in self.sensors:
                        last_ts = vals.get("last_updated")
                        is_fresh = bool(last_ts and (time.time() - last_ts < SENSOR_FRESHNESS_THRESHOLD_SECONDS))
                        self.sensors[mac_u]["online"] = is_fresh
                        self.sensors[mac_u]["source"] = SOURCE_CACHE
                        # Always preserve last known physical measurements from cache
                        for k in ("temperature", "humidity", "battery", "last_updated"):
                            v = vals.get(k)
                            if v is not None:
                                self.sensors[mac_u][k] = v
        except Exception as e:
            logger.error(f"Error loading sensor cache: {e}")

        # Fallback to SQLite TelemetryDB if any sensor is missing temperature
        if hasattr(self, "telemetry_db") and self.telemetry_db:
            try:
                latest_floors = self.telemetry_db.get_latest_by_floor()
                with self._lock:
                    for s in self.sensors.values():
                        f_key = s.get("floor")
                        if f_key in latest_floors and s.get("temperature") is None:
                            db_rec = latest_floors[f_key]
                            last_ts = db_rec.get("timestamp")
                            s["temperature"] = db_rec.get("temperature")
                            s["humidity"] = db_rec.get("humidity")
                            s["battery"] = db_rec.get("battery")
                            s["last_updated"] = last_ts
                            is_db_fresh = bool(last_ts and (time.time() - last_ts < SENSOR_FRESHNESS_THRESHOLD_SECONDS))
                            s["online"] = is_db_fresh
                            s["source"] = SOURCE_SQLITE_HISTORY
            except Exception as e:
                logger.error(f"Error falling back to telemetry DB in sensor manager: {e}")

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

    def start(self, interval_seconds: int = SENSOR_POLL_INTERVAL_SECONDS):
        """Initialize sensor manager with 30-minute background polling cycle."""
        self._load_config()
        self._load_cache()
        if not self._running:
            self._running = True
            self.poll_interval = interval_seconds
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="BluetoothSensorWorker")
            self._thread.start()
            logger.info(f"BluetoothSensorManager started with {interval_seconds}s (30 min) periodic cycle.")

    def stop(self):
        """Stop background worker if active."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("BluetoothSensorManager stopped.")

    def poll_on_demand(self, mac: str | None = None):
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
        """Worker loop polling sensors every 30 minutes."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        time.sleep(3)
        while self._running:
            try:
                self._load_config()
                loop.run_until_complete(self._poll_all_sensors())
            except Exception as e:
                logger.error(f"Error in Bluetooth sensor polling cycle: {e}")
            interval = getattr(self, "poll_interval", SENSOR_POLL_INTERVAL_SECONDS)
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
                if "LYWSD03MMC" in (s.get("name") or "").upper() or s.get("type") == "temperature_sensor" or (self._get_floor2_mac() and mac == self._get_floor2_mac())
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
        logger.debug(f"Attempting to read BLE sensor {mac}...")
        temp_found = None
        hum_found = None
        battery_found = None

        def handle_notification(sender, data: bytearray):
            nonlocal temp_found, hum_found
            if len(data) >= 3:
                temp_raw = int.from_bytes(data[0:2], byteorder="little", signed=True)
                temp_found = round(temp_raw / 100.0, 1)
                hum_found = int(data[2])

        client_target = mac
        connected = False

        # Attempt 1: Direct connection by MAC address (fastest and avoids BlueZ scanner conflicts)
        try:
            async with BleakClient(client_target, timeout=12.0) as client:
                if client.is_connected:
                    connected = True
                    try:
                        bat_raw = await client.read_gatt_char(CHAR_BATTERY)
                        if bat_raw:
                            battery_found = int(bat_raw[0])
                    except Exception:
                        pass

                    try:
                        raw_data = await client.read_gatt_char(CHAR_DATA_NOTIFY)
                        if raw_data and len(raw_data) >= 3:
                            temp_raw = int.from_bytes(raw_data[0:2], byteorder="little", signed=True)
                            temp_found = round(temp_raw / 100.0, 1)
                            hum_found = int(raw_data[2])
                    except Exception as e:
                        logger.debug(f"Direct read on {CHAR_DATA_NOTIFY} failed: {e}")

                    if temp_found is None or hum_found is None:
                        try:
                            await client.start_notify(CHAR_DATA_NOTIFY, handle_notification)
                            await asyncio.sleep(2.5)
                            await client.stop_notify(CHAR_DATA_NOTIFY)
                        except Exception as e:
                            logger.debug(f"Error subscribing to notify on {mac}: {e}")
        except Exception as e:
            logger.debug(f"Direct connection to {mac} failed ({e}), trying discovery scan...")

        # Attempt 2: Fallback to discovery scanner if direct connection was not successful
        if not connected or temp_found is None:
            try:
                device = await BleakScanner.find_device_by_address(mac, timeout=10.0)
                if device:
                    async with BleakClient(device, timeout=12.0) as client:
                        if client.is_connected:
                            try:
                                bat_raw = await client.read_gatt_char(CHAR_BATTERY)
                                if bat_raw:
                                    battery_found = int(bat_raw[0])
                            except Exception:
                                pass
                            try:
                                raw_data = await client.read_gatt_char(CHAR_DATA_NOTIFY)
                                if raw_data and len(raw_data) >= 3:
                                    temp_raw = int.from_bytes(raw_data[0:2], byteorder="little", signed=True)
                                    temp_found = round(temp_raw / 100.0, 1)
                                    hum_found = int(raw_data[2])
                            except Exception:
                                pass
                            if temp_found is None or hum_found is None:
                                try:
                                    await client.start_notify(CHAR_DATA_NOTIFY, handle_notification)
                                    await asyncio.sleep(2.5)
                                    await client.stop_notify(CHAR_DATA_NOTIFY)
                                except Exception:
                                    pass
            except Exception as e:
                logger.debug(f"Discovery fallback failed for {mac}: {e}")

        # Update cache if valid values obtained, otherwise mark offline after grace period
        updated = False
        with self._lock:
            if mac in self.sensors:
                s = self.sensors[mac]
                if temp_found is not None:
                    s["temperature"] = temp_found
                    if hum_found is not None:
                        s["humidity"] = hum_found
                    if battery_found is not None:
                        s["battery"] = battery_found
                    s["online"] = True
                    s["source"] = SOURCE_BLE_DIRECT
                    s["last_updated"] = time.time()
                    updated = True
                    logger.info(f"Updated BLE sensor {mac}: Temp={s['temperature']}°C, Hum={s.get('humidity')}%, Bat={s.get('battery')}%")
                elif battery_found is not None:
                    # Battery-only read does NOT update climate freshness and does not make climate sensor online
                    s["battery"] = battery_found
                    s["heartbeat_timestamp"] = time.time()
                else:
                    last = s.get("last_updated")
                    if not last or (time.time() - last > SENSOR_FRESHNESS_THRESHOLD_SECONDS):
                        s["online"] = False

        if updated and temp_found is not None:
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

    def get_telemetry(self) -> dict[str, Any]:
        """Return thread-safe snapshot of all sensor data, primary values, and floor climate."""
        now = time.time()
        with self._lock:
            device_list = list(self.sensors.values())

            # Map configured devices by floor
            floor_sensor_map: dict[str, dict[str, Any]] = {}
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
                if f_key:
                    floor_sensor_map[f_key] = s

            # Build standardized floor payloads conforming to freshness and truth contract
            floors = {}
            default_floor_names = {
                "floor1": "1-й поверх (Гараж)",
                "floor2": "2-й поверх",
                "basement": "Підвал"
            }

            for f_key in ("floor1", "floor2", "basement"):
                s = floor_sensor_map.get(f_key)
                if s and s.get("mac"):
                    floors[f_key] = build_sensor_payload(
                        floor=f_key,
                        name=s.get("alias") or s.get("name") or default_floor_names[f_key],
                        mac=s.get("mac"),
                        temperature=s.get("temperature"),
                        humidity=s.get("humidity"),
                        battery=s.get("battery"),
                        last_updated=s.get("last_updated"),
                        is_online_reported=bool(s.get("online", False)),
                        source=s.get("source") or SOURCE_BLE_DIRECT,
                        installed=True,
                        now=now
                    )
                else:
                    floors[f_key] = build_sensor_payload(
                        floor=f_key,
                        name=default_floor_names[f_key],
                        mac=None,
                        temperature=None,
                        humidity=None,
                        battery=None,
                        last_updated=None,
                        is_online_reported=False,
                        source=SOURCE_NONE,
                        installed=False,
                        now=now
                    )

            # Primary sensor resolution:
            # 1. Prefer online & fresh sensor with temperature
            # 2. If none is online, fallback to sensor with freshest last_updated
            primary_floor = None
            for fk in ("basement", "floor2", "floor1"):
                if floors[fk]["online"] and floors[fk]["current_temperature"] is not None:
                    primary_floor = floors[fk]
                    break

            if not primary_floor:
                candidates = [f for f in floors.values() if f.get("last_known_temperature") is not None]
                if candidates:
                    candidates.sort(key=lambda x: x.get("last_updated") or 0, reverse=True)
                    primary_floor = candidates[0]

            primary_temp = primary_floor["current_temperature"] if primary_floor else None
            primary_last_known = primary_floor["last_known_temperature"] if primary_floor else None
            primary_hum = primary_floor["current_humidity"] if primary_floor else None
            primary_name = primary_floor["name"] if primary_floor else "1-й поверх"
            primary_online = primary_floor["online"] if primary_floor else False
            primary_status = primary_floor["status"] if primary_floor else STATUS_NOT_INSTALLED
            primary_source = primary_floor["source"] if primary_floor else SOURCE_NONE
            primary_lu = primary_floor.get("last_updated") if primary_floor else None
            primary_lu_iso = primary_floor.get("last_updated_iso") if primary_floor else None

            return {
                "devices": [dict(d) for d in device_list],
                "floors": floors,
                "primary_mac": primary_floor.get("mac") if primary_floor else self.primary_mac,
                "primary_temperature": primary_temp,  # None if offline/stale
                "primary_current_temperature": primary_temp,
                "primary_last_known_temperature": primary_last_known,
                "primary_humidity": primary_hum,
                "primary_battery": primary_floor.get("battery") if primary_floor else None,
                "primary_name": primary_name,
                "primary_online": primary_online,
                "primary_status": primary_status,
                "primary_source": primary_source,
                "primary_last_updated": primary_lu,
                "primary_last_updated_iso": primary_lu_iso
            }

    def bind_sensor(self, floor_key: str, new_mac: str, alias: str | None = None) -> bool:
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
                with open(self.config_path, encoding="utf-8") as f:
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
