import time
import socket
import urllib.request
import json
import threading
import os
import uuid
from collections import deque
from typing import Optional, Dict, Any, List
from server.config import config

try:
    import serial
except ImportError:
    serial = None

try:
    import paho.mqtt.client as paho_mqtt
    MQTT_AVAILABLE = True
except ImportError:
    paho_mqtt = None
    MQTT_AVAILABLE = False


def format_relative_time(ts: Optional[float]) -> str:
    """Форматування відносного часу українською мовою."""
    if not ts:
        return "Ніколи"
    diff = max(0, int(time.time() - ts))
    if diff < 5:
        return "щойно"
    if diff < 60:
        return f"{diff} с тому"
    if diff < 3600:
        m = diff // 60
        return f"{m} хв тому"
    if diff < 86400:
        h = diff // 3600
        m = (diff % 3600) // 60
        return f"{h} год {m} хв тому" if m else f"{h} год тому"
    d = diff // 86400
    return f"{d} д тому"


def is_interface_up(ifname: Optional[str]) -> bool:
    """Перевірка чи мережевий інтерфейс активний та має статус UP."""
    if not ifname:
        return False
    try:
        with open(f"/sys/class/net/{ifname}/operstate", "r") as f:
            return f.read().strip() == "up"
    except Exception:
        return False


