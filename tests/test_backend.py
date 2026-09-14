import os
os.environ["TESTING"] = "1"
import unittest
import tempfile
import time
from pathlib import Path
import json

from server.memory.memory import Memory
from server.commands.processor import CommandProcessor
from server.router.router import CommandRouter
from server.storage.telemetry_db import TelemetryDB
from server.ai.tools import GARAGE_TOOLS, ToolDispatcher
from server.webapp import app


class DummyLogger:
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class DummyAI:
    def __init__(self):
        self.called_with = None
        self.last_context = None

    def chat(self, prompt, context_info=""):
        self.called_with = prompt
        self.last_context = context_info
        return f"AI response to: {prompt}"


class TestMemory(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        self.memory_file = Path(self.tmp.name)
        self.memory = Memory(filename=self.memory_file)

    def tearDown(self):
        if self.memory_file.exists():
            self.memory_file.unlink()

    def test_empty_memory(self):
        self.assertEqual(self.memory.all(), {})

    def test_set_and_get(self):
        self.memory.set("garage_door", "closed")
        self.assertEqual(self.memory.get("garage_door"), "closed")
        self.assertIsNone(self.memory.get("non_existent"))
        self.assertEqual(self.memory.get("non_existent", "default"), "default")

    def test_delete(self):
        self.memory.set("temp", 22)
        self.assertEqual(self.memory.get("temp"), 22)
        self.memory.delete("temp")
        self.assertIsNone(self.memory.get("temp"))

    def test_persistence(self):
        self.memory.set("key1", "val1")
        mem2 = Memory(filename=self.memory_file)
        self.assertEqual(mem2.get("key1"), "val1")


class TestCommandProcessor(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        self.memory_file = Path(self.tmp.name)
        self.memory = Memory(filename=self.memory_file)
        self.processor = CommandProcessor(DummyLogger(), memory=self.memory)

    def tearDown(self):
        if self.memory_file.exists():
            self.memory_file.unlink()

    def test_status_command(self):
        handled, response = self.processor.execute("status")
        self.assertTrue(handled)
        self.assertEqual(response, "Smart Garage is running.")

    def test_help_command(self):
        handled, response = self.processor.execute("help")
        self.assertTrue(handled)
        self.assertIn("Available commands:", response)

    def test_remember_and_memory_command(self):
        handled, resp = self.processor.execute("remember light on")
        self.assertTrue(handled)
        self.assertIn("Saved 'light'", resp)

        handled, resp = self.processor.execute("memory")
        self.assertTrue(handled)
        self.assertIn("'light': 'on'", resp)

    def test_forget_command(self):
        self.processor.execute("remember light on")
        handled, resp = self.processor.execute("forget light")
        self.assertTrue(handled)
        self.assertIn("Deleted 'light'", resp)
        self.assertEqual(self.memory.get("light"), None)

    def test_projector_commands(self):
        handled, resp = self.processor.execute("project status")
        self.assertTrue(handled)
        self.assertIn("Projector HY350MAX", resp)

        handled, resp = self.processor.execute("project pause")
        self.assertTrue(handled)
        self.assertIn("паузу", resp)

        handled, resp = self.processor.execute("project resume")
        self.assertTrue(handled)
        self.assertIn("продовжено", resp)

        handled, resp = self.processor.execute("зупини проектор")
        self.assertTrue(handled)
        self.assertIn("зупинено", resp)


    def test_esp32_commands(self):
        handled, resp = self.processor.execute("door open")
        self.assertTrue(handled)
        self.assertIn("OPEN", resp)

        handled, resp = self.processor.execute("відкрий ворота")
        self.assertTrue(handled)
        self.assertIn("відкрито", resp.lower())

        handled, resp = self.processor.execute("light on")
        self.assertTrue(handled)
        self.assertIn("увімкнено", resp.lower())

        handled, resp = self.processor.execute("fan on")
        self.assertTrue(handled)
        self.assertIn("увімкнено", resp.lower())

        handled, resp = self.processor.execute("sensors")
        self.assertTrue(handled)
        self.assertIn("Стан", resp)

    def test_floor_climate_commands(self):
        handled, resp = self.processor.execute("температура в підвалі")
        self.assertTrue(handled)
        self.assertIn("підвал", resp.lower())

        handled, resp = self.processor.execute("яка температура на 2 поверсі")
        self.assertTrue(handled)
        self.assertIn("2-му поверсі", resp.lower())

        handled, resp = self.processor.execute("клімат 1 поверх")
        self.assertTrue(handled)
        self.assertIn("1-му поверсі", resp.lower())

    def test_scenario_commands(self):
        handled, resp = self.processor.execute("я приїхав")
        self.assertTrue(handled)
        self.assertIn("Прибуття авто", resp)

        handled, resp = self.processor.execute("добраніч")
        self.assertTrue(handled)
        self.assertIn("Нічний режим", resp)

        handled, resp = self.processor.execute("сценарії")
        self.assertTrue(handled)
        self.assertIn("Доступні сценарії", resp)

    def test_unknown_command(self):
        handled, response = self.processor.execute("What is the weather outside?")
        self.assertFalse(handled)
        self.assertIsNone(response)



class TestProjectorController(unittest.TestCase):

    def setUp(self):
        from server.devices.projector import ProjectorController
        self.controller = ProjectorController(ip="127.0.0.1", port=9999)

    def test_initial_status(self):
        status = self.controller.get_status()
        self.assertEqual(status["ip"], "127.0.0.1")
        self.assertEqual(status["port"], 9999)
        self.assertFalse(status["mirroring"])

    def test_mirroring_toggle(self):
        self.controller.start_mirroring()
        self.assertTrue(self.controller.mirroring)
        self.controller.stop_mirroring()
        self.assertFalse(self.controller.mirroring)



class TestCommandRouter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        self.memory_file = Path(self.tmp.name)
        self.memory = Memory(filename=self.memory_file)
        self.processor = CommandProcessor(DummyLogger(), memory=self.memory)
        self.ai = DummyAI()
        self.router = CommandRouter(self.processor, self.ai)

    def tearDown(self):
        if self.memory_file.exists():
            self.memory_file.unlink()

    def test_routes_status_to_processor(self):
        response = self.router.execute("status")
        self.assertEqual(response, "Smart Garage is running.")
        self.assertIsNone(self.ai.called_with)

    def test_routes_ai_query_to_ai(self):
        response = self.router.execute("Tell me a joke")
        self.assertEqual(response, "AI response to: Tell me a joke")
        self.assertEqual(self.ai.called_with, "Tell me a joke")

    def test_routes_ai_query_with_context_provider(self):
        router = CommandRouter(self.processor, self.ai, context_provider=lambda: "temp: 20C")
        res = router.execute("What is the temperature?")
        self.assertEqual(self.ai.called_with, "What is the temperature?")
        self.assertEqual(self.ai.last_context, "temp: 20C")

    def test_empty_or_none_prompt(self):
        self.assertEqual(self.router.execute(""), "")
        self.assertEqual(self.router.execute(None), "")
        self.assertEqual(self.router.execute("   "), "")


class TestWebApp(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    def test_health_endpoint(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {"status": "ok"})

    def test_command_endpoint_missing(self):
        res = self.client.post("/command", json={})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["success"])

    def test_command_endpoint_status(self):
        res = self.client.post("/command", json={"command": "status"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["response"], "Smart Garage is running.")


    def test_index_page(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Smart Garage", res.data)
        self.assertIn(b"app.js", res.data)

    def test_dashboard_page(self):
        res = self.client.get("/dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Smart Garage", res.data)
        self.assertIn(b"dashboard.js", res.data)

        res_floor1 = self.client.get("/floor1")
        self.assertEqual(res_floor1.status_code, 200)
        self.assertIn(b"dashboard.js", res_floor1.data)

    def test_static_assets(self):
        with self.client.get("/static/css/style.css") as css_res:
            self.assertEqual(css_res.status_code, 200)
        with self.client.get("/static/js/app.js") as js_res:
            self.assertEqual(js_res.status_code, 200)
        with self.client.get("/static/css/dashboard.css") as dash_css:
            self.assertEqual(dash_css.status_code, 200)
        with self.client.get("/static/js/dashboard.js") as dash_js:
            self.assertEqual(dash_js.status_code, 200)
        with self.client.get("/static/js/chart.min.js") as chart_res:
            self.assertEqual(chart_res.status_code, 200)
        with self.client.get("/manifest.json") as manifest_res:
            self.assertEqual(manifest_res.status_code, 200)

    def test_telemetry_history_endpoint(self):
        res = self.client.get("/api/telemetry/history?floor=basement&hours=24")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("history", data)
        self.assertIn("points", data)
        self.assertIn("stats", data)

    def test_system_stats_endpoint(self):
        res = self.client.get("/api/system/stats")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("cpu_temp", data["stats"])
        self.assertIn("ram_percent", data["stats"])
        self.assertIn("uptime_str", data["stats"])

    def test_device_control_endpoints(self):
        res_light = self.client.post("/api/device/light/toggle")
        self.assertEqual(res_light.status_code, 200)
        self.assertTrue(res_light.get_json()["success"])

        res_light_state = self.client.post("/api/device/light/state", json={"state": True})
        self.assertEqual(res_light_state.status_code, 200)
        self.assertTrue(res_light_state.get_json()["success"])

        res_fan = self.client.post("/api/device/fan/toggle")
        self.assertEqual(res_fan.status_code, 200)
        self.assertTrue(res_fan.get_json()["success"])

        res_door = self.client.post("/api/device/door/toggle")
        self.assertEqual(res_door.status_code, 200)
        self.assertTrue(res_door.get_json()["success"])

    def test_garage_state_endpoint(self):
        res = self.client.get("/api/garage/state")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("door", data["state"])

    def test_esp32_telemetry_webhook(self):
        res = self.client.post("/api/esp32/telemetry", json={"temperature": 24.0, "humidity": 55.0, "car_present": True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])


    def test_scenario_endpoint(self):
        res = self.client.post("/api/scenarios/arrival")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

    def test_telemetry_history_endpoint(self):
        res = self.client.get("/api/telemetry/history")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["history"], list)
        self.assertGreater(len(data["history"]), 0)

    def test_media_list_endpoint(self):
        res = self.client.get("/api/media/list")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["media"], list)

    def test_media_control_endpoint(self):
        res = self.client.post("/api/media/control", json={"action": "pause"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

        res_stop = self.client.post("/api/media/control", json={"action": "stop"})
        self.assertEqual(res_stop.status_code, 200)
        self.assertTrue(res_stop.get_json()["success"])

    def test_projector_status_endpoint(self):
        res = self.client.get("/api/projector/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("projector", data)

    def test_projector_mirror_endpoint(self):
        res = self.client.post("/api/projector/mirror", json={"action": "stop"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["mirroring"])

    def test_sensors_floors_endpoint(self):
        res = self.client.get("/api/sensors/floors")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("floors", data)
        self.assertIn("floor1", data["floors"])
        self.assertIn("floor2", data["floors"])
        self.assertIn("basement", data["floors"])

    def test_sensors_bind_endpoint(self):
        res = self.client.post("/api/sensors/bind", json={"floor": "floor2", "mac": "A4:C1:38:EC:EC:6C", "alias": "2-й поверх"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])


class TestESP32Controller(unittest.TestCase):

    def setUp(self):
        from server.devices.esp32 import ESP32Controller
        self.esp = ESP32Controller(host="127.0.0.1", port=9998)

    def test_door_actions(self):
        self.assertEqual(self.esp.door_open(), "open")
        self.assertEqual(self.esp.door_close(), "closed")
        self.assertEqual(self.esp.door_toggle(), "open")

    def test_light_actions(self):
        self.assertTrue(self.esp.light_on())
        self.assertFalse(self.esp.light_off())
        self.assertTrue(self.esp.light_toggle())

    def test_fan_actions(self):
        self.assertTrue(self.esp.fan_on())
        self.assertFalse(self.esp.fan_off())
        self.assertTrue(self.esp.fan_toggle())

    def test_telemetry(self):
        tel = self.esp.get_telemetry()
        self.assertIn("temperature", tel)
        self.assertIn("humidity", tel)
        self.assertIn("car_present", tel)


class TestAutomationEngine(unittest.TestCase):

    def setUp(self):
        from server.devices.esp32 import ESP32Controller
        from server.devices.projector import ProjectorController
        from server.automation.engine import AutomationEngine
        self.esp = ESP32Controller(host="127.0.0.1", port=9997)
        self.projector = ProjectorController(ip="127.0.0.1", port=9996)
        self.engine = AutomationEngine(self.esp, self.projector, logger=DummyLogger())

    def test_arrival_scenario(self):
        success, msg = self.engine.scenario_car_arrival()
        self.assertTrue(success)
        self.assertEqual(self.esp.state["door"], "open")
        self.assertTrue(self.esp.state["light"])

    def test_night_scenario(self):
        success, msg = self.engine.scenario_night_mode()
        self.assertTrue(success)
        self.assertEqual(self.esp.state["door"], "closed")
        self.assertFalse(self.esp.state["light"])

    def test_gas_alarm_scenario(self):
        success, msg = self.engine.scenario_gas_alarm()
        self.assertTrue(success)
        self.assertTrue(self.esp.state["fan"])


class TestPresenceBLEMatching(unittest.TestCase):
    """Covers RPA-rotation matching for BLE-only devices (earbuds, fitness bands)
    that don't respond to Classic Bluetooth, via Service UUID and continuity fallback.
    """

    def setUp(self):
        from server.devices.presence import PresenceManager
        self.tmp_dir = tempfile.TemporaryDirectory()
        # Small window/tolerance for deterministic, fast tests.
        self.presence = PresenceManager(
            data_dir=Path(self.tmp_dir.name),
            logger=DummyLogger(),
            presence_config={
                "rpa_continuity_window_sec": 120,
                "rpa_continuity_rssi_tolerance": 10,
            }
        )
        # Clear the auto-registered owner_phone/owner_watch defaults so tests
        # only deal with the fixtures they set up explicitly.
        self.presence.devices = {}
        self.presence._save_devices()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_service_uuid_match_survives_rpa_rotation(self):
        """A BLE-only device (e.g. earbuds) keeps its Service UUID across MAC rotation."""
        self.presence.register_device(
            device_id="owner_earbuds",
            name="Юрій (Навушники)",
            role="owner",
            device_type="earbuds",
            ble_services=["3e1d50cd-0000-0000-0000-000000000001"],
            ble_mac="AA:AA:AA:AA:AA:01"
        )

        # New, never-before-seen MAC, but same Service UUID as registered.
        result = self.presence.record_sighting(
            mac="BB:BB:BB:BB:BB:02",
            name="",
            rssi=-55,
            service_uuids=["3e1d50cd-0000-0000-0000-000000000001"],
            source="esp32_ble"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "owner_earbuds")
        self.assertIn("BB:BB:BB:BB:BB:02", result["recent_ble_rpa"])
        self.assertEqual(result["status"], "present")

    def test_service_uuid_mismatch_does_not_match(self):
        """A device advertising an unrelated Service UUID must not be matched."""
        self.presence.register_device(
            device_id="owner_earbuds",
            name="Юрій (Навушники)",
            role="owner",
            ble_services=["3e1d50cd-0000-0000-0000-000000000001"],
            ble_mac="AA:AA:AA:AA:AA:01"
        )

        result = self.presence.record_sighting(
            mac="CC:CC:CC:CC:CC:03",
            name="",
            rssi=-55,
            service_uuids=["00000000-1111-2222-3333-444444444444"],
            source="esp32_ble"
        )

        self.assertIsNone(result)

    def test_rpa_continuity_heuristic_matches_close_rssi_within_window(self):
        """An unrecognized MAC appearing shortly after a known device vanished, with
        similar RSSI and no Service UUID, is matched via the continuity fallback."""
        self.presence.register_device(
            device_id="owner_band",
            name="Юрій (Браслет)",
            role="owner",
            device_type="bracelet",
            ble_mac="AA:AA:AA:AA:AA:11"
        )
        # Simulate the device having been seen recently with a given RSSI.
        with self.presence._lock:
            self.presence.devices["owner_band"]["status"] = "present"
            self.presence.devices["owner_band"]["last_rssi"] = -60
            self.presence.devices["owner_band"]["last_seen"] = time.time() - 5

        result = self.presence.record_sighting(
            mac="DD:DD:DD:DD:DD:22",
            name="",
            rssi=-64,  # within tolerance (10 dBm) of -60
            service_uuids=[],
            source="esp32_ble"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "owner_band")
        self.assertIn("DD:DD:DD:DD:DD:22", result["recent_ble_rpa"])

    def test_rpa_continuity_heuristic_rejects_outside_window(self):
        """No continuity match once the device has been silent longer than the window."""
        self.presence.register_device(
            device_id="owner_band",
            name="Юрій (Браслет)",
            role="owner",
            ble_mac="AA:AA:AA:AA:AA:11"
        )
        with self.presence._lock:
            self.presence.devices["owner_band"]["status"] = "present"
            self.presence.devices["owner_band"]["last_rssi"] = -60
            # Outside the 120s test window.
            self.presence.devices["owner_band"]["last_seen"] = time.time() - 300

        result = self.presence.record_sighting(
            mac="EE:EE:EE:EE:EE:33",
            name="",
            rssi=-61,
            service_uuids=[],
            source="esp32_ble"
        )

        self.assertIsNone(result)

    def test_rpa_continuity_heuristic_rejects_large_rssi_delta(self):
        """No continuity match if the RSSI jump is too large to plausibly be the same
        physical device (more likely a different, unrelated peripheral)."""
        self.presence.register_device(
            device_id="owner_band",
            name="Юрій (Браслет)",
            role="owner",
            ble_mac="AA:AA:AA:AA:AA:11"
        )
        with self.presence._lock:
            self.presence.devices["owner_band"]["status"] = "present"
            self.presence.devices["owner_band"]["last_rssi"] = -50
            self.presence.devices["owner_band"]["last_seen"] = time.time() - 5

        result = self.presence.record_sighting(
            mac="FF:FF:FF:FF:FF:44",
            name="",
            rssi=-90,  # 40 dBm jump, well outside the 10 dBm tolerance
            service_uuids=[],
            source="esp32_ble"
        )

        self.assertIsNone(result)

    def test_classic_mac_match_still_takes_priority(self):
        """Existing Classic MAC matching behavior (e.g. owner's phone) is unchanged."""
        self.presence.register_device(
            device_id="owner_phone",
            name="Юрій",
            role="owner",
            device_type="phone",
            classic_mac="B8:7E:39:88:22:9B"
        )

        result = self.presence.record_sighting(
            mac="B8:7E:39:88:22:9B",
            name="",
            rssi=-47,
            service_uuids=[],
            source="bluetooth_classic"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "owner_phone")


class TestTelemetryDB(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        self.db = TelemetryDB(db_path=str(self.db_path))

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()
        wal = self.db_path.with_name(self.db_path.name + "-wal")
        shm = self.db_path.with_name(self.db_path.name + "-shm")
        if wal.exists(): wal.unlink()
        if shm.exists(): shm.unlink()

    def test_record_and_get_history(self):
        # Record initial reading
        now = time.time()
        ok1 = self.db.record(floor="basement", temperature=21.5, humidity=55.0, battery=90, timestamp=now - 3600, force=True)
        self.assertTrue(ok1)

        ok2 = self.db.record(floor="basement", temperature=22.0, humidity=54.0, battery=89, timestamp=now, force=True)
        self.assertTrue(ok2)

        ok3 = self.db.record(floor="floor2", temperature=23.0, humidity=50.0, battery=95, timestamp=now, force=True)
        self.assertTrue(ok3)

        # Query basement history
        history_b = self.db.get_history(floor="basement", hours=24)
        self.assertTrue(history_b["success"])
        self.assertEqual(len(history_b["points"]), 2)
        stats = history_b["stats"]
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["min_temp"], 21.5)
        self.assertEqual(stats["max_temp"], 22.0)
        self.assertEqual(stats["current_temp"], 22.0)

        # Query floor2 history
        history_f2 = self.db.get_history(floor="floor2", hours=24)
        self.assertTrue(history_f2["success"])
        self.assertEqual(len(history_f2["points"]), 1)
        self.assertEqual(history_f2["stats"]["current_temp"], 23.0)

    def test_rate_limiting(self):
        now = time.time()
        # First record
        ok1 = self.db.record(floor="basement", temperature=20.0, humidity=50.0, timestamp=now)
        self.assertTrue(ok1)

        # Immediate record with identical values within 60s should be skipped
        ok2 = self.db.record(floor="basement", temperature=20.0, humidity=50.0, timestamp=now + 10)
        self.assertFalse(ok2)

        # Significant change should be recorded
        ok3 = self.db.record(floor="basement", temperature=21.0, humidity=50.0, timestamp=now + 15)
        self.assertTrue(ok3)

    def test_latest_by_floor(self):
        now = time.time()
        self.db.record(floor="basement", temperature=18.5, humidity=60.0, timestamp=now - 10, force=True)
        self.db.record(floor="floor2", temperature=22.2, humidity=48.0, timestamp=now, force=True)

        latest = self.db.get_latest_by_floor()
        self.assertIn("basement", latest)
        self.assertIn("floor2", latest)
        self.assertEqual(latest["basement"]["temperature"], 18.5)
        self.assertEqual(latest["floor2"]["temperature"], 22.2)


class TestAITools(unittest.TestCase):

    def setUp(self):
        from server.core.core import SmartGarage
        self.garage = SmartGarage(start_workers=False)
        self.dispatcher = ToolDispatcher(self.garage)

    def test_garage_tools_schema(self):
        self.assertTrue(len(GARAGE_TOOLS) >= 5)
        names = [t["function"]["name"] for t in GARAGE_TOOLS]
        self.assertIn("control_device", names)
        self.assertIn("play_media", names)
        self.assertIn("stop_media", names)
        self.assertIn("run_scenario", names)
        self.assertIn("speaker_control", names)
        self.assertIn("get_climate_history", names)
        self.assertIn("show_climate_chart", names)

    def test_control_device_door(self):
        res = self.dispatcher.execute("control_device", {"device": "door", "action": "open"})
        self.assertTrue(res["success"])
        self.assertIn("відчиняються", res["message"])

        res_close = self.dispatcher.execute("control_device", {"device": "door", "action": "close"})
        self.assertTrue(res_close["success"])
        self.assertIn("зачиняються", res_close["message"])

    def test_control_device_light_and_fan(self):
        res_l = self.dispatcher.execute("control_device", {"device": "light", "action": "on"})
        self.assertTrue(res_l["success"])
        self.assertTrue(self.garage.esp32.state["light"])

        res_f = self.dispatcher.execute("control_device", {"device": "fan", "action": "on"})
        self.assertTrue(res_f["success"])
        self.assertTrue(self.garage.esp32.state["fan"])

    def test_run_scenario(self):
        res = self.dispatcher.execute("run_scenario", {"scenario": "arrival"})
        self.assertTrue(res["success"])
        self.assertIn("виконано", res["message"])

    def test_show_climate_chart_tool(self):
        from unittest.mock import MagicMock
        self.garage.telegram.send_climate_chart = MagicMock(return_value=True)
        res = self.dispatcher.execute("show_climate_chart", {"floor": "floor1", "hours": 24}, session_id="tg_12345")
        self.assertTrue(res["success"])
        self.assertTrue(res["fallback_to_basement"])
        self.garage.telegram.send_climate_chart.assert_called_once_with(chat_id=12345, floor="basement", hours=24.0)

    def test_unknown_tool(self):
        res = self.dispatcher.execute("non_existent_tool", {})
        self.assertFalse(res["success"])
        self.assertIn("Невідомий інструмент", res["error"])


class TestChartRenderer(unittest.TestCase):

    def test_generate_climate_chart(self):
        from server.storage.chart_renderer import generate_climate_chart
        points = [
            {"timestamp": time.time() - 3600, "temperature": 18.5, "humidity": 70.0},
            {"timestamp": time.time(), "temperature": 18.8, "humidity": 71.5},
        ]
        stats = {"current_temp": 18.8, "min_temp": 18.5, "max_temp": 18.8, "current_hum": 71.5}
        chart_bytes = generate_climate_chart(points, stats, floor_title="Підвал", hours=24.0)
        self.assertIsNotNone(chart_bytes)
        self.assertTrue(isinstance(chart_bytes, bytes))
        self.assertTrue(chart_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_generate_climate_chart_empty(self):
        from server.storage.chart_renderer import generate_climate_chart
        self.assertIsNone(generate_climate_chart([], {}))


if __name__ == "__main__":
    unittest.main()




