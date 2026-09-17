from pathlib import Path
import time
from collections import deque
import threading
import traceback
import urllib.parse
import psutil
from flask import Flask, request, jsonify, render_template, send_from_directory
from .core.core import SmartGarage
from .devices.projector import get_local_ip
from server.config import config
from server.services.radio_service import radio_service


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
garage = SmartGarage()
telemetry_history = TelemetryHistory()
MEDIA_DIR = Path(__file__).parent.parent / "media"


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
        "tailscale_ip": "100.122.57.39"
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
@app.route("/floor1")
def dashboard():
    return render_template("dashboard.html")


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
def toggle_light():
    state = garage.esp32.light_toggle()
    return jsonify({"success": True, "light": state})


@app.route("/api/device/light/state", methods=["POST"])
def set_light():
    data = request.get_json(silent=True) or {}
    on = data.get("state", True)
    state = garage.esp32.light_on() if on else garage.esp32.light_off()
    return jsonify({"success": True, "light": state})


@app.route("/api/device/fan/toggle", methods=["POST"])
def toggle_fan():
    state = garage.esp32.fan_toggle()
    return jsonify({"success": True, "fan": state})


@app.route("/api/device/door/toggle", methods=["POST"])
def toggle_door():
    state = garage.esp32.door_toggle()
    return jsonify({"success": True, "door": state})


@app.route("/media/<path:filename>")
def serve_media(filename):
    return send_from_directory(MEDIA_DIR, filename)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/garage/state", methods=["GET"])
def garage_state():
    state = garage.esp32.get_telemetry()
    bt_telemetry = garage.bt_sensors.get_telemetry() if hasattr(garage, "bt_sensors") else {}

    floors = bt_telemetry.get("floors", {})
    # If ESP32 reports floors from its BLE reads, merge with higher priority or fallback
    esp_floors = state.get("floors", {})
    if isinstance(esp_floors, dict):
        for fk, fval in esp_floors.items():
            if isinstance(fval, dict) and fval.get("mac"):
                is_esp_online = bool(fval.get("online", False))
                if is_esp_online and fval.get("temperature") is not None:
                    if fk not in floors:
                        floors[fk] = dict(fval)
                    else:
                        floors[fk]["temperature"] = fval["temperature"]
                        floors[fk]["humidity"] = fval.get("humidity", floors[fk].get("humidity"))
                        floors[fk]["battery"] = fval.get("battery", floors[fk].get("battery"))
                        floors[fk]["online"] = True
                    floors[fk]["last_updated"] = fval.get("last_updated") or time.time()
                    floors[fk]["source"] = "esp32"
                elif not is_esp_online and fk in floors:
                    # Sensor is confirmed offline by ESP32; ensure online is False
                    floors[fk]["online"] = False

    # Mark uninstalled floors clearly (e.g. Floor 1 currently has no physical sensor)
    if "floor1" not in floors or not floors["floor1"].get("mac"):
        if "floor1" not in floors:
            floors["floor1"] = {}
        floors["floor1"]["name"] = "1-й поверх (Гараж)"
        floors["floor1"]["temperature"] = None
        floors["floor1"]["humidity"] = None
        floors["floor1"]["online"] = False
        floors["floor1"]["battery"] = None
        floors["floor1"]["installed"] = False
        floors["floor1"]["status_text"] = "Очікує датчик"

    # Format human-readable update times for all floors
    for fk, f in floors.items():
        lu = f.get("last_updated")
        if lu and f.get("temperature") is not None:
            f["last_updated_formatted"] = time.strftime("%H:%M:%S (%d.%m.%Y)", time.localtime(lu))
            f["last_updated_time"] = time.strftime("%H:%M:%S", time.localtime(lu))
        else:
            f["last_updated_formatted"] = "Очікує встановлення" if not f.get("mac") else "Очікується оновлення"
            f["last_updated_time"] = "--:--"

    # Primary climate resolution: pick real active sensor
    primary_temp = None
    primary_hum = None
    primary_name = "Підвал"
    primary_lu = None
    for pref_floor in ("basement", "floor2", "floor1"):
        if pref_floor in floors and floors[pref_floor].get("temperature") is not None and floors[pref_floor].get("online", False):
            primary_temp = floors[pref_floor]["temperature"]
            primary_hum = floors[pref_floor]["humidity"]
            primary_name = floors[pref_floor]["name"]
            primary_lu = floors[pref_floor].get("last_updated")
            break

    state["temperature"] = primary_temp
    state["humidity"] = primary_hum

    # Mark uninstalled GPIO hardware clearly so UI doesn't display floating pin noise
    state["gas_ppm"] = None
    state["gas_installed"] = False
    state["distance_cm"] = None
    state["car_present"] = None
    state["car_sensor_installed"] = False
    state["motion_detected"] = None
    state["motion_installed"] = False
    state["door"] = "not_installed"
    state["door_installed"] = False
    state["relays_installed"] = False

    state["bluetooth_sensors"] = bt_telemetry.get("devices", [])
    state["floors"] = floors
    state["primary_sensor"] = {
        "name": primary_name,
        "temperature": primary_temp,
        "humidity": primary_hum,
        "online": True if primary_temp is not None else False,
        "last_updated": primary_lu,
        "last_updated_formatted": time.strftime("%H:%M:%S (%d.%m.%Y)", time.localtime(primary_lu)) if primary_lu else "--"
    }
    state["speaker"] = garage.speaker.get_status() if hasattr(garage, "speaker") else {}

    # Record point into telemetry history only if real readings exist
    if primary_temp is not None:
        telemetry_history.add(temp=primary_temp, hum=primary_hum or 0, door="closed", light=False, car=False)

    # Persist all active floor measurements into SQLite
    if hasattr(garage, "telemetry_db") and garage.telemetry_db:
        for fk, fval in floors.items():
            if isinstance(fval, dict) and fval.get("temperature") is not None and fval.get("online"):
                garage.telemetry_db.record(
                    floor=fk,
                    temperature=fval.get("temperature"),
                    humidity=fval.get("humidity"),
                    battery=fval.get("battery"),
                    mac=fval.get("mac"),
                    sensor_name=fval.get("name")
                )

    return jsonify({
        "success": True,
        "state": state
    })