class ESP32Controller:
    """
    Контролер обладнання ESP32 / ESP32-S3 для Smart Garage.
    Підтримує багатоканальний зв'язок: Wi-Fi HTTP API, MQTT (LWT), USB Serial.
    Веде журнал активності, відстежує стан підключення та реальні часові мітки опитування BLE-датчиків.
    """

    def __init__(self, host=None, port=None, serial_port=None, baudrate=115200, mode=None):
        cfg = config.get("esp32", {}) if isinstance(config, dict) else {}
        self.host = host or cfg.get("host", "192.168.100.114")
        self.port = port or cfg.get("port", 80)
        
        raw_iface = cfg.get("interface")
        self.interface = raw_iface if is_interface_up(raw_iface) else None

        self.serial_port_name = serial_port or cfg.get("serial_port", "/dev/ttyACM0")
        self.baudrate = baudrate or cfg.get("baudrate", 115200)
        self.mode = mode or ("mock" if os.environ.get("TESTING") else cfg.get("mode", "auto"))

        self._lock = threading.RLock()
        self._serial = None
        self._running = True
        self._reader_thread = None
        self._network_thread = None
        self._mqtt_client = None
        self._mqtt_thread = None
        self.last_ble_scan_results = None
        self.last_ping_ms: Optional[float] = None

        # Журнал активності та статистика
        self.activity_logs = deque(maxlen=200)
        self.stats = {
            "polls_total": 0,
            "polls_success": 0,
            "polls_failed": 0,
            "last_poll_time": None,
            "last_successful_poll": None,
        }

        # Стан пристрою
        self.state: Dict[str, Any] = {
            "online": False,
            "door": "closed",
            "light": False,
            "fan": False,
            "temperature": None,
            "humidity": None,
            "car_present": False,
            "distance_cm": 240,
            "motion_detected": False,
            "gas_ppm": 35,
            "transport": "none",
            "last_seen": None,
            "wifi_ip": self.host,
            "floors": {}
        }

        # Початковий запис у журнал
        self.log_event(
            "connection",
            "info",
            "Ініціалізація контролера ESP32",
            f"Налаштовано хост {self.host}:{self.port}, інтерфейс: {self.interface or 'авто (ОС)'}"
        )

        # Старт послідовного порту (якщо налаштовано)
        if self.mode in ("auto", "serial") and serial is not None and not os.environ.get("TESTING"):
            self._start_serial_reader()

        # Старт фонового опитування мережі
        if self.mode in ("auto", "network", "http") and not os.environ.get("TESTING"):
            self._start_network_worker()

        # Старт фонового MQTT клієнта для швидкого відстеження LWT статусу
        if MQTT_AVAILABLE and not os.environ.get("TESTING"):
            self._start_mqtt_worker()

    def log_event(self, event_type: str, status: str, title: str, message: str, details: Optional[dict] = None):
        """Додати подію до кільцевого буфера журналу ESP32."""
        with self._lock:
            now = time.time()
            entry = {
                "id": str(uuid.uuid4())[:8],
                "timestamp": now,
                "time": time.strftime("%H:%M:%S", time.localtime(now)),
                "date": time.strftime("%d.%m.%Y", time.localtime(now)),
                "type": event_type,       # "sensor_read" | "connection" | "command" | "telemetry" | "error"
                "status": status,         # "success" | "error" | "warning" | "info"
                "title": title,
                "message": message,
                "details": details or {}
            }
            self.activity_logs.append(entry)

    def _start_mqtt_worker(self):
        """Запуск фонового MQTT підписника для моніторингу статусу ESP32."""
        try:
            mqtt_cfg = config.get("mqtt", {}) if isinstance(config, dict) else {}
            if not mqtt_cfg.get("enabled", True):
                return

            broker_host = mqtt_cfg.get("broker_host", "127.0.0.1")
            broker_port = int(mqtt_cfg.get("broker_port", 1883))
            username = mqtt_cfg.get("username", "smartgarage")
            password = mqtt_cfg.get("password", "smartgarage_secret")
            topic_prefix = mqtt_cfg.get("topic_prefix", "smartgarage")

            client = paho_mqtt.Client(client_id=f"SmartGarage-ESP32Mon-{str(uuid.uuid4())[:6]}")
            if username and password:
                client.username_pw_set(username, password)

            def on_connect(cli, userdata, flags, rc):
                if rc == 0:
                    cli.subscribe(f"{topic_prefix}/esp32/status", qos=1)
                    cli.subscribe(f"{topic_prefix}/esp32/telemetry", qos=1)

            def on_message(cli, userdata, msg):
                try:
                    payload = msg.payload.decode("utf-8", errors="ignore").strip()
                    if msg.topic == f"{topic_prefix}/esp32/status":
                        is_online = (payload.lower() == "online")
                        with self._lock:
                            was_online = self.state.get("online", False)
                            self.state["online"] = is_online
                            if is_online:
                                self.state["transport"] = "mqtt"
                                self.state["last_seen"] = time.time()
                        if is_online and not was_online:
                            self.log_event("connection", "success", "ESP32 онлайн (MQTT)", "Контролер підключився до MQTT брокера", {"topic": msg.topic})
                        elif not is_online and was_online:
                            self.log_event("connection", "warning", "ESP32 офлайн (MQTT LWT)", "Брокер зафіксував втрату зв'язку з ESP32", {"topic": msg.topic})
                    elif msg.topic == f"{topic_prefix}/esp32/telemetry":
                        data = json.loads(payload)
                        self.update_from_webhook(data, transport="mqtt")
                except Exception as e:
                    self.log_event("error", "error", "Помилка обробки повідомлення MQTT", str(e))

            client.on_connect = on_connect
            client.on_message = on_message
            self._mqtt_client = client

            def _mqtt_loop():
                try:
                    client.connect(broker_host, broker_port, 60)
                    client.loop_forever()
                except Exception:
                    pass

            self._mqtt_thread = threading.Thread(target=_mqtt_loop, daemon=True, name="ESP32-MQTTMonitor")
            self._mqtt_thread.start()
        except Exception as e:
            self.log_event("error", "warning", "Не вдалося ініціалізувати MQTT монітор", str(e))

    def _start_network_worker(self):
        if self._network_thread and self._network_thread.is_alive():
            return
        self._network_thread = threading.Thread(target=self._network_worker, daemon=True, name="ESP32-NetworkWorker")
        self._network_thread.start()

    def _network_worker(self):
        while self._running:
            try:
                if not (self._serial and self._serial.is_open):
                    self._poll_network_telemetry()
            except Exception:
                pass
            time.sleep(12)

    def _poll_network_telemetry(self):
        online = self.is_online(timeout=0.8)
        with self._lock:
            self.stats["polls_total"] += 1
            self.stats["last_poll_time"] = time.time()

        if not online:
            with self._lock:
                self.stats["polls_failed"] += 1
            return

        remote = self._send_request("/api/telemetry", method="GET", timeout=2.5)
        if not remote or not isinstance(remote, dict) or not remote.get("floors"):
            ble_data = self._send_request("/api/ble/sensors", method="GET", timeout=2.5)
            if ble_data and isinstance(ble_data, dict):
                if remote and isinstance(remote, dict):
                    remote["floors"] = ble_data.get("floors", {})
                else:
                    remote = ble_data

        if remote and isinstance(remote, dict):
            with self._lock:
                self.stats["polls_success"] += 1
                self.stats["last_successful_poll"] = time.time()
            self.update_from_webhook(remote, transport="http")

    def _start_serial_reader(self):
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_thread = threading.Thread(target=self._serial_worker, daemon=True, name="ESP32-SerialWorker")
        self._reader_thread.start()

    def _serial_worker(self):
        last_poll_cmd = 0.0
        while self._running:
            try:
                if self._serial is None:
                    if os.path.exists(self.serial_port_name):
                        self._serial = serial.Serial(self.serial_port_name, self.baudrate, timeout=1.0, write_timeout=1.0)
                        with self._lock:
                            self.state["online"] = True
                            self.state["transport"] = "serial"
                            self.state["last_seen"] = time.time()
                        self.log_event("connection", "success", "Підключено через USB Serial", f"Порт: {self.serial_port_name}")
                        time.sleep(0.5)
                        self._send_serial_command("CMD:GET_TELEMETRY")
                        last_poll_cmd = time.time()
                    else:
                        time.sleep(2)
                        continue

                # Periodically query telemetry in background every 5 seconds
                now = time.time()
                if now - last_poll_cmd > 5.0:
                    self._send_serial_command("CMD:GET_TELEMETRY")
                    last_poll_cmd = now

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
                    self.log_event("connection", "warning", "Втрата зв'язку USB Serial", f"Порт {self.serial_port_name} відключено")
                time.sleep(2)

    def _parse_serial_line(self, line: str):
        if line.startswith("TELEMETRY:"):
            raw_json = line[len("TELEMETRY:"):].strip()
            try:
                data = json.loads(raw_json)
                self.update_from_webhook(data, transport="serial")
            except Exception:
                pass
        elif line.startswith("BLE_DEVICE:"):
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
                    uuid_val = info.get("uuid", "")
                    self._active_scan_devices[mac] = {
                        "mac": mac,
                        "name": info.get("name", ""),
                        "rssi": rssi_val,
                        "service_uuids": [uuid_val] if uuid_val else []
                    }
        elif "[BLE_SCAN] Completed" in line:
            with self._lock:
                if hasattr(self, "_active_scan_devices") and self._active_scan_devices:
                    self.last_ble_scan_results = list(self._active_scan_devices.values())
                else:
                    self.last_ble_scan_results = []
            self.log_event("command", "info", "Сканування BLE завершено", f"Знайдено пристроїв: {len(self.last_ble_scan_results or [])}")
        elif line.startswith("RESP:"):
            raw_json = line[len("RESP:"):].strip()
            try:
                data = json.loads(raw_json)
                if data.get("type") == "ble_scan":
                    devices = data.get("devices", [])
                    for dev in devices:
                        u = dev.get("service_uuid")
                        dev["service_uuids"] = [u] if u else []
                    with self._lock:
                        self.last_ble_scan_results = devices
                else:
                    self.update_from_webhook(data, transport="serial")
            except Exception:
                pass
        else:
            if line:
                print(f"[ESP32 RAW] {line}")
                self.log_event("connection", "info", "ESP32", line)

    def scan_ble(self, duration: int = 15, timeout: Optional[float] = None) -> list:
        """Запустити активне сканування BLE на ESP32 та повернути знайдені пристрої."""
        actual_timeout = timeout if timeout is not None else float(duration + 4)
        with self._lock:
            self.last_ble_scan_results = None
            self._active_scan_devices = {}
        ok = self._send_serial_command(f"CMD:SCAN_BLE:{duration}")
        if not ok:
            # Fallback to HTTP API
            remote = self._send_request(f"/api/ble/scan?duration={duration}", method="GET", timeout=actual_timeout)
            if remote and isinstance(remote, dict) and "devices" in remote:
                return remote["devices"]
            return []

        start_t = time.time()
        while time.time() - start_t < actual_timeout:
            with self._lock:
                if self.last_ble_scan_results is not None:
                    return self.last_ble_scan_results
            time.sleep(0.5)

        with self._lock:
            if hasattr(self, "_active_scan_devices") and self._active_scan_devices:
                return list(self._active_scan_devices.values())
        return []

    def poll_ble(self, timeout: float = 5.0) -> dict:
        """
        Надіслати запит на негайне опитування кліматичних датчиків BLE через ESP32.
        Використовує доступні канали: Serial -> HTTP -> MQTT.
        """
        self.log_event("command", "info", "Запит опитування датчиків", "Відправка запиту на опитування BLE-датчиків...")

        # 1. Спроба через USB Serial
        if self._serial and self._serial.is_open:
            if self._send_serial_command("CMD:POLL_BLE"):
                self.log_event("command", "success", "Команду POLL_BLE надіслано через Serial", "Очікування оновлення телеметрії")
                return {"success": True, "transport": "serial", "message": "Команду надіслано через Serial"}

        # 2. Спроба через HTTP API
        res = self._send_request("/api/ble/refresh", method="POST", timeout=timeout)
        if res and isinstance(res, dict) and res.get("status") == "ok":
            self.log_event("command", "success", "Датчики опитано через HTTP", "ESP32 успішно виконав опитування BLE-датчиків", res)
            time.sleep(0.4)
            self._poll_network_telemetry()
            return {"success": True, "transport": "http", "message": "Опитування успішно виконано через HTTP"}

        # 3. Спроба через MQTT
        if self._mqtt_client and self._mqtt_client.is_connected():
            try:
                mqtt_cfg = config.get("mqtt", {}) if isinstance(config, dict) else {}
                topic_prefix = mqtt_cfg.get("topic_prefix", "smartgarage")
                self._mqtt_client.publish(f"{topic_prefix}/esp32/command", json.dumps({"action": "poll_ble"}))
                self.log_event("command", "success", "Команду надіслано через MQTT", "Очікування оновленої телеметрії від брокера")
                return {"success": True, "transport": "mqtt", "message": "Команду надіслано через MQTT"}
            except Exception as e:
                pass

        self.log_event("command", "error", "Не вдалося опитати датчики", f"ESP32 недоступний за адресою {self.host}:{self.port}")
        return {"success": False, "error": f"ESP32 офлайн або недоступний ({self.host}:{self.port})"}

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

    def check_connection(self, timeout=0.8) -> dict:
        """
        Активна перевірка доступності ESP32 у мережі з вимірюванням затримки (ping).
        """
        if self.mode == "mock" or os.environ.get("TESTING"):
            return {"online": True, "latency_ms": 1.2, "host": self.host, "port": self.port, "transport": "mock"}

        if self._serial and self._serial.is_open:
            return {"online": True, "latency_ms": 0.5, "host": "USB-Serial", "port": self.serial_port_name, "transport": "serial"}

        t_start = time.time()
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            if self.interface:
                try:
                    s.setsockopt(socket.SOL_SOCKET, 25, self.interface.encode())
                except Exception:
                    pass
            s.connect((self.host, int(self.port)))
            s.close()
            latency = round((time.time() - t_start) * 1000, 1)
            self.last_ping_ms = latency

            with self._lock:
                was_online = self.state.get("online", False)
                self.state["online"] = True
                self.state["last_seen"] = time.time()
                if self.state.get("transport") == "none":
                    self.state["transport"] = "http"

            if not was_online:
                self.log_event("connection", "success", "Зв'язок з ESP32 відновлено", f"Ping: {latency} мс до {self.host}:{self.port}", {"latency_ms": latency})
            return {"online": True, "latency_ms": latency, "host": self.host, "port": self.port, "transport": self.state.get("transport", "http")}
        except Exception as e:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
            with self._lock:
                was_online = self.state.get("online", False)
                self.state["online"] = False

            if was_online:
                self.log_event("connection", "warning", "Втрата зв'язку з ESP32", f"ESP32 ({self.host}:{self.port}) не відповідає: {e}")
            return {"online": False, "latency_ms": None, "host": self.host, "port": self.port, "transport": "none", "error": str(e)}

    def is_online(self, timeout=0.8) -> bool:
        """Перевірка чи контролер ESP32 в мережі."""
        res = self.check_connection(timeout=timeout)
        return bool(res.get("online"))

    def _send_request(self, endpoint, data=None, method="GET", timeout=2.5):
        if self.mode == "mock" or os.environ.get("TESTING"):
            return None
        url = f"http://{self.host}:{self.port}{endpoint}"

        # 1. Primary: urllib.request
        try:
            body = json.dumps(data).encode("utf-8") if data else None
            headers = {"Connection": "close"}
            if data:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                with self._lock:
                    self.state["last_seen"] = time.time()
                    self.state["transport"] = "http"
                    self.state["online"] = True
                return json.loads(res.read().decode("utf-8"))
        except Exception:
            pass

        # 2. Fallback: curl якщо вказано інтерфейс
        if self.interface:
            try:
                import subprocess
                cmd = [
                    "curl", "--interface", self.interface, "-s",
                    "--connect-timeout", str(max(1, int(timeout))),
                    "--max-time", str(max(2, int(timeout) + 1))
                ]
                if method == "POST":
                    cmd.extend(["-X", "POST"])
                    if data:
                        cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(data)])
                cmd.append(url)
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
                if res.returncode == 0 and res.stdout.strip():
                    parsed = json.loads(res.stdout)
                    with self._lock:
                        self.state["last_seen"] = time.time()
                        self.state["transport"] = "http"
                        self.state["online"] = True
                    return parsed
            except Exception:
                pass

        return None

    # --- DOOR / GATES ---
    def door_open(self):
        with self._lock:
            if self._send_serial_command("CMD:DOOR_OPEN"):
                self.state["door"] = "open"
                self.state["last_seen"] = time.time()
                self.log_event("command", "info", "Команда воріт", "Відкрито через Serial")
                return "open"

            remote = self._send_request("/api/door/open", method="POST")
            if remote and "door" in remote:
                self.state["door"] = remote["door"]
            else:
                self.state["door"] = "open"
            self.log_event("command", "info", "Команда воріт", "Відкрито через HTTP")
            return self.state["door"]

    def door_close(self):
        with self._lock:
            if self._send_serial_command("CMD:DOOR_CLOSE"):
                self.state["door"] = "closed"
                self.state["last_seen"] = time.time()
                self.log_event("command", "info", "Команда воріт", "Зачинено через Serial")
                return "closed"

            remote = self._send_request("/api/door/close", method="POST")
            if remote and "door" in remote:
                self.state["door"] = remote["door"]
            else:
                self.state["door"] = "closed"
            self.log_event("command", "info", "Команда воріт", "Зачинено через HTTP")
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
                self.log_event("command", "info", "Керування освітленням", "Світло увімкнено (Serial)")
                return True

            remote = self._send_request("/api/light/on", method="POST")
            if remote and "light" in remote:
                self.state["light"] = bool(remote["light"])
            else:
                self.state["light"] = True
            self.log_event("command", "info", "Керування освітленням", "Світло увімкнено (HTTP)")
            return self.state["light"]

    def light_off(self):
        with self._lock:
            if self._send_serial_command("CMD:LIGHT_OFF"):
                self.state["light"] = False
                self.state["last_seen"] = time.time()
                self.log_event("command", "info", "Керування освітленням", "Світло вимкнено (Serial)")
                return False

            remote = self._send_request("/api/light/off", method="POST")
            if remote and "light" in remote:
                self.state["light"] = bool(remote["light"])
            else:
                self.state["light"] = False
            self.log_event("command", "info", "Керування освітленням", "Світло вимкнено (HTTP)")
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
                self.log_event("command", "info", "Керування вентиляцією", "Вентилятор увімкнено (Serial)")
                return True

            remote = self._send_request("/api/fan/on", method="POST")
            if remote and "fan" in remote:
                self.state["fan"] = bool(remote["fan"])
            else:
                self.state["fan"] = True
            self.log_event("command", "info", "Керування вентиляцією", "Вентилятор увімкнено (HTTP)")
            return self.state["fan"]

    def fan_off(self):
        with self._lock:
            if self._send_serial_command("CMD:FAN_OFF"):
                self.state["fan"] = False
                self.state["last_seen"] = time.time()
                self.log_event("command", "info", "Керування вентиляцією", "Вентилятор вимкнено (Serial)")
                return False

            remote = self._send_request("/api/fan/off", method="POST")
            if remote and "fan" in remote:
                self.state["fan"] = bool(remote["fan"])
            else:
                self.state["fan"] = False
            self.log_event("command", "info", "Керування вентиляцією", "Вентилятор вимкнено (HTTP)")
            return self.state["fan"]

    def fan_toggle(self):
        with self._lock:
            if self.state["fan"]:
                return self.fan_off()
            return self.fan_on()

    # --- TELEMETRY & SENSORS ---
    def get_telemetry(self):
        with self._lock:
            return dict(self.state)

    def update_from_webhook(self, telemetry_dict: dict, transport: str = "http") -> bool:
        """
        Обробка вхідного пакету телеметрії від ESP32.
        Зберігає реальні часові мітки опитування датчиків та фіксує події в журналі.
        """
        if not isinstance(telemetry_dict, dict):
            return False

        now = time.time()
        with self._lock:
            # Збереження попередніх поверхів для об'єднання
            current_floors = self.state.get("floors", {})
            new_floors = telemetry_dict.get("floors")

            if isinstance(new_floors, dict):
                for fk, fval in new_floors.items():
                    if isinstance(fval, dict):
                        f_name = fval.get("name") or fk
                        f_online = bool(fval.get("online", False))
                        f_temp = fval.get("temperature")
                        f_hum = fval.get("humidity")
                        f_bat = fval.get("battery")
                        mac = fval.get("mac", "")

                        # Встановлюємо реальний час зчитування
                        fval["last_read_ts"] = now
                        fval["last_read_formatted"] = time.strftime("%H:%M:%S (%d.%m.%Y)", time.localtime(now))
                        fval["last_read_time"] = time.strftime("%H:%M:%S", time.localtime(now))

                        if f_online and f_temp is not None:
                            self.log_event(
                                "sensor_read",
                                "success",
                                f"Зчитано датчик: {f_name}",
                                f"Температура: {f_temp}°C, Вологість: {f_hum}%, Заряд: {f_bat or 100}%",
                                {"floor": fk, "mac": mac, "temp": f_temp, "hum": f_hum, "battery": f_bat, "transport": transport}
                            )
                        elif not f_online:
                            self.log_event(
                                "sensor_read",
                                "warning",
                                f"Датчик {f_name} недоступний для ESP32",
                                f"ESP32 не зміг встановити BLE-з'єднання з {mac}",
                                {"floor": fk, "mac": mac, "transport": transport}
                            )

                current_floors.update(new_floors)
                telemetry_dict["floors"] = current_floors

            self.state.update(telemetry_dict)
            self.state["online"] = True
            self.state["last_seen"] = now
            self.state["transport"] = transport

        if hasattr(self, "on_telemetry_callback") and callable(self.on_telemetry_callback):
            try:
                self.on_telemetry_callback(telemetry_dict)
            except Exception:
                pass
        return True

    def get_diagnostics(self) -> dict:
        """
        Повна діагностика ESP32 для веб-панелі: статус зв'язку, логи та стан датчиків.
        """
        with self._lock:
            online = self.state.get("online", False)
            last_seen = self.state.get("last_seen")
            transport = self.state.get("transport", "none")
            floors = self.state.get("floors", {})

            # Формування стану кожного датчика
            sensor_details = {}
            for fk, f in floors.items():
                if isinstance(f, dict):
                    lr = f.get("last_read_ts") or f.get("last_updated") or last_seen
                    # Датчик вважається свіжим, тільки якщо отриманий не більше 20 хв тому
                    is_fresh = bool(online and f.get("online") and lr and (time.time() - lr < 1200))
                    sensor_details[fk] = {
                        "name": f.get("name", fk),
                        "mac": f.get("mac", ""),
                        "temperature": f.get("temperature"),
                        "humidity": f.get("humidity"),
                        "battery": f.get("battery"),
                        "online": is_fresh,
                        "last_read_ts": lr,
                        "last_read_formatted": time.strftime("%H:%M:%S (%d.%m.%Y)", time.localtime(lr)) if lr else "--",
                        "last_read_time": time.strftime("%H:%M:%S", time.localtime(lr)) if lr else "--:--",
                        "last_read_relative": format_relative_time(lr),
                        "is_stale": not is_fresh if (f.get("temperature") is not None) else False
                    }

            logs_list = list(self.activity_logs)
            logs_list.reverse()  # найновіші спочатку

            return {
                "online": online,
                "host": self.host,
                "port": self.port,
                "transport": transport,
                "last_seen": last_seen,
                "last_seen_formatted": time.strftime("%H:%M:%S (%d.%m.%Y)", time.localtime(last_seen)) if last_seen else "Ніколи",
                "last_seen_time": time.strftime("%H:%M:%S", time.localtime(last_seen)) if last_seen else "--:--",
                "last_seen_relative": format_relative_time(last_seen),
                "ping_ms": self.last_ping_ms,
                "wifi_ip": self.state.get("wifi_ip") or self.host,
                "stats": dict(self.stats),
                "sensors": sensor_details,
                "logs": logs_list[:80]
            }

    def clear_logs(self):
        """Очистити журнал подій."""
        with self._lock:
            self.activity_logs.clear()
            self.log_event("command", "info", "Журнал очищено", "Користувач очистив журнал подій")

    def close(self):
        self._running = False
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        if self._mqtt_client:
            try:
                self._mqtt_client.disconnect()
            except Exception:
                pass
