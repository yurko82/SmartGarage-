import json
import logging
import os
import socket
import threading
import time
import urllib.request
import uuid
from collections import deque
from typing import Any, Dict, List, Optional

from server.config import config
from server.sensors.freshness import (
    SENSOR_FRESHNESS_THRESHOLD_SECONDS,
    SOURCE_ESP32_BRIDGE,
    format_iso_timestamp,
    format_relative_time_ua,
)

logger = logging.getLogger(__name__)

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


def format_relative_time(ts: float | None) -> str:
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


def is_interface_up(ifname: str | None) -> bool:
    """Перевірка чи мережевий інтерфейс активний та має статус UP."""
    if not ifname:
        return False
    try:
        with open(f"/sys/class/net/{ifname}/operstate") as f:
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
        self.last_ping_ms: float | None = None
        self._rf_tx_event = threading.Event()
        self.last_rf_tx_result = None

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
        self.state: dict[str, Any] = {
            "online": False,
            "light": False,
            "fan": False,
            "relays_installed": False,
            "temperature": None,
            "humidity": None,
            "car_present": False,
            "distance_cm": 240,
            "motion_detected": False,
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

        # Менеджер 433 МГц радіосигналів, зон освітлення та дедуплікації
        from server.devices.rf_manager import RfManager
        self.rf_manager = RfManager()

        # Старт послідовного порту (якщо налаштовано)
        if self.mode in ("auto", "serial") and serial is not None and not os.environ.get("TESTING"):
            self._start_serial_reader()

        # Старт фонового опитування мережі
        if self.mode in ("auto", "network", "http") and not os.environ.get("TESTING"):
            self._start_network_worker()

        # Старт фонового MQTT клієнта для швидкого відстеження LWT статусу
        if MQTT_AVAILABLE and not os.environ.get("TESTING"):
            self._start_mqtt_worker()

    def log_event(self, event_type: str, status: str, title: str, message: str, details: dict | None = None):
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
            if event_type == "rf" or status in ("warning", "error"):
                logger.info("[%s] %s: %s", event_type.upper(), title, message)

    def _start_mqtt_worker(self):
        """Запуск фонового MQTT підписника для моніторингу статусу ESP32."""
        try:
            mqtt_cfg = config.get("mqtt", {}) if isinstance(config, dict) else {}
            if not mqtt_cfg.get("enabled", True):
                return

            broker_host = mqtt_cfg.get("broker_host", "127.0.0.1")
            broker_port = int(mqtt_cfg.get("broker_port", 1883))
            username = mqtt_cfg.get("username", "smartgarage")
            password = os.getenv("MQTT_PASSWORD") or mqtt_cfg.get("password")
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
                            # Не вимикаємо статус, якщо контролер активно працює через USB Serial
                            if not is_online and (self._serial and self._serial.is_open):
                                pass
                            else:
                                self.state["online"] = is_online
                                if is_online:
                                    self.state["transport"] = "mqtt"
                                    self.state["last_seen"] = time.time()
                                elif self.state.get("transport") == "mqtt":
                                    self.state["transport"] = "none"
                        if is_online and not was_online:
                            self.log_event("connection", "success", "ESP32 онлайн (MQTT)", "Контролер підключився до MQTT брокера", {"topic": msg.topic})
                        elif not is_online and was_online and not (self._serial and self._serial.is_open):
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

    def _find_available_serial_port(self) -> str | None:
        """Auto-discover available USB CDC / Serial ports for ESP32."""
        if self.serial_port_name and os.path.exists(self.serial_port_name):
            return self.serial_port_name
        import glob
        candidates = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
        return candidates[0] if candidates else None

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
                    port_to_try = self._find_available_serial_port()
                    if port_to_try and os.path.exists(port_to_try):
                        self._serial = serial.Serial(port_to_try, self.baudrate, timeout=1.0, write_timeout=1.0)
                        self._serial.dtr = False
                        self._serial.rts = False
                        self.serial_port_name = port_to_try
                        with self._lock:
                            self._serial_handshake_verified = False
                            # Port opened, but not online until verified handshake!
                            self.state["transport"] = "serial"
                        self.log_event("connection", "info", "Відкрито USB Serial порт", f"Порт: {self.serial_port_name}. Очікування handshake...")
                        time.sleep(0.3)
                        # Send PING handshake to verify ESP32 identity
                        self._send_raw_serial("CMD:PING")
                        last_poll_cmd = time.time()
                    else:
                        time.sleep(2)
                        continue

                # Check Heartbeat TTL (45s to accommodate BLE polling duration)
                now = time.time()
                last_seen = self.state.get("last_seen") or 0
                if getattr(self, "_serial_handshake_verified", False) and (now - last_seen > 45.0):
                    with self._lock:
                        self._serial_handshake_verified = False
                        self.state["online"] = False
                        if self.state.get("transport") == "serial":
                            self.state["transport"] = "none"
                    self.log_event("connection", "warning", "ESP32 Heartbeat TTL вичерпано", "Втрачено підтверджений зв'язок з ESP32")

                # Periodically query telemetry in background every 5 seconds if verified
                if getattr(self, "_serial_handshake_verified", False) and (now - last_poll_cmd > 5.0):
                    self._send_serial_command("CMD:STATUS")
                    self._send_serial_command("CMD:RF_STATUS")
                    last_poll_cmd = now
                elif not getattr(self, "_serial_handshake_verified", False) and (now - last_poll_cmd > 3.0):
                    self._send_raw_serial("CMD:STATUS")
                    self._send_raw_serial("CMD:PING")
                    last_poll_cmd = now

                try:
                    line = self._serial.readline().decode("utf-8", errors="ignore").strip()
                except Exception as read_err:
                    logger.warning("Помилка читання з Serial: %s", read_err)
                    raise read_err

                if line:
                    try:
                        self._parse_serial_line(line)
                    except Exception as parse_err:
                        logger.error("Помилка обробки рядка Serial '%s': %s", line, parse_err)
            except Exception as err:
                logger.warning("Втрата або збій з'єднання Serial: %s", err)
                if self._serial:
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                    self._serial = None
                    self._serial_handshake_verified = False
                    with self._lock:
                        self.state["online"] = False
                    self.log_event("connection", "warning", "Втрата зв'язку USB Serial", f"Порт {self.serial_port_name} відключено ({err})")
                time.sleep(2)

    def _send_raw_serial(self, cmd: str) -> bool:
        """Send raw line over serial port without handshake requirement."""
        with self._lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.write(f"{cmd}\n".encode())
                    self._serial.flush()
                    return True
                except Exception:
                    return False
            return False

    @staticmethod
    def _decode_raw_rf_timings(timings: list[int], sync_us: int = 0) -> dict[str, Any] | None:
        """
        Адаптивний декодер сирих імпульсів 433 МГц (EV1527, PT2262, PWM).
        Перевіряє зміщення (offset 1, 2, 0) та полярність бітів.
        """
        if not timings or len(timings) < 16:
            return None

        best_result = None

        for offset in (1, 2, 0):
            for invert in (False, True):
                code = 0
                bits = 0
                shorters = []
                valid = True

                for i in range(offset, len(timings) - 1, 2):
                    t1 = timings[i]
                    t2 = timings[i + 1]
                    longer = max(t1, t2)
                    shorter = min(t1, t2)

                    # Допуски для 433 МГц OOK
                    if shorter < 60 or shorter > 1300 or longer < 180 or longer > 3800:
                        valid = False
                        break
                    if longer * 10 < shorter * 13:
                        valid = False
                        break

                    bit_val = 1 if (t1 > t2 if not invert else t1 < t2) else 0
                    code = (code << 1) | bit_val
                    bits += 1
                    shorters.append(shorter)
                    if bits >= 32:
                        break

                if bits >= 12 and (valid or bits >= 20):
                    avg_delay = int(sum(shorters) / len(shorters)) if shorters else 320
                    result = {
                        "code": code,
                        "hex": hex(code).upper().replace("X", "x"),
                        "bits": bits,
                        "delay": avg_delay,
                        "protocol": 1,
                        "valid": valid
                    }
                    if valid and bits in (24, 20, 32):
                        return result
                    if best_result is None or bits > best_result["bits"]:
                        best_result = result

        return best_result

    def _parse_serial_line(self, line: str):
        # 1. Handshake verification response
        if "PONG" in line or "pong" in line or "[SmartGarage]" in line or "[CC1101]" in line or "esp32_smartgarage" in line:
            with self._lock:
                self._serial_handshake_verified = True
                self.state["online"] = True
                self.state["last_seen"] = time.time()
                self.state["transport"] = "serial"
            self.log_event("connection", "success", "Підключено та верифіковано через USB Serial", f"Порт: {self.serial_port_name}")
            return

        if line.startswith("[BLE]") or line.startswith("[AHT10]") or "[RF_" in line:
            with self._lock:
                self.state["last_seen"] = time.time()
                if getattr(self, "_serial_handshake_verified", False):
                    self.state["online"] = True

        if line.startswith("TELEMETRY:"):
            raw_json = line[len("TELEMETRY:"):].strip()
            try:
                data = json.loads(raw_json)
                with self._lock:
                    self._serial_handshake_verified = True
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
                elif "cc1101" in data or "rssi" in data or "diag" in data:
                    with self._lock:
                        self._serial_handshake_verified = True
                        if "diag" in data:
                            self.state["rf_diag"] = data
                            self.state["rf_status"] = data
                            self.log_event("rf", "info", "CC1101 SPI Diag", f"VER={data.get('ver')}, MARC={data.get('marc')}, GDO0={data.get('gdo0')}, Edges={data.get('edges')}", data)
                        else:
                            self.state["rf_status"] = data
                elif "rf_sent" in data or "tx_ok" in data:
                    logger.info("RF_SEND response received: %s", data)
                    with self._lock:
                        self._serial_handshake_verified = True
                        self.last_rf_tx_result = {
                            "tx_ok": bool(data.get("tx_ok", data.get("status") == "ok")),
                            "tx_state": data.get("tx_state"),
                            "rx_restored": bool(data.get("rx_restored", True)),
                            "rf_sent": data.get("rf_sent"),
                            "status": data.get("status", "ok"),
                            "time": time.time(),
                        }
                    if hasattr(self, "_rf_tx_event"):
                        self._rf_tx_event.set()
                else:
                    with self._lock:
                        self._serial_handshake_verified = True
                    self.update_from_webhook(data, transport="serial")
            except Exception:
                pass
        elif "[RF_RX]" in line or "[RF_RX_ADAPTIVE]" in line or "[RF_LEARN]" in line or "[RF_RX_RAW]" in line or "[RF_RAW_DATA]" in line:
            # Приклад: [RF_RX] Код: 15835393 (0xF1A101) | Біти: 24 | Протокол: 1 | Затримка: 320
            # Або: [RF_LEARN] {"code":15835393,"hex":"0xF1A101","bits":24,"proto":1,"delay":320}
            # Або: [RF_RAW_DATA] count=55 sync=9800 timings=[...]
            try:
                import re
                code_val = None
                hex_val = None
                bits_val = 24
                proto_val = 1
                delay_val = 320
                sync_val = None
                mode = "standard"

                if "[RF_LEARN]" in line:
                    idx = line.find("[RF_LEARN]")
                    payload_str = line[idx + len("[RF_LEARN]"):].strip()
                    try:
                        learn_data = json.loads(payload_str)
                        code_val = learn_data.get("code")
                        hex_val = learn_data.get("hex")
                        bits_val = learn_data.get("bits", 24)
                        proto_val = learn_data.get("proto", 1)
                        delay_val = learn_data.get("delay", 320)
                        sync_val = learn_data.get("sync")
                        mode = learn_data.get("mode", "learn")
                    except Exception:
                        pass

                if code_val is None:
                    m = re.search(r"Код:\s*(\d+)\s*\((0x[0-9a-fA-F]+)\)\s*\|\s*Біти:\s*(\d+)", line)
                    if m:
                        code_val = int(m.group(1))
                        hex_val = m.group(2)
                        bits_val = int(m.group(3))
                        proto_m = re.search(r"Протокол:\s*(\d+)", line)
                        proto_val = int(proto_m.group(1)) if proto_m else 1
                        delay_m = re.search(r"Затримка:\s*(\d+)", line)
                        delay_val = int(delay_m.group(1)) if delay_m else 320
                        sync_m = re.search(r"Синхропауза:\s*(\d+)", line)
                        sync_val = int(sync_m.group(1)) if sync_m else None
                        mode = "adaptive" if "[RF_RX_ADAPTIVE]" in line else "standard"
                    else:
                        m_raw = re.search(r"Розпізнано:\s*(0x[0-9a-fA-F]+)\s*\((\d+)\)\s*\|\s*Біти:\s*(\d+)", line)
                        if m_raw:
                            hex_val = m_raw.group(1)
                            code_val = int(m_raw.group(2))
                            bits_val = int(m_raw.group(3))
                            sync_m = re.search(r"Sync:\s*(\d+)", line)
                            sync_val = int(sync_m.group(1)) if sync_m else None
                            mode = "raw_adaptive"

                if code_val is None and "[RF_RAW_DATA]" in line:
                    m_timings = re.search(r"timings=\[([0-9,\s]+)\]", line)
                    if m_timings:
                        raw_str = m_timings.group(1).strip()
                        if raw_str:
                            timings = [int(x.strip()) for x in raw_str.split(",") if x.strip().isdigit()]
                            m_sync = re.search(r"sync=(\d+)", line)
                            sync_val = int(m_sync.group(1)) if m_sync else 0
                            decoded = self._decode_raw_rf_timings(timings, sync_val)
                            if decoded:
                                code_val = decoded["code"]
                                hex_val = decoded["hex"]
                                bits_val = decoded["bits"]
                                delay_val = decoded["delay"]
                                proto_val = decoded.get("protocol", 1)
                                mode = "raw_python"

                if code_val is not None:
                    rf_info = {
                        "code": code_val,
                        "hex": hex_val or hex(code_val),
                        "bits": bits_val,
                        "protocol": proto_val,
                        "delay": delay_val,
                        "sync": sync_val,
                        "timestamp": time.time(),
                        "mode": mode
                    }
                    with self._lock:
                        self.state["last_rf_sniffed"] = rf_info

                    # Передача в RF Manager для дедуплікації та прив'язки дій до зон освітлення
                    res = self.rf_manager.process_rf_event(rf_info, callback_zone_off=self.light_off_zone)

                    log_msg = f"Код: {code_val} ({hex_val}) | Біти: {bits_val} | Протокол: {proto_val} | Затримка: {delay_val} мкс"
                    if res.get("status") == "executed":
                        self.log_event("rf", "success", f"💡 Вимкнено {res.get('zone')} за RF-кнопкою!", log_msg, rf_info)
                    elif res.get("status") == "learning":
                        self.log_event("rf", "info", "📡 Захоплено сигнал у режимі навчання", log_msg, rf_info)
                    elif not res.get("deduplicated"):
                        self.log_event("rf", "info", "📡 Перехоплено 433 МГц радіосигнал", log_msg, rf_info)
                elif "[RF_RX_RAW]" in line or "[RF_RAW_DATA]" in line:
                    self.log_event("rf", "info", "📡 Сигнал 433 МГц виявлено (невідомий протокол)", line)
                    logger.info("📡 [RF_RAW] %s", line)
                    if hasattr(self, "rf_manager") and self.rf_manager.is_learning():
                        now = time.time()
                        last_raw = getattr(self, "_last_raw_log_time", 0.0)
                        if now - last_raw >= 1.5:
                            self._last_raw_log_time = now
                            self.rf_manager.log_activity(
                                direction="RX",
                                code=0,
                                action="raw",
                                zone_title="Нерозпізнаний сигнал",
                                status="warning",
                                details=line[:120]
                            )
                else:
                    self.log_event("rf", "info", "ESP32 RF_RX", line)
            except Exception as e:
                self.log_event("rf", "warning", "Помилка парсингу RF_RX", f"{e}: {line}")
        elif "[RF_DETECT]" in line:
            self.log_event("rf", "info", "📡 Сплеск 433 МГц сигналу", line)
            logger.info("📡 [RF_DETECT] %s", line)
            if hasattr(self, "rf_manager"):
                self.rf_manager.log_activity(
                    direction="RX",
                    code=0,
                    action="detect",
                    zone_title="Детекція несучої",
                    status="info",
                    details=line
                )
        elif "[RF_PULSES]" in line:
            self.log_event("rf", "info", "📡 Зафіксовано радіоімпульси 433 МГц", line)
            logger.info("📡 [RF_PULSES] %s", line)
        else:
            if line:
                # Arbitrary serial line does NOT verify port or make online
                self.log_event("connection", "info", "ESP32 RAW", line)

    def scan_ble(self, duration: int = 15, timeout: float | None = None) -> list:
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
            except Exception:
                pass

        self.log_event("command", "error", "Не вдалося опитати датчики", f"ESP32 недоступний за адресою {self.host}:{self.port}")
        return {"success": False, "error": f"ESP32 офлайн або недоступний ({self.host}:{self.port})"}

    def _send_serial_command(self, cmd: str) -> bool:
        with self._lock:
            if self.mode == "mock" or os.environ.get("TESTING"):
                return True
            if not getattr(self, "_serial_handshake_verified", False):
                return False
            if self._serial and self._serial.is_open:
                try:
                    self._serial.write(f"{cmd}\n".encode())
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
            with self._lock:
                self.state["online"] = True
                self.state["transport"] = "serial"
                if not self.state.get("last_seen"):
                    self.state["last_seen"] = time.time()
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

    # --- DOOR / GATES (Read-Only / Disabled: Gate opening not planned) ---
    def door_open(self):
        with self._lock:
            self.log_event("command", "warning", "Команда воріт", "Відкриття воріт вимкнено: привід не встановлений")
            return "unknown"

    def door_close(self):
        with self._lock:
            self.log_event("command", "warning", "Команда воріт", "Керування воротами вимкнено: привід не встановлений")
            return "unknown"

    def door_toggle(self):
        with self._lock:
            self.log_event("command", "warning", "Команда воріт", "Керування воротами вимкнено: привід не встановлений")
            return "unknown"

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

    def control_zone(self, zone: str, action: str = "off") -> bool:
        """
        Керування пристроєм у зоні (підвал: світло/вентиляція, 2-й поверх: кухня/вітальня/загальне, гараж).
        Підтримує радіореле 433 МГц та прямі апаратні канали.
        """
        with self._lock:
            zone_norm = (zone or "main_light").lower().strip()
            act_norm = (action or "off").lower().strip()

            if zone_norm in ("main_light", "garage", "floor1", "light"):
                if act_norm == "on":
                    return self.light_on()
                else:
                    self.light_off()
                    self._send_serial_command("CMD:LIGHT:MAIN:OFF")
                    return True

            elif zone_norm in ("main_fan", "garage_fan"):
                if act_norm == "on":
                    return self.fan_on()
                else:
                    return self.fan_off()

            elif zone_norm in ("all", "all_lights", "всі", "все"):
                if act_norm == "off":
                    self.light_off()
                    self._send_serial_command("CMD:LIGHT:MAIN:OFF")
                    self._send_serial_command("CMD:LIGHT:BASEMENT:OFF")
                    self._send_serial_command("CMD:LIGHT:FLOOR2:OFF")
                    for z in ("floor2_kitchen", "floor2_living_room"):
                        if hasattr(self, "rf_manager"):
                            r = self.rf_manager.get_relay_by_zone(z)
                            if r:
                                self.rf_transmit(r["code_off"], zone=z, action="off", name=r.get("name"))
                    return True
                else:
                    return self.light_on()

            # Обробка зон через RfManager та радіореле 433 МГц
            relay = None
            if hasattr(self, "rf_manager"):
                relay = self.rf_manager.get_relay_by_zone(zone_norm)

            if relay:
                code = relay["code_on"] if act_norm == "on" else relay["code_off"]
                name = relay.get("name", zone_norm)
                ok = self.rf_transmit(
                    code=code,
                    zone=zone_norm,
                    action=act_norm,
                    name=name,
                    protocol=relay.get("protocol", 1),
                    bits=relay.get("bits", 24),
                    delay=relay.get("delay", 320)
                )
                if hasattr(self, "rf_manager"):
                    self.rf_manager.update_relay_state(relay["id"], act_norm)
                return ok

            # Fallback для стандартних зон без окремого запису реле
            if zone_norm in ("basement_light", "basement"):
                if act_norm == "off":
                    ok = self._send_serial_command("CMD:LIGHT:BASEMENT:OFF")
                    self.log_event("command", "info", "Вимкнення світла: Підвал", "Надіслано команду вимкнення для зони basement_light")
                    if hasattr(self, "rf_manager"):
                        self.rf_manager.log_activity("TX", 15835394, action="off", zone="basement_light", details="Fallback serial command")
                    return ok
                else:
                    return self.rf_transmit(15835393, zone="basement_light", action="on", name="Підвал: Світло")

            elif zone_norm in ("basement_fan", "basement_ventilation"):
                code = 15835395 if act_norm == "on" else 15835396
                return self.rf_transmit(code, zone="basement_fan", action=act_norm, name="Підвал: Вентиляція")

            elif zone_norm in ("floor2_kitchen", "kitchen"):
                code = 15835397 if act_norm == "on" else 15835398
                return self.rf_transmit(code, zone="floor2_kitchen", action=act_norm, name="2-й поверх: Кімната 1 (Кухня)")

            elif zone_norm in ("floor2_living_room", "living_room"):
                code = 15835399 if act_norm == "on" else 15835400
                return self.rf_transmit(code, zone="floor2_living_room", action=act_norm, name="2-й поверх: Кімната 2 (Вітальня)")

            elif zone_norm in ("floor2_light", "floor2"):
                if act_norm == "off":
                    ok = self._send_serial_command("CMD:LIGHT:FLOOR2:OFF")
                    self.log_event("command", "info", "Вимкнення світла: 2-й поверх", "Надіслано команду вимкнення для зони floor2_light")
                    if hasattr(self, "rf_manager"):
                        self.rf_manager.log_activity("TX", 15835394, action="off", zone="floor2_light", details="Fallback serial command")
                    return ok
                else:
                    return self.rf_transmit(15835394, zone="floor2_light", action="on", name="2-й поверх: Загальне світло")

            else:
                self.log_event("command", "warning", f"Невідома зона '{zone}'", f"Виконується дія за замовчуванням: {act_norm}")
                if act_norm == "off":
                    return self.light_off()
                return self.light_on()

    def light_off_zone(self, zone: str) -> bool:
        """
        Гарантоване вимкнення світла для окремої зони.
        Ніколи не перемикає (toggle) і не вмикає світло через RF-подію.
        """
        return self.control_zone(zone, "off")

    def rf_transmit(
        self,
        code: int,
        zone: str | None = None,
        action: str = "transmit",
        name: str = "",
        repeats: int = 10,
        protocol: int = 1,
        bits: int = 24,
        delay: int = 320
    ) -> bool:
        """Трансляція 433 МГц радіосигналу в ефір через CC1101 із самоперевіркою та записом у журнал активності."""
        c_int = int(code)
        hex_code = hex(c_int).upper().replace("X", "x")
        from server.devices.rf_manager import ZONE_DESCRIPTIONS
        desc = name or (ZONE_DESCRIPTIONS.get(zone) if zone else f"Код {hex_code}")

        if hasattr(self, "_rf_tx_event"):
            self._rf_tx_event.clear()
        with self._lock:
            self.last_rf_tx_result = None

        ok = self._send_serial_command(f"CMD:RF_SEND:{c_int}")
        logger.info("RF_SEND dispatched to serial: code=%s, ok=%s", c_int, ok)

        # Очікування відповіді від ESP32 або емуляція в mock/testing
        tx_ok = ok
        tx_state = 0x13 if ok else 0x01
        rx_restored = ok

        if self.mode == "mock" or os.environ.get("TESTING"):
            tx_ok = True
            tx_state = 0x13
            rx_restored = True
            with self._lock:
                self.last_rf_tx_result = {
                    "tx_ok": True,
                    "tx_state": 0x13,
                    "rx_restored": True,
                    "rf_sent": c_int,
                    "status": "ok",
                    "time": time.time(),
                }
        elif ok:
            if hasattr(self, "_rf_tx_event"):
                event_set = self._rf_tx_event.wait(timeout=3.0)
                logger.info("RF_SEND event wait result: event_set=%s, last_rf_tx_result=%s", event_set, self.last_rf_tx_result)
            with self._lock:
                if self.last_rf_tx_result:
                    tx_ok = bool(self.last_rf_tx_result.get("tx_ok", True))
                    tx_state = self.last_rf_tx_result.get("tx_state")
                    rx_restored = bool(self.last_rf_tx_result.get("rx_restored", True))
                else:
                    tx_ok = False
                    tx_state = None
                    rx_restored = False
                    self.last_rf_tx_result = {
                        "tx_ok": False,
                        "tx_state": None,
                        "rx_restored": False,
                        "status": "timeout",
                        "time": time.time(),
                    }

        is_success = bool(ok and tx_ok and rx_restored)
        log_status = "info" if is_success else "error"
        log_title = f"📡 Передача 433 МГц: {desc}"
        log_msg = f"Код: {c_int} ({hex_code}) | Дія: {action.upper()} | TX: {'OK' if tx_ok else 'FAIL'} (state={tx_state}) | RX: {'OK' if rx_restored else 'FAIL'}"
        self.log_event("rf", log_status, log_title, log_msg, {
            "code": c_int,
            "hex": hex_code,
            "zone": zone,
            "action": action,
            "tx_ok": tx_ok,
            "tx_state": tx_state,
            "rx_restored": rx_restored
        })

        if hasattr(self, "rf_manager"):
            self.rf_manager.log_activity(
                direction="TX",
                code=c_int,
                action=action,
                zone=zone,
                zone_title=desc,
                status="success" if is_success else "error",
                details=f"Команда {action.upper()} для {desc} (tx_ok={tx_ok}, state={tx_state}, rx_restored={rx_restored})",
                protocol=protocol,
                bits=bits,
                delay=delay
            )
        return is_success

    def rf_pair_relay(self, code: int, duration_sec: int = 15, name: str = "") -> bool:
        """Безперервна трансляція коду для запису в нове радіореле під час сполучення."""
        with self._lock:
            c_int = int(code)
            ok = self._send_serial_command(f"CMD:RF_PAIR:{c_int}:{duration_sec}")
            hex_code = hex(c_int).upper().replace("X", "x")
            desc = name or f"Реле {hex_code}"
            self.log_event(
                "rf", "info", f"📡 Сполучення радіореле: {desc}",
                f"Трансляція коду {c_int} ({hex_code}) на {duration_sec} сек"
            )
            if hasattr(self, "rf_manager"):
                self.rf_manager.log_activity(
                    direction="TX",
                    code=c_int,
                    action="pair",
                    zone_title=f"Сполучення: {desc}",
                    status="info",
                    details=f"Безперервна трансляція {duration_sec}с для прив'язки реле"
                )
            return ok

    def rf_learn_start(self, duration_sec: int = 600) -> bool:
        """Запуск окремого діагностичного режиму навчання 433 МГц."""
        with self._lock:
            if hasattr(self, "rf_manager"):
                self.rf_manager.start_learning(duration_sec)
            ok = self._send_serial_command(f"CMD:RF_LEARN:START:{duration_sec}")
            self.log_event("rf", "info", "Режим навчання 433 МГц", f"Запущено режим навчання на {duration_sec} сек")
            return ok

    def rf_learn_stop(self) -> bool:
        """Зупинка режиму навчання 433 МГц."""
        with self._lock:
            if hasattr(self, "rf_manager"):
                self.rf_manager.stop_learning()
            ok = self._send_serial_command("CMD:RF_LEARN:STOP")
            self.log_event("rf", "info", "Режим навчання 433 МГц", "Зупинено режим навчання")
            return ok

    def rf_learn_status(self) -> dict:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.get_learning_status()
        return {"learning_active": False, "remaining_sec": 0, "captured_count": 0, "recent_events": []}

    def get_rf_mappings(self) -> dict:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.get_mappings()
        return {}

    def set_rf_mapping(self, code: int, zone: str, name: str = "", action: str = "off", **kwargs) -> bool:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.set_mapping(code=code, zone=zone, name=name, action="off", **kwargs)
        return False

    def delete_rf_mapping(self, code: int) -> bool:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.delete_mapping(code)
        return False

    def get_rf_relays(self) -> dict:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.get_relays()
        return {}

    def set_rf_relay(self, relay_id: str, zone: str, name: str, code_on: int, code_off: int, **kwargs) -> bool:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.set_relay(relay_id=relay_id, zone=zone, name=name, code_on=code_on, code_off=code_off, **kwargs)
        return False

    def delete_rf_relay(self, relay_id: str) -> bool:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.delete_relay(relay_id)
        return False

    def test_rf_relay(self, relay_id: str, action: str = "on") -> bool:
        if hasattr(self, "rf_manager"):
            relay = self.rf_manager.get_relay(relay_id)
            if relay:
                code = relay["code_on"] if action.lower() == "on" else relay["code_off"]
                return self.rf_transmit(
                    code=code,
                    zone=relay.get("zone"),
                    action=action.lower(),
                    name=relay.get("name"),
                    protocol=relay.get("protocol", 1),
                    bits=relay.get("bits", 24),
                    delay=relay.get("delay", 320)
                )
        return False

    def pair_rf_relay(self, relay_id: str, action: str = "on", duration_sec: int = 15) -> bool:
        if hasattr(self, "rf_manager"):
            relay = self.rf_manager.get_relay(relay_id)
            if relay:
                code = relay["code_on"] if action.lower() == "on" else relay["code_off"]
                return self.rf_pair_relay(code, duration_sec=duration_sec, name=f"{relay.get('name')} ({action.upper()})")
        return False

    def get_rf_activity(self, limit: int = 50) -> list:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.get_activity_log(limit=limit)
        return []

    def get_rf_metrics(self) -> dict:
        if hasattr(self, "rf_manager"):
            return self.rf_manager.get_metrics()
        return {}

    def clear_rf_activity(self) -> bool:
        """Очистити журнал активності 433 МГц, останні захоплені пакети та буфер навчання."""
        with self._lock:
            self.state["last_rf_sniffed"] = None
            if hasattr(self, "rf_manager"):
                self.rf_manager.clear_activity_log()
                self.rf_manager.clear_learning_buffer()
        return True

    def rf_pair(self, duration_sec: int = 30) -> bool:
        """Запуск безперервної трансляції коду сполучення для запису в пам'ять реле."""
        with self._lock:
            ok = self._send_serial_command(f"CMD:RF_PAIR:{duration_sec}")
            self.log_event("command", "info", "Режим навчання 433 МГц", f"Запущено постійну трансляцію коду на {duration_sec} сек")
            return ok

    def rf_pair_stop(self) -> bool:
        """Зупинка режиму сполучення."""
        with self._lock:
            ok = self._send_serial_command("CMD:RF_PAIR_STOP")
            self.log_event("command", "info", "Режим навчання 433 МГц", "Зупинено трансляцію коду")
            return ok

    def rf_diag(self) -> bool:
        """Запит детальної апаратної діагностики CC1101."""
        with self._lock:
            return self._send_serial_command("CMD:RF_DIAG")

    def get_rf_diagnostics(self) -> dict[str, Any]:
        """
        Повертає повну, розшифровану апаратну діагностику радіотракту CC1101 (433.92 МГц).
        Включає поточний стан кінцевого автомата (MARCSTATE), точну обчислену частоту,
        режим модуляції, статус піна GDO0, тест шини SPI та лічильник імпульсів.
        """
        with self._lock:
            diag = self.state.get("rf_diag") or self.state.get("rf_status") or {}
            last_sniffed = self.state.get("last_rf_sniffed")
            learning = self.rf_learn_status()
            metrics = self.get_rf_metrics() if hasattr(self, "rf_manager") else {"tx_count": 0, "rx_count": 0}

            # Розшифровка MARCSTATE (стан кінцевого автомата радіоядра TI CC1101)
            marc_raw = diag.get("marc")
            marc_states = {
                0: ("SLEEP", "Сон / вимкнено", "secondary"),
                1: ("IDLE", "Спокій / очікування", "warning"),
                6: ("MANCAL", "Ручне калібрування", "info"),
                7: ("MANRTX", "Перемикання RX/TX", "info"),
                8: ("FS_WAKEUP", "Прокидання синтезатора", "info"),
                9: ("CALIBRATE", "Калібрування PLL", "info"),
                10: ("SETTLING", "Стабілізація частоти", "info"),
                13: ("RX", "Прийом ефіру (демодулятор активний)", "success"),
                14: ("RX_END", "Завершення прийому", "info"),
                17: ("RXFIFO_OVERFLOW", "Переповнення RX буфера", "danger"),
                19: ("TX", "Передача в ефір", "primary"),
                22: ("TXFIFO_UNDERFLOW", "Помилка буфера TX", "danger"),
            }
            marc_info = marc_states.get(
                marc_raw,
                (f"0x{marc_raw:02X}" if marc_raw is not None else "--", "Невідомий стан", "secondary"),
            )

            # Точний динамічний розрахунок робочої частоти за регістрами FREQ[2..0]
            freq_arr = diag.get("f")
            freq_mhz = 433.92
            if isinstance(freq_arr, (list, tuple)) and len(freq_arr) == 3:
                try:
                    f_val = (freq_arr[0] << 16) | (freq_arr[1] << 8) | freq_arr[2]
                    freq_mhz = round((f_val * 26.0) / 65536.0, 3)
                except Exception:
                    freq_mhz = 433.92

            # Тип модуляції (MDMCFG2)
            m2 = diag.get("m2")
            modulation = "ASK / OOK (Пульти EV1527/PT2262)"
            if m2 is not None:
                mod_type = (m2 >> 4) & 0x07
                if mod_type == 3:
                    modulation = "ASK / OOK (Амплітудна модуляція)"
                elif mod_type == 0:
                    modulation = "2-FSK"
                elif mod_type == 1:
                    modulation = "GFSK"
                elif mod_type == 4:
                    modulation = "4-FSK"
                elif mod_type == 7:
                    modulation = "MSK"

            # Режим пакетів (PKTCTRL0)
            pk0 = diag.get("pk0")
            packet_mode = "Асинхронний послідовний на GDO0"
            if pk0 is not None:
                fmt = pk0 & 0x03
                if fmt == 2:
                    packet_mode = "Асинхронний послідовний (прямі імпульси GDO0)"
                elif fmt == 0:
                    packet_mode = "Пакетний режим з FIFO"
                elif fmt == 1:
                    packet_mode = "Синхронний послідовний"

            # Конфігурація піна даних GDO0 (IOCFG0)
            io0 = diag.get("io0")
            gdo0_mode = "0x0D (Serial Data Out демодулятора)"
            if io0 == 0x0D:
                gdo0_mode = "Вихід демодулятора (RX) на пін GDO0"
            elif io0 == 0x2E:
                gdo0_mode = "Hi-Z вхід модулятора (TX) на пін GDO0"

            # Тест шини SPI
            spi_verified = diag.get("bb_tw") == 66  # 0x42
            spi_status_text = "Bit-Bang SPI 500 кГц ✅ (OK, тест 0x42 пройдено)" if spi_verified else "SPI не підтверджено"

            ver = diag.get("ver")
            chip_desc = "Texas Instruments CC1101 (Rev 0x14)" if ver in ("0x14", 0x14) else f"CC1101 ({ver})"

            patable = diag.get("patable")
            agc2 = diag.get("agc2")
            agc1 = diag.get("agc1")
            agc0 = diag.get("agc0")
            frend0 = diag.get("frend0")
            mcsm1 = diag.get("mcsm1")

            agc_formatted = None
            if agc2 is not None and agc1 is not None and agc0 is not None:
                try:
                    agc_formatted = f"{int(agc2):02X}/{int(agc1):02X}/{int(agc0):02X}"
                except (ValueError, TypeError):
                    agc_formatted = None

            return {
                "success": True,
                "available": bool(diag.get("diag") == "spi_active" or spi_verified),
                "frequency_mhz": freq_mhz,
                "frequency_registers": freq_arr or [16, 176, 113],
                "marc_state": marc_raw,
                "marc_state_name": marc_info[0],
                "marc_state_desc": marc_info[1],
                "marc_state_color": marc_info[2],
                "modulation": modulation,
                "filter_bandwidth_khz": 325,
                "packet_mode": packet_mode,
                "gdo0_mode": gdo0_mode,
                "gdo0_level": diag.get("gdo0", 0),
                "edge_count": diag.get("edges", 0),
                "rssi_dbm": diag.get("rssi", -138),
                "spi_status": spi_status_text,
                "chip_version": chip_desc,
                "patable": patable,
                "agc2": agc2,
                "agc1": agc1,
                "agc0": agc0,
                "frend0": frend0,
                "mcsm1": mcsm1,
                "agc_formatted": agc_formatted,
                "pins": {
                    "csn": diag.get("csn", 10),
                    "sck": diag.get("sck", 12),
                    "mosi": diag.get("mosi", 11),
                    "miso": diag.get("miso", 13),
                    "gdo0": 7,
                },
                "learning": learning,
                "last_captured": last_sniffed,
                "metrics": metrics,
                "raw": diag,
            }

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
        Чітко розділяє sample_timestamp (час фізичного виміру на сенсорі),
        heartbeat_timestamp (час зв'язку/отримання payload) та last_known_* значення.
        """
        if not isinstance(telemetry_dict, dict):
            return False

        now = time.time()
        with self._lock:
            # Обчислення базового sample_timestamp пакета
            base_sample_ts = None
            if "sample_timestamp" in telemetry_dict:
                try:
                    cand = float(telemetry_dict["sample_timestamp"])
                    if cand <= now + 60:  # Захист від майбутніх міток часу
                        base_sample_ts = cand
                except (ValueError, TypeError):
                    base_sample_ts = None
            elif "last_read_ago_sec" in telemetry_dict:
                try:
                    ago = float(telemetry_dict["last_read_ago_sec"])
                    if ago >= 0:
                        base_sample_ts = max(0.0, now - ago)
                except (ValueError, TypeError):
                    base_sample_ts = None

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

                        fval["source"] = SOURCE_ESP32_BRIDGE
                        fval["heartbeat_timestamp"] = now

                        # Визначення sample_timestamp для конкретного датчика
                        f_sample_ts = None
                        if "last_read_ago_sec" in fval:
                            try:
                                ago = float(fval["last_read_ago_sec"])
                                if ago >= 0:
                                    f_sample_ts = max(0.0, now - ago)
                            except (ValueError, TypeError):
                                f_sample_ts = None
                        elif "sample_timestamp" in fval:
                            try:
                                cand = float(fval["sample_timestamp"])
                                if cand <= now + 60:
                                    f_sample_ts = cand
                            except (ValueError, TypeError):
                                f_sample_ts = None

                        if f_sample_ts is None:
                            f_sample_ts = base_sample_ts or now

                        # Якщо мітка часу в майбутньому (> 60 с) — вважаємо недійсною
                        if f_sample_ts > now + 60:
                            f_online = False
                            f_temp = None

                        # Battery-only read: якщо температури немає (None), оновлення клімату не відбувається
                        if f_online and f_temp is not None:
                            fval["sample_timestamp"] = f_sample_ts
                            fval["last_read_ts"] = f_sample_ts
                            fval["last_updated"] = f_sample_ts
                            fval["current_temperature"] = f_temp
                            fval["current_humidity"] = f_hum
                            fval["last_known_temperature"] = f_temp
                            fval["last_known_humidity"] = f_hum
                            fval["last_read_formatted"] = time.strftime("%H:%M:%S (%d.%m.%Y)", time.localtime(f_sample_ts))
                            fval["last_read_time"] = time.strftime("%H:%M:%S", time.localtime(f_sample_ts))
                            bat_str = f", Заряд: {f_bat}%" if f_bat is not None else ""
                            self.log_event(
                                "sensor_read",
                                "success",
                                f"Зчитано датчик: {f_name}",
                                f"Температура: {f_temp}°C, Вологість: {f_hum}%{bat_str}",
                                {"floor": fk, "mac": mac, "temp": f_temp, "hum": f_hum, "battery": f_bat, "transport": transport}
                            )
                        else:
                            # Офлайн, застарілий або battery-only стан: current_temperature strictly None
                            fval["online"] = False
                            fval["current_temperature"] = None
                            fval["current_humidity"] = None

                            prev = current_floors.get(fk, {})
                            prev_temp = prev.get("last_known_temperature") or prev.get("temperature")
                            prev_hum = prev.get("last_known_humidity") or prev.get("humidity")
                            prev_ts = prev.get("sample_timestamp") or prev.get("last_read_ts")

                            fval["last_known_temperature"] = prev_temp
                            fval["last_known_humidity"] = prev_hum
                            fval["sample_timestamp"] = prev_ts
                            fval["last_read_ts"] = prev_ts
                            fval["last_updated"] = prev_ts
                            fval["temperature"] = prev_temp  # Історичне значення для backward-compatibility
                            fval["humidity"] = prev_hum

                            self.log_event(
                                "sensor_read",
                                "warning",
                                f"Датчик {f_name} недоступний для ESP32",
                                f"ESP32 не зміг отримати свіжий вимір з {mac}",
                                {"floor": fk, "mac": mac, "transport": transport}
                            )

            # Очищення застарілих / заборонених ключів воріт та газу
            telemetry_dict.pop("door", None)
            telemetry_dict.pop("door_installed", None)
            telemetry_dict.pop("door_status", None)
            telemetry_dict.pop("gas_ppm", None)
            telemetry_dict.pop("gas_installed", None)
            telemetry_dict.pop("gas_status", None)

            self.state.update(telemetry_dict)
            self.state["online"] = bool(telemetry_dict.get("online", True))
            self.state["last_seen"] = now
            self.state["heartbeat_timestamp"] = now
            self.state["sample_timestamp"] = base_sample_ts
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
                    # Датчик вважається свіжим, тільки якщо отриманий не більше freshness threshold
                    is_fresh = bool(online and f.get("online") and lr and (time.time() - lr < SENSOR_FRESHNESS_THRESHOLD_SECONDS))
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
                "rf_status": self.state.get("rf_status"),
                "rf_diagnostics": self.get_rf_diagnostics(),
                "rf_learning": self.rf_learn_status(),
                "rf_mappings": self.get_rf_mappings(),
                "last_rf_sniffed": self.state.get("last_rf_sniffed"),
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
