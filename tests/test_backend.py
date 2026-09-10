import os
os.environ["TESTING"] = "1"
import unittest
import tempfile
from pathlib import Path
import json

from server.memory.memory import Memory
from server.commands.processor import CommandProcessor
from server.router.router import CommandRouter
from server.webapp import app


class DummyLogger:
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class DummyAI:
    def __init__(self):
        self.called_with = None

    def chat(self, prompt):
        self.called_with = prompt
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
        with self.client.get("/manifest.json") as manifest_res:
            self.assertEqual(manifest_res.status_code, 200)

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


if __name__ == "__main__":
    unittest.main()




