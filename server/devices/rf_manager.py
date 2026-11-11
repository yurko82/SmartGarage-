"""
RF Manager for Smart Garage.
Handles 433 MHz RF button event decoding, deduplication, zone mapping, radio relay management,
and real-time RF activity logging / diagnostics.

Key safety rules:
1. Button Action is strictly idempotent 'off' (never turns lights ON or TOGGLES from RF buttons).
2. Zones:
   - basement_light (Підвал: Світло)
   - basement_fan (Підвал: Вентиляція)
   - floor2_kitchen (2-й поверх: Кімната 1 "Кухня")
   - floor2_living_room (2-й поверх: Кімната 2 "Вітальня")
   - floor2_light (2-й поверх: Загальне світло)
   - main_light (1-й поверх / Гараж: Світло)
   - main_fan (1-й поверх / Гараж: Вентиляція)
3. Radio Relays: Registered 433 MHz wireless relay modules that accept TX commands (ON/OFF)
   and support pairing modes.
4. Deduplication: Burst packet repeats (within dedup_window) are counted for diagnostics
   but trigger the zone action at most ONCE.
5. Activity Log & Metrics: Circular buffer tracking all incoming (RX) and outgoing (TX) RF packets.
"""

import json
import logging
import os
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("smartgarage.rf_manager")

VALID_ZONES = (
    "basement_light",
    "basement_fan",
    "floor2_kitchen",
    "floor2_living_room",
    "floor2_light",
    "main_light",
    "main_fan",
)

ZONE_DESCRIPTIONS = {
    "basement_light": "Підвал: Світло",
    "basement_fan": "Підвал: Вентиляція",
    "floor2_kitchen": "2-й поверх: Кімната 1 (Кухня)",
    "floor2_living_room": "2-й поверх: Кімната 2 (Вітальня)",
    "floor2_light": "2-й поверх: Загальне світло",
    "main_light": "1-й поверх (Гараж): Світло",
    "main_fan": "1-й поверх (Гараж): Вентиляція",
}

from server.utils.paths import get_rf_mappings_file
DEFAULT_MAPPINGS_FILE = get_rf_mappings_file()


