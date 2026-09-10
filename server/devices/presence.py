import json
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    from server.logger.logger import Logger
except ImportError:
    import logging
    Logger = logging.getLogger


class PresenceManager:
    """Manages presence detection, device registry, and visitor access logs.
    Supports tracking owners, family members, and guests via Bluetooth LE (RPA / Service UUIDs)
    and Classic Bluetooth (static MAC addresses).
    """

    def __init__(self, data_dir: Optional[Path] = None, logger=None):
        self.logger = logger or Logger()
        base_dir = data_dir or (Path(__file__).resolve().parent.parent.parent / "devices")
        self.devices_path = base_dir / "presence_devices.json"
        self.log_path = base_dir / "presence_log.json"
        self._lock = threading.RLock()

        self.devices: Dict[str, Dict[str, Any]] = {}
        self.log: List[Dict[str, Any]] = []

        # Away timeout in seconds (15 minutes of inactivity before marking as away)
        self.away_timeout = 900
        self._last_active_check = 0.0

        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self.event_callback = None

        self._load_data()
        self._ensure_defaults()

    def set_event_callback(self, cb):
        self.event_callback = cb

    def _load_data(self):
        """Load registered devices and presence logs from disk."""
        if self.devices_path.exists():
            try:
                with open(self.devices_path, "r", encoding="utf-8") as f:
                    self.devices = json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading presence_devices.json: {e}")

        if self.log_path.exists():
            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    self.log = json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading presence_log.json: {e}")

    def _save_devices(self):
        """Save registered devices to disk."""
        try:
            self.devices_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.devices_path, "w", encoding="utf-8") as f:
                json.dump(self.devices, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving presence_devices.json: {e}")

    def _save_log(self):
        """Save presence log to disk (retaining latest 500 events)."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            trimmed = self.log[-500:]
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(trimmed, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving presence_log.json: {e}")

    def _ensure_defaults(self):
        """Initialize owner's phone and watch if not registered yet."""
        with self._lock:
            changed = False
            now = time.time()

            # 1. Owner's Smartphone (Motorola Edge 50 Pro)
            if "owner_phone" not in self.devices:
                self.devices["owner_phone"] = {
                    "id": "owner_phone",
                    "name": "Юрій (Власник)",
                    "role": "owner",
                    "device_type": "phone",
                    "device_name": "Motorola Edge 50 Pro",
                    "classic_mac": "B8:7E:39:88:22:9B",
                    "ble_services": ["3e1d50cd-7e3e-427d-8e1c-b78aa87fe624"],
                    "recent_ble_rpa": ["62:FD:D0:F6:F2:CF"],
                    "status": "present",
                    "last_seen": now,
                    "last_rssi": -47,
                    "proximity": "immediate",
                    "auto_welcome": True
                }
                changed = True

            # 2. Owner's Smartwatch
            if "owner_watch" not in self.devices:
                self.devices["owner_watch"] = {
                    "id": "owner_watch",
                    "name": "Юрій (Смарт-годинник)",
                    "role": "owner",
                    "device_type": "watch",
                    "device_name": "Смарт-годинник",
                    "classic_mac": "",
                    "ble_services": [],
                    "recent_ble_rpa": ["5C:56:EB:EC:CE:AB"],
                    "status": "present",
                    "last_seen": now,
                    "last_rssi": -80,
                    "proximity": "near",
                    "auto_welcome": False
                }
                changed = True

            if changed:
                self._save_devices()
                if not self.log:
                    self._add_log_entry(
                        event="ARRIVED",
                        device_id="owner_phone",
                        person_name="Юрій (Власник)",
                        device_name="Motorola Edge 50 Pro",
                        rssi=-47,
                        source="esp32_ble",
                        note="Початкова фіксація присутності біля гаража"
                    )

    def _proximity_from_rssi(self, rssi: Optional[int]) -> str:
        if rssi is None:
            return "unknown"
        if rssi >= -60:
            return "immediate"  # < 2 meters (right next to garage)
        elif rssi >= -75:
            return "near"       # 2 - 6 meters
        else:
            return "approaching" # > 6 meters (approaching garage)

    def _add_log_entry(self, event: str, device_id: str, person_name: str,
                       device_name: str, rssi: Optional[int], source: str = "esp32_ble",
                       note: str = ""):
        now = time.time()
        dt = datetime.fromtimestamp(now)
        entry = {
            "timestamp": now,
            "formatted_time": dt.strftime("%H:%M:%S (%d.%m.%Y)"),
            "event": event,  # ARRIVED | DEPARTED | SIGHTING
            "device_id": device_id,
            "person_name": person_name,
            "device_name": device_name,
            "rssi": rssi,
            "proximity": self._proximity_from_rssi(rssi),
            "source": source,
            "note": note
        }
        self.log.append(entry)
        self._save_log()
        self.logger.info(f"📍 [PRESENCE] {event}: {person_name} ({device_name}) | RSSI={rssi}dBm | {source}")

        if self.event_callback and callable(self.event_callback):
            try:
                self.event_callback(entry)
            except Exception as e:
                self.logger.error(f"Error in presence event callback: {e}")

    def record_sighting(self, mac: str, name: str = "", rssi: Optional[int] = None,
                        service_uuids: Optional[List[str]] = None, source: str = "esp32_ble") -> Optional[Dict[str, Any]]:
        """Process a sighted Bluetooth device from ESP32 or server scan and match against registry."""
        mac_upper = mac.upper().strip()
        matched_device_id = None

        with self._lock:
            # 1. Match by static Classic MAC
            for dev_id, dev in self.devices.items():
                if dev.get("classic_mac") and dev["classic_mac"].upper() == mac_upper:
                    matched_device_id = dev_id
                    break

            # 2. Match by registered MAC / RPA
            if not matched_device_id:
                for dev_id, dev in self.devices.items():
                    if mac_upper in [r.upper() for r in dev.get("recent_ble_rpa", [])]:
                        matched_device_id = dev_id
                        break

            # 4. Match by Device Name if explicitly broadcasted
            if not matched_device_id and name:
                for dev_id, dev in self.devices.items():
                    if dev.get("device_name") and dev["device_name"].lower() == name.lower():
                        matched_device_id = dev_id
                        break

            if matched_device_id:
                dev = self.devices[matched_device_id]
                was_present = (dev.get("status") == "present")
                now = time.time()

                dev["last_seen"] = now
                dev["last_rssi"] = rssi
                dev["proximity"] = self._proximity_from_rssi(rssi)
                dev["status"] = "present"

                # Update recent RPA list
                rpa_list = dev.setdefault("recent_ble_rpa", [])
                if mac_upper not in rpa_list:
                    rpa_list.append(mac_upper)
                    if len(rpa_list) > 10:
                        rpa_list.pop(0)

                if not was_present:
                    self._add_log_entry(
                        event="ARRIVED",
                        device_id=matched_device_id,
                        person_name=dev.get("name", "Невідомий"),
                        device_name=dev.get("device_name", ""),
                        rssi=rssi,
                        source=source,
                        note="Пристрій з'явився в радіусі гаража"
                    )

                self._save_devices()
                return dev

            return None

    def check_departures(self):
        """Periodic check for devices that have not been seen within away_timeout."""
        now = time.time()
        with self._lock:
            for dev_id, dev in self.devices.items():
                if dev.get("status") == "present":
                    last_seen = dev.get("last_seen", 0)
                    if now - last_seen > self.away_timeout:
                        dev["status"] = "away"
                        self._add_log_entry(
                            event="DEPARTED",
                            device_id=dev_id,
                            person_name=dev.get("name", "Невідомий"),
                            device_name=dev.get("device_name", ""),
                            rssi=None,
                            source="system_timeout",
                            note=f"Не спостерігався понад {int(self.away_timeout / 60)} хв"
                        )
                        self._save_devices()

    def register_device(self, device_id: str, name: str, role: str = "guest",
                        device_type: str = "phone", device_name: str = "",
                        classic_mac: str = "", ble_mac: str = "",
                        ble_services: Optional[List[str]] = None,
                        auto_welcome: bool = False) -> Dict[str, Any]:
        """Register a new device / guest entity."""
        with self._lock:
            clean_id = device_id.lower().replace(" ", "_").strip()
            item = {
                "id": clean_id,
                "name": name,
                "role": role,
                "device_type": device_type,
                "device_name": device_name or name,
                "classic_mac": classic_mac.upper().strip(),
                "ble_services": ble_services or [],
                "recent_ble_rpa": [ble_mac.upper().strip()] if ble_mac else [],
                "status": "present" if ble_mac else "away",
                "last_seen": time.time() if ble_mac else None,
                "last_rssi": None,
                "proximity": "unknown",
                "auto_welcome": auto_welcome
            }
            self.devices[clean_id] = item
            self._save_devices()

            if ble_mac:
                self._add_log_entry(
                    event="REGISTERED",
                    device_id=clean_id,
                    person_name=name,
                    device_name=item["device_name"],
                    rssi=None,
                    source="manual",
                    note="Пристрій додано до реєстру"
                )

            return item

    def remove_device(self, device_id: str) -> bool:
        """Remove a registered device from registry."""
        with self._lock:
            if device_id in self.devices:
                del self.devices[device_id]
                self._save_devices()
                return True
            return False

    def _check_classic_mac(self, mac: str) -> Optional[str]:
        """Check if device is responding to Classic Bluetooth inquiry/name request."""
        if not mac:
            return None
        clean_mac = mac.strip().upper()
        try:
            res = subprocess.run(
                ["hcitool", "name", clean_mac],
                capture_output=True,
                text=True,
                timeout=4.0
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception as e:
            self.logger.debug(f"Classic BT check error for {mac}: {e}")
        return None

    def poll_active_presence(self, force: bool = False):
        """Actively query registered devices with Classic Bluetooth MAC."""
        now = time.time()
        if not force and (now - self._last_active_check < 25.0):
            return
        self._last_active_check = now

        with self._lock:
            devices_to_check = [
                (dev_id, dev.get("classic_mac", ""))
                for dev_id, dev in self.devices.items()
                if dev.get("classic_mac")
            ]

        for dev_id, mac in devices_to_check:
            name_resp = self._check_classic_mac(mac)
            if name_resp:
                self.record_sighting(
                    mac=mac,
                    name=name_resp,
                    rssi=-50,
                    source="bluetooth_classic"
                )
                # If owner's phone is present, update owner's watch state as well
                if dev_id == "owner_phone":
                    with self._lock:
                        if "owner_watch" in self.devices:
                            watch = self.devices["owner_watch"]
                            was_away = (watch.get("status") != "present")
                            watch["status"] = "present"
                            watch["last_seen"] = time.time()
                            watch["proximity"] = "near"
                            if was_away:
                                self._add_log_entry(
                                    event="ARRIVED",
                                    device_id="owner_watch",
                                    person_name=watch.get("name", "Юрій (Смарт-годинник)"),
                                    device_name=watch.get("device_name", "Смарт-годинник"),
                                    rssi=-70,
                                    source="paired_with_owner",
                                    note="Підтверджено присутність разом із телефоном"
                                )
                            self._save_devices()

    def start(self):
        """Start background presence checking thread."""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="PresenceWorker")
        self._worker_thread.start()
        self.logger.info("📡 [PRESENCE] Background monitoring worker started.")

    def stop(self):
        """Stop background presence checking thread."""
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)

    def _worker_loop(self):
        """Background loop checking presence every 45 seconds."""
        time.sleep(2)
        while self._running:
            try:
                self.poll_active_presence(force=True)
                self.check_departures()
            except Exception as e:
                self.logger.error(f"Error in presence worker loop: {e}")

            for _ in range(45):
                if not self._running:
                    break
                time.sleep(1)

    def get_status(self) -> Dict[str, Any]:
        """Get summary of presence status: who is present right now and list of all known entities."""
        with self._lock:
            owner_away = self.devices.get("owner_phone", {}).get("status") != "present"

        # If owner is marked away or last probe was >30s ago, do an active inquiry immediately
        if owner_away or (time.time() - self._last_active_check > 30.0):
            self.poll_active_presence(force=True)

        self.check_departures()
        with self._lock:
            present_entities = [d for d in self.devices.values() if d.get("status") == "present"]
            away_entities = [d for d in self.devices.values() if d.get("status") != "present"]
            return {
                "total_registered": len(self.devices),
                "present_count": len(present_entities),
                "present_now": present_entities,
                "away_now": away_entities,
                "devices": self.devices,
                "recent_log": self.log[-20:]
            }

    def get_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent visitor and presence log entries."""
        with self._lock:
            return list(reversed(self.log[-limit:]))
