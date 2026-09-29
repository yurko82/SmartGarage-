#!/usr/bin/env python3
"""
Smart Garage - MQTT Bridge & Home Assistant Auto-Discovery Service
Connects ESP32, Antigravity AI Core, and Home Assistant via MQTT.
Provides two-way synchronization and publishes retained discovery payloads.
"""
import os
import sys
import json
import time
import signal
import asyncio
import logging
import argparse
from pathlib import Path
from typing import Optional, Dict, Any

# Compatible import with both aiomqtt and asyncio_mqtt
try:
    from aiomqtt import Client, MqttError, Will
except ImportError:
    from asyncio_mqtt import Client, MqttError, Will

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [MQTT-Bridge] %(message)s"
)
logger = logging.getLogger("MQTTBridge")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> Dict[str, Any]:
    """Load configuration from config/config.yaml."""
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            import yaml
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Error loading config.yaml: {e}")
    return cfg


class SmartGarageMQTTBridge:
    """
    Two-way bridge between Home Assistant MQTT, ESP32 hardware, and Antigravity Core AI.
    """

    def __init__(
        self,
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        username: Optional[str] = "smartgarage",
        password: Optional[str] = "smartgarage_secret",
        discovery_prefix: str = "homeassistant",
        topic_prefix: str = "smartgarage",
        garage_instance = None
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password
        self.discovery_prefix = discovery_prefix
        self.topic_prefix = topic_prefix
        self.garage = garage_instance

        self.running = False
        self.client: Optional[Client] = None

        # Device info unified block for Home Assistant
        self.device_info = {
            "identifiers": ["smartgarage_antigravity_core"],
            "name": "Smart Garage Antigravity",
            "model": "ESP32-S3 + Antigravity AI Core",
            "manufacturer": "Yurko AI",
            "sw_version": "0.3.0"
        }

        # Cached states
        self.state_door = "closed"
        self.state_light = "OFF"
        self.state_fan = "OFF"
        self.state_ai_status = "idle"
        self.latest_telemetry: Dict[str, Any] = {}

    async def publish_discovery(self, client: Client):
        """Publish retained Home Assistant MQTT Discovery configuration topics."""
        logger.info(f"Publishing Home Assistant discovery configs (prefix='{self.discovery_prefix}')...")

        # 1. Garage Door Cover
        cover_config = {
            "name": "Ворота Гаража",
            "unique_id": "smartgarage_door_cover",
            "command_topic": f"{self.topic_prefix}/door/set",
            "state_topic": f"{self.topic_prefix}/door/state",
            "device_class": "garage",
            "payload_open": "OPEN",
            "payload_close": "CLOSE",
            "payload_stop": "STOP",
            "state_open": "open",
            "state_closed": "closed",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/cover/{self.topic_prefix}/door/config",
            payload=json.dumps(cover_config, ensure_ascii=False),
            retain=True
        )

        # 2. Door Contact Sensor (Binary Sensor)
        door_sensor_config = {
            "name": "Ворота (Датчик геркона)",
            "unique_id": "smartgarage_door_contact_sensor",
            "state_topic": f"{self.topic_prefix}/door/state",
            "device_class": "garage_door",
            "payload_on": "open",
            "payload_off": "closed",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/binary_sensor/{self.topic_prefix}/door_contact/config",
            payload=json.dumps(door_sensor_config, ensure_ascii=False),
            retain=True
        )

        # 3. Light Switch
        light_config = {
            "name": "Освітлення Гаража",
            "unique_id": "smartgarage_light_switch",
            "command_topic": f"{self.topic_prefix}/light/set",
            "state_topic": f"{self.topic_prefix}/light/state",
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
            "icon": "mdi:lightbulb",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/switch/{self.topic_prefix}/light/config",
            payload=json.dumps(light_config, ensure_ascii=False),
            retain=True
        )

        # 4. Exhaust Fan Switch
        fan_config = {
            "name": "Вентиляція Гаража",
            "unique_id": "smartgarage_fan_switch",
            "command_topic": f"{self.topic_prefix}/fan/set",
            "state_topic": f"{self.topic_prefix}/fan/state",
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
            "icon": "mdi:fan",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/switch/{self.topic_prefix}/fan/config",
            payload=json.dumps(fan_config, ensure_ascii=False),
            retain=True
        )

        # 5. Basement Temperature & Humidity Sensors
        basement_temp = {
            "name": "Підвал Температура",
            "unique_id": "smartgarage_basement_temperature",
            "state_topic": f"{self.topic_prefix}/telemetry",
            "value_template": "{{ value_json.floors.basement.temperature }}",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "state_class": "measurement",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/sensor/{self.topic_prefix}/basement_temperature/config",
            payload=json.dumps(basement_temp, ensure_ascii=False),
            retain=True
        )

        basement_hum = {
            "name": "Підвал Вологість",
            "unique_id": "smartgarage_basement_humidity",
            "state_topic": f"{self.topic_prefix}/telemetry",
            "value_template": "{{ value_json.floors.basement.humidity }}",
            "unit_of_measurement": "%",
            "device_class": "humidity",
            "state_class": "measurement",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/sensor/{self.topic_prefix}/basement_humidity/config",
            payload=json.dumps(basement_hum, ensure_ascii=False),
            retain=True
        )

        # 6. Floor 2 Temperature & Humidity Sensors
        floor2_temp = {
            "name": "2-й поверх Температура",
            "unique_id": "smartgarage_floor2_temperature",
            "state_topic": f"{self.topic_prefix}/telemetry",
            "value_template": "{{ value_json.floors.floor2.temperature }}",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "state_class": "measurement",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/sensor/{self.topic_prefix}/floor2_temperature/config",
            payload=json.dumps(floor2_temp, ensure_ascii=False),
            retain=True
        )

        floor2_hum = {
            "name": "2-й поверх Вологість",
            "unique_id": "smartgarage_floor2_humidity",
            "state_topic": f"{self.topic_prefix}/telemetry",
            "value_template": "{{ value_json.floors.floor2.humidity }}",
            "unit_of_measurement": "%",
            "device_class": "humidity",
            "state_class": "measurement",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/sensor/{self.topic_prefix}/floor2_humidity/config",
            payload=json.dumps(floor2_hum, ensure_ascii=False),
            retain=True
        )

        # 7. Gas MQ2 Sensor
        gas_sensor = {
            "name": "Газ MQ2 (Дим)",
            "unique_id": "smartgarage_gas_sensor",
            "state_topic": f"{self.topic_prefix}/telemetry",
            "value_template": "{{ value_json.gas_ppm }}",
            "unit_of_measurement": "ppm",
            "icon": "mdi:molecule-co2",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/sensor/{self.topic_prefix}/gas_sensor/config",
            payload=json.dumps(gas_sensor, ensure_ascii=False),
            retain=True
        )

        # 8. AI Status Sensor
        ai_sensor = {
            "name": "Статус AI Antigravity",
            "unique_id": "smartgarage_ai_status",
            "state_topic": f"{self.topic_prefix}/ai/status",
            "icon": "mdi:robot",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/sensor/{self.topic_prefix}/ai_status/config",
            payload=json.dumps(ai_sensor, ensure_ascii=False),
            retain=True
        )

        # 9. AI Last Response Sensor
        ai_resp_sensor = {
            "name": "Остання відповідь AI",
            "unique_id": "smartgarage_ai_response",
            "state_topic": f"{self.topic_prefix}/ai/response",
            "icon": "mdi:chat-processing",
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": self.device_info
        }
        await client.publish(
            f"{self.discovery_prefix}/sensor/{self.topic_prefix}/ai_response/config",
            payload=json.dumps(ai_resp_sensor, ensure_ascii=False),
            retain=True
        )

        logger.info("✅ All Home Assistant MQTT discovery configs published successfully.")

    async def _execute_garage_command(self, action_type: str, param: str) -> str:
        """Forward actions to SmartGarage core or fallback to local HTTP API."""
        if self.garage and hasattr(self.garage, "router"):
            try:
                if action_type == "door":
                    if param == "OPEN":
                        self.garage.esp32.door_open()
                        return "Ворота відчинено"
                    elif param == "CLOSE":
                        self.garage.esp32.door_close()
                        return "Ворота зачинено"
                elif action_type == "light":
                    if param == "ON":
                        self.garage.esp32.light_on()
                        return "Світло увімкнено"
                    else:
                        self.garage.esp32.light_off()
                        return "Світло вимкнено"
                elif action_type == "fan":
                    if param == "ON":
                        self.garage.esp32.fan_on()
                        return "Вентиляцію увімкнено"
                    else:
                        self.garage.esp32.fan_off()
                        return "Вентиляцію вимкнено"
                elif action_type == "ai":
                    return self.garage.router.execute(param, session_id="homeassistant")
            except Exception as e:
                logger.error(f"Error executing garage action {action_type}:{param}: {e}")
                return str(e)

        # Standalone HTTP Fallback
        import aiohttp
        async with aiohttp.ClientSession() as session:
            try:
                if action_type == "ai":
                    async with session.post("http://127.0.0.1:5000/command", json={"command": param}) as resp:
                        data = await resp.json()
                        return data.get("response", "Виконано")
                elif action_type == "door":
                    endpoint = "/api/door/open" if param == "OPEN" else "/api/door/close"
                    async with session.post(f"http://127.0.0.1:5000{endpoint}") as resp:
                        return "Команду воріт надіслано"
                elif action_type == "light":
                    endpoint = "/api/light/on" if param == "ON" else "/api/light/off"
                    async with session.post(f"http://127.0.0.1:5000{endpoint}") as resp:
                        return "Команду світла надіслано"
                elif action_type == "fan":
                    endpoint = "/api/fan/on" if param == "ON" else "/api/fan/off"
                    async with session.post(f"http://127.0.0.1:5000{endpoint}") as resp:
                        return "Команду вентиляції надіслано"
            except Exception as e:
                logger.error(f"HTTP fallback error for {action_type}: {e}")
                return str(e)
        return ""

    async def handle_message(self, client: Client, topic: str, payload_str: str):
        """Process incoming messages from Home Assistant and ESP32."""
        logger.debug(f"[MQTT RX] {topic}: {payload_str}")

        # 1. Home Assistant re-announced itself online
        if topic == f"{self.discovery_prefix}/status" and payload_str.lower() == "online":
            logger.info("Home Assistant reconnected. Re-publishing auto-discovery configs...")
            await self.publish_discovery(client)
            return

        # 2. Door Control from HA
        if topic == f"{self.topic_prefix}/door/set":
            cmd = payload_str.upper().strip()
            logger.info(f"HA Door Command: {cmd}")
            await self._execute_garage_command("door", cmd)
            self.state_door = "open" if cmd == "OPEN" else "closed"
            await client.publish(f"{self.topic_prefix}/door/state", payload=self.state_door, retain=True)

        # 3. Light Control from HA
        elif topic == f"{self.topic_prefix}/light/set":
            cmd = payload_str.upper().strip()
            logger.info(f"HA Light Command: {cmd}")
            await self._execute_garage_command("light", cmd)
            self.state_light = "ON" if cmd == "ON" else "OFF"
            await client.publish(f"{self.topic_prefix}/light/state", payload=self.state_light, retain=True)

        # 4. Fan Control from HA
        elif topic == f"{self.topic_prefix}/fan/set":
            cmd = payload_str.upper().strip()
            logger.info(f"HA Fan Command: {cmd}")
            await self._execute_garage_command("fan", cmd)
            self.state_fan = "ON" if cmd == "ON" else "OFF"
            await client.publish(f"{self.topic_prefix}/fan/state", payload=self.state_fan, retain=True)

        # 5. Natural Language AI Command from HA
        elif topic == f"{self.topic_prefix}/ai/command":
            prompt = payload_str.strip()
            if prompt:
                logger.info(f"HA AI Prompt: «{prompt}»")
                await client.publish(f"{self.topic_prefix}/ai/status", payload="processing", retain=False)
                resp = await self._execute_garage_command("ai", prompt)
                await client.publish(f"{self.topic_prefix}/ai/response", payload=resp or "Виконано", retain=False)
                await client.publish(f"{self.topic_prefix}/ai/status", payload="idle", retain=False)
                logger.info(f"HA AI Response: «{resp}»")

        # 6. ESP32 Raw Telemetry Ingestion
        elif topic == f"{self.topic_prefix}/esp32/telemetry":
            try:
                data = json.loads(payload_str)
                self.latest_telemetry = data

                # Synchronize discrete state topics for Home Assistant
                if "door_status" in data:
                    self.state_door = data["door_status"]
                    await client.publish(f"{self.topic_prefix}/door/state", payload=self.state_door, retain=True)

                if "light" in data:
                    self.state_light = "ON" if data["light"] else "OFF"
                    await client.publish(f"{self.topic_prefix}/light/state", payload=self.state_light, retain=True)

                if "fan" in data:
                    self.state_fan = "ON" if data["fan"] else "OFF"
                    await client.publish(f"{self.topic_prefix}/fan/state", payload=self.state_fan, retain=True)

                # Re-publish unified telemetry with retain=True for HA sensors
                await client.publish(f"{self.topic_prefix}/telemetry", payload=payload_str, retain=True)

            except Exception as e:
                logger.error(f"Failed to process ESP32 telemetry JSON: {e}")

    async def _periodic_telemetry_sync(self, client: Client):
        """Periodically sync state and telemetry even if ESP32 communicates over HTTP/Serial."""
        while self.running:
            try:
                await asyncio.sleep(10)
                # Pull telemetry from local server or instance
                if self.garage and hasattr(self.garage, "get_floors_telemetry"):
                    st = self.garage.esp32.get_telemetry() if hasattr(self.garage, "esp32") else {}
                    floors = self.garage.get_floors_telemetry()
                    doc = {
                        "device": "smartgarage-core",
                        "door_status": st.get("door", self.state_door),
                        "light": bool(st.get("light", False)),
                        "fan": bool(st.get("fan", False)),
                        "gas_ppm": st.get("gas_ppm", 35),
                        "floors": floors,
                        "timestamp": time.time()
                    }
                    await client.publish(f"{self.topic_prefix}/telemetry", payload=json.dumps(doc), retain=True)
            except Exception as e:
                logger.debug(f"Periodic telemetry sync error: {e}")

    async def run(self):
        """Run MQTT bridge with exponential backoff on disconnects."""
        self.running = True
        backoff = 1.0

        # Last Will and Testament: report offline if bridge crashes
        will = Will(
            topic=f"{self.topic_prefix}/bridge/status",
            payload="offline",
            qos=1,
            retain=True
        )

        while self.running:
            try:
                logger.info(f"Connecting to MQTT Broker at {self.broker_host}:{self.broker_port}...")
                client_kwargs = {
                    "hostname": self.broker_host,
                    "port": self.broker_port,
                    "will": will,
                    "identifier": f"{self.topic_prefix}_bridge_{int(time.time())}"
                }
                if self.username:
                    client_kwargs["username"] = self.username
                if self.password:
                    client_kwargs["password"] = self.password

                async with Client(**client_kwargs) as client:
                    self.client = client
                    backoff = 1.0  # Reset backoff on successful connection
                    logger.info("Connected to MQTT Broker!")

                    # Publish Bridge Online status
                    await client.publish(f"{self.topic_prefix}/bridge/status", payload="online", retain=True)
                    await client.publish(f"{self.topic_prefix}/ai/status", payload="idle", retain=True)

                    # Publish Home Assistant Discovery
                    await self.publish_discovery(client)

                    # Subscribe to topics
                    subscriptions = [
                        (f"{self.discovery_prefix}/status", 1),
                        (f"{self.topic_prefix}/door/set", 1),
                        (f"{self.topic_prefix}/light/set", 1),
                        (f"{self.topic_prefix}/fan/set", 1),
                        (f"{self.topic_prefix}/ai/command", 1),
                        (f"{self.topic_prefix}/esp32/telemetry", 1),
                        (f"{self.topic_prefix}/esp32/status", 1),
                    ]
                    for sub_topic, qos in subscriptions:
                        await client.subscribe(sub_topic, qos=qos)
                        logger.info(f"Subscribed to topic: {sub_topic}")

                    # Spawn background sync loop
                    sync_task = asyncio.create_task(self._periodic_telemetry_sync(client))

                    # Process incoming messages
                    async for message in client.messages:
                        topic = message.topic.value if hasattr(message.topic, "value") else str(message.topic)
                        payload = message.payload.decode("utf-8", errors="ignore")
                        await self.handle_message(client, topic, payload)

            except (MqttError, OSError, Exception) as e:
                if not self.running:
                    break
                logger.warning(f"MQTT connection lost or failed ({e}). Reconnecting in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

        logger.info("MQTT Bridge stopped.")

    def stop(self):
        self.running = False


def main():
    parser = argparse.ArgumentParser(description="Smart Garage MQTT & Home Assistant Discovery Bridge")
    parser.add_argument("--broker", type=str, default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--user", type=str, default=None, help="MQTT username")
    parser.add_argument("--password", type=str, default=None, help="MQTT password")
    args = parser.parse_args()

    cfg = load_config()
    mqtt_cfg = cfg.get("mqtt", {})
    broker = mqtt_cfg.get("broker_host", args.broker)
    port = int(mqtt_cfg.get("broker_port", args.port))
    user = mqtt_cfg.get("username", args.user)
    pwd = mqtt_cfg.get("password", args.password)
    disc_prefix = mqtt_cfg.get("discovery_prefix", "homeassistant")
    topic_prefix = mqtt_cfg.get("topic_prefix", "smartgarage")

    bridge = SmartGarageMQTTBridge(
        broker_host=broker,
        broker_port=port,
        username=user,
        password=pwd,
        discovery_prefix=disc_prefix,
        topic_prefix=topic_prefix
    )

    def _sig_handler(sig, frame):
        logger.info(f"Shutdown signal ({sig}) received.")
        bridge.stop()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        asyncio.run(bridge.run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bridge terminated.")


if __name__ == "__main__":
    main()
