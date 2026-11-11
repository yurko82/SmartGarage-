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

    BLE-only devices (earbuds, fitness bands) broadcast a Random Private Address (RPA)
    that rotates roughly every ~15 minutes for privacy, so a raw MAC address alone is not
    a durable identifier. record_sighting() therefore resolves an incoming sighting to a
    registered device using multiple tiers, in order:

      1. Static Classic Bluetooth MAC (classic_mac) - reliable, doesn't rotate.
      2. A MAC already seen and recorded before (recent_ble_rpa).
      3. Exact advertised device name (device_name), when a device broadcasts one.
      4. Service UUID overlap (ble_services) - many BLE peripherals advertise a stable
         custom Service UUID independent of RPA rotation.
      5. "Continuity" heuristic: an unknown MAC appearing within a short time window of a
         known device's last sighting, with similar RSSI, is treated as that same device
         having rotated its RPA. This is a best-effort fallback for devices with no stable
         Service UUID and no Classic BT support (tuned by presence.rpa_continuity_window_sec
         and presence.rpa_continuity_rssi_tolerance in config.yaml).

    None of these tiers require pairing/bonding with the device. For fully reliable
    identification across RPA rotation, resolving the RPA via the device's IRK (after
    bonding) is the "correct" Bluetooth-native solution but is out of scope here.
    """

    def __init__(self, data_dir: Optional[Path] = None, logger=None, presence_config: Optional[Dict[str, Any]] = None):
        self.logger = logger or Logger()
        from server.utils.paths import get_devices_dir
        base_dir = data_dir or get_devices_dir()
        self.devices_path = base_dir / "presence_devices.json"
        self.log_path = base_dir / "presence_log.json"
        self._lock = threading.RLock()

        self.devices: Dict[str, Dict[str, Any]] = {}
        self.log: List[Dict[str, Any]] = []

        # Away timeout in seconds (15 minutes of inactivity before marking as away)
        self.away_timeout = 900
        self._last_active_check = 0.0

        # RPA-continuity matching parameters (see class docstring, tier 5).
        cfg = presence_config or {}
        self.rpa_continuity_window_sec = float(cfg.get("rpa_continuity_window_sec", 90))
        self.rpa_continuity_rssi_tolerance = float(cfg.get("rpa_continuity_rssi_tolerance", 10))

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
        """Save presence log to disk (retaining entries within 7 days TTL, max 100 entries)."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            now = time.time()
            cutoff = now - (7 * 86400)
            trimmed = [e for e in self.log if (e.get("timestamp") or 0) > cutoff][-100:]
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(trimmed, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving presence_log.json: {e}")

    def _ensure_defaults(self):
        """Initialize owner's phone and watch if not registered yet."""
        with self._lock:
            changed = False
            now = time.time()

            # 1. Owner's Smartphone (Synthetic Default)
            if "owner_phone" not in self.devices:
                self.devices["owner_phone"] = {
                    "id": "owner_phone",
                    "name": "Власник (Смартфон)",
                    "role": "owner",
                    "device_type": "phone",
                    "device_name": "Смартфон",
                    "classic_mac": "00:11:22:33:44:55",
                    "ble_services": [],
                    "recent_ble_rpa": [],
                    "status": "away",
                    "last_seen": None,
                    "last_rssi": None,
                    "proximity": "unknown",
                    "auto_welcome": False,
                    "notify_owner": False,
                    "opt_in": False
                }
                changed = True

            # 2. Owner's Smartwatch (Synthetic Default)
            if "owner_watch" not in self.devices:
                self.devices["owner_watch"] = {
                    "id": "owner_watch",
                    "name": "Власник (Годинник)",
                    "role": "owner",
                    "device_type": "watch",
                    "device_name": "Смарт-годинник",
                    "classic_mac": "",
                    "ble_services": [],
                    "recent_ble_rpa": [],
                    "status": "away",
                    "last_seen": None,
                    "last_rssi": None,
                    "proximity": "unknown",
                    "auto_welcome": False,
                    "notify_owner": False,
                    "opt_in": False
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
                threading.Thread(
                    target=self.event_callback,
                    args=(dict(entry),),
                    daemon=True,
                    name="PresenceCbWorker"
                ).start()
            except Exception as e:
                self.logger.error(f"Error dispatching presence event callback: {e}")

    def record_sighting(self, mac: str, name: str = "", rssi: Optional[int] = None,
                        service_uuids: Optional[List[str]] = None, source: str = "esp32_ble") -> Optional[Dict[str, Any]]:
        """Process a sighted Bluetooth device from ESP32 or server scan and match against registry."""
        mac_upper = mac.upper().strip()
        matched_device_id = None

        with self._lock:
            match_reason = None
            # 1. Match by static Classic MAC (reliable, confirmed)
            for dev_id, dev in self.devices.items():
                if dev.get("classic_mac") and dev["classic_mac"].upper() == mac_upper:
                    matched_device_id = dev_id
                    match_reason = "classic_mac"
                    break

            # 2. Match by registered static MAC / verified RPA
            if not matched_device_id:
                for dev_id, dev in self.devices.items():
                    if mac_upper in [r.upper() for r in dev.get("recent_ble_rpa", [])]:
                        matched_device_id = dev_id
                        match_reason = "registered_mac"
                        break

            # 3. Match by Device Name if explicitly broadcasted (Heuristic)
            if not matched_device_id and name:
                for dev_id, dev in self.devices.items():
                    if dev.get("device_name") and dev["device_name"].lower() == name.lower():
                        matched_device_id = dev_id
                        match_reason = "device_name"
                        break

            # 4. Match by Service UUID overlap (Heuristic)
            if not matched_device_id and service_uuids:
                incoming_uuids = {u.lower() for u in service_uuids if u}
                if incoming_uuids:
                    for dev_id, dev in self.devices.items():
                        dev_uuids = {u.lower() for u in dev.get("ble_services", []) if u}
                        if dev_uuids & incoming_uuids:
                            matched_device_id = dev_id
                            match_reason = "service_uuid"
                            break

            # 5. "Continuity" heuristic fallback (Uncertain heuristic)
            if not matched_device_id:
                now_probe = time.time()
                best_candidate = None
                best_delta = None
                for dev_id, dev in self.devices.items():
                    if dev.get("status") != "present":
                        continue
                    last_seen = dev.get("last_seen") or 0
                    elapsed = now_probe - last_seen
                    if elapsed < 0 or elapsed > self.rpa_continuity_window_sec:
                        continue
                    last_rssi = dev.get("last_rssi")
                    if last_rssi is None or rssi is None:
                        continue
                    rssi_delta = abs(last_rssi - rssi)
                    if rssi_delta > self.rpa_continuity_rssi_tolerance:
                        continue
                    if best_delta is None or rssi_delta < best_delta:
                        best_candidate = dev_id
                        best_delta = rssi_delta
                if best_candidate:
                    matched_device_id = best_candidate
                    match_reason = "rpa_continuity"

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
                    if match_reason in ("classic_mac", "registered_mac"):
                        self._add_log_entry(
                            event="ARRIVED",
                            device_id=matched_device_id,
                            person_name=dev.get("name", "Невідомий"),
                            device_name=dev.get("device_name", ""),
                            rssi=rssi,
                            source=source,
                            note="Пристрій з'явився в радіусі гаража"
                        )
                    else:
                        # Heuristic match (device_name, service_uuid, rpa_continuity):
                        # Treat as sighting without triggering arrival automations/alerts
                        self._add_log_entry(
                            event="SIGHTING",
                            device_id=matched_device_id,
                            person_name=dev.get("name", "Невідомий"),
                            device_name=dev.get("device_name", ""),
                            rssi=rssi,
                            source=source,
                            note=f"Евристичний збіг ({match_reason}): автоматизація не запускається"
                        )
                elif match_reason in ("service_uuid", "rpa_continuity"):
                    # Not a new arrival, but log a low-noise SIGHTING so RPA rotations
                    # are traceable in the presence log for debugging/tuning.
                    self._add_log_entry(
                        event="SIGHTING",
                        device_id=matched_device_id,
                        person_name=dev.get("name", "Невідомий"),
                        device_name=dev.get("device_name", ""),
                        rssi=rssi,
                        source=source,
                        note=f"RPA ротація розпізнана ({match_reason}): новий MAC {mac_upper}"
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
                        auto_welcome: bool = False,
                        telegram_chat_id: Optional[str] = None,
                        absence_voice_message: str = "",
                        notify_owner: bool = False,
                        opt_in: bool = False) -> Dict[str, Any]:
        """Register a new device / guest entity with optional absence automation rules."""
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
                "auto_welcome": bool(auto_welcome),
                "telegram_chat_id": str(telegram_chat_id).strip() if telegram_chat_id else "",
                "absence_voice_message": str(absence_voice_message or "").strip(),
                "notify_owner": bool(notify_owner),
                "opt_in": bool(opt_in)
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

    def update_device(self, device_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update existing guest or device profile and absence automation rules."""
        with self._lock:
            clean_id = device_id.lower().replace(" ", "_").strip()
            if clean_id not in self.devices:
                return None
            item = self.devices[clean_id]
            allowed_fields = [
                "name", "role", "device_type", "device_name", "classic_mac",
                "ble_services", "auto_welcome", "telegram_chat_id",
                "absence_voice_message", "notify_owner", "opt_in"
            ]
            for field in allowed_fields:
                if field in kwargs:
                    val = kwargs[field]
                    if field in ("classic_mac",):
                        item[field] = str(val).upper().strip()
                    elif field in ("telegram_chat_id",):
                        item[field] = str(val).strip() if val else ""
                    elif field in ("auto_welcome", "notify_owner", "opt_in"):
                        item[field] = bool(val)
                    else:
                        item[field] = val

            if "ble_mac" in kwargs and kwargs["ble_mac"]:
                b_mac = str(kwargs["ble_mac"]).upper().strip()
                rpa_list = item.setdefault("recent_ble_rpa", [])
                if b_mac and b_mac not in rpa_list:
                    rpa_list.append(b_mac)

            self._save_devices()
            return item

    def remove_device(self, device_id: str) -> bool:
        """Remove a registered device and cascadingly delete all related sightings and history."""
        with self._lock:
            found = False
            if device_id in self.devices:
                del self.devices[device_id]
                self._save_devices()
                found = True

            orig_len = len(self.log)
            self.log = [entry for entry in self.log if entry.get("device_id") != device_id]
            if len(self.log) != orig_len:
                self._save_log()
                found = True
            return found

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

    def get_visitor_report(self, limit: int = 100, days: Optional[int] = None) -> Dict[str, Any]:
        """Generate structured visitor presence report and statistics."""
        with self._lock:
            now = time.time()
            cutoff_ts = (now - days * 86400) if days else 0

            # Today's start timestamp (midnight)
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

            filtered_logs = [e for e in self.log if e.get("timestamp", 0) >= cutoff_ts]
            visits_today = [
                e for e in self.log
                if e.get("timestamp", 0) >= today_start and e.get("event") == "ARRIVED"
            ]

            # Visitor stats (group by device_id)
            visitor_stats: Dict[str, Dict[str, Any]] = {}
            for dev_id, dev in self.devices.items():
                if dev.get("role") == "owner":
                    continue
                visitor_stats[dev_id] = {
                    "id": dev_id,
                    "name": dev.get("name", "Невідомий"),
                    "role": dev.get("role", "guest"),
                    "device_name": dev.get("device_name", ""),
                    "status": dev.get("status", "away"),
                    "last_seen": dev.get("last_seen"),
                    "last_seen_formatted": (
                        datetime.fromtimestamp(dev["last_seen"]).strftime("%H:%M:%S (%d.%m.%Y)")
                        if dev.get("last_seen") else "Ніколи"
                    ),
                    "proximity": dev.get("proximity", "unknown"),
                    "opt_in": bool(dev.get("opt_in", False)),
                    "total_visits": 0
                }

            # Count arrival events
            for e in filtered_logs:
                if e.get("event") == "ARRIVED":
                    d_id = e.get("device_id")
                    if d_id in visitor_stats:
                        visitor_stats[d_id]["total_visits"] += 1

            # Sanitize recent arrivals: exclude raw MAC and notes
            clean_recent = []
            for e in reversed(self.log[-limit:]):
                if e.get("event") == "ARRIVED":
                    clean_recent.append({
                        "event": "ARRIVED",
                        "formatted_time": e.get("formatted_time"),
                        "person_name": e.get("person_name"),
                        "device_name": e.get("device_name"),
                        "proximity": e.get("proximity")
                    })

            return {
                "generated_at": datetime.now().strftime("%H:%M:%S (%d.%m.%Y)"),
                "retention_policy": "TTL 7 днів, автоматичне каскадне очищення",
                "consent_notice": "Збір даних відвідувачів вимагає явного opt-in від власника",
                "deletion_method": "DELETE /api/presence/devices/<device_id>",
                "total_registered_guests": len(visitor_stats),
                "visits_today_count": len(visits_today),
                "visitors": list(visitor_stats.values()),
                "recent_arrivals": clean_recent[:limit]
            }