class RfManager:
    @property
    def config_path(self) -> Path:
        if getattr(self, "_custom_config_path", None):
            return self._custom_config_path
        from server.utils.paths import get_rf_mappings_file
        return get_rf_mappings_file()

    @config_path.setter
    def config_path(self, val):
        self._custom_config_path = Path(val) if val else None

    def __init__(self, config_path: Optional[Path] = None, dedup_window_sec: float = 0.8):
        self._custom_config_path = Path(config_path) if config_path else None
        self.dedup_window_sec = dedup_window_sec
        self.mappings: Dict[str, Dict[str, Any]] = {}
        self.relays: Dict[str, Dict[str, Any]] = {}

        # In-memory tracking for deduplication & diagnostics
        self._last_event_time: Dict[str, float] = {}
        self._repeat_counts: Dict[str, int] = {}

        # Activity log & telemetry metrics
        self.activity_log = deque(maxlen=100)
        self.stats = {
            "tx_count": 0,
            "rx_count": 0,
            "burst_dedup_count": 0,
            "last_tx_time": None,
            "last_tx_code": None,
            "last_rx_time": None,
            "last_rx_code": None,
        }

        # Learning / Diagnostics mode
        self.learning_active = False
        self.learning_expires_at = 0.0
        self.learning_buffer: List[Dict[str, Any]] = []

        self.load_mappings()

    def load_mappings(self) -> None:
        """Load RF mappings and radio relays from persistent JSON storage."""
        if not self.config_path.exists():
            self._init_default_mappings()
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.mappings = data.get("mappings", {})
                self.relays = data.get("relays", {})
                settings = data.get("settings", {})
                self.dedup_window_sec = float(settings.get("dedup_window_sec", self.dedup_window_sec))

            # Ensure default relays exist if empty
            if not self.relays:
                self._populate_default_relays()
                self.save_mappings()

            logger.info(f"Loaded {len(self.mappings)} RF button mappings and {len(self.relays)} relays from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to read RF mappings from {self.config_path}: {e}")
            self.mappings = {}
            self.relays = {}

    def _init_default_mappings(self) -> None:
        """Create initial schema with default buttons and relays."""
        self.mappings = {
            "15835393": {
                "code": 15835393,
                "hex": "0xF1A101",
                "name": "Пульт Кнопка A (Підвал: Світло)",
                "zone": "basement_light",
                "action": "off",
                "enabled": True,
                "protocol": 1,
                "bits": 24,
                "delay": 320,
                "created_at": time.time(),
                "last_triggered": None
            },
            "15835394": {
                "code": 15835394,
                "hex": "0xF1A102",
                "name": "Пульт Кнопка B (2-й поверх: Світло)",
                "zone": "floor2_light",
                "action": "off",
                "enabled": True,
                "protocol": 1,
                "bits": 24,
                "delay": 320,
                "created_at": time.time(),
                "last_triggered": None
            }
        }
        self._populate_default_relays()
        self.save_mappings()

    def _populate_default_relays(self) -> None:
        """Initialize standard relay configurations for requested zones."""
        self.relays = {
            "relay_basement_light": {
                "id": "relay_basement_light",
                "name": "Підвал: Світло",
                "zone": "basement_light",
                "code_on": 15835393,
                "code_off": 15835394,
                "protocol": 1,
                "bits": 24,
                "delay": 320,
                "enabled": True,
                "created_at": time.time(),
                "last_switched": None,
                "last_action": None
            },
            "relay_basement_fan": {
                "id": "relay_basement_fan",
                "name": "Підвал: Вентиляція",
                "zone": "basement_fan",
                "code_on": 15835395,
                "code_off": 15835396,
                "protocol": 1,
                "bits": 24,
                "delay": 320,
                "enabled": True,
                "created_at": time.time(),
                "last_switched": None,
                "last_action": None
            },
            "relay_floor2_kitchen": {
                "id": "relay_floor2_kitchen",
                "name": "2-й поверх: Кімната 1 (Кухня)",
                "zone": "floor2_kitchen",
                "code_on": 15835397,
                "code_off": 15835398,
                "protocol": 1,
                "bits": 24,
                "delay": 320,
                "enabled": True,
                "created_at": time.time(),
                "last_switched": None,
                "last_action": None
            },
            "relay_floor2_living_room": {
                "id": "relay_floor2_living_room",
                "name": "2-й поверх: Кімната 2 (Вітальня)",
                "zone": "floor2_living_room",
                "code_on": 15835399,
                "code_off": 15835400,
                "protocol": 1,
                "bits": 24,
                "delay": 320,
                "enabled": True,
                "created_at": time.time(),
                "last_switched": None,
                "last_action": None
            }
        }

    def save_mappings(self) -> bool:
        """Save current RF button mappings and relays to persistent JSON storage."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": "2.0",
                "updated_at": time.time(),
                "settings": {
                    "dedup_window_sec": self.dedup_window_sec,
                    "allow_rf_turn_on": False
                },
                "mappings": self.mappings,
                "relays": self.relays
            }
            tmp_path = self.config_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.config_path)
            return True
        except Exception as e:
            logger.error(f"Failed to write RF mappings to {self.config_path}: {e}")
            return False

    # --- BUTTON MAPPINGS (RX) ---
    def get_mappings(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.mappings)

    def set_mapping(
        self,
        code: int,
        zone: str,
        name: str = "",
        action: str = "off",
        protocol: int = 1,
        bits: int = 24,
        delay: int = 320,
        enabled: bool = True
    ) -> bool:
        """
        Register or update a button-to-zone mapping.
        STRICT SAFETY: action is guaranteed to be 'off'.
        """
        if zone not in VALID_ZONES:
            raise ValueError(f"Invalid zone '{zone}'. Must be one of {VALID_ZONES}")

        safe_action = "off"
        code_str = str(code)

        self.mappings[code_str] = {
            "code": int(code),
            "hex": hex(int(code)).upper().replace("X", "x"),
            "name": name or f"Кнопка {hex(int(code))}",
            "zone": zone,
            "action": safe_action,
            "enabled": bool(enabled),
            "protocol": int(protocol),
            "bits": int(bits),
            "delay": int(delay),
            "created_at": time.time(),
            "last_triggered": None
        }
        return self.save_mappings()

    def delete_mapping(self, code: int) -> bool:
        code_str = str(code)
        if code_str in self.mappings:
            del self.mappings[code_str]
            return self.save_mappings()
        return False

    # --- RADIO RELAYS (TX) ---
    def get_relays(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.relays)

    def get_relay(self, relay_id: str) -> Optional[Dict[str, Any]]:
        return self.relays.get(str(relay_id))

    def get_relay_by_zone(self, zone: str) -> Optional[Dict[str, Any]]:
        zone_norm = (zone or "").strip().lower()
        for r in self.relays.values():
            if r.get("enabled", True) and r.get("zone", "").lower() == zone_norm:
                return dict(r)
        return None

    def set_relay(
        self,
        relay_id: str,
        zone: str,
        name: str,
        code_on: int,
        code_off: int,
        protocol: int = 1,
        bits: int = 24,
        delay: int = 320,
        enabled: bool = True
    ) -> bool:
        if zone not in VALID_ZONES:
            raise ValueError(f"Invalid zone '{zone}'. Must be one of {VALID_ZONES}")

        r_id = str(relay_id).strip() or f"relay_{zone}_{int(time.time())}"
        self.relays[r_id] = {
            "id": r_id,
            "name": name or ZONE_DESCRIPTIONS.get(zone, f"Реле {zone}"),
            "zone": zone,
            "code_on": int(code_on),
            "code_off": int(code_off),
            "code_on_hex": hex(int(code_on)).upper().replace("X", "x"),
            "code_off_hex": hex(int(code_off)).upper().replace("X", "x"),
            "protocol": int(protocol),
            "bits": int(bits),
            "delay": int(delay),
            "enabled": bool(enabled),
            "created_at": self.relays.get(r_id, {}).get("created_at", time.time()),
            "last_switched": None,
            "last_action": None
        }
        return self.save_mappings()

    def delete_relay(self, relay_id: str) -> bool:
        r_id = str(relay_id)
        if r_id in self.relays:
            del self.relays[r_id]
            return self.save_mappings()
        return False

    def update_relay_state(self, relay_id: str, action: str) -> None:
        r_id = str(relay_id)
        if r_id in self.relays:
            self.relays[r_id]["last_switched"] = time.time()
            self.relays[r_id]["last_action"] = action

    # --- ACTIVITY LOGGING & METRICS ---
    def log_activity(
        self,
        direction: str,  # "TX" or "RX"
        code: int,
        action: str = "info",
        zone: Optional[str] = None,
        zone_title: Optional[str] = None,
        status: str = "success",
        details: str = "",
        protocol: int = 1,
        bits: int = 24,
        delay: int = 320,
        is_repeat: bool = False
    ) -> Dict[str, Any]:
        """Record an incoming or outgoing RF event in the circular log buffer."""
        now = time.time()
        c_int = int(code) if code is not None else 0
        h_code = hex(c_int).upper().replace("X", "x") if c_int else "0x0"

        if direction.upper() == "TX":
            self.stats["tx_count"] += 1
            self.stats["last_tx_time"] = now
            self.stats["last_tx_code"] = c_int
        else:
            self.stats["rx_count"] += 1
            self.stats["last_rx_time"] = now
            self.stats["last_rx_code"] = c_int
            if is_repeat:
                self.stats["burst_dedup_count"] += 1

        entry = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": now,
            "time": time.strftime("%H:%M:%S", time.localtime(now)),
            "direction": direction.upper(),
            "code": c_int,
            "hex": h_code,
            "protocol": protocol,
            "bits": bits,
            "delay": delay,
            "zone": zone,
            "zone_title": zone_title or (ZONE_DESCRIPTIONS.get(zone) if zone else ""),
            "action": action,
            "status": status,
            "details": details,
            "is_repeat": is_repeat
        }
        self.activity_log.append(entry)
        return entry

    def get_activity_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return newest activity entries first."""
        items = list(self.activity_log)
        return items[-limit:][::-1]

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "tx_count": self.stats["tx_count"],
            "rx_count": self.stats["rx_count"],
            "burst_dedup_count": self.stats["burst_dedup_count"],
            "last_tx_time": self.stats["last_tx_time"],
            "last_tx_code": self.stats["last_tx_code"],
            "last_rx_time": self.stats["last_rx_time"],
            "last_rx_code": self.stats["last_rx_code"],
            "log_size": len(self.activity_log),
            "relays_count": len(self.relays),
            "mappings_count": len(self.mappings)
        }

    # --- LEARNING & DIAGNOSTICS ---
    def start_learning(self, duration_sec: int = 30) -> None:
        self.learning_active = True
        self.learning_expires_at = time.time() + max(5, int(duration_sec))
        logger.info(f"RF learning mode activated for {duration_sec}s")

    def stop_learning(self) -> None:
        self.learning_active = False
        self.learning_expires_at = 0.0
        logger.info("RF learning mode stopped")

    def is_learning(self) -> bool:
        if self.learning_active and time.time() > self.learning_expires_at:
            self.learning_active = False
        return self.learning_active

    def get_learning_status(self) -> Dict[str, Any]:
        active = self.is_learning()
        remain = max(0.0, self.learning_expires_at - time.time()) if active else 0.0
        return {
            "learning_active": active,
            "remaining_sec": round(remain, 1),
            "captured_count": len(self.learning_buffer),
            "recent_events": self.learning_buffer[-20:]
        }

    def clear_learning_buffer(self) -> None:
        self.learning_buffer.clear()

    # --- INCOMING RX EVENT PROCESSING ---
    def process_rf_event(
        self,
        event_data: Dict[str, Any],
        callback_zone_off: Optional[Callable[[str], bool]] = None
    ) -> Dict[str, Any]:
        """
        Process an incoming RF event.
        1. Checks deduplication window.
        2. Logs to activity log.
        3. If learning mode active, records event into buffer.
        4. If button is mapped and action == 'off', executes callback_zone_off(zone).
        """
        code = event_data.get("code")
        if not code:
            return {"status": "ignored", "reason": "no_code"}

        code_str = str(code)
        now = time.time()
        last_seen = self._last_event_time.get(code_str, 0.0)
        time_diff = now - last_seen

        is_repeat = (time_diff < self.dedup_window_sec)

        if is_repeat:
            self._repeat_counts[code_str] = self._repeat_counts.get(code_str, 1) + 1
        else:
            self._repeat_counts[code_str] = 1
            self._last_event_time[code_str] = now

        current_repeats = self._repeat_counts[code_str]
        protocol = event_data.get("protocol", 1)
        bits = event_data.get("bits", 24)
        delay = event_data.get("delay", 320)

        # In learning mode, record to buffer
        if self.is_learning():
            learn_record = {
                "code": code,
                "hex": event_data.get("hex") or hex(code),
                "bits": bits,
                "protocol": protocol,
                "delay": delay,
                "sync": event_data.get("sync"),
                "mode": event_data.get("mode", "standard"),
                "timestamp": now,
                "is_repeat": is_repeat,
                "repeats": current_repeats
            }
            if not is_repeat or (len(self.learning_buffer) > 0 and self.learning_buffer[-1].get("code") != code):
                self.learning_buffer.append(learn_record)
                if len(self.learning_buffer) > 100:
                    self.learning_buffer.pop(0)

            self.log_activity(
                direction="RX",
                code=code,
                action="learn",
                status="info",
                details=f"Захоплено у режимі навчання ({current_repeats} повт.)",
                protocol=protocol,
                bits=bits,
                delay=delay,
                is_repeat=is_repeat
            )

            return {
                "status": "learning",
                "code": code,
                "repeats": current_repeats,
                "action_taken": False
            }

        # Check mapping
        mapping = self.mappings.get(code_str)
        if not mapping or not mapping.get("enabled", True):
            self.log_activity(
                direction="RX",
                code=code,
                action="unmapped",
                status="info" if is_repeat else "warning",
                details=f"Неприв'язаний сигнал ({current_repeats} повт.)" if is_repeat else "Новий невідомий радіокод",
                protocol=protocol,
                bits=bits,
                delay=delay,
                is_repeat=is_repeat
            )
            return {
                "status": "unmapped",
                "code": code,
                "is_repeat": is_repeat,
                "repeats": current_repeats,
                "action_taken": False
            }

        zone = mapping.get("zone")
        action = mapping.get("action", "off")
        btn_name = mapping.get("name", f"Кнопка {hex(code)}")

        # STRICT SAFETY: Only 'off' is ever permitted via RF button events
        if action != "off":
            logger.warning(f"Rejected non-off action '{action}' for RF code {code}")
            self.log_activity(
                direction="RX",
                code=code,
                zone=zone,
                action="rejected",
                status="error",
                details=f"Відхилено дію '{action}' (дозволено лише 'off')",
                protocol=protocol,
                bits=bits,
                delay=delay
            )
            return {
                "status": "rejected",
                "reason": "action_must_be_off",
                "action_taken": False
            }

        # Deduplicate execution: execute ONLY on the first packet of a burst
        if is_repeat:
            self.log_activity(
                direction="RX",
                code=code,
                zone=zone,
                zone_title=btn_name,
                action="burst_repeat",
                status="info",
                details=f"Відфільтровано повторний пакет #{current_repeats}",
                protocol=protocol,
                bits=bits,
                delay=delay,
                is_repeat=True
            )
            return {
                "status": "deduplicated",
                "code": code,
                "zone": zone,
                "repeats": current_repeats,
                "action_taken": False
            }

        # First packet of new press: execute OFF action
        executed = False
        if callback_zone_off and zone in VALID_ZONES:
            try:
                executed = callback_zone_off(zone)
                mapping["last_triggered"] = now
                logger.info(f"RF Event: Executed 'off' for zone '{zone}' (button '{btn_name}', code={code})")
            except Exception as e:
                logger.error(f"Error executing zone off callback for {zone}: {e}")

        self.log_activity(
            direction="RX",
            code=code,
            zone=zone,
            zone_title=btn_name,
            action="off",
            status="success" if executed else "error",
            details=f"Виконано вимкнення зони {ZONE_DESCRIPTIONS.get(zone, zone)}",
            protocol=protocol,
            bits=bits,
            delay=delay,
            is_repeat=False
        )

        return {
            "status": "executed" if executed else "failed",
            "code": code,
            "zone": zone,
            "action": "off",
            "action_taken": executed,
            "repeats": 1
        }
