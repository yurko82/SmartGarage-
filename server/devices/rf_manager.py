"""
RF Manager for Smart Garage.
Handles 433 MHz RF button event decoding, deduplication, zone mapping, and safe execution.

Key safety rules:
1. Action is strictly idempotent 'off' (never turns lights ON or TOGGLES from RF buttons).
2. Zones: 'basement_light', 'floor2_light', 'main_light'.
3. Deduplication: Burst packet repeats (within dedup_window) are counted for diagnostics
   but trigger the zone action at most ONCE.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("smartgarage.rf_manager")

VALID_ZONES = ("basement_light", "floor2_light", "main_light")
ZONE_DESCRIPTIONS = {
    "basement_light": "Світло підвалу",
    "floor2_light": "Світло 2-го поверху",
    "main_light": "Світло 1-го поверху (Гараж)"
}

DEFAULT_MAPPINGS_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "rf_mappings.json"


class RfManager:
    def __init__(self, config_path: Optional[Path] = None, dedup_window_sec: float = 0.8):
        self.config_path = Path(config_path) if config_path else DEFAULT_MAPPINGS_FILE
        self.dedup_window_sec = dedup_window_sec
        self.mappings: Dict[str, Dict[str, Any]] = {}
        
        # In-memory tracking for deduplication & diagnostics
        self._last_event_time: Dict[str, float] = {}
        self._repeat_counts: Dict[str, int] = {}
        
        # Learning / Diagnostics mode
        self.learning_active = False
        self.learning_expires_at = 0.0
        self.learning_buffer: List[Dict[str, Any]] = []
        
        self.load_mappings()

    def load_mappings(self) -> None:
        """Load RF mappings from persistent JSON storage."""
        if not self.config_path.exists():
            self._init_default_mappings()
            return
            
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.mappings = data.get("mappings", {})
                settings = data.get("settings", {})
                self.dedup_window_sec = float(settings.get("dedup_window_sec", self.dedup_window_sec))
            logger.info(f"Loaded {len(self.mappings)} RF button mappings from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to read RF mappings from {self.config_path}: {e}")
            self.mappings = {}

    def _init_default_mappings(self) -> None:
        """Create initial schema with disabled/configurable template."""
        self.mappings = {
            "15835393": {
                "code": 15835393,
                "hex": "0xF1A101",
                "name": "Пульт Кнопка A (Підвал)",
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
                "name": "Пульт Кнопка B (2-й поверх)",
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
        self.save_mappings()

    def save_mappings(self) -> bool:
        """Save current RF button mappings to persistent JSON storage."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": "1.0",
                "updated_at": time.time(),
                "settings": {
                    "dedup_window_sec": self.dedup_window_sec,
                    "allow_rf_turn_on": False
                },
                "mappings": self.mappings
            }
            tmp_path = self.config_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.config_path)
            return True
        except Exception as e:
            logger.error(f"Failed to write RF mappings to {self.config_path}: {e}")
            return False

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
            
        # Strict enforcement: action can only be 'off'
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

    def process_rf_event(
        self,
        event_data: Dict[str, Any],
        callback_zone_off: Optional[Callable[[str], bool]] = None
    ) -> Dict[str, Any]:
        """
        Process an incoming RF event.
        1. Checks deduplication window.
        2. If learning mode active, records event into buffer.
        3. If button is mapped and action == 'off', executes callback_zone_off(zone).
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

        # In learning mode, record to buffer
        if self.is_learning():
            learn_record = {
                "code": code,
                "hex": event_data.get("hex") or hex(code),
                "bits": event_data.get("bits", 24),
                "protocol": event_data.get("protocol", 1),
                "delay": event_data.get("delay", 320),
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

        # In learning mode, do NOT trigger any physical light actions!
        if self.is_learning():
            return {
                "status": "learning",
                "code": code,
                "repeats": current_repeats,
                "action_taken": False
            }

        # Check mapping
        mapping = self.mappings.get(code_str)
        if not mapping or not mapping.get("enabled", True):
            return {
                "status": "unmapped",
                "code": code,
                "is_repeat": is_repeat,
                "repeats": current_repeats,
                "action_taken": False
            }

        zone = mapping.get("zone")
        action = mapping.get("action", "off")

        # STRICT SAFETY: Only 'off' is ever permitted via RF button events
        if action != "off":
            logger.warning(f"Rejected non-off action '{action}' for RF code {code}")
            return {
                "status": "rejected",
                "reason": "action_must_be_off",
                "action_taken": False
            }

        # Deduplicate execution: execute ONLY on the first packet of a burst
        if is_repeat:
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
                logger.info(f"RF Event: Executed 'off' for zone '{zone}' (button '{mapping.get('name')}', code={code})")
            except Exception as e:
                logger.error(f"Error executing zone off callback for {zone}: {e}")

        return {
            "status": "executed" if executed else "failed",
            "code": code,
            "zone": zone,
            "action": "off",
            "action_taken": executed,
            "repeats": 1
        }
