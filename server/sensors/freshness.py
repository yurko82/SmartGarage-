"""
Smart Garage - Sensor Freshness & Telemetry Truth Engine
Provides unified rules for determining sensor freshness, status categorization,
ISO-8601 formatting with timezones, and transparent source attribution.
"""
from datetime import datetime, timezone
import time
from typing import Dict, Any, Optional, Tuple

# Configuration Constants
# Default polling cycle is 30 minutes (1800 seconds)
SENSOR_POLL_INTERVAL_SECONDS = 1800

# Freshness window: 30 min poll interval + 10 min grace window for BLE connection retries
SENSOR_FRESHNESS_THRESHOLD_SECONDS = 2400

# Sensor Status Enum Constants
STATUS_ONLINE = "online"
STATUS_STALE = "stale"
STATUS_OFFLINE = "offline"
STATUS_NOT_INSTALLED = "not_installed"
STATUS_NEVER_SEEN = "never_seen"

SOURCE_BLE_DIRECT = "ble_direct"
SOURCE_ESP32_BRIDGE = "esp32_ble_bridge"
SOURCE_SQLITE_HISTORY = "sqlite_history"
SOURCE_CACHE = "cache"
SOURCE_NONE = "none"

SOURCE_DESCRIPTIONS = {
    SOURCE_BLE_DIRECT: "Прямий BLE-зв'язок",
    SOURCE_ESP32_BRIDGE: "BLE через міст ESP32",
    SOURCE_SQLITE_HISTORY: "Історія SQLite",
    SOURCE_CACHE: "Локальний кеш",
    SOURCE_NONE: "Немає джерела"
}


def format_iso_timestamp(timestamp: Optional[float]) -> Optional[str]:
    """Format Unix epoch timestamp into ISO-8601 string with local timezone offset."""
    if timestamp is None:
        return None
    try:
        # Use local system timezone
        local_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()
        return local_dt.isoformat()
    except Exception:
        return None


def format_relative_time_ua(timestamp: Optional[float], now: Optional[float] = None) -> str:
    """Format Unix timestamp into human-readable relative Ukrainian string."""
    if timestamp is None:
        return "Ніколи"
    cur = now if now is not None else time.time()
    diff = int(cur - timestamp)
    if diff < 0:
        return "Щойно"
    if diff < 60:
        return "Щойно"
    if diff < 3600:
        minutes = diff // 60
        return f"{minutes} хв тому"
    if diff < 86400:
        hours = diff // 3600
        return f"{hours} год тому"
    days = diff // 86400
    return f"{days} дн тому"


def get_sensor_status(
    last_updated: Optional[float],
    is_online_reported: bool = True,
    has_mac: bool = True,
    has_reading: bool = True,
    threshold_seconds: Optional[int] = None,
    now: Optional[float] = None
) -> Tuple[str, str]:
    """
    Determine single authoritative sensor status and Ukrainian explanation text.
    Returns (status_code, status_text_ua)
    """
    if not has_mac:
        return STATUS_NOT_INSTALLED, "Датчик не встановлено"

    if not has_reading or last_updated is None:
        return STATUS_NEVER_SEEN, "Очікує першого виміру"

    cur = now if now is not None else time.time()
    threshold = threshold_seconds or SENSOR_FRESHNESS_THRESHOLD_SECONDS
    age = cur - last_updated

    rel_str = format_relative_time_ua(last_updated, now=cur)

    # 0. Future timestamp protection (reject future timestamps from setting online)
    if last_updated is not None and (last_updated > cur + 60):
        return STATUS_STALE, "Помилка часової мітки: час виміру в майбутньому"

    # 1. If reading is older than freshness threshold, status is strictly stale
    if age > threshold:
        return STATUS_STALE, f"Дані застаріли ({rel_str})"

    # 2. If fresh reading was taken, but transport is currently disconnected
    if not is_online_reported:
        return STATUS_OFFLINE, f"Офлайн — останній вимір {rel_str}"

    # 3. Reading is fresh and bridge/sensor reported online
    return STATUS_ONLINE, "Актуально"


