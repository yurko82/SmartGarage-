import time
import socket
import urllib.request
import json
import threading
import os
from typing import Optional
from server.config import config

try:
    import serial
except ImportError:
    serial = None


class ESP32Controller:

    def __init__(self, host=None, port=None, serial_port=None, baudrate=115200, mode=None):
        cfg = config.get("esp32", {}) if isinstance(config, dict) else {}
        self.host = host or cfg.get("host", "192.168.100.222")
        self.port = port or cfg.get("port", 80)
        self.serial_port_name = serial_port or cfg.get("serial_port", "/dev/ttyACM0")
        self.baudrate = baudrate or cfg.get("baudrate", 115200)
        self.mode = mode or ("mock" if os.environ.get("TESTING") else cfg.get("mode", "auto"))  # auto | network | serial | mock
        self._lock = threading.RLock()
        self._serial = None
        self._running = True
        self._reader_thread = None
        self.last_ble_scan_results = None

        # State cache
        self.state = {
            "online": False,
            "door": "closed",         # open | closed | opening | closing
            "light": False,           # True (ON) | False (OFF)
            "fan": False,             # True (ON) | False (OFF)
            "temperature": None,
            "humidity": None,
            "car_present": False,
            "distance_cm": 240,       # Distance to obstacle / car
            "motion_detected": False,
            "gas_ppm": 35,            # Air quality
            "transport": "none",      # serial | http | webhook | simulated
            "last_seen": None,
        }

        # Start serial reader if configured / available
        if self.mode in ("auto", "serial") and serial is not None and not os.environ.get("TESTING"):
            self._start_serial_reader()

    def _start_serial_reader(self):
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_thread = threading.Thread(target=self._serial_worker, daemon=True, name="ESP32-SerialWorker")
        self._reader_thread.start()

    def _serial_worker(self):
        while self._running:
            try:
                if self._serial is None:
                    if os.path.exists(self.serial_port_name):
                        self._serial = serial.Serial(self.serial_port_name, self.baudrate, timeout=1)
                        with self._lock:
                            self.state["online"] = True
                            self.state["transport"] = "serial"
                    else:
                        time.sleep(2)
                        continue

                line = self._serial.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self._parse_serial_line(line)
            except Exception:
                if self._serial:
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                    self._serial = None
                time.sleep(2)

    def _parse_serial_line(self, line: str):
        if line.startswith("TELEMETRY:"):
            raw_json = line[len("TELEMETRY:"):].strip()
            try:
                data = json.loads(raw_json)
                self.update_from_webhook(data)
                self.state["transport"] = "serial"
            except Exception:
                pass
        elif line.startswith("BLE_DEVICE:"):
            # format: BLE_DEVICE:mac=...|name=...|rssi=...|uuid=...
            parts = line[len("BLE_DEVICE:"):].split("|")
            info = {}
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    info[k] = v
            mac = info.get("mac")
            if mac:
                with self._lock:
                    if not hasattr(self, "_active_scan_devices") or self._active_scan_devices is None:
                        self._active_scan_devices = {}
                    try:
                        rssi_val = int(info.get("rssi", -99))
                    except ValueError:
                        rssi_val = -99
                    uuid = info.get("uuid", "")
                    self._active_scan_devices[mac] = {
                        "mac": mac,
                        "name": info.get("name", ""),
                        "rssi": rssi_val,
                        "service_uuids": [uuid] if uuid else []
                    }
        elif "[BLE_SCAN] Completed" in line:
            with self._lock:
                if hasattr(self, "_active_scan_devices") and self._active_scan_devices:
                    self.last_ble_scan_results = list(self._active_scan_devices.values())
                else:
                    self.last_ble_scan_results = []
        elif line.startswith("RESP:"):
            raw_json = line[len("RESP:"):].strip()
            try:
                data = json.loads(raw_json)
                if data.get("type") == "ble_scan":
                    devices = data.get("devices", [])
                    # Firmware reports a single "service_uuid" per device; normalize to the
                    # "service_uuids" list shape expected by presence matching downstream
                    # (server/devices/presence.py record_sighting, server/webapp.py).
                    for dev in devices:
                        uuid = dev.get("service_uuid")
                        dev["service_uuids"] = [uuid] if uuid else []
                    with self._lock:
                        self.last_ble_scan_results = devices
                with self._lock:
                    if "door" in data:
                        self.state["door"] = data["door"]
                    if "light" in data:
                        self.state["light"] = bool(data["light"])
                    if "fan" in data:
                        self.state["fan"] = bool(data["fan"])
                    self.state["last_seen"] = time.time()
                    self.state["online"] = True
            except Exception:
                pass

    def scan_ble(self, duration: int = 15, timeout: Optional[float] = None) -> list:
        """Trigger active BLE scan on the ESP32 hardware and return list of discovered devices."""
        actual_timeout = timeout if timeout is not None else float(duration + 4)
        with self._lock:
            self.last_ble_scan_results = None
            self._active_scan_devices = {}
        ok = self._send_serial_command(f"CMD:SCAN_BLE:{duration}")
        if not ok:
            return []
        start_t = time.time()
        while time.time() - start_t < actual_timeout:
            with self._lock:
                if self.last_ble_scan_results is not None:
                    return self.last_ble_scan_results
            time.sleep(0.5)
        # Timeout fallback - return whatever was collected
        with self._lock:
            if hasattr(self, "_active_scan_devices") and self._active_scan_devices:
                return list(self._active_scan_devices.values())
        return []

    def _send_serial_command(self, cmd: str) -> bool:
        with self._lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.write(f"{cmd}\n".encode("utf-8"))
                    self._serial.flush()
                    return True
                except Exception:
                    return False
            return False

    def is_online(self, timeout=1.0):
        if self.mode == "mock" or os.environ.get("TESTING"):
            return True
        if self._serial and self._serial.is_open:
            return True
        if self.state.get("last_seen") and (time.time() - self.state["last_seen"] < 15):
            return True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            res = s.connect_ex((self.host, int(self.port)))
            s.close()
            online = (res == 0)
            self.state["online"] = online
            return online
        except Exception:
            self.state["online"] = False
            return False

    def _send_request(self, endpoint, data=None, method="GET", timeout=2.0):
        if self.mode == "mock" or os.environ.get("TESTING"):
            return None
        if not self.is_online():
            return None
        url = f"http://{self.host}:{self.port}{endpoint}"
        try:
            body = json.dumps(data).encode("utf-8") if data else None
            headers = {"Content-Type": "application/json"} if data else {}
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                self.state["last_seen"] = time.time()
                self.state["transport"] = "http"
                return json.loads(res.read().decode("utf-8"))
        except Exception:
            return None

    # --- DOOR / GATES ---
    def door_open(self):
        with self._lock:
            if self._send_serial_command("CMD:DOOR_OPEN"):
                self.state["door"] = "open"
                self.state["last_seen"] = time.time()
                return "open"

            remote = self._send_request("/api/door/open", method="POST")
            if remote and "door" in remote:
                self.state["door"] = remote["door"]
            else:
                self.state["door"] = "open"
            return self.state["door"]

    def door_close(self):
        with self._lock:
            if self._send_serial_command("CMD:DOOR_CLOSE"):
                self.state["door"] = "closed"
                self.state["last_seen"] = time.time()
                return "closed"

            remote = self._send_request("/api/door/close", method="POST")
            if remote and "door" in remote:
                self.state["door"] = remote["door"]
            else:
                self.state["door"] = "closed"
            return self.state["door"]

    def door_toggle(self):
        with self._lock:
            target = "open" if self.state["door"] == "closed" else "closed"
            if target == "open":
                return self.door_open()
            return self.door_close()

    # --- LIGHTS ---
    def light_on(self):
        with self._lock:
            if self._send_serial_command("CMD:LIGHT_ON"):
                self.state["light"] = True
                self.state["last_seen"] = time.time()
                return True

            remote = self._send_request("/api/light/on", method="POST")
            if remote and "light" in remote:
                self.state["light"] = bool(remote["light"])
            else:
                self.state["light"] = True
            return self.state["light"]

    def light_off(self):
        with self._lock:
            if self._send_serial_command("CMD:LIGHT_OFF"):
                self.state["light"] = False
                self.state["last_seen"] = time.time()
                return False

            remote = self._send_request("/api/light/off", method="POST")
            if remote and "light" in remote:
                self.state["light"] = bool(remote["light"])
            else:
                self.state["light"] = False
            return self.state["light"]

    def light_toggle(self):
        with self._lock:
            if self.state["light"]:
                return self.light_off()
            return self.light_on()

    # --- FAN / VENTILATION ---
    def fan_on(self):
        with self._lock:
            if self._send_serial_command("CMD:FAN_ON"):
                self.state["fan"] = True
                self.state["last_seen"] = time.time()
                return True

            remote = self._send_request("/api/fan/on", method="POST")
            if remote and "fan" in remote:
                self.state["fan"] = bool(remote["fan"])
            else:
                self.state["fan"] = True
            return self.state["fan"]

    def fan_off(self):
        with self._lock:
            if self._send_serial_command("CMD:FAN_OFF"):
                self.state["fan"] = False
                self.state["last_seen"] = time.time()
                return False

            remote = self._send_request("/api/fan/off", method="POST")
            if remote and "fan" in remote:
                self.state["fan"] = bool(remote["fan"])
            else:
                self.state["fan"] = False
            return self.state["fan"]

    def fan_toggle(self):
        with self._lock:
            if self.state["fan"]:
                return self.fan_off()
            return self.fan_on()

    # --- TELEMETRY & SENSORS ---
    def get_telemetry(self):
        if self._serial and self._serial.is_open:
            self._send_serial_command("CMD:GET_TELEMETRY")

        remote = self._send_request("/api/telemetry", method="GET")
        if remote and isinstance(remote, dict):
            with self._lock:
                self.state.update(remote)
                self.state["online"] = True
        return dict(self.state)

    def update_from_webhook(self, telemetry_dict):
        if isinstance(telemetry_dict, dict):
            with self._lock:
                self.state.update(telemetry_dict)
                self.state["online"] = True
                self.state["last_seen"] = time.time()
            return True
        return False

    def close(self):
        self._running = False
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