@app.route("/api/sensors/floors", methods=["GET"])
def sensors_floors():
    if hasattr(garage, "get_floors_telemetry"):
        floors = garage.get_floors_telemetry()
    else:
        bt_telemetry = garage.bt_sensors.get_telemetry() if hasattr(garage, "bt_sensors") else {}
        floors = bt_telemetry.get("floors", {})
    return jsonify({
        "success": True,
        "floors": floors
    })


@app.route("/api/sensors/refresh", methods=["POST"])
def sensors_refresh():
    if hasattr(garage, "bt_sensors") and garage.bt_sensors:
        data = request.get_json(silent=True) or {}
        mac = data.get("mac")
        garage.bt_sensors.poll_on_demand(mac)
        return jsonify({"success": True, "message": "On-demand sensor polling triggered"})
    return jsonify({"success": False, "error": "Sensor manager not available"}), 500


@app.route("/api/sensors/bind", methods=["POST"])
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
    data = request.get_json(silent=True) or {}
    success = garage.esp32.update_from_webhook(data)
    if success:
        garage.automation.evaluate_telemetry(data)
        # Update cache from ESP32 BLE reading if present
        if "floors" in data and hasattr(garage, "bt_sensors") and garage.bt_sensors:
            with garage.bt_sensors._lock:
                for fk, fval in data["floors"].items():
                    mac = fval.get("mac")
                    if mac and mac in garage.bt_sensors.sensors:
                        s = garage.bt_sensors.sensors[mac]
                        if fval.get("temperature") is not None:
                            s["temperature"] = fval["temperature"]
                        if fval.get("humidity") is not None:
                            s["humidity"] = fval["humidity"]
                        if fval.get("battery") is not None:
                            s["battery"] = fval["battery"]
                        s["online"] = fval.get("online", True)
                        s["last_updated"] = time.time()
                garage.bt_sensors._save_cache()

            # Record into SQLite TelemetryDB
            if hasattr(garage, "telemetry_db") and garage.telemetry_db:
                for fk, fval in data["floors"].items():
                    if isinstance(fval, dict) and fval.get("temperature") is not None:
                        garage.telemetry_db.record(
                            floor=fk,
                            temperature=fval["temperature"],
                            humidity=fval.get("humidity"),
                            battery=fval.get("battery"),
                            mac=fval.get("mac"),
                            sensor_name=fval.get("name")
                        )

        temp = data.get("temperature", 21.3)
        hum = data.get("humidity", 63.0)
        door = garage.esp32.state.get("door", "closed")
        light = garage.esp32.state.get("light", False)
        car = data.get("car_present", False)
        telemetry_history.add(temp=temp, hum=hum, door=door, light=light, car=car)
        if hasattr(garage, "telemetry_db") and garage.telemetry_db and "floors" not in data:
            garage.telemetry_db.record(floor="basement", temperature=temp, humidity=hum)

    return jsonify({
        "success": success,
        "status": "received"
    })


def _scan_all_ble(duration: int = 15) -> list:
    """Hybrid scanner combining ESP32 BLE scan and Host Bluetooth (Bleak) scan."""
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

    # Also check known Classic BT devices (e.g. Owner phone)
    if hasattr(garage, "presence") and garage.presence:
        with garage.presence._lock:
            classic_list = [
                (dev_id, dev.get("classic_mac", ""))
                for dev_id, dev in garage.presence.devices.items()
                if dev.get("classic_mac")
            ]
        for dev_id, cmac in classic_list:
            if cmac:
                cmac_upper = cmac.upper().strip()
                cname = garage.presence._check_classic_mac(cmac_upper)
                if cname and cmac_upper not in merged:
                    merged[cmac_upper] = {
                        "mac": cmac_upper,
                        "name": cname,
                        "rssi": -50,
                        "service_uuids": [],
                        "source": "bluetooth_classic"
                    }

    all_devices = sorted(merged.values(), key=lambda x: x.get("rssi", -99), reverse=True)

    if hasattr(garage, "presence") and garage.presence:
        for d in all_devices:
            garage.presence.record_sighting(
                mac=d.get("mac", ""),
                name=d.get("name", ""),
                rssi=d.get("rssi"),
                service_uuids=d.get("service_uuids", []),
                source=d.get("source", "ble_scan")
            )

    return all_devices


