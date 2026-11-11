import json
import subprocess
import threading
import time
import traceback
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil
from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory, session

from server.config import config
from server.security import (
    audit_log,
    command_rate_limiter,
    generate_csrf_token,
    get_client_ip,
    init_session_security,
    rate_limiter,
    require_auth,
    telemetry_rate_limiter,
    tts_rate_limiter,
    verify_esp32_auth,
    verify_pin_secure,
)
from server.sensors.freshness import (
    SENSOR_FRESHNESS_THRESHOLD_SECONDS,
    SOURCE_BLE_DIRECT,
    SOURCE_CACHE,
    SOURCE_ESP32_BRIDGE,
    SOURCE_ESP32_SENSOR,
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
    merge_sensor_readings,
)
from server.services.neural_tts import clean_text_for_tts, neural_tts
from server.services.radio_service import radio_service
from server.services.ytmusic_service import ytmusic_service
from server.tts.manager import tts_manager

from .core.core import SmartGarage
from .devices.projector import get_local_ip


class TelemetryHistory:
    """Thread-safe in-memory ring buffer for telemetry history."""
    def __init__(self, maxlen=100):
        self.maxlen = maxlen
        self._history = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, temp, hum, door="closed", light=False, car=False):
        with self._lock:
            now = time.time()
            if self._history and (now - self._history[-1]["timestamp"] < 3):
                self._history[-1].update({
                    "temperature": temp,
                    "humidity": hum,
                    "door": door,
                    "light": light,
                    "car_present": car
                })
                return
            self._history.append({
                "timestamp": now,
                "time": time.strftime("%H:%M:%S", time.localtime(now)),
                "temperature": temp,
                "humidity": hum,
                "door": door,
                "light": light,
                "car_present": car
            })

    def get_all(self):
        with self._lock:
            return list(self._history)


app = Flask(__name__)
init_session_security(app)
garage = SmartGarage()
telemetry_history = TelemetryHistory()
MEDIA_DIR = Path(__file__).parent.parent / "media"
_seen_telemetry_nonces = deque(maxlen=1000)
_seen_nonces_lock = threading.Lock()


def create_app(test_config=None, garage_instance=None):
    """Application factory pattern for test isolation and dependency injection."""
    global garage, telemetry_history
    if garage_instance is not None:
        garage = garage_instance
    if test_config:
        app.config.update(test_config)
    return app


def get_tailscale_ip() -> str | None:
    """Detect Tailscale IPv4 address dynamically from tailscale0 interface without hardcoded IPs."""
    try:
        addrs = psutil.net_if_addrs()
        for iface_name, iface_addrs in addrs.items():
            if "tailscale" in iface_name.lower():
                for a in iface_addrs:
                    if getattr(a, "family", None) == 2:  # AF_INET
                        return a.address
    except Exception:
        pass
    return None