def build_sensor_payload(
    floor: str,
    name: str,
    mac: Optional[str] = None,
    temperature: Optional[float] = None,
    humidity: Optional[float] = None,
    battery: Optional[int] = None,
    last_updated: Optional[float] = None,
    is_online_reported: bool = False,
    source: str = SOURCE_NONE,
    installed: bool = True,
    threshold_seconds: Optional[int] = None,
    now: Optional[float] = None
) -> Dict[str, Any]:
    """
    Construct a validated, transparent sensor telemetry dictionary conforming to owner constraints:
    - Never presents old data as current when stale or offline
    - Distinct current_temperature vs last_known_temperature
    - Detailed source attribution and ISO-8601 timezone timestamp
    """
    cur = now if now is not None else time.time()
    threshold = threshold_seconds or SENSOR_FRESHNESS_THRESHOLD_SECONDS

    has_reading = (temperature is not None or humidity is not None)
    has_mac = bool(mac and installed)

    status_code, status_text = get_sensor_status(
        last_updated=last_updated,
        is_online_reported=is_online_reported,
        has_mac=has_mac,
        has_reading=has_reading,
        threshold_seconds=threshold,
        now=cur
    )

    is_online = (status_code == STATUS_ONLINE)
    age_seconds = int(cur - last_updated) if last_updated is not None else None
    is_stale = (status_code == STATUS_STALE) or (age_seconds is not None and age_seconds > threshold)

    # Current readings: ONLY available if sensor is genuinely fresh & online
    current_temp = round(temperature, 1) if (is_online and temperature is not None) else None
    current_hum = round(humidity, 1) if (is_online and humidity is not None) else None

    # Last known readings: preserved historical measurements
    last_known_temp = round(temperature, 1) if temperature is not None else None
    last_known_hum = round(humidity, 1) if humidity is not None else None

    sample_ts = last_updated if (has_reading and not (last_updated and last_updated > cur + 60)) else None
    heartbeat_ts = cur

    iso_str = format_iso_timestamp(last_updated)

    return {
        "floor": floor,
        "name": name,
        "mac": mac if installed else None,
        "installed": installed,
        "status": status_code,
        "online": is_online,
        "is_stale": is_stale,
        "sample_timestamp": sample_ts,
        "heartbeat_timestamp": heartbeat_ts,
        "last_known_sample_timestamp": sample_ts,
        "current_temperature": current_temp,
        "current_humidity": current_hum,
        "last_known_temperature": last_known_temp,
        "last_known_humidity": last_known_hum,
        "temperature": last_known_temp,  # Backward compatibility field
        "humidity": last_known_hum,        # Backward compatibility field
        "battery": battery,
        "source": source if has_reading else SOURCE_NONE,
        "source_name": SOURCE_DESCRIPTIONS.get(source, "Невідомо") if has_reading else "Немає джерела",
        "last_updated": last_updated,
        "last_successful_epoch": last_updated,
        "last_updated_iso": iso_str,
        "last_successful_iso": iso_str,
        "last_updated_relative": format_relative_time_ua(last_updated, now=cur),
        "last_updated_time": time.strftime("%H:%M:%S", time.localtime(last_updated)) if last_updated else "--:--",
        "last_updated_formatted": time.strftime("%H:%M:%S (%d.%m.%Y)", time.localtime(last_updated)) if last_updated else "--",
        "age_seconds": age_seconds,
        "status_text": status_text
    }


def merge_sensor_readings(primary_reading: Dict[str, Any], secondary_reading: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge readings from two different transport channels (e.g. host BLE direct vs ESP32 BLE bridge).
    Guarantees:
    - Fresher successful measurement ALWAYS wins.
    - A failed / offline update does NOT overwrite a fresher online reading.
    """
    ts1 = primary_reading.get("last_updated") or 0
    ts2 = secondary_reading.get("last_updated") or 0

    has_temp1 = primary_reading.get("last_known_temperature") is not None
    has_temp2 = secondary_reading.get("last_known_temperature") is not None

    online1 = primary_reading.get("online", False)
    online2 = secondary_reading.get("online", False)

    # 1. If one reading is online and fresh while other is not: online wins
    if online1 and not online2:
        return primary_reading
    if online2 and not online1:
        return secondary_reading

    # 2. Both online or both offline: compare timestamps
    if ts2 > ts1 and has_temp2:
        return secondary_reading
    if ts1 > ts2 and has_temp1:
        return primary_reading

    # 3. Fallback: whichever has a temperature reading
    if has_temp2 and not has_temp1:
        return secondary_reading
    return primary_reading