@app.route("/api/esp32/scan_ble", methods=["GET", "POST"])
def esp32_scan_ble():
    duration = int(request.args.get("duration", 15))
    if duration <= 0:
        duration = 10
    devices = _scan_all_ble(duration=duration)
    return jsonify({
        "success": True,
        "count": len(devices),
        "devices": devices
    })


@app.route("/api/presence/status", methods=["GET"])
def presence_status():
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    return jsonify({
        "success": True,
        "presence": garage.presence.get_status()
    })


@app.route("/api/presence/log", methods=["GET"])
def presence_log():
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    limit = int(request.args.get("limit", 50))
    return jsonify({
        "success": True,
        "log": garage.presence.get_log(limit=limit)
    })


@app.route("/api/presence/devices", methods=["POST"])
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
        auto_welcome=data.get("auto_welcome", False)
    )
    return jsonify({"success": True, "device": item})


@app.route("/api/presence/devices/<device_id>", methods=["DELETE"])
def presence_remove_device(device_id):
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    removed = garage.presence.remove_device(device_id)
    return jsonify({"success": removed})


@app.route("/api/presence/scan", methods=["POST"])
def presence_scan_and_record():
    if not hasattr(garage, "presence") or not garage.presence:
        return jsonify({"success": False, "error": "Presence manager not available"}), 500
    duration = int(request.args.get("duration", 15))
    if duration <= 0:
        duration = 10
    devices = _scan_all_ble(duration=duration)
    return jsonify({
        "success": True,
        "scanned_count": len(devices),
        "devices": devices,
        "presence": garage.presence.get_status()
    })


@app.route("/api/admin/verify", methods=["POST"])
def admin_verify():
    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", "")).strip()
    admin_cfg = config.get("admin", {}) if isinstance(config, dict) else {}
    expected_pin = str(admin_cfg.get("pin", "7777")).strip()
    if pin and pin == expected_pin:
        return jsonify({"success": True, "authenticated": True})
    return jsonify({"success": False, "error": "Невірний PIN-код"}), 401




@app.route("/api/scenarios/<name>", methods=["POST"])
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
    data = request.get_json(silent=True) or {}

    command_text = data.get("command")
    if not command_text:
        return jsonify({
            "success": False,
            "response": "Missing command"
        }), 400

    response = garage.router.execute(command_text, session_id="web_console")

    return jsonify({
        "success": True,
        "response": response
    })


# --- BLUETOOTH SPEAKER API (JBL Clip 5) ---
@app.route("/api/speaker/status", methods=["GET"])
def speaker_status():
    status = garage.speaker.get_status()
    return jsonify({"success": True, "speaker": status})


@app.route("/api/speaker/connect", methods=["POST"])
def speaker_connect():
    data = request.get_json(silent=True) or {}
    mac = data.get("mac")
    ok = garage.speaker.connect(mac)
    spk_name = garage.speaker.name or "Колонку"
    return jsonify({
        "success": ok,
        "connected": garage.speaker.is_connected(),
        "response": f"{spk_name} підключено" if ok else f"Не вдалося підключити {spk_name}"
    })


@app.route("/api/speaker/disconnect", methods=["POST"])
def speaker_disconnect():
    spk_name = garage.speaker.name or "Колонку"
    ok = garage.speaker.disconnect()
    return jsonify({
        "success": ok,
        "connected": False,
        "response": f"{spk_name} відключено"
    })


@app.route("/api/speaker/volume", methods=["POST"])
def speaker_volume():
    data = request.get_json(silent=True) or {}
    val = data.get("value", data.get("volume", data.get("val", 75)))
    ok = garage.speaker.set_volume(val)
    return jsonify({
        "success": ok,
        "volume": garage.speaker.get_volume(),
        "response": f"Гучність встановлено: {val}%"
    })


@app.route("/api/speaker/play", methods=["POST"])
def speaker_play():
    data = request.get_json(silent=True) or {}
    query = data.get("query") or data.get("filename") or ""
    query = query.strip()
    if not query:
        return jsonify({"success": False, "response": "Вкажіть назву треку або файл"}), 400

    ok = garage.speaker.play_youtube(query)
    return jsonify({
        "success": ok,
        "playing": garage.speaker.is_playing(),
        "response": f"Грає на JBL: {query}" if ok else f"Не вдалося запустити: {query}"
    })


@app.route("/api/speaker/control", methods=["POST"])
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
    return jsonify({"success": False, "response": f"Невідома дія: {action}"}), 400


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
def radio_play():
    data = request.get_json(silent=True) or {}
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
        "response": f"Трансляція {name} на {spk_name}" if ok else f"Не вдалося запустити {name}"
    })



if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error("Exception when running server:")
        logger.error(traceback.format_exc())