def get_system_stats():
    """Collect Linux system metrics (CPU temp, RAM, Uptime, IPs)."""
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    cpu_temp = None
    try:
        temps = psutil.sensors_temperatures()
        if "coretemp" in temps and temps["coretemp"]:
            cpu_temp = round(temps["coretemp"][0].current, 1)
        elif "acpitz" in temps and temps["acpitz"]:
            cpu_temp = round(temps["acpitz"][0].current, 1)
    except Exception:
        pass

    # Battery info
    battery_percent = None
    battery_plugged = None
    try:
        b = psutil.sensors_battery()
        if b:
            battery_percent = round(b.percent, 1)
            battery_plugged = b.power_plugged
    except Exception:
        pass

    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)
    uptime_hours = uptime_seconds // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60

    return {
        "cpu_percent": round(cpu_percent, 1),
        "cpu_temp": cpu_temp or 55.0,
        "ram_percent": round(mem.percent, 1),
        "ram_used_mb": round(mem.used / (1024 * 1024), 1),
        "ram_total_mb": round(mem.total / (1024 * 1024), 1),
        "disk_percent": round(disk.percent, 1),
        "battery_percent": battery_percent,
        "battery_plugged": battery_plugged,
        "uptime_str": f"{uptime_hours} год {uptime_minutes} хв",
        "uptime_seconds": uptime_seconds,
        "local_ip": get_local_ip(),
        "tailscale_ip": get_tailscale_ip()
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
@app.route("/floor1")
def dashboard():
    return render_template("dashboard.html")


@app.after_request
def add_no_cache_headers(response):
    if request.path.startswith("/static/") or request.path in ("/", "/dashboard", "/floor1"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/manifest.json")
def serve_manifest():
    return send_from_directory(
        Path(__file__).parent / "static",
        "manifest.json",
        mimetype="application/manifest+json"
    )


@app.route("/api/system/stats", methods=["GET"])
def system_stats():
    return jsonify({
        "success": True,
        "stats": get_system_stats()
    })


@app.route("/api/device/light/toggle", methods=["POST"])
@require_auth
def toggle_light():
    state = garage.esp32.light_toggle()
    return jsonify({"success": True, "light": state})


@app.route("/api/device/light/state", methods=["POST"])
@require_auth
def set_light():
    data = request.get_json(silent=True) or {}
    on = data.get("state", True)
    state = garage.esp32.light_on() if on else garage.esp32.light_off()
    return jsonify({"success": True, "light": state})


@app.route("/api/device/light/zone/off", methods=["POST"])
@require_auth
def light_zone_off():
    data = request.get_json(silent=True) or {}
    zone = data.get("zone", "main_light")
    if hasattr(garage, "turn_off_light_zone"):
        ok = garage.turn_off_light_zone(zone)
        return jsonify({"success": True, "zone": zone, "action": "off", "executed": ok})
    elif hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.light_off_zone(zone)
        return jsonify({"success": True, "zone": zone, "action": "off", "executed": ok})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/device/zone/control", methods=["POST"])
@require_auth
def device_zone_control():
    data = request.get_json(silent=True) or {}
    zone = data.get("zone", "main_light")
    action = data.get("action", "off")
    if hasattr(garage, "control_zone"):
        ok = garage.control_zone(zone, action)
        return jsonify({"success": True, "zone": zone, "action": action, "executed": ok})
    elif hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.control_zone(zone, action)
        return jsonify({"success": True, "zone": zone, "action": action, "executed": ok})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/device/fan/toggle", methods=["POST"])
@require_auth
def toggle_fan():
    state = garage.esp32.fan_toggle()
    return jsonify({"success": True, "fan": state})


@app.route("/api/device/door/toggle", methods=["POST"])
@require_auth
def toggle_door():
    return jsonify({
        "success": False,
        "error": "Керування воротами вимкнено: привід воріт не планується / не встановлений",
        "door": "unknown"
    })


@app.route("/api/door/open", methods=["POST"])
@require_auth
def open_door():
    return jsonify({
        "success": False,
        "error": "Керування воротами вимкнено: привід воріт не планується / не встановлений",
        "door": "unknown"
    })


@app.route("/api/door/close", methods=["POST"])
@require_auth
def close_door():
    return jsonify({
        "success": False,
        "error": "Керування воротами вимкнено: привід воріт не планується / не встановлений",
        "door": "unknown"
    })


@app.route("/media/<path:filename>")
def serve_media(filename):
    return send_from_directory(MEDIA_DIR, filename)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


def get_consolidated_floors_telemetry() -> dict[str, dict[str, Any]]:
    """
    Consolidates floor climate readings across all available channels:
    1. Host direct BLE (Bleak)
    2. ESP32 BLE Bridge (HTTP / MQTT)
    3. SQLite Telemetry DB fallback
    Guarantees that a fresher online measurement is never overridden by an older or offline poll.
    """
    now = time.time()
    bt_telemetry = garage.bt_sensors.get_telemetry() if hasattr(garage, "bt_sensors") and garage.bt_sensors else {}
    bt_floors = bt_telemetry.get("floors", {})

    esp_telemetry = garage.esp32.get_telemetry() if hasattr(garage, "esp32") and garage.esp32 else {}
    esp_floors = esp_telemetry.get("floors", {})
    esp_is_online = bool(esp_telemetry.get("online", False))
    esp_last_seen = esp_telemetry.get("last_seen")

    default_names = {
        "floor1": "1-й поверх (Гараж)",
        "floor2": "2-й поверх",
        "basement": "Підвал"
    }

    consolidated = {}
    for fk in ("floor1", "floor2", "basement"):
        # 1. Base from host BLE
        base_payload = bt_floors.get(fk)
        if not base_payload:
            base_payload = build_sensor_payload(
                floor=fk,
                name=default_names[fk],
                mac="ESP32-AHT10" if fk == "floor1" else None,
                installed=True,
                now=now
            )

        # 2. Check ESP32 reading for this floor
        if isinstance(esp_floors, dict) and fk in esp_floors and isinstance(esp_floors[fk], dict):
            ef = esp_floors[fk]
            last_read = ef.get("last_read_ts") or ef.get("last_updated") or (esp_last_seen if ef.get("online") else None)
            esp_reported_online = bool(esp_is_online and ef.get("online", False))

            esp_payload = build_sensor_payload(
                floor=fk,
                name=ef.get("name") or base_payload.get("name") or default_names[fk],
                mac=ef.get("mac") or base_payload.get("mac") or ("ESP32-AHT10" if fk == "floor1" else None),
                temperature=ef.get("temperature"),
                humidity=ef.get("humidity"),
                battery=ef.get("battery"),
                last_updated=last_read,
                is_online_reported=esp_reported_online,
                source=SOURCE_ESP32_SENSOR if fk == "floor1" else SOURCE_ESP32_BRIDGE,
                installed=True,
                now=now
            )
            # Merge: fresher reading wins, offline cannot overwrite fresh online
            base_payload = merge_sensor_readings(base_payload, esp_payload)

        # 3. If still no temperature recorded and floor is installed, check SQLite telemetry DB
        if base_payload.get("installed") and base_payload.get("last_known_temperature") is None and hasattr(garage, "telemetry_db") and garage.telemetry_db:
            try:
                latest_db = garage.telemetry_db.get_latest_by_floor()
                if fk in latest_db and latest_db[fk].get("temperature") is not None:
                    db_val = latest_db[fk]
                    db_payload = build_sensor_payload(
                        floor=fk,
                        name=db_val.get("sensor_name") or base_payload.get("name") or default_names[fk],
                        mac=db_val.get("mac") or base_payload.get("mac"),
                        temperature=db_val.get("temperature"),
                        humidity=db_val.get("humidity"),
                        battery=db_val.get("battery"),
                        last_updated=db_val.get("timestamp"),
                        is_online_reported=False,  # Database historical fallback is inherently offline/stale
                        source=SOURCE_SQLITE_HISTORY,
                        installed=True,
                        now=now
                    )
                    base_payload = merge_sensor_readings(base_payload, db_payload)
            except Exception:
                pass

        consolidated[fk] = base_payload

    return consolidated


@app.route("/api/garage/state", methods=["GET"])
def garage_state():
    state = garage.esp32.get_telemetry()
    bt_telemetry = garage.bt_sensors.get_telemetry() if hasattr(garage, "bt_sensors") and garage.bt_sensors else {}

    floors = get_consolidated_floors_telemetry()

    # Primary climate resolution:
    # 1. Prefer online & fresh sensor with temperature
    # 2. Fallback to candidate with freshest last_updated
    primary_floor = None
    for pref_floor in ("basement", "floor2", "floor1"):
        if floors[pref_floor]["online"] and floors[pref_floor]["current_temperature"] is not None:
            primary_floor = floors[pref_floor]
            break

    if not primary_floor:
        candidates = [f for f in floors.values() if f.get("installed") and f.get("last_known_temperature") is not None]
        if candidates:
            candidates.sort(key=lambda x: x.get("last_updated") or 0, reverse=True)
            primary_floor = candidates[0]

    primary_current_temp = primary_floor["current_temperature"] if primary_floor else None
    primary_last_known_temp = primary_floor["last_known_temperature"] if primary_floor else None
    primary_current_hum = primary_floor["current_humidity"] if primary_floor else None
    primary_last_known_hum = primary_floor["last_known_humidity"] if primary_floor else None
    primary_name = primary_floor["name"] if primary_floor else "Підвал"
    primary_online = primary_floor["online"] if primary_floor else False
    primary_lu = primary_floor.get("last_updated") if primary_floor else None

    # Never return old temperature as current if sensor is offline / stale
    state["current_temperature"] = primary_current_temp
    state["current_humidity"] = primary_current_hum
    state["last_known_temperature"] = primary_last_known_temp
    state["last_known_humidity"] = primary_last_known_hum
    state["temperature"] = primary_current_temp   # Must be None if offline/stale!
    state["humidity"] = primary_current_hum

    # Mark uninstalled GPIO hardware clearly so UI doesn't display floating pin noise
    state["gas_ppm"] = None
    state["gas_installed"] = False
    state["gas_status"] = "not_installed"
    state["distance_cm"] = None
    state["car_present"] = None
    state["car_sensor_installed"] = False
    state["motion_detected"] = None
    state["motion_installed"] = False
    state["door"] = "unknown"
    state["door_installed"] = False
    state["door_status"] = "unknown"
    state["relays_installed"] = False

    state["bluetooth_sensors"] = bt_telemetry.get("devices", [])
    state["floors"] = floors
    state["primary_sensor"] = primary_floor or {
        "name": primary_name,
        "temperature": None,
        "current_temperature": None,
        "last_known_temperature": None,
        "humidity": None,
        "current_humidity": None,
        "last_known_humidity": None,
        "online": False,
        "is_stale": False,
        "status": STATUS_NOT_INSTALLED,
        "source": SOURCE_NONE,
        "last_updated": None,
        "last_updated_iso": None,
        "last_updated_formatted": "--",
        "last_updated_relative": "Ніколи",
        "status_text": "Датчик не встановлено"
    }
    state["speaker"] = garage.speaker.get_status() if hasattr(garage, "speaker") else {}
    state["esp32"] = garage.esp32.get_diagnostics() if hasattr(garage, "esp32") else {}
    state["rf"] = garage.esp32.get_rf_diagnostics() if hasattr(garage, "esp32") and garage.esp32 else {}

    # Record point into telemetry history only if real FRESH readings exist
    if primary_current_temp is not None and primary_online:
        telemetry_history.add(temp=primary_current_temp, hum=primary_current_hum or 0, door="unknown", light=False, car=False)

    return jsonify({
        "success": True,
        "state": state
    })


@app.route("/api/sensors/floors", methods=["GET"])
def sensors_floors():
    floors = get_consolidated_floors_telemetry()
    return jsonify({
        "success": True,
        "floors": floors
    })


@app.route("/api/sensors/refresh", methods=["POST"])
@require_auth
def sensors_refresh():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")

    # 1. Trigger ESP32 BLE climate polling
    esp_res = {}
    if hasattr(garage, "esp32") and garage.esp32:
        try:
            esp_res = garage.esp32.poll_ble()
        except Exception as e:
            esp_res = {"success": False, "error": str(e)}

    # 2. Also trigger Host Bluetooth polling
    if hasattr(garage, "bt_sensors") and garage.bt_sensors:
        garage.bt_sensors.poll_on_demand(mac)

    return jsonify({
        "success": True,
        "message": "Запит на опитування датчиків надіслано (ESP32 + Bluetooth)",
        "esp32": esp_res
    })


@app.route("/api/esp32/status", methods=["GET"])
def esp32_status():
    if hasattr(garage, "esp32") and garage.esp32:
        return jsonify({
            "success": True,
            "status": garage.esp32.get_diagnostics()
        })
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/esp32/ping", methods=["POST"])
@require_auth
def esp32_ping():
    if hasattr(garage, "esp32") and garage.esp32:
        res = garage.esp32.check_connection(timeout=1.0)
        return jsonify({
            "success": True,
            "result": res,
            "status": garage.esp32.get_diagnostics()
        })
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/esp32/poll", methods=["POST"])
@require_auth
def esp32_poll():
    if hasattr(garage, "esp32") and garage.esp32:
        res = garage.esp32.poll_ble()
        return jsonify({
            "success": True,
            "result": res,
            "status": garage.esp32.get_diagnostics()
        })
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/pair", methods=["POST"])
@require_auth
def rf_pair_start():
    data = request.get_json(silent=True) or {}
    duration = int(data.get("duration", 600))
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.rf_pair(duration_sec=duration)
        return jsonify({"success": ok, "pairing": True, "duration_sec": duration})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/pair_stop", methods=["POST"])
@require_auth
def rf_pair_stop():
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.rf_pair_stop()
        return jsonify({"success": ok, "pairing": False})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/diag", methods=["GET", "POST"])
@require_auth
def rf_diag_route():
    if hasattr(garage, "esp32") and garage.esp32:
        if request.method == "POST":
            garage.esp32.rf_diag()
            import time

            time.sleep(0.08)
        diagnostics = garage.esp32.get_rf_diagnostics()
        return jsonify({
            "success": True,
            "rf_status": diagnostics.get("raw") or garage.esp32.state.get("rf_diag") or garage.esp32.state.get("rf_status"),
            "diagnostics": diagnostics,
        })
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/learn/start", methods=["POST"])
@require_auth
def rf_learn_start_route():
    data = request.get_json(silent=True) or {}
    duration = int(data.get("duration", 600))
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.rf_learn_start(duration_sec=duration)
        return jsonify({"success": ok, "learning": True, "duration_sec": duration})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/learn/stop", methods=["POST"])
@require_auth
def rf_learn_stop_route():
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.rf_learn_stop()
        return jsonify({"success": ok, "learning": False})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/learn/status", methods=["GET"])
@require_auth
def rf_learn_status_route():
    if hasattr(garage, "esp32") and garage.esp32:
        status = garage.esp32.rf_learn_status()
        return jsonify({"success": True, "status": status})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/mappings", methods=["GET"])
@require_auth
def rf_mappings_get():
    if hasattr(garage, "esp32") and garage.esp32:
        mappings = garage.esp32.get_rf_mappings()
        return jsonify({"success": True, "mappings": mappings})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/mappings", methods=["POST"])
@require_auth
def rf_mappings_set():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    zone = data.get("zone")
    name = data.get("name", "")
    if not code or not zone:
        return jsonify({"success": False, "error": "Параметри 'code' та 'zone' є обов'язковими"}), 400
    try:
        code_int = int(code)
    except ValueError:
        return jsonify({"success": False, "error": "Невірний числовий формат коду"}), 400

    if hasattr(garage, "esp32") and garage.esp32:
        try:
            ok = garage.esp32.set_rf_mapping(
                code=code_int,
                zone=zone,
                name=name,
                action="off",
                protocol=int(data.get("protocol", 1)),
                bits=int(data.get("bits", 24)),
                delay=int(data.get("delay", 320))
            )
            return jsonify({"success": ok, "code": code_int, "zone": zone, "action": "off"})
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/mappings/<code_id>", methods=["DELETE"])
@require_auth
def rf_mappings_delete(code_id):
    try:
        code_int = int(code_id)
    except ValueError:
        return jsonify({"success": False, "error": "Невірний формат code_id"}), 400
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.delete_rf_mapping(code_int)
        return jsonify({"success": ok, "deleted_code": code_int})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/status", methods=["GET"])
@require_auth
def rf_status_get():
    if hasattr(garage, "esp32") and garage.esp32:
        metrics = garage.esp32.get_rf_metrics()
        activity = garage.esp32.get_rf_activity(limit=25)
        learn_status = garage.esp32.rf_learn_status()
        diagnostics = garage.esp32.get_rf_diagnostics()
        raw_rf = diagnostics.get("raw") or garage.esp32.state.get("rf_status") or {"cc1101": True, "freq": 433.92, "rssi": -85}
        return jsonify({
            "success": True,
            "metrics": metrics,
            "activity": activity,
            "learning": learn_status,
            "rf_status": raw_rf,
            "diagnostics": diagnostics,
        })
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/activity", methods=["GET"])
@require_auth
def rf_activity_get():
    limit = int(request.args.get("limit", 50))
    if hasattr(garage, "esp32") and garage.esp32:
        activity = garage.esp32.get_rf_activity(limit=limit)
        metrics = garage.esp32.get_rf_metrics()
        return jsonify({"success": True, "activity": activity, "metrics": metrics})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/zones", methods=["GET"])
@require_auth
def rf_zones_get():
    from server.devices.rf_manager import VALID_ZONES, ZONE_DESCRIPTIONS
    zones = []
    for z in VALID_ZONES:
        cat = "basement" if "basement" in z else ("floor2" if "floor2" in z else "garage")
        zones.append({"id": z, "name": ZONE_DESCRIPTIONS.get(z, z), "category": cat})
    return jsonify({"success": True, "zones": zones})


@app.route("/api/rf/relays", methods=["GET"])
@require_auth
def rf_relays_get():
    if hasattr(garage, "esp32") and garage.esp32:
        relays = garage.esp32.get_rf_relays()
        return jsonify({"success": True, "relays": relays})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/relays", methods=["POST"])
@require_auth
def rf_relays_set():
    data = request.get_json(silent=True) or {}
    zone = data.get("zone")
    name = data.get("name", "")
    code_on = data.get("code_on")
    code_off = data.get("code_off")
    relay_id = data.get("id") or f"relay_{zone}_{int(time.time())}"
    if not zone or code_on is None or code_off is None:
        return jsonify({"success": False, "error": "Параметри 'zone', 'code_on' та 'code_off' обов'язкові"}), 400
    try:
        on_int = int(code_on)
        off_int = int(code_off)
    except ValueError:
        return jsonify({"success": False, "error": "Невірний числовий формат кодів ON/OFF"}), 400
    if hasattr(garage, "esp32") and garage.esp32:
        try:
            ok = garage.esp32.set_rf_relay(
                relay_id=relay_id,
                zone=zone,
                name=name,
                code_on=on_int,
                code_off=off_int,
                protocol=int(data.get("protocol", 1)),
                bits=int(data.get("bits", 24)),
                delay=int(data.get("delay", 320)),
                enabled=bool(data.get("enabled", True))
            )
            return jsonify({"success": ok, "relay_id": relay_id, "zone": zone, "name": name})
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/relays/<relay_id>", methods=["DELETE"])
@require_auth
def rf_relays_delete(relay_id):
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.delete_rf_relay(relay_id)
        return jsonify({"success": ok, "deleted_relay_id": relay_id})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/relays/<relay_id>/test", methods=["POST"])
@require_auth
def rf_relays_test(relay_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action", "on")
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.test_rf_relay(relay_id, action=action)
        return jsonify({"success": ok, "relay_id": relay_id, "action": action})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/relays/<relay_id>/pair", methods=["POST"])
@require_auth
def rf_relays_pair(relay_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action", "on")
    duration = int(data.get("duration", 15))
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.pair_rf_relay(relay_id, action=action, duration_sec=duration)
        return jsonify({"success": ok, "relay_id": relay_id, "action": action, "duration": duration})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/rf/transmit", methods=["POST"])
@require_auth
def rf_transmit_route():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    if code is None:
        return jsonify({"success": False, "error": "Параметр 'code' обов'язковий"}), 400
    try:
        code_int = int(code)
    except ValueError:
        return jsonify({"success": False, "error": "Невірний формат коду"}), 400
    zone = data.get("zone")
    action = data.get("action", "transmit")
    name = data.get("name", "")
    if hasattr(garage, "esp32") and garage.esp32:
        ok = garage.esp32.rf_transmit(
            code=code_int,
            zone=zone,
            action=action,
            name=name,
            repeats=int(data.get("repeats", 10)),
            protocol=int(data.get("protocol", 1)),
            bits=int(data.get("bits", 24)),
            delay=int(data.get("delay", 320))
        )
        return jsonify({"success": ok, "code": code_int, "zone": zone, "action": action})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/automation/rules", methods=["GET"])
@require_auth
def get_automation_rules():
    rules_file = Path(__file__).resolve().parent.parent / "config" / "automation_rules.json"
    if rules_file.exists():
        try:
            with open(rules_file, encoding="utf-8") as f:
                rules_data = json.load(f)
            return jsonify({"success": True, "rules": rules_data.get("rules", [])})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": True, "rules": []})


@app.route("/api/esp32/clear_logs", methods=["POST"])
@require_auth
def esp32_clear_logs():
    if hasattr(garage, "esp32") and garage.esp32:
        garage.esp32.clear_logs()
        return jsonify({"success": True, "message": "Журнал ESP32 очищено"})
    return jsonify({"success": False, "error": "ESP32 не ініціалізовано"}), 500


@app.route("/api/sensors/bind", methods=["POST"])
@require_auth
def bind_sensor_route():
    data = request.get_json(silent=True) or {}
    floor_key = data.get("floor")
    mac = data.get("mac")
    alias = data.get("alias")
    if not floor_key or not mac:
        return jsonify({"success": False, "error": "floor and mac are required"}), 400

    if hasattr(garage, "bt_sensors") and garage.bt_sensors:
        res = garage.bt_sensors.bind_sensor(floor_key, mac, alias)
        return jsonify({"success": res, "floor": floor_key, "mac": mac})
    return jsonify({"success": False, "error": "Bluetooth sensor manager not initialized"}), 500


@app.route("/api/telemetry/history", methods=["GET"])
def get_telemetry_history():
    floor = request.args.get("floor")
    try:
        hours = float(request.args.get("hours", 24))
    except (ValueError, TypeError):
        hours = 24.0
    try:
        limit = int(request.args.get("limit", 500))
    except (ValueError, TypeError):
        limit = 500

    if hasattr(garage, "telemetry_db") and garage.telemetry_db:
        res = garage.telemetry_db.get_history(floor=floor, hours=hours, limit=limit)
        # Compatibility with existing index.html / app.js
        res["history"] = res.get("points", [])
        return jsonify(res)

    return jsonify({
        "success": True,
        "history": telemetry_history.get_all(),
        "points": telemetry_history.get_all(),
        "stats": {}
    })


@app.route("/api/esp32/telemetry", methods=["POST"])
def esp32_telemetry():
    ip = get_client_ip()

    # 1. Device authentication
    if not verify_esp32_auth():
        audit_log("esp32", "telemetry_auth_failed", "DENIED", {"ip": ip})
        return jsonify({
            "success": False,
            "error": "Неавторизований доступ ESP32 (недійсний або відсутній API-ключ)"
        }), 401

    # 2. Rate limit check
    is_limited, wait_sec = telemetry_rate_limiter.is_rate_limited(ip)
    if is_limited:
        audit_log("esp32", "telemetry_ratelimited", "BLOCKED", {"ip": ip, "wait_sec": wait_sec})
        return jsonify({
            "success": False,
            "error": f"Занадто часті запити телеметрії. Зачекайте {wait_sec} сек."
        }), 429

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "Некоректний формат JSON"}), 400

    now = time.time()

    # 3. Replay protection: timestamp check (+/- 300s window)
    ts = data.get("timestamp")
    if ts is not None:
        try:
            ts_float = float(ts)
            if ts_float < now - 300.0 or ts_float > now + 60.0:
                audit_log("esp32", "telemetry_stale_timestamp", "BLOCKED", {"ts": ts_float, "server_now": now, "ip": ip})
                return jsonify({"success": False, "error": "Застаріла або некоректна мітка часу телеметрії"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Некоректний формат мітки часу"}), 400

    # 4. Replay protection: nonce / seq deduplication
    nonce = data.get("nonce") or data.get("seq")
    if nonce is not None:
        nonce_str = str(nonce).strip()
        with _seen_nonces_lock:
            if nonce_str in _seen_telemetry_nonces:
                audit_log("esp32", "telemetry_replay_detected", "BLOCKED", {"nonce": nonce_str, "ip": ip})
                return jsonify({"success": False, "error": "Повторний запит телеметрії (replay attack detected)"}), 400
            _seen_telemetry_nonces.append(nonce_str)

    # 5. Schema & Range validation
    temp = data.get("temperature")
    if temp is not None:
        try:
            t_val = float(temp)
            if not (-50.0 <= t_val <= 100.0):
                return jsonify({"success": False, "error": "Температура поза допустимим діапазоном (-50..100°C)"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Некоректне значення температури"}), 400

    hum = data.get("humidity")
    if hum is not None:
        try:
            h_val = float(hum)
            if not (0.0 <= h_val <= 100.0):
                return jsonify({"success": False, "error": "Вологість поза допустимим діапазоном (0..100%)"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Некоректне значення вологості"}), 400

    bat = data.get("battery")
    if bat is not None:
        try:
            b_val = float(bat)
            if not (0.0 <= b_val <= 100.0):
                return jsonify({"success": False, "error": "Рівень батареї поза допустимим діапазоном (0..100%)"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Некоректний рівень батареї"}), 400

    floors = data.get("floors")
    if isinstance(floors, dict):
        for fk, fval in floors.items():
            if isinstance(fval, dict):
                ftemp = fval.get("temperature")
                if ftemp is not None:
                    try:
                        ft_val = float(ftemp)
                        if not (-50.0 <= ft_val <= 100.0):
                            return jsonify({"success": False, "error": f"Температура для {fk} поза допустимим діапазоном"}), 400
                    except (ValueError, TypeError):
                        return jsonify({"success": False, "error": f"Некоректна температура для {fk}"}), 400
                fhum = fval.get("humidity")
                if fhum is not None:
                    try:
                        fh_val = float(fhum)
                        if not (0.0 <= fh_val <= 100.0):
                            return jsonify({"success": False, "error": f"Вологість для {fk} поза допустимим діапазоном"}), 400
                    except (ValueError, TypeError):
                        return jsonify({"success": False, "error": f"Некоректна вологість для {fk}"}), 400
                fbat = fval.get("battery")
                if fbat is not None:
                    try:
                        fb_val = float(fbat)
                        if not (0.0 <= fb_val <= 100.0):
                            return jsonify({"success": False, "error": f"Батарея для {fk} поза допустимим діапазоном"}), 400
                    except (ValueError, TypeError):
                        return jsonify({"success": False, "error": f"Некоректна батарея для {fk}"}), 400

    success = garage.esp32.update_from_webhook(data, transport="http")
    if success:
        garage.automation.evaluate_telemetry(data)
        # Update cache from ESP32 BLE reading if present
        if "floors" in data and hasattr(garage, "bt_sensors") and garage.bt_sensors:
            with garage.bt_sensors._lock:
                for fk, fval in data["floors"].items():
                    mac = fval.get("mac")
                    if mac and mac in garage.bt_sensors.sensors:
                        s = garage.bt_sensors.sensors[mac]
                        is_sensor_online = bool(fval.get("online", False))
                        if fval.get("temperature") is not None and is_sensor_online:
                            s["temperature"] = fval["temperature"]
                            s["humidity"] = fval.get("humidity")
                            s["battery"] = fval.get("battery")
                            s["online"] = True
                            s["source"] = SOURCE_ESP32_BRIDGE
                            s["last_updated"] = time.time()
                        elif not is_sensor_online:
                            # Preserve fresher direct BLE reading if present; do not overwrite fresh reading
                            cur_lu = s.get("last_updated")
                            if not cur_lu or (time.time() - cur_lu > SENSOR_FRESHNESS_THRESHOLD_SECONDS):
                                s["online"] = False
            garage.bt_sensors._save_cache()

            # Record into SQLite TelemetryDB only for online readings
            if hasattr(garage, "telemetry_db") and garage.telemetry_db:
                for fk, fval in data["floors"].items():
                    if isinstance(fval, dict) and fval.get("online") and fval.get("temperature") is not None:
                        garage.telemetry_db.record(
                            floor=fk,
                            temperature=fval["temperature"],
                            humidity=fval.get("humidity"),
                            battery=fval.get("battery"),
                            mac=fval.get("mac"),
                            sensor_name=fval.get("name")
                        )
        temp = data.get("temperature")
        hum = data.get("humidity")
        door = garage.esp32.state.get("door", "unknown")
        light = garage.esp32.state.get("light", False)
        car = bool(data.get("car_present"))
        if (temp is not None or hum is not None) and data.get("online"):
            telemetry_history.add(temp=temp, hum=hum, door=door, light=light, car=car)

    return jsonify({
        "success": success,
        "status": "received"
    })


def get_bound_macs() -> set:
    """Returns set of uppercase MAC addresses for all already bound / configured devices in the garage.
    Includes:
      - Climate sensors (Basement, 2nd floor, etc.) from bluetooth_devices.json
      - Garage speakers (JX-BT, JBL Clip 5)
      - Registered owner devices (Motorola phone, smartwatch) from presence_devices.json
      - All already registered guests
    """
    bound = set()

    # 1. Configured hardware / sensors / speakers from bluetooth_devices.json
    try:
        from server.utils.paths import get_devices_dir
        bt_file = get_devices_dir() / "bluetooth_devices.json"
        if bt_file.exists():
            with open(bt_file, encoding="utf-8") as f:
                data = json.load(f)
                for mac in data.keys():
                    if mac:
                        bound.add(mac.upper().strip())
    except Exception as e:
        if hasattr(garage, "logger"):
            garage.logger.debug(f"Error loading bound MACs from bluetooth_devices.json: {e}")

    # 2. Registered presence devices (owner phone, watch, registered guests)
    if hasattr(garage, "presence") and garage.presence:
        with garage.presence._lock:
            for dev in garage.presence.devices.values():
                cmac = dev.get("classic_mac")
                if cmac:
                    bound.add(cmac.upper().strip())
                for rpa in dev.get("recent_ble_rpa", []):
                    if rpa:
                        bound.add(rpa.upper().strip())

    return bound


def _scan_all_ble(duration: int = 15, only_new: bool = True) -> list:
    """Hybrid scanner combining ESP32 BLE scan and Host Bluetooth (Bleak) scan.

    When only_new=True, filters out already bound garage infrastructure
    (temperature sensors, speakers, owner devices, registered guests) so that
    only new / unknown devices are discovered and presented for binding.
    """
    import concurrent.futures

    def _host_scan():
        try:
            import asyncio

            from bleak import BleakScanner

            async def _run():
                discovered = await BleakScanner.discover(timeout=float(duration), return_adv=True)
                res = []
                for addr, (dev, adv) in discovered.items():
                    res.append({
                        "mac": addr.upper().strip(),
                        "name": adv.local_name or dev.name or "",
                        "rssi": adv.rssi if hasattr(adv, "rssi") else -90,
                        "service_uuids": list(adv.service_uuids) if hasattr(adv, "service_uuids") else [],
                        "source": "host_ble"
                    })
                return res

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_run())
            finally:
                loop.close()
        except Exception as e:
            garage.logger.warning(f"Host BLE scanner exception: {e}")
            return []

    def _esp_scan():
        try:
            return garage.esp32.scan_ble(duration=duration)
        except Exception as e:
            garage.logger.warning(f"ESP32 BLE scan exception: {e}")
            return []

    esp_devs = []
    host_devs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_esp = ex.submit(_esp_scan)
        f_host = ex.submit(_host_scan)
        try:
            esp_devs = f_esp.result(timeout=duration + 6)
        except Exception:
            esp_devs = []
        try:
            host_devs = f_host.result(timeout=duration + 6)
        except Exception:
            host_devs = []

    merged = {}
    for d in esp_devs:
        mac = d.get("mac", "").upper().strip()
        if mac:
            merged[mac] = {
                "mac": mac,
                "name": d.get("name", ""),
                "rssi": d.get("rssi", -99),
                "service_uuids": d.get("service_uuids", []),
                "source": "esp32"
            }

    for d in host_devs:
        mac = d.get("mac", "").upper().strip()
        if not mac:
            continue
        if mac in merged:
            if d.get("name") and not merged[mac]["name"]:
                merged[mac]["name"] = d["name"]
            if d.get("rssi", -99) > merged[mac]["rssi"]:
                merged[mac]["rssi"] = d["rssi"]
            if d.get("service_uuids"):
                uuids = list(set(merged[mac].get("service_uuids", []) + d["service_uuids"]))
                merged[mac]["service_uuids"] = uuids
            merged[mac]["source"] = "esp32 + host"
        else:
            merged[mac] = d

    # Record sightings in presence system for all physically received signals in the air
    if hasattr(garage, "presence") and garage.presence:
        for d in merged.values():
            garage.presence.record_sighting(
                mac=d.get("mac", ""),
                name=d.get("name", ""),
                rssi=d.get("rssi"),
                service_uuids=d.get("service_uuids", []),
                source=d.get("source", "ble_scan")
            )

    # Filter out already bound devices if only_new is True
    if only_new:
        bound_macs = get_bound_macs()
        merged = {m: d for m, d in merged.items() if m not in bound_macs}

    all_devices = sorted(merged.values(), key=lambda x: x.get("rssi", -99), reverse=True)
    return all_devices


@app.route("/api/esp32/scan_ble", methods=["GET", "POST"])
@require_auth
def esp32_scan_ble():
    duration = int(request.args.get("duration", 15))
    if duration <= 0:
        duration = 10
    only_new = request.args.get("only_new", "true").lower() in ("true", "1", "yes")
    devices = _scan_all_ble(duration=duration, only_new=only_new)
    return jsonify({
        "success": True,
        "count": len(devices),
        "devices": devices,
        "only_new": only_new
    })


@app.route("/api/presence/status", methods=["GET"])
@require_auth
def presence_status():
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    return jsonify({
        "success": True,
        "presence": garage.presence.get_status()
    })


@app.route("/api/presence/log", methods=["GET"])
@require_auth
def presence_log():
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    limit = int(request.args.get("limit", 50))
    return jsonify({
        "success": True,
        "log": garage.presence.get_log(limit=limit)
    })


@app.route("/api/presence/report", methods=["GET"])
@require_auth
def presence_report():
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    limit = int(request.args.get("limit", 100))
    days = int(request.args.get("days", 7))
    report = garage.presence.get_visitor_report(limit=limit, days=days)
    return jsonify({
        "success": True,
        "report": report
    })


@app.route("/api/presence/devices", methods=["POST"])
@require_auth
def presence_register_device():
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"success": False, "error": "Name is required"}), 400

    device_id = data.get("id") or name.lower().replace(" ", "_")
    item = garage.presence.register_device(
        device_id=device_id,
        name=name,
        role=data.get("role", "guest"),
        device_type=data.get("device_type", "phone"),
        device_name=data.get("device_name", name),
        classic_mac=data.get("classic_mac", ""),
        ble_mac=data.get("ble_mac", ""),
        ble_services=data.get("ble_services", []),
        auto_welcome=data.get("auto_welcome", False),
        telegram_chat_id=data.get("telegram_chat_id", ""),
        absence_voice_message=data.get("absence_voice_message", ""),
        notify_owner=data.get("notify_owner", False),
        opt_in=data.get("opt_in", False)
    )
    return jsonify({"success": True, "device": item})


@app.route("/api/presence/devices/<device_id>", methods=["PUT", "PATCH"])
@require_auth
def presence_update_device(device_id):
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    data = request.get_json(silent=True) or {}
    updated = garage.presence.update_device(device_id, **data)
    if updated is None:
        return jsonify({"success": False, "error": "Device not found"}), 404
    return jsonify({"success": True, "device": updated})


@app.route("/api/presence/devices/<device_id>", methods=["DELETE"])
@require_auth
def presence_remove_device(device_id):
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    removed = garage.presence.remove_device(device_id)
    return jsonify({"success": removed})


@app.route("/api/presence/scan", methods=["POST"])
@require_auth
def presence_scan_and_record():
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    duration = int(request.args.get("duration", 15))
    if duration <= 0:
        duration = 10
    only_new = request.args.get("only_new", "true").lower() in ("true", "1", "yes")
    devices = _scan_all_ble(duration=duration, only_new=only_new)
    return jsonify({
        "success": True,
        "scanned_count": len(devices),
        "devices": devices,
        "only_new": only_new,
        "presence": garage.presence.get_status()
    })


@app.route("/api/admin/verify", methods=["POST"])
@app.route("/api/admin/login", methods=["POST"])
def admin_verify():
    ip = get_client_ip()
    is_limited, wait_sec = rate_limiter.is_rate_limited(ip)
    if is_limited:
        audit_log("web", "admin_login_ratelimited", "BLOCKED", {"ip": ip, "wait_sec": wait_sec})
        return jsonify({
            "success": False,
            "error": f"Забагато невдалих спроб входу. Зачекайте {wait_sec} сек."
        }), 429

    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", "")).strip()

    if verify_pin_secure(pin):
        rate_limiter.reset(ip)
        session.permanent = True
        session["authenticated"] = True
        session["login_time"] = time.time()
        import secrets
        session["dialog_session_id"] = f"web_{secrets.token_hex(16)}"
        csrf_token = generate_csrf_token()
        audit_log("web", "admin_login", "SUCCESS", {"ip": ip}, actor="admin")
        return jsonify({
            "success": True,
            "authenticated": True,
            "csrf_token": csrf_token,
            "session_id": session["dialog_session_id"]
        })

    rate_limiter.record_failure(ip)
    audit_log("web", "admin_login_failed", "DENIED", {"ip": ip})
    return jsonify({"success": False, "authenticated": False, "error": "Невірний PIN-код"}), 401


@app.route("/api/admin/logout", methods=["POST"])
@require_auth
def admin_logout():
    ip = get_client_ip()
    session.clear()
    audit_log("web", "admin_logout", "SUCCESS", {"ip": ip})
    return jsonify({"success": True, "authenticated": False})


@app.route("/api/csrf", methods=["GET"])
def get_csrf():
    if session.get("authenticated"):
        return jsonify({"success": True, "csrf_token": generate_csrf_token()})
    return jsonify({"success": False, "csrf_token": None}), 401




@app.route("/api/scenarios/<name>", methods=["POST"])
@require_auth
def trigger_scenario(name):
    handlers = {
        "arrival": garage.automation.scenario_car_arrival,
        "departure": garage.automation.scenario_departure,
        "night": garage.automation.scenario_night_mode,
        "cinema": garage.automation.scenario_cinema_mode,
        "safety": garage.automation.scenario_gas_alarm,
    }
    handler = handlers.get(name.lower())
    if not handler:
        return jsonify({"success": False, "response": f"Unknown scenario: {name}"}), 400
    success, msg = handler()
    return jsonify({"success": success, "response": msg})


# --- MEDIA HUB & PROJECTOR API ---
@app.route("/api/media/list", methods=["GET"])
def media_list():
    media_files = []
    stream_files = []
    local_ip = get_local_ip()

    if MEDIA_DIR.exists():
        for f in MEDIA_DIR.iterdir():
            if f.is_file() and not f.name.endswith(".part") and not f.name.startswith("."):
                is_stream = f.name.startswith("stream_") and f.name != "stream_test_ok.mp4"
                raw_name = f.stem
                if is_stream:
                    clean_name = f"⚡ Стрім ({raw_name[7:17]})"
                else:
                    clean_name = raw_name.replace("_", " ").replace("-", " ").title()

                size_mb = round(f.stat().st_size / (1024 * 1024), 2)
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
                item = {
                    "filename": f.name,
                    "title": clean_name,
                    "size_mb": size_mb,
                    "modified": mtime,
                    "ext": f.suffix.lower(),
                    "is_stream": is_stream,
                    "url": f"http://{local_ip}:5000/media/{f.name}"
                }
                if is_stream:
                    stream_files.append(item)
                else:
                    media_files.append(item)

    media_files.sort(key=lambda x: x["modified"], reverse=True)
    stream_files.sort(key=lambda x: x["modified"], reverse=True)

    all_streams = request.args.get("all_streams", default="0") == "1"
    visible_streams = stream_files if all_streams else stream_files[:6]

    combined = media_files + visible_streams
    return jsonify({
        "success": True,
        "media": combined,
        "media_count": len(media_files),
        "streams_count": len(stream_files),
        "total_count": len(media_files) + len(stream_files)
    })


@app.route("/api/media/delete", methods=["POST"])
@require_auth
def media_delete():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"success": False, "response": "Не вказано файл"}), 400

    target = (MEDIA_DIR / filename).resolve()
    media_dir_resolved = str(MEDIA_DIR.resolve())
    if not str(target).startswith(media_dir_resolved + "/") or not target.is_file():
        return jsonify({"success": False, "response": "Файл не знайдено"}), 404

    try:
        target.unlink()
        return jsonify({"success": True, "response": f"Файл {filename} видалено"})
    except Exception as e:
        return jsonify({"success": False, "response": f"Помилка видалення: {e}"}), 500


@app.route("/api/media/cleanup", methods=["POST"])
@require_auth
def media_cleanup():
    """Purge temporary cached stream files (stream_*.mp4) to free space."""
    deleted = 0
    freed_bytes = 0
    if MEDIA_DIR.exists():
        for f in MEDIA_DIR.iterdir():
            if f.is_file() and (f.name.startswith("stream_") or f.name.endswith(".part")) and f.name != "stream_test_ok.mp4":
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    deleted += 1
                    freed_bytes += sz
                except Exception:
                    pass

    freed_mb = round(freed_bytes / (1024 * 1024), 2)
    return jsonify({
        "success": True,
        "deleted_count": deleted,
        "freed_mb": freed_mb,
        "response": f"Видалено {deleted} тимчасових стрімів (звільнено {freed_mb} MB)"
    })


@app.route("/api/media/play", methods=["POST"])
@require_auth
def media_play():
    try:
        data = request.get_json(silent=True) or {}
        filename = data.get("filename")
        url = data.get("url")
        if not url and filename:
            local_ip = get_local_ip()
            url = f"http://{local_ip}:5000/media/{filename}"

        if not url:
            return jsonify({"success": False, "response": "Не вказано файл або URL"}), 400

        success = garage.projector.play_video(url)
        return jsonify({
            "success": success,
            "playing": filename or url,
            "response": "Відтворення запущено на проекторі" if success else "Не вдалося запустити відтворення на проекторі"
        })
    except Exception as e:
        return jsonify({"success": False, "response": f"Помилка відтворення: {str(e)}"}), 500


@app.route("/api/media/control", methods=["POST"])
@require_auth
def media_control():
    try:
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        if action == "stop":
            garage.projector.stop_video()
            return jsonify({"success": True, "response": "Відтворення зупинено"})
        elif action == "pause":
            garage.projector.pause_video()
            return jsonify({"success": True, "response": "Пауза"})
        elif action == "resume":
            garage.projector.resume_video()
            return jsonify({"success": True, "response": "Продовжено"})
        elif action == "volume":
            val = data.get("value", 80)
            garage.projector.set_volume(val)
            return jsonify({"success": True, "response": f"Гучність: {val}%"})
        return jsonify({"success": False, "response": f"Невідома дія: {action}"}), 400
    except Exception as e:
        return jsonify({"success": False, "response": f"Помилка керування медіа: {str(e)}"}), 500


@app.route("/api/media/stream_url", methods=["POST"])
@require_auth
def media_stream_url():
    try:
        data = request.get_json(silent=True) or {}
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"success": False, "response": "Вкажіть пошуковий запит або посилання"}), 400

        success, stream_url = garage.projector.stream_online_video(query)
        return jsonify({
            "success": success,
            "url": stream_url,
            "response": f"Стрім запущено: {query}" if success else f"Не вдалося завантажити або відтворити: {query}"
        })
    except Exception as e:
        return jsonify({"success": False, "response": f"Помилка стріму: {str(e)}"}), 500


@app.route("/api/projector/status", methods=["GET"])
def projector_status():
    status = garage.projector.get_status()
    status["local_ip"] = get_local_ip()
    return jsonify({"success": True, "projector": status})


@app.route("/api/projector/mirror", methods=["POST"])
@require_auth
def projector_mirror():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "toggle")
    if action == "start":
        garage.projector.start_mirroring()
    elif action == "stop":
        garage.projector.stop_mirroring()
    else:
        if garage.projector.mirroring:
            garage.projector.stop_mirroring()
        else:
            garage.projector.start_mirroring()
    return jsonify({"success": True, "mirroring": garage.projector.mirroring})


@app.route("/command", methods=["POST"])
def command():
    ip = get_client_ip()
    is_limited, wait_sec = command_rate_limiter.is_rate_limited(ip)
    if is_limited:
        audit_log("web", "command_ratelimited", "BLOCKED", {"ip": ip, "wait_sec": wait_sec})
        return jsonify({
            "success": False,
            "response": f"Забагато команд. Зачекайте {wait_sec} сек."
        }), 429

    data = request.get_json(silent=True) or {}

    command_text = data.get("command")
    if not command_text:
        return jsonify({
            "success": False,
            "response": "Missing command"
        }), 400

    import secrets

    from server.ai.session_manager import is_safe_session_id

    client_sid = data.get("session_id")
    is_browser_session = bool(session.get("authenticated"))

    if is_browser_session:
        if "dialog_session_id" not in session or not is_safe_session_id(session.get("dialog_session_id", "")):
            session["dialog_session_id"] = f"web_{secrets.token_hex(16)}"
            session.permanent = True
            session.modified = True

        server_sid = session["dialog_session_id"]

        if client_sid:
            if client_sid != server_sid or not is_safe_session_id(client_sid):
                cid = request.headers.get("X-Correlation-ID", "")
                audit_log("web", "session_hijack_blocked", "BLOCKED", {
                    "client_sid": client_sid,
                    "server_sid": server_sid
                }, cid, server_sid)
                return jsonify({
                    "success": False,
                    "response": "Помилка безпеки: підміна session_id заборонена."
                }), 403
            effective_sid = client_sid
        else:
            effective_sid = server_sid
    else:
        if client_sid:
            if not is_safe_session_id(client_sid):
                return jsonify({
                    "success": False,
                    "response": "Некоректний або небезпечний формат session_id."
                }), 400
            if client_sid.startswith("web_"):
                return jsonify({
                    "success": False,
                    "response": "Префікс 'web_' зарезервовано для браузерних сесій."
                }), 403
            effective_sid = client_sid
        else:
            effective_sid = f"api_{secrets.token_hex(16)}"

    response = garage.router.execute(command_text, session_id=effective_sid)
    if not response:
        return jsonify({
            "success": True,
            "response": "",
            "ignored": True,
            "session_id": effective_sid
        })

    return jsonify({
        "success": True,
        "response": response,
        "session_id": effective_sid
    })


# --- VOICE INTERFACE API ---
@app.route("/api/voice/command", methods=["POST"])
@require_auth
def voice_command():
    """Endpoint for recognized voice commands from voice_listener service."""
    data = request.get_json(silent=True) or {}
    command_text = (data.get("command") or data.get("text") or "").strip()
    source = data.get("source", "voice")

    if not command_text:
        return jsonify({
            "success": False,
            "response": "Відсутній текст голосової команди"
        }), 400

    response = garage.process_voice_command(command_text, source=source)
    return jsonify({
        "success": True,
        "source": source,
        "command": command_text,
        "response": response
    })


@app.route("/api/voice/status", methods=["GET"])
def voice_status():
    """Status and metrics of the voice interface queue."""
    stats = garage.voice_queue.get_stats() if hasattr(garage, "voice_queue") else {}
    return jsonify({
        "success": True,
        "stats": stats
    })


@app.route("/api/voice/tts", methods=["GET", "POST"])
def voice_tts():
    """Generates and streams high-definition neural Ukrainian speech (MP3/WAV) for web clients."""
    ip = get_client_ip()
    is_limited, wait_sec = tts_rate_limiter.is_rate_limited(ip)
    if is_limited:
        audit_log("web", "tts_ratelimited", "BLOCKED", {"ip": ip, "wait_sec": wait_sec})
        return jsonify({
            "success": False,
            "error": f"Перевищено ліміт запитів генерації мовлення. Зачекайте {wait_sec} сек."
        }), 429

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        text = data.get("text") or ""
        voice = data.get("voice")
        provider = data.get("provider")
    else:
        text = request.args.get("text", "")
        voice = request.args.get("voice")
        provider = request.args.get("provider")

    if not (text and text.strip()):
        return jsonify({"success": False, "error": "Порожній текст"}), 400

    try:
        result = tts_manager.synthesize(text, provider_name=provider, voice_id=voice)
        resp = Response(result.audio_bytes, mimetype=result.content_type)
        resp.headers["X-TTS-Provider"] = result.provider
        resp.headers["X-TTS-Voice"] = result.voice_id
        resp.headers["X-TTS-Fallback"] = "true" if result.fallback_used else "false"
        if result.fallback_reason:
            resp.headers["X-TTS-Fallback-Reason"] = urllib.parse.quote(result.fallback_reason[:200])
        resp.headers["X-TTS-Cached"] = "true" if result.cached else "false"
        return resp
    except Exception as e:
        app.logger.warning(f"TTS synthesis error: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "fallback_to_browser": True
        }), 503


@app.route("/api/voice/providers", methods=["GET"])
def voice_providers():
    """Returns available TTS providers, active provider and voices status."""
    status = tts_manager.get_providers_status()
    return jsonify({"success": True, **status})


@app.route("/api/voice/config", methods=["GET", "POST"])
@require_auth
def voice_config():
    """Inspect or configure active server-side TTS provider and voice."""
    if request.method == "GET":
        return jsonify({
            "success": True,
            "active_provider": tts_manager.active_provider_name,
            "active_voice_id": tts_manager.active_voice_id,
            "fallback_provider": tts_manager.fallback_provider_name,
        })

    data = request.get_json(silent=True) or {}
    provider = data.get("provider")
    voice_id = data.get("voice_id")
    if provider:
        if not tts_manager.set_active_provider(provider):
            return jsonify({"success": False, "error": f"Невідомий провайдер TTS: {provider}"}), 400
    if voice_id:
        tts_manager.set_active_voice(voice_id)
    return jsonify({
        "success": True,
        "active_provider": tts_manager.active_provider_name,
        "active_voice_id": tts_manager.active_voice_id,
        "fallback_provider": tts_manager.fallback_provider_name,
    })


@app.route("/api/voice/preview", methods=["POST"])
@require_auth
def voice_preview():
    """Developer preview endpoint to synthesize test phrases with chosen provider/voice."""
    ip = get_client_ip()
    is_limited, wait_sec = tts_rate_limiter.is_rate_limited(ip)
    if is_limited:
        audit_log("web", "tts_ratelimited", "BLOCKED", {"ip": ip, "wait_sec": wait_sec})
        return jsonify({
            "success": False,
            "error": f"Перевищено ліміт запитів генерації мовлення. Зачекайте {wait_sec} сек."
        }), 429

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    provider = data.get("provider")
    voice = data.get("voice")

    if not text:
        text = "Світло в гаражі увімкнено."

    try:
        result = tts_manager.synthesize(text, provider_name=provider, voice_id=voice, use_cache=False)
        resp = Response(result.audio_bytes, mimetype=result.content_type)
        resp.headers["X-TTS-Provider"] = result.provider
        resp.headers["X-TTS-Voice"] = result.voice_id
        resp.headers["X-TTS-Fallback"] = "true" if result.fallback_used else "false"
        return resp
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/voice/speak", methods=["POST"])
def voice_speak():
    """Server-side TTS announcement via neural TTS to Bluetooth/PipeWire output."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = data.get("voice")
    if not text:
        return jsonify({"success": False, "error": "Порожній текст"}), 400

    clean = clean_text_for_tts(text)
    if not clean:
        return jsonify({"success": False, "error": "Порожній текст після очищення"}), 400

    neural_tts.speak_locally(clean, voice=voice)
    return jsonify({"success": True, "spoken": clean})


# --- BLUETOOTH SPEAKER API (JBL Clip 5) ---
@app.route("/api/speaker/status", methods=["GET"])
def speaker_status():
    status = garage.speaker.get_status()
    return jsonify({"success": True, "speaker": status})


@app.route("/api/speaker/connect", methods=["POST"])
@require_auth
def speaker_connect():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")
    if mac and mac.upper() != garage.speaker.mac.upper():
        ok = garage.speaker.switch_speaker(mac)
    else:
        ok = garage.speaker.connect(mac)
    spk_name = garage.speaker.name or "Колонка"
    return jsonify({
        "success": ok,
        "connected": garage.speaker.is_connected(),
        "mac": garage.speaker.mac,
        "name": spk_name,
        "playing": garage.speaker.is_playing(),
        "response": f"{spk_name} підключено" if ok else f"Не вдалося підключити {spk_name}"
    })


@app.route("/api/speaker/switch", methods=["POST"])
@require_auth
def speaker_switch():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")
    if not mac:
        return jsonify({"success": False, "response": "Не вказано MAC-адресу колонки"}), 400
    ok = garage.speaker.switch_speaker(mac)
    spk_name = garage.speaker.name or "Колонка"
    return jsonify({
        "success": ok,
        "connected": garage.speaker.is_connected(),
        "mac": garage.speaker.mac,
        "name": spk_name,
        "playing": garage.speaker.is_playing(),
        "response": f"Аудіо перемкнуто на {spk_name}" if ok else f"Не вдалося підключити {spk_name}"
    })


@app.route("/api/speaker/disconnect", methods=["POST"])
@require_auth
def speaker_disconnect():
    spk_name = garage.speaker.name or "Колонку"
    ok = garage.speaker.disconnect()
    return jsonify({
        "success": ok,
        "connected": False,
        "response": f"{spk_name} відключено"
    })


@app.route("/api/speaker/volume", methods=["POST"])
@require_auth
def speaker_volume():
    data = request.get_json(silent=True) or {}
    val = data.get("value", data.get("volume", data.get("val", 33)))
    ok = garage.speaker.set_volume(val)
    return jsonify({
        "success": ok,
        "volume": garage.speaker.get_volume(),
        "response": f"Гучність встановлено: {val}%"
    })


@app.route("/api/speaker/play", methods=["POST"])
@require_auth
def speaker_play():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")
    if mac:
        garage.speaker.set_active_speaker(mac)
    query = data.get("query") or data.get("filename") or ""
    query = query.strip()
    if not query:
        return jsonify({"success": False, "response": "Вкажіть назву треку або файл"}), 400

    ok = garage.speaker.play_youtube(query)
    spk_name = garage.speaker.name or "колонці"
    return jsonify({
        "success": ok,
        "playing": garage.speaker.is_playing(),
        "response": f"Грає на {spk_name}: {query}" if ok else f"Не вдалося запустити на {spk_name}: {query}"
    })


@app.route("/api/speaker/control", methods=["POST"])
@require_auth
def speaker_control():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "stop")
    if action == "stop":
        garage.speaker.stop()
        return jsonify({"success": True, "response": "Зупинено"})
    elif action == "pause":
        garage.speaker.pause()
        return jsonify({"success": True, "response": "Пауза"})
    elif action == "resume":
        garage.speaker.resume()
        return jsonify({"success": True, "response": "Продовжено"})
    elif action == "next":
        ok, p_title, t_title = garage.speaker.play_next()
        return jsonify({"success": ok, "track_title": t_title, "response": f"Наступний: {t_title}" if ok else "Помилка перемикання"})
    elif action == "prev":
        ok, p_title, t_title = garage.speaker.play_prev()
        return jsonify({"success": ok, "track_title": t_title, "response": f"Попередній: {t_title}" if ok else "Помилка перемикання"})
    elif action == "seek":
        pos = data.get("position", 0)
        ok = garage.speaker.seek(int(pos))
        return jsonify({"success": ok, "position": pos, "response": f"Перемотано на {pos}с"})
    return jsonify({"success": False, "response": f"Невідома дія: {action}"}), 400


@app.route("/api/speaker/seek", methods=["POST"])
@require_auth
def speaker_seek():
    data = request.get_json(silent=True) or {}
    pos = data.get("position")
    delta = data.get("delta")

    if not hasattr(garage, "speaker") or not garage.speaker:
        return jsonify({"success": False, "error": "Колонка недоступна"}), 500

    if delta is not None:
        st = garage.speaker.get_status()
        current_elapsed = st.get("elapsed_seconds", 0)
        pos = max(0, current_elapsed + int(delta))

    if pos is None:
        return jsonify({"success": False, "error": "Не вказано позицію для перемотування"}), 400

    ok = garage.speaker.seek(int(pos))
    return jsonify({
        "success": ok,
        "position": int(pos),
        "status": garage.speaker.get_status()
    })


@app.route("/api/speaker/prev", methods=["POST"])
@require_auth
def speaker_prev():
    if not hasattr(garage, "speaker") or not garage.speaker:
        return jsonify({"success": False, "error": "Колонка недоступна"}), 500
    ok, p_title, t_title = garage.speaker.play_prev()
    return jsonify({
        "success": ok,
        "playing": garage.speaker.is_playing(),
        "playlist_title": p_title,
        "track_title": t_title,
        "response": f"⏮ Попередній трек: {t_title}" if ok else "Не вдалося перемкнути на попередній трек"
    })



# --- INTERNET RADIO API (Radio Browser) ---
@app.route("/api/radio/stations", methods=["GET"])
def radio_stations():
    limit = request.args.get("limit", default=24, type=int)
    country = request.args.get("country", default="UA", type=str)
    stations = radio_service.get_top_stations(limit=limit, country_code=country)
    return jsonify({"success": True, "stations": stations})


@app.route("/api/radio/search", methods=["GET"])
def radio_search():
    q = request.args.get("q", default="", type=str).strip()
    limit = request.args.get("limit", default=20, type=int)
    stations = radio_service.search_stations(query=q, limit=limit)
    return jsonify({"success": True, "stations": stations})


@app.route("/api/radio/play", methods=["POST"])
@require_auth
def radio_play():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")
    if mac:
        garage.speaker.set_active_speaker(mac)
    url = data.get("url", "").strip()
    name = data.get("name", "Інтернет-радіо").strip()
    if not url:
        return jsonify({"success": False, "response": "Не вказано URL потоку"}), 400

    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in ("http", "https"):
        return jsonify({"success": False, "response": "Неприпустима схема URL (дозволено лише http:// та https://)"}), 400

    ok = garage.speaker.play_stream(url, track_title=name)
    spk_name = garage.speaker.name or "колонці"
    return jsonify({
        "success": ok,
        "playing": garage.speaker.is_playing(),
        "response": f"Трансляція {name} на {spk_name}" if ok else f"Не вдалося підключити {spk_name} (пристрій не відповідає)"
    })


# --- YOUTUBE MUSIC API ---
@app.route("/api/ytmusic/playlists", methods=["GET"])
def ytmusic_playlists():
    refresh = request.args.get("refresh", default="0").lower() in ("1", "true", "yes")
    playlists = ytmusic_service.get_user_playlists(force_refresh=refresh)
    return jsonify({
        "success": True,
        "playlists": playlists,
        "current_playlist_id": ytmusic_service.current_playlist_id
    })


@app.route("/api/ytmusic/playlist/<playlist_id>/tracks", methods=["GET"])
def ytmusic_playlist_tracks(playlist_id):
    refresh = request.args.get("refresh", default="0").lower() in ("1", "true", "yes")
    tracks = ytmusic_service.get_playlist_tracks(playlist_id, force_refresh=refresh)
    return jsonify({
        "success": True,
        "playlist_id": playlist_id,
        "count": len(tracks),
        "tracks": tracks
    })


@app.route("/api/ytmusic/play", methods=["POST"])
@require_auth
def ytmusic_play():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")
    if mac and hasattr(garage, "speaker"):
        garage.speaker.set_active_speaker(mac)

    playlist_id = data.get("playlist_id")
    track_id = data.get("track_id")
    track_title = data.get("track_title")
    uploader = data.get("uploader", "")
    query = data.get("query", "").strip()
    shuffle = data.get("shuffle", False)

    spk_name = garage.speaker.name if hasattr(garage, "speaker") else "колонці"

    # Track from a playlist requested
    if playlist_id:
        target_pl = playlist_id
        if track_id:
            ok, p_title, t_title = garage.speaker.play_playlist(target_pl, shuffle=shuffle, track_id=track_id)
        else:
            ok, p_title, t_title = garage.speaker.play_playlist(target_pl, shuffle=shuffle)
        if not ok and (track_title or track_id):
            t_display = track_title or track_id
            target_query = f"{track_title} {uploader}".strip() if uploader else track_title if track_title else f"https://www.youtube.com/watch?v={track_id}"
            ok = garage.speaker.play_youtube(target_query, track_title=t_display)
            p_title = target_pl
            t_title = t_display

        return jsonify({
            "success": ok,
            "playing": garage.speaker.is_playing() if hasattr(garage, "speaker") else False,
            "playlist_id": target_pl,
            "playlist_title": p_title,
            "track_title": t_title,
            "response": f"Грає '{t_title}' з '{p_title}' на {spk_name}" if ok else f"Не вдалося запустити трек на {spk_name}"
        })

    # Specific track requested without playlist
    if track_title or query or track_id:
        if track_title:
            target_query = f"{track_title} {uploader}".strip() if uploader else track_title
            if target_query.endswith(" - Topic"):
                target_query = target_query[:-8]
            t_display = track_title
        elif query:
            target_query = query
            t_display = query
        else:
            target_query = f"https://www.youtube.com/watch?v={track_id}"
            t_display = track_id

        ok = garage.speaker.play_youtube(target_query, track_title=t_display)
        return jsonify({
            "success": ok,
            "playing": garage.speaker.is_playing() if hasattr(garage, "speaker") else False,
            "track_title": t_display,
            "response": f"Грає '{t_display}' на {spk_name}" if ok else f"Не вдалося запустити на {spk_name}"
        })

    # Liked songs or playlist fallback
    target_pl = "LM"
    ok, p_title, t_title = garage.speaker.play_playlist(target_pl, shuffle=shuffle)
    return jsonify({
        "success": ok,
        "playing": garage.speaker.is_playing() if hasattr(garage, "speaker") else False,
        "playlist_id": target_pl,
        "playlist_title": p_title,
        "track_title": t_title,
        "response": f"Грає '{t_title}' з '{p_title}' на {spk_name}" if ok else f"Не вдалося запустити плейлист на {spk_name}"
    })


@app.route("/api/ytmusic/next", methods=["POST"])
@require_auth
def ytmusic_next():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")
    if mac and hasattr(garage, "speaker"):
        garage.speaker.set_active_speaker(mac)
    shuffle = data.get("shuffle")

    ok, p_title, t_title = garage.speaker.play_next(shuffle=shuffle)
    spk_name = garage.speaker.name if hasattr(garage, "speaker") else "колонці"
    return jsonify({
        "success": ok,
        "playing": garage.speaker.is_playing() if hasattr(garage, "speaker") else False,
        "playlist_title": p_title,
        "track_title": t_title,
        "response": f"Наступний трек: '{t_title}' на {spk_name}" if ok else f"Не вдалося перемкнути трек на {spk_name}"
    })


@app.route("/api/ytmusic/prev", methods=["POST"])
@require_auth
def ytmusic_prev():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")
    if mac and hasattr(garage, "speaker"):
        garage.speaker.set_active_speaker(mac)
    shuffle = data.get("shuffle")

    ok, p_title, t_title = garage.speaker.play_prev(shuffle=shuffle)
    spk_name = garage.speaker.name if hasattr(garage, "speaker") else "колонці"
    return jsonify({
        "success": ok,
        "playing": garage.speaker.is_playing() if hasattr(garage, "speaker") else False,
        "playlist_title": p_title,
        "track_title": t_title,
        "response": f"Попередній трек: '{t_title}' на {spk_name}" if ok else f"Не вдалося повернутися до попереднього треку на {spk_name}"
    })


@app.route("/api/ytmusic/status", methods=["GET"])
def ytmusic_status():
    spk_status = garage.speaker.get_status() if hasattr(garage, "speaker") else {}
    autoplay = getattr(garage.speaker, "_playlist_autoplay", False) if hasattr(garage, "speaker") else False
    p_id = getattr(garage.speaker, "_playlist_id", None) or ytmusic_service.current_playlist_id
    upcoming = ytmusic_service.get_upcoming_track(p_id) if (autoplay or p_id) else None
    return jsonify({
        "success": True,
        "current_playlist_id": ytmusic_service.current_playlist_id,
        "current_playlist_title": ytmusic_service.current_playlist_title,
        "current_track": spk_status.get("current_track"),
        "playing": garage.speaker.is_playing() if hasattr(garage, "speaker") else False,
        "paused": spk_status.get("paused", False),
        "autoplay": autoplay,
        "elapsed_seconds": spk_status.get("elapsed_seconds", 0),
        "duration_seconds": spk_status.get("duration_seconds", 0),
        "upcoming_track": upcoming,
        "speaker": spk_status
    })



if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except Exception:
        logger.error("Exception when running server:")
        logger.error(traceback.format_exc())
