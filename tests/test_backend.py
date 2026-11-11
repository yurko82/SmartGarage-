import os

os.environ["TESTING"] = "1"
os.environ["ADMIN_PIN"] = "9876"
os.environ["ESP32_API_KEY"] = "test_esp32_secret_key_12345"
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.ai.tools import GARAGE_TOOLS, ToolDispatcher
from server.commands.processor import CommandProcessor
from server.memory.memory import Memory
from server.router.router import CommandRouter
from server.storage.telemetry_db import TelemetryDB
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

        handled, resp = self.processor.execute("стан проектора")
        self.assertTrue(handled)
        self.assertIn("Проектор HY350MAX", resp)

        handled, resp = self.processor.execute("підключись до проектора")
        self.assertTrue(handled)
        self.assertIn("HY350MAX", resp)

        handled, resp = self.processor.execute("спроби з'єднатися з проектором")
        self.assertTrue(handled)
        self.assertIn("HY350MAX", resp)

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
        self.assertIn("вимкнено", resp.lower())

        handled, resp = self.processor.execute("відкрий ворота")
        self.assertTrue(handled)
        self.assertIn("вимкнено", resp.lower())

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

    def test_youtube_music_song_commands(self):
        import unittest.mock
        with unittest.mock.patch.object(self.processor.speaker, "play_youtube", return_value=True) as mock_play:
            handled, resp = self.processor.execute("включи пісню")
            self.assertTrue(handled)
            self.assertIn("YouTube Music", resp)
            mock_play.assert_called_with("ADAM - Сильно Сильно")

        with unittest.mock.patch.object(self.processor.speaker, "play_youtube", return_value=True) as mock_play:
            handled, resp = self.processor.execute("просто включи пісню")
            self.assertTrue(handled)
            self.assertIn("YouTube Music", resp)
            mock_play.assert_called_with("ADAM - Сильно Сильно")

        with unittest.mock.patch.object(self.processor.speaker, "play_youtube", return_value=True) as mock_play:
            handled, resp = self.processor.execute("включи пісню на ютуб мюзік")
            self.assertTrue(handled)
            self.assertIn("YouTube Music", resp)
            mock_play.assert_called_with("ADAM - Сильно Сильно")

        with unittest.mock.patch.object(self.processor.speaker, "play_youtube", return_value=True) as mock_play:
            handled, resp = self.processor.execute("включи пісню adam сильно-сильно на youtube music")
            self.assertTrue(handled)
            self.assertIn("YouTube Music", resp)
            mock_play.assert_called_with("adam сильно-сильно")

        with unittest.mock.patch.object(self.processor.speaker, "play_youtube", return_value=True) as mock_play:
            handled, resp = self.processor.execute("просто включи музику")
            self.assertTrue(handled)
            self.assertIn("YouTube Music", resp)

    def test_youtube_music_playlist_commands(self):
        import unittest.mock
        # 1. Inquiry for playlists
        handled, resp = self.processor.execute("мої плейлисти")
        self.assertTrue(handled)
        self.assertIn("Ваші плейлисти", resp)

        # 2. Play liked songs (sequential by default)
        with unittest.mock.patch.object(self.processor.speaker, "play_liked", return_value=(True, "Улюблені пісні", "TUMAN")) as mock_liked:
            handled, resp = self.processor.execute("включи мої улюблені")
            self.assertTrue(handled)
            self.assertIn("Улюблені пісні", resp)
            self.assertIn("TUMAN", resp)
            mock_liked.assert_called_with(shuffle=False)

            handled, resp = self.processor.execute("включи мої улюблені перемішай")
            self.assertTrue(handled)
            mock_liked.assert_called_with(shuffle=True)

        # 3. Play specific playlist
        with unittest.mock.patch("server.services.ytmusic_service.ytmusic_service.find_playlist", return_value={"id": "PL123", "title": "Український рок: драйв та емоції"}), \
             unittest.mock.patch.object(self.processor.speaker, "play_playlist", return_value=(True, "Український рок: драйв та емоції", "Пригадай")) as mock_pl:
            handled, resp = self.processor.execute("включи плейлист рок")
            self.assertTrue(handled)
            self.assertIn("Український рок", resp)
            self.assertIn("Пригадай", resp)

        # 4. Next song voice command
        with unittest.mock.patch.object(self.processor.speaker, "play_next", return_value=(True, "Плейлист", "Бумбокс")) as mock_next:
            handled, resp = self.processor.execute("наступна пісня")
            self.assertTrue(handled)
            self.assertIn("Бумбокс", resp)
            mock_next.assert_called_once()

    def test_unknown_command(self):
        handled, response = self.processor.execute("What is the weather outside?")
        self.assertFalse(handled)
        self.assertIsNone(response)

    def test_wake_phrase_commands(self):
        # Exact wake phrases
        for phrase in ("альо, гараж", "Альо гараж", "Ало, гараж", "алло гараж", "Альо, гараж?", "Гараж", "гараж, прийом"):
            handled, resp = self.processor.execute(phrase)
            self.assertTrue(handled, f"Failed for phrase: {phrase}")
            self.assertEqual(resp, "Що тобі потрібно?")

        # Pure echo prompts must return None / empty to break any loop
        for phrase in ("що тобі потрібно", "що тобі треба", "що треба", "що потрібно"):
            handled, resp = self.processor.execute(phrase)
            self.assertTrue(handled, f"Failed for echo phrase: {phrase}")
            self.assertIsNone(resp)

        # Wake phrase with actual commands
        handled, resp = self.processor.execute("Альо гараж, відчини ворота")
        self.assertTrue(handled)
        self.assertIn("вимкнено", resp)

        handled, resp = self.processor.execute("Альо гараж увімкни світло")
        self.assertTrue(handled)
        self.assertIn("Освітлення", resp)

        handled, resp = self.processor.execute("Ало гараж увімкни вентиляцію")
        self.assertTrue(handled)
        self.assertIn("Вентиляцію", resp)

        # Echo prompt prefix stripped when microphone captured assistant's own voice before command
        handled, resp = self.processor.execute("Що тобі потрібно, увімкни світло")
        self.assertTrue(handled)
        self.assertIn("Освітлення", resp)

        self.processor._last_wake_prompt_time = 0.0
        handled, resp = self.processor.execute("Що тобі треба увімкни вентиляцію")
        self.assertTrue(handled)
        self.assertIn("Вентиляцію", resp)

    def test_radio_commands_routing(self):
        from unittest.mock import MagicMock
        mock_speaker = MagicMock()
        mock_speaker.name = "Юрій: JBL Clip 5"
        mock_speaker.play_stream.return_value = True
        self.processor.speaker = mock_speaker

        handled, resp = self.processor.execute("включи радіо на jbl")
        self.assertTrue(handled)
        mock_speaker.set_active_speaker.assert_called_with(self.processor.garage_speaker_mac, "Юрій: JBL Clip 5")
        self.assertIn("Hit FM", resp)
        self.assertIn("JBL Clip 5", resp)

        handled, resp = self.processor.execute("увімкни радіо kiss fm на jbl")
        self.assertTrue(handled)
        self.assertIn("Kiss FM", resp)

        handled, resp = self.processor.execute("вкючи радіо хіт фм")
        self.assertTrue(handled)
        self.assertIn("Hit FM", resp)

        handled, resp = self.processor.execute("зупини радіо на jbl")
        self.assertTrue(handled)
        mock_speaker.stop.assert_called()

        mock_speaker.connect.return_value = True
        handled, resp = self.processor.execute("на оид грає норм, спробуй включити на xt-bt")
        self.assertTrue(handled)
        mock_speaker.set_active_speaker.assert_called_with(self.processor.floor1_speaker_mac, "JX-BT (1-й поверх)")
        self.assertIn("JX-BT", resp)

        # Commands without explicit word 'радіо'
        handled, resp = self.processor.execute("включи кіс фм")
        self.assertTrue(handled)
        self.assertIn("Kiss FM", resp)

        handled, resp = self.processor.execute("увімкни кіс фм")
        self.assertTrue(handled)
        self.assertIn("Kiss FM", resp)

        handled, resp = self.processor.execute("включи хіт фм")
        self.assertTrue(handled)
        self.assertIn("Hit FM", resp)

        handled, resp = self.processor.execute("kiss fm")
        self.assertTrue(handled)
        self.assertIn("Kiss FM", resp)

    def test_audio_inquiries_not_intercepted_as_playback(self):
        # Inquiries like "чому не грає..." must NOT be intercepted as streaming commands
        for q in (
            "чому не грає радіо",
            "чому не грає хіт фм",
            "чому не грає хід фм",
            "чому мовчить колонка",
            "чому вимкнено радіо",
            "чому не чути музику",
            "радіо чому не грає хід фм",
        ):
            handled, resp = self.processor.execute(q)
            self.assertFalse(handled, f"Query '{q}' should NOT be handled as a command, but routed to AI")

    def test_audio_status_inquiries(self):
        mock_speaker = MagicMock()
        mock_speaker.get_status.return_value = {
            "name": "Музика 1-й поверх",
            "volume": 40,
            "playing": True,
            "paused": False,
            "current_track": "📻 Хіт FM"
        }
        self.processor.speaker = mock_speaker
        handled, resp = self.processor.execute("що зараз грає")
        self.assertTrue(handled)
        self.assertIn("Хіт FM", resp)
        self.assertIn("40%", resp)

        mock_speaker.get_status.return_value = {
            "name": "Музика 1-й поверх",
            "volume": 0,
            "playing": False,
            "paused": False,
            "current_track": None
        }
        handled, resp = self.processor.execute("чи грає радіо")
        self.assertTrue(handled)
        self.assertIn("не грає", resp)



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

    def test_routes_layout_typo_prompt(self):
        # 'cnfy' in English layout corresponds to 'стан' in Ukrainian
        res = self.router.execute("cnfy")
        self.assertIn("Smart Garage", res)
        self.assertIsNone(self.ai.called_with)

    def test_wake_phrase_routing(self):
        res = self.router.execute("Альо, гараж")
        self.assertEqual(res, "Що тобі потрібно?")
        self.assertIsNone(self.ai.called_with)

        # Accidental QWERTY layout: 'Fkmj ufhf;' -> 'Альо гараж'
        res = self.router.execute("Fkmj ufhf;")
        self.assertEqual(res, "Що тобі потрібно?")
        self.assertIsNone(self.ai.called_with)

        # Wake phrase prefix before AI query strips prefix
        res = self.router.execute("Альо гараж, розкажи казку")
        self.assertEqual(self.ai.called_with, "розкажи казку")

    def test_audio_inquiry_routes_to_ai(self):
        # Audio inquiries must be passed to AI rather than returning station not found
        res = self.router.execute("чому не грає радіо")
        self.assertEqual(self.ai.called_with, "чому не грає радіо")

        res2 = self.router.execute("чому не грає хід фм")
        self.assertEqual(self.ai.called_with, "чому не грає хід фм")

    def test_scan_and_complex_inquiry_routes_to_ai(self):
        res = self.router.execute("Проскануй повністю bluetooth ефір що ти бачиш дай мені номінування датчиків в загальному")
        self.assertEqual(self.ai.called_with, "Проскануй повністю bluetooth ефір що ти бачиш дай мені номінування датчиків в загальному")

        res2 = self.router.execute("чому датчик у підвалі показує таку вологість")
        self.assertEqual(self.ai.called_with, "чому датчик у підвалі показує таку вологість")


class TestWebApp(unittest.TestCase):

    def setUp(self):
        app.config["TESTING"] = True
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
        self.assertIn(b"api.js", res.data)
        self.assertIn(b"app.js", res.data)

    def test_dashboard_page(self):
        res = self.client.get("/dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Smart Garage", res.data)
        self.assertIn(b"api.js", res.data)
        self.assertIn(b"dashboard.js", res.data)

        res_floor1 = self.client.get("/floor1")
        self.assertEqual(res_floor1.status_code, 200)
        self.assertIn(b"api.js", res_floor1.data)
        self.assertIn(b"dashboard.js", res_floor1.data)

    def test_static_assets(self):
        with self.client.get("/static/css/style.css") as css_res:
            self.assertEqual(css_res.status_code, 200)
        with self.client.get("/static/js/api.js") as api_js_res:
            self.assertEqual(api_js_res.status_code, 200)
            self.assertIn(b"GarageAPI", api_js_res.data)
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

    def test_telemetry_history_query_params(self):
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
        self.assertFalse(res_door.get_json()["success"])
        self.assertEqual(res_door.get_json()["door"], "unknown")
        self.assertIn("error", res_door.get_json())

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
        from server.webapp import garage, telemetry_history
        if hasattr(garage, "telemetry_db") and garage.telemetry_db:
            garage.telemetry_db.record(floor="floor1", temperature=20.0, humidity=50.0, force=True)
        else:
            telemetry_history.add({"temperature": 20.0, "humidity": 50.0})
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
        res = self.client.post("/api/sensors/bind", json={"floor": "floor2", "mac": "00:11:22:33:44:04", "alias": "2-й поверх"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])


class TestESP32Controller(unittest.TestCase):

    def setUp(self):
        from server.devices.esp32 import ESP32Controller
        self.esp = ESP32Controller(host="127.0.0.1", port=9998)

    def test_door_actions(self):
        self.assertEqual(self.esp.door_open(), "unknown")
        self.assertEqual(self.esp.door_close(), "unknown")
        self.assertEqual(self.esp.door_toggle(), "unknown")

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
        from server.automation.engine import AutomationEngine
        from server.devices.esp32 import ESP32Controller
        from server.devices.projector import ProjectorController
        self.esp = ESP32Controller(host="127.0.0.1", port=9997)
        self.projector = ProjectorController(ip="127.0.0.1", port=9996)
        self.engine = AutomationEngine(self.esp, self.projector, logger=DummyLogger())

    def test_arrival_scenario(self):
        success, msg = self.engine.scenario_car_arrival()
        self.assertTrue(success)
        self.assertNotIn("door", self.esp.state)
        self.assertTrue(self.esp.state["light"])

    def test_night_scenario(self):
        success, msg = self.engine.scenario_night_mode()
        self.assertTrue(success)
        self.assertNotIn("door", self.esp.state)
        self.assertFalse(self.esp.state["light"])

    def test_gas_alarm_scenario(self):
        success, msg = self.engine.scenario_gas_alarm()
        self.assertFalse(success)
        self.assertIn("не встановлений", msg)


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
            classic_mac="00:11:22:33:44:05"
        )

        result = self.presence.record_sighting(
            mac="00:11:22:33:44:05",
            name="",
            rssi=-47,
            service_uuids=[],
            source="bluetooth_classic"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "owner_phone")

    def test_guest_registration_with_custom_absence_rules(self):
        """Guests can be registered with custom voice message and Telegram Chat ID."""
        guest = self.presence.register_device(
            device_id="guest_max",
            name="Макс",
            role="guest",
            device_type="phone",
            device_name="iPhone Макса",
            ble_mac="11:22:33:44:55:66",
            absence_voice_message="Макс, Юри в гаражі немає, гуляйте собі далі...",
            telegram_chat_id="987654321",
            notify_owner=True
        )
        self.assertEqual(guest["id"], "guest_max")
        self.assertEqual(guest["name"], "Макс")
        self.assertEqual(guest["absence_voice_message"], "Макс, Юри в гаражі немає, гуляйте собі далі...")
        self.assertEqual(guest["telegram_chat_id"], "987654321")
        self.assertTrue(guest["notify_owner"])

        # Test update_device
        updated = self.presence.update_device(
            "guest_max",
            absence_voice_message="Максе, гараж зачинено, подзвони Юрі."
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["absence_voice_message"], "Максе, гараж зачинено, подзвони Юрі.")

    def test_visitor_report_generation(self):
        """PresenceManager generates visitor report aggregating visits."""
        self.presence.register_device(
            device_id="guest_max",
            name="Макс",
            role="guest",
            ble_mac="11:22:33:44:55:66"
        )
        self.presence._add_log_entry(
            event="ARRIVED",
            device_id="guest_max",
            person_name="Макс",
            device_name="iPhone",
            rssi=-65
        )
        rep = self.presence.get_visitor_report(days=1)
        self.assertTrue(rep["total_registered_guests"] >= 1)
        self.assertTrue(rep["visits_today_count"] >= 1)
        visitor_ids = [v["id"] for v in rep["visitors"]]
        self.assertIn("guest_max", visitor_ids)


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
        self.assertIn("scan_bluetooth_devices", names)
        self.assertIn("manage_workshop_profile", names)
        self.assertIn("search_bike_knowledge", names)
        self.assertIn("manage_presence_guest", names)
        self.assertIn("get_visitor_report", names)

    def test_scan_bluetooth_devices_tool(self):
        with patch("server.webapp._scan_all_ble") as mock_scan:
            mock_scan.return_value = [
                {"mac": "00:11:22:33:44:03", "name": "LYWSD03MMC", "rssi": -55, "source": "ble"},
                {"mac": "11:22:33:44:55:66", "name": "", "rssi": -85, "source": "ble"}
            ]
            res = self.dispatcher.execute("scan_bluetooth_devices", {"duration": 5})
            self.assertTrue(res["success"])
            self.assertEqual(res["count"], 2)
            dev_names = [d["name"] for d in res["devices"]]
            self.assertIn("Xiaomi Mijia (Підвал)", dev_names)
            # Пристрої, яких не було в ефірі (JBL Clip 5, Motorola), категорично не повинні додаватися
            self.assertNotIn("JBL Clip 5 (Гараж)", dev_names)
            self.assertNotIn("Motorola Edge 50 Pro (Юрій)", dev_names)

    def test_manage_workshop_profile_tool(self):
        # 1. Get profile
        res_get = self.dispatcher.execute("manage_workshop_profile", {"action": "get"})
        self.assertTrue(res_get["success"])
        self.assertIn("profile", res_get)

        # 2. Add client bike
        res_bike = self.dispatcher.execute("manage_workshop_profile", {
            "action": "add_client_bike",
            "bike_model": "Trek Marlin 7",
            "client_name": "Олег",
            "work_description": "Прокачування гальм та заміна ланцюга"
        })
        self.assertTrue(res_bike["success"])
        bike_id = res_bike["bike"]["id"]

        # 3. Update bike status
        res_upd = self.dispatcher.execute("manage_workshop_profile", {
            "action": "update_bike_status",
            "bike_id": bike_id,
            "status": "completed"
        })
        self.assertTrue(res_upd["success"])

        # 4. Add tool
        res_tool = self.dispatcher.execute("manage_workshop_profile", {
            "action": "add_tool",
            "tool_name": "Park Tool DAG-2.2"
        })
        self.assertTrue(res_tool["success"])

        # 5. Add note
        res_note = self.dispatcher.execute("manage_workshop_profile", {
            "action": "add_note",
            "note": "Перевірити запас колонок B01S"
        })
        self.assertTrue(res_note["success"])

    def test_search_bike_knowledge_tool(self):
        # 1. Search torque
        res_t = self.dispatcher.execute("search_bike_knowledge", {"query": "винос кермо карбон"})
        self.assertTrue(res_t["success"])
        self.assertGreaterEqual(res_t["count"], 1)

        # 2. Search brakes
        res_b = self.dispatcher.execute("search_bike_knowledge", {"query": "sram dot fluid", "category": "brakes"})
        self.assertTrue(res_b["success"])
        self.assertGreaterEqual(res_b["count"], 1)

        # 3. Search suspension sag
        res_s = self.dispatcher.execute("search_bike_knowledge", {"query": "розрахунок sag вилки"})
        self.assertTrue(res_s["success"])
        self.assertGreaterEqual(res_s["count"], 1)

    def test_manage_presence_guest_and_report_tools(self):
        # 1. Register guest Max
        res_reg = self.dispatcher.execute("manage_presence_guest", {
            "action": "register",
            "device_id": "guest_max",
            "name": "Макс",
            "mac": "11:22:33:44:55:66",
            "absence_voice_message": "Макс, Юри в гаражі немає, гуляйте собі далі...",
            "telegram_chat_id": "987654321"
        })
        self.assertTrue(res_reg["success"])
        self.assertIn("Макс", res_reg["message"])

        # 2. List guests
        res_list = self.dispatcher.execute("manage_presence_guest", {"action": "list"})
        self.assertTrue(res_list["success"])
        self.assertIn("guest_max", res_list["devices"])

        # 3. Update guest
        res_up = self.dispatcher.execute("manage_presence_guest", {
            "action": "update",
            "device_id": "guest_max",
            "absence_voice_message": "Оновлена фраза"
        })
        self.assertTrue(res_up["success"])
        self.assertEqual(res_up["device"]["absence_voice_message"], "Оновлена фраза")

        # 4. Get visitor report
        res_rep = self.dispatcher.execute("get_visitor_report", {"days": 7})
        self.assertTrue(res_rep["success"])
        self.assertIn("report", res_rep)

        # 5. Delete guest
        res_del = self.dispatcher.execute("manage_presence_guest", {
            "action": "delete",
            "device_id": "guest_max"
        })
        self.assertTrue(res_del["success"])

    def test_control_device_door(self):
        res = self.dispatcher.execute("control_device", {"device": "door", "action": "open"})
        self.assertFalse(res["success"])
        self.assertIn("вимкнено", res["error"])

        res_close = self.dispatcher.execute("control_device", {"device": "door", "action": "close"})
        self.assertFalse(res_close["success"])
        self.assertIn("вимкнено", res_close["error"])

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

        res_safety = self.dispatcher.execute("run_scenario", {"scenario": "safety"})
        self.assertFalse(res_safety["success"])
        self.assertIn("недоступний", res_safety["error"])

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
        self.assertIn("заборонено", res["error"])


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


class TestTelegramClimateSubmenu(unittest.TestCase):

    def setUp(self):
        from server.core.core import SmartGarage
        self.garage = SmartGarage(start_workers=False)
        self.tg = self.garage.telegram
        self.tg.send_message = lambda chat_id, text, reply_markup=None: True
        self.tg.edit_message = lambda chat_id, message_id, text, reply_markup=None: True

    def test_main_keyboard_has_temperature(self):
        kb = self.tg._get_main_keyboard()
        buttons = [b["text"] for row in kb["keyboard"] for b in row]
        self.assertIn("🌡️ Температура", buttons)
        self.assertIn("📊 Статус гаража", buttons)

    def test_climate_menu_markup(self):
        captured = {}
        def mock_send(chat_id, text, reply_markup=None):
            captured["text"] = text
            captured["markup"] = reply_markup
            return True
        self.tg.send_message = mock_send

        self.tg._send_climate_menu(12345)
        self.assertIn("Клімат та температура Smart Garage", captured["text"])
        callbacks = [btn["callback_data"] for row in captured["markup"]["inline_keyboard"] for btn in row]
        self.assertIn("clim_floor1", callbacks)
        self.assertIn("clim_floor2", callbacks)
        self.assertIn("clim_basement", callbacks)
        self.assertIn("clim_outdoor", callbacks)
        self.assertIn("chart_basement_24", callbacks)

    def test_floor_details(self):
        captured = {}
        def mock_send(chat_id, text, reply_markup=None):
            captured["text"] = text
            return True
        self.tg.send_message = mock_send

        self.tg._send_floor1_details(12345)
        self.assertIn("1-й поверх", captured["text"])

        self.tg._send_floor2_details(12345)
        self.assertIn("2-й поверх", captured["text"])

        self.tg._send_basement_details(12345)
        self.assertIn("Підвал", captured["text"])

        self.tg._send_outdoor_details(12345)
        self.assertIn("Вулиця", captured["text"])


class TestPresenceGreetingDebounce(unittest.TestCase):

    def test_owner_arrival_greeting_debounced(self):
        from unittest.mock import MagicMock

        from server.core.core import SmartGarage

        garage = SmartGarage(start_workers=False)
        garage.presence.update_device("owner_phone", auto_welcome=True, opt_in=True)
        garage.telegram.notify_admin = MagicMock()
        garage.ai.chat = MagicMock(return_value="Привіт, Юрію!")
        garage.get_context_snapshot = MagicMock(return_value="Контекст гаража")
        garage.telegram.notify_admin.reset_mock()

        cb = garage.presence.event_callback
        self.assertIsNotNone(cb)

        # 1. Phone arrives
        event_phone = {
            "event": "ARRIVED",
            "device_id": "owner_phone",
            "person_name": "Юрій (Власник)",
            "device_name": "Motorola Edge 50 Pro",
            "role": "owner",
            "proximity": "immediate",
            "source": "bluetooth_classic"
        }
        cb(event_phone)
        self.assertEqual(garage.telegram.notify_admin.call_count, 1)

        # 2. Watch paired event arrives immediately after (0.002s later)
        event_watch = {
            "event": "ARRIVED",
            "device_id": "owner_watch",
            "person_name": "Юрій (Смарт-годинник)",
            "device_name": "Смарт-годинник",
            "role": "owner",
            "proximity": "near",
            "source": "paired_with_owner"
        }
        cb(event_watch)
        # Should still be exactly 1 call (no duplicate greeting)
        self.assertEqual(garage.telegram.notify_admin.call_count, 1)

    def test_guest_arrival_automation_when_owner_away(self):
        from unittest.mock import MagicMock, patch

        from server.core.core import SmartGarage

        garage = SmartGarage(start_workers=False)
        garage.telegram.notify_admin = MagicMock()
        garage.telegram.send_message = MagicMock()

        # Mark all owner devices as away
        with garage.presence._lock:
            for d in garage.presence.devices.values():
                d["status"] = "away"

        # 1. Without opt-in (default privacy), guest arrival triggers NO notifications or TTS
        garage.presence.register_device(
            device_id="guest_no_optin",
            name="Анонімний Гість",
            role="guest",
            device_name="iPhone",
            ble_mac="11:22:33:44:55:77",
            notify_owner=True,
            opt_in=False
        )
        cb = garage.presence.event_callback
        self.assertIsNotNone(cb)
        with patch("server.services.neural_tts.neural_tts.speak_locally") as mock_speak_default:
            cb({
                "event": "ARRIVED",
                "device_id": "guest_no_optin",
                "person_name": "Анонімний Гість",
                "device_name": "iPhone",
                "role": "guest",
                "proximity": "near",
                "source": "esp32_ble"
            })
            garage.telegram.notify_admin.assert_not_called()
            mock_speak_default.assert_not_called()

        # 2. With explicit opt-in and notify_owner:
        # Neutral Telegram notification to owner, NO absence broadcast over speaker
        garage.presence.register_device(
            device_id="guest_max",
            name="Макс",
            role="guest",
            device_name="iPhone Макса",
            ble_mac="11:22:33:44:55:66",
            notify_owner=True,
            opt_in=True
        )

        with patch("server.services.neural_tts.neural_tts.speak_locally") as mock_speak:
            cb({
                "event": "ARRIVED",
                "device_id": "guest_max",
                "person_name": "Макс",
                "device_name": "iPhone Макса",
                "role": "guest",
                "proximity": "near",
                "source": "esp32_ble"
            })

            # Owner notified neutrally via Telegram without leaking absence to guest or speaker
            garage.telegram.notify_admin.assert_called_once()
            args, _ = garage.telegram.notify_admin.call_args
            self.assertIn("Макс", args[0])

            # Privacy constraint: speaker must NOT announce owner absence
            mock_speak.assert_not_called()
            garage.telegram.send_message.assert_not_called()



class TestAudioAndRadio(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    def test_radio_fetch_from_mirrors_fallback(self):
        from unittest.mock import MagicMock, patch

        from server.services.radio_service import RadioService

        radio = RadioService()
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = [{"name": "Test FM", "url": "https://test.fm/stream"}]

        with patch("requests.get") as mock_get:
            # First 2 mirrors fail, 3rd succeeds
            mock_get.side_effect = [
                Exception("Connection timeout"),
                MagicMock(status_code=500),
                resp_ok
            ]
            result = radio._fetch_from_mirrors("/json/stations/top")
            self.assertEqual(result, [{"name": "Test FM", "url": "https://test.fm/stream"}])
            self.assertEqual(mock_get.call_count, 3)

    def test_radio_fetch_from_mirrors_all_fail(self):
        from unittest.mock import patch

        from server.services.radio_service import RadioService

        radio = RadioService()
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("All mirrors unreachable")
            result = radio._fetch_from_mirrors("/json/stations/top")
            self.assertIsNone(result)

    def test_media_delete_path_traversal(self):
        # 1. Path traversal attempt
        res = self.client.post("/api/media/delete", json={"filename": "../../etc/passwd"})
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["response"], "Файл не знайдено")

        # 2. Directory traversal attempt
        res_dir = self.client.post("/api/media/delete", json={"filename": ".."})
        self.assertEqual(res_dir.status_code, 404)

        # 3. Empty filename
        res_empty = self.client.post("/api/media/delete", json={"filename": ""})
        self.assertEqual(res_empty.status_code, 400)

    def test_media_delete_legitimate_file(self):
        from server.webapp import MEDIA_DIR
        test_file = MEDIA_DIR / "temp_unit_test_file.mp4"
        test_file.write_text("dummy test content")
        try:
            self.assertTrue(test_file.exists())
            res = self.client.post("/api/media/delete", json={"filename": "temp_unit_test_file.mp4"})
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()["success"])
            self.assertFalse(test_file.exists())
        finally:
            if test_file.exists():
                test_file.unlink()

    def test_radio_play_invalid_url_scheme_api(self):
        # file:// scheme must be rejected with 400
        res = self.client.post("/api/radio/play", json={"url": "file:///etc/passwd"})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["success"])
        self.assertIn("Неприпустима схема URL", res.get_json()["response"])

        # ftp:// scheme must be rejected with 400
        res_ftp = self.client.post("/api/radio/play", json={"url": "ftp://example.com/stream"})
        self.assertEqual(res_ftp.status_code, 400)
        self.assertFalse(res_ftp.get_json()["success"])

        # Missing url
        res_no_url = self.client.post("/api/radio/play", json={})
        self.assertEqual(res_no_url.status_code, 400)

    def test_speaker_play_stream_invalid_scheme(self):
        from server.devices.bluetooth_speaker import BluetoothSpeakerController
        speaker = BluetoothSpeakerController()
        # Invalid schemes or empty URLs must return False
        self.assertFalse(speaker.play_stream("file:///etc/shadow"))
        self.assertFalse(speaker.play_stream("rtsp://internal/cam"))
        self.assertFalse(speaker.play_stream(""))
        self.assertFalse(speaker.play_stream("   "))


class TestVoiceInterface(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    def test_voice_command_queue(self):
        from server.services.voice_queue import VoiceCommandQueue
        vq = VoiceCommandQueue(maxsize=10)
        self.assertTrue(vq.empty())
        self.assertEqual(vq.qsize(), 0)

        # Synchronous put
        vq.put_sync("відкрий ворота", source="voice", priority=1)
        self.assertEqual(vq.qsize(), 1)
        self.assertFalse(vq.empty())

        stats = vq.get_stats()
        self.assertEqual(stats["total_received"], 1)
        self.assertEqual(stats["recent_history"][0]["text"], "відкрий ворота")

    def test_api_voice_command_status(self):
        res = self.client.post("/api/voice/command", json={"command": "status", "source": "voice"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["source"], "voice")
        self.assertIn("Smart Garage is running", data["response"])

    def test_api_voice_command_empty(self):
        res = self.client.post("/api/voice/command", json={"command": ""})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["success"])

    def test_api_voice_status(self):
        res = self.client.get("/api/voice/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("queue_size", data["stats"])


class TestMQTTBridge(unittest.TestCase):

    def test_discovery_payloads_generation(self):
        from server.services.mqtt_bridge import SmartGarageMQTTBridge
        bridge = SmartGarageMQTTBridge()

        published = {}
        class MockClient:
            async def publish(self, topic, payload, retain=False):
                published[topic] = {"payload": payload, "retain": retain}

        import asyncio
        asyncio.run(bridge.publish_discovery(MockClient()))

        # Check essential discovery topics
        self.assertNotIn("homeassistant/sensor/smartgarage/door_status/config", published)
        self.assertNotIn("homeassistant/cover/smartgarage/door/config", published)
        self.assertNotIn("homeassistant/sensor/smartgarage/gas_sensor/config", published)
        self.assertIn("homeassistant/switch/smartgarage/light/config", published)
        self.assertIn("homeassistant/switch/smartgarage/fan/config", published)
        self.assertIn("homeassistant/sensor/smartgarage/basement_temperature/config", published)
        self.assertIn("homeassistant/sensor/smartgarage/ai_status/config", published)

    def test_message_handling(self):
        from server.services.mqtt_bridge import SmartGarageMQTTBridge
        bridge = SmartGarageMQTTBridge()

        published = {}
        class MockClient:
            async def publish(self, topic, payload, retain=False):
                published[topic] = payload

        import asyncio
        telemetry_sample = json.dumps({
            "door_status": "open",
            "light": True,
            "fan": False,
            "temperature": 18.5,
            "floors": {
                "basement": {"temperature": 16.2, "humidity": 60}
            }
        })
        asyncio.run(bridge.handle_message(MockClient(), "smartgarage/esp32/telemetry", telemetry_sample))
        self.assertEqual(published["smartgarage/door/state"], "open")
        self.assertEqual(published["smartgarage/light/state"], "ON")
        self.assertEqual(published["smartgarage/fan/state"], "OFF")
        self.assertIn("16.2", published["smartgarage/telemetry"])

    def test_russian_language_and_music_taboo(self):
        from server.commands.processor import CommandProcessor
        from server.logger.logger import Logger
        cp = CommandProcessor(Logger())

        # 1. Command containing Russian-specific letters
        handled, resp = cp.execute("включи свет пожалуйста")
        self.assertTrue(handled)
        self.assertIn("табу", resp.lower())

        # 2. Command requesting Russian music explicitly
        handled, resp = cp.execute("увімкни російську музику")
        self.assertTrue(handled)
        self.assertIn("табу", resp.lower())

        # 3. Bluetooth speaker play_youtube with Russian query
        from server.devices.bluetooth_speaker import BluetoothSpeakerController
        spk = BluetoothSpeakerController()
        self.assertFalse(spk.play_youtube("русская песня"))

    def test_play_song_tool_and_speaker(self):
        from unittest.mock import MagicMock, patch

        from server.ai.tools import GARAGE_TOOLS, ToolDispatcher

        # Check tool declaration
        tool_names = [t["function"]["name"] for t in GARAGE_TOOLS]
        self.assertIn("play_song", tool_names)

        garage = MagicMock()
        garage.speaker.is_connected.return_value = True
        garage.speaker.play_youtube.return_value = True
        garage.speaker.name = "Юрій: JBL Clip 5"
        dispatcher = ToolDispatcher(garage=garage)

        # 1. Standard query
        res = dispatcher.execute("play_song", {"query": "Океан Ельзи"})
        self.assertTrue(res["success"])
        self.assertIn("YouTube Music", res["message"])
        garage.speaker.play_youtube.assert_called_with("Океан Ельзи")

        # 2. Generic query fallback
        res2 = dispatcher.execute("play_song", {"query": "включи пісню"})
        self.assertTrue(res2["success"])
        self.assertIn("YouTube Music", res2["message"])

        # 3. Bluetooth speaker suffix stripping
        import hashlib

        from server.devices.bluetooth_speaker import BluetoothSpeakerController
        spk = BluetoothSpeakerController()
        clean_target = "Океан Ельзи"
        hash_name = hashlib.md5(clean_target.encode("utf-8")).hexdigest()[:10]
        test_file = spk.media_dir / f"stream_{hash_name}.mp4"
        test_file.write_bytes(b"0" * 100001)
        try:
            with patch.object(spk, "play_file", return_value=True) as mock_pf:
                ok = spk.play_youtube("Океан Ельзи на youtube music")
                self.assertTrue(ok)
                mock_pf.assert_called_with(str(test_file), track_title=clean_target, duration=0)
        finally:
            test_file.unlink(missing_ok=True)

        # 4. Playlist tools check
        self.assertIn("play_user_playlist", tool_names)
        self.assertIn("list_user_playlists", tool_names)
        garage.speaker.play_playlist.return_value = (True, "Український рок", "Пригадай")
        res_pl = dispatcher.execute("play_user_playlist", {"playlist": "рок"})
        self.assertTrue(res_pl["success"])
        self.assertIn("Український рок", res_pl["message"])


class TestYTMusicWebAPI(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    @patch("server.webapp.ytmusic_service")
    def test_api_ytmusic_playlists(self, mock_yt):
        mock_yt.get_user_playlists.return_value = [
            {"id": "LM", "title": "Улюблені пісні", "is_liked": True, "track_count": 116},
            {"id": "PL123", "title": "Український рок", "is_liked": False, "track_count": 50}
        ]
        mock_yt.current_playlist_id = "LM"

        res = self.client.get("/api/ytmusic/playlists")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["playlists"]), 2)
        self.assertEqual(data["playlists"][0]["id"], "LM")

    @patch("server.webapp.ytmusic_service")
    def test_api_ytmusic_playlist_tracks(self, mock_yt):
        mock_yt.get_playlist_tracks.return_value = [
            {"id": "trk1", "title": "Червона рута", "uploader": "ВІА Смерічка", "duration": 180}
        ]

        res = self.client.get("/api/ytmusic/playlist/PL123/tracks")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["playlist_id"], "PL123")
        self.assertEqual(len(data["tracks"]), 1)
        self.assertEqual(data["tracks"][0]["title"], "Червона рута")

    @patch("server.webapp.garage")
    def test_api_ytmusic_play_playlist(self, mock_garage):
        mock_garage.speaker.play_playlist.return_value = (True, "Український рок", "Океан Ельзи - Майже весна")
        mock_garage.speaker.is_playing.return_value = True
        mock_garage.speaker.name = "JX-BT"

        res = self.client.post("/api/ytmusic/play", json={"playlist_id": "PL123", "shuffle": True})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["playing"])
        self.assertEqual(data["track_title"], "Океан Ельзи - Майже весна")
        mock_garage.speaker.play_playlist.assert_called_with("PL123", shuffle=True)

    @patch("server.webapp.garage")
    def test_api_ytmusic_play_specific_track(self, mock_garage):
        mock_garage.speaker.play_youtube.return_value = True
        mock_garage.speaker.is_playing.return_value = True
        mock_garage.speaker.name = "JBL Clip 5"

        res = self.client.post("/api/ytmusic/play", json={
            "track_id": "xyz123",
            "track_title": "Човен",
            "uploader": "Один в каное"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["track_title"], "Човен")
        mock_garage.speaker.play_youtube.assert_called_with("Човен Один в каное", track_title="Човен")

    @patch("server.webapp.garage")
    def test_api_ytmusic_next(self, mock_garage):
        mock_garage.speaker.play_next.return_value = (True, "Український рок", "Бумбокс - Люди")
        mock_garage.speaker.is_playing.return_value = True
        mock_garage.speaker.name = "JX-BT"

        res = self.client.post("/api/ytmusic/next", json={"shuffle": True})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["track_title"], "Бумбокс - Люди")
        mock_garage.speaker.play_next.assert_called_with(shuffle=True)

    def test_api_ytmusic_status(self):
        res = self.client.get("/api/ytmusic/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("speaker", data)

    def test_ytmusic_service_sequential_autoplay(self):
        """Test that songs in a playlist play one after another sequentially ('одна за одною по черзі')."""
        from server.services.ytmusic_service import YTMusicService
        yt = YTMusicService()
        mock_tracks = [
            {"id": "t1", "title": "Пісня 1", "uploader": "Виконавець 1", "duration": 180},
            {"id": "t2", "title": "Пісня 2", "uploader": "Виконавець 2", "duration": 200},
            {"id": "t3", "title": "Пісня 3", "uploader": "Виконавець 3", "duration": 220},
        ]
        with patch.object(yt, "get_playlist_tracks", return_value=mock_tracks):
            # 1. Starting playlist sequentially should pick track 0
            t0 = yt.get_track_to_play("test_pl", shuffle=False)
            self.assertEqual(t0["id"], "t1")
            self.assertEqual(t0["track_index"], 0)

            # 2. Next track should be track 1
            t1 = yt.get_next_track_to_play("test_pl", shuffle=False)
            self.assertEqual(t1["id"], "t2")
            self.assertEqual(t1["track_index"], 1)

            # 3. Next track should be track 2
            t2 = yt.get_next_track_to_play("test_pl", shuffle=False)
            self.assertEqual(t2["id"], "t3")
            self.assertEqual(t2["track_index"], 2)

            # 4. Next track should loop back to track 0
            t3 = yt.get_next_track_to_play("test_pl", shuffle=False)
            self.assertEqual(t3["id"], "t1")
            self.assertEqual(t3["track_index"], 0)

            # 5. Selecting a specific track by ID should set index and play next in order
            tspec = yt.get_track_to_play("test_pl", shuffle=False, track_id="t2")
            self.assertEqual(tspec["id"], "t2")
            self.assertEqual(tspec["track_index"], 1)

            tnext = yt.get_next_track_to_play("test_pl", shuffle=False)
            self.assertEqual(tnext["id"], "t3")
            self.assertEqual(tnext["track_index"], 2)

    def test_speaker_autoplay_flag_and_stop(self):
        """Test speaker autoplay flag is set on play_playlist and cleared on manual stop."""
        from unittest.mock import MagicMock

        from server.devices.bluetooth_speaker import BluetoothSpeakerController
        spk = BluetoothSpeakerController(mac="AA:BB:CC:DD:EE:FF", name="Test Speaker")
        spk.play_youtube = MagicMock(return_value=True)

        mock_track = {"id": "t1", "title": "Пісня", "uploader": "Артист", "duration": 180, "playlist_id": "LM", "playlist_title": "Улюблені"}
        with patch("server.services.ytmusic_service.ytmusic_service.get_track_to_play", return_value=mock_track):
            ok, p_title, t_title = spk.play_playlist("LM", shuffle=False)
            self.assertTrue(ok)
            self.assertTrue(spk._playlist_autoplay)
            self.assertEqual(spk._playlist_id, "LM")
            self.assertFalse(spk._playlist_shuffle)

        # Manual stop must cancel autoplay
        spk.stop(manual=True)
        self.assertFalse(spk._playlist_autoplay)

    def test_play_file_preserves_playlist_autoplay(self):
        """Ensure play_file (internal track start) does NOT clear _playlist_autoplay."""
        from server.devices.bluetooth_speaker import BluetoothSpeakerController
        spk = BluetoothSpeakerController(mac="AA:BB:CC:DD:EE:FF", name="Test Speaker")
        spk._playlist_autoplay = True
        spk.is_connected = MagicMock(return_value=True)

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            ok = spk.play_file("https://example.com/stream.mp4", track_title="Тестовий трек")
            self.assertTrue(ok)
            # Autoplay flag MUST remain True for continuous playlist playback
            self.assertTrue(spk._playlist_autoplay)

    def test_processor_next_song_phrases(self):
        """Test processor recognizes Ukrainian phrases for skipping/next song."""
        from server.commands.processor import CommandProcessor
        cp = CommandProcessor(DummyLogger(), memory=Memory(os.path.join(tempfile.gettempdir(), 'mem_next.json')))
        with patch.object(cp.speaker, "play_next", return_value=(True, "Улюблені", "Стефанія")) as mock_next:
            for phrase in ("включи наступну пісню", "увімкни наступний трек", "наступну пісню", "пропусти пісню", "грай далі"):
                handled, res = cp.execute(phrase)
                self.assertTrue(handled, f"Phrase '{phrase}' was not handled")
                self.assertIn("Стефанія", res)
            self.assertEqual(mock_next.call_count, 5)

    def test_ai_tools_next_music_track(self):
        """Test AI tools execute_tool dispatches next_music_track correctly."""
        from server.ai.tools import ToolDispatcher
        garage_mock = MagicMock()
        garage_mock.speaker.play_next.return_value = (True, "Улюблені", "ADAM - Танцюй")
        garage_mock.speaker.name = "JX-BT"
        td = ToolDispatcher(garage_mock)
        res = td.execute("next_music_track", {})
        self.assertTrue(res.get("success"))
        self.assertIn("ADAM - Танцюй", res.get("message", ""))

    def test_ytmusic_service_prev_and_upcoming_track(self):
        """Test ytmusic service get_prev_track_to_play and get_upcoming_track."""
        from server.services.ytmusic_service import YTMusicService
        yt = YTMusicService()
        mock_tracks = [
            {"id": "t1", "title": "Пісня 1", "uploader": "Виконавець 1", "duration": 180},
            {"id": "t2", "title": "Пісня 2", "uploader": "Виконавець 2", "duration": 200},
            {"id": "t3", "title": "Пісня 3", "uploader": "Виконавець 3", "duration": 220},
        ]
        with patch.object(yt, "get_playlist_tracks", return_value=mock_tracks):
            yt.get_track_to_play("test_pl", shuffle=False, track_id="t2")
            self.assertEqual(yt.current_track_index, 1)

            upcoming = yt.get_upcoming_track("test_pl")
            self.assertIsNotNone(upcoming)
            self.assertEqual(upcoming["id"], "t3")
            self.assertEqual(upcoming["track_index"], 2)
            self.assertEqual(yt.current_track_index, 1)

            prev_t = yt.get_prev_track_to_play("test_pl", shuffle=False)
            self.assertEqual(prev_t["id"], "t1")
            self.assertEqual(prev_t["track_index"], 0)

            prev_loop = yt.get_prev_track_to_play("test_pl", shuffle=False)
            self.assertEqual(prev_loop["id"], "t3")
            self.assertEqual(prev_loop["track_index"], 2)

    @patch("server.webapp.garage")
    def test_api_ytmusic_prev(self, mock_garage):
        mock_garage.speaker.play_prev.return_value = (True, "Український рок", "Один в каное - Човен")
        mock_garage.speaker.is_playing.return_value = True
        mock_garage.speaker.name = "JBL Clip 5"

        res = self.client.post("/api/ytmusic/prev", json={})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["track_title"], "Один в каное - Човен")
        mock_garage.speaker.play_prev.assert_called_once()

    @patch("server.webapp.garage")
    def test_api_speaker_seek(self, mock_garage):
        mock_garage.speaker.seek.return_value = True
        mock_garage.speaker.get_status.return_value = {
            "elapsed_seconds": 45,
            "duration_seconds": 180,
            "playing": True
        }

        res = self.client.post("/api/speaker/seek", json={"position": 45})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["position"], 45)
        mock_garage.speaker.seek.assert_called_with(45)

        res_delta = self.client.post("/api/speaker/seek", json={"delta": 10})
        self.assertEqual(res_delta.status_code, 200)
        data_delta = res_delta.get_json()
        self.assertTrue(data_delta["success"])
        self.assertEqual(data_delta["position"], 55)
        mock_garage.speaker.seek.assert_called_with(55)

    def test_processor_prev_and_seek_phrases(self):
        """Test processor recognizes Ukrainian phrases for previous song and seeking."""
        from server.commands.processor import CommandProcessor
        cp = CommandProcessor(DummyLogger(), memory=Memory(os.path.join(tempfile.gettempdir(), 'mem_prev_seek.json')))

        with patch.object(cp.speaker, "play_prev", return_value=(True, "Улюблені", "Океан Ельзи - Без бою")) as mock_prev:
            for phrase in ("попередня пісня", "попередній трек", "поверни трек назад", "назад"):
                handled, res = cp.execute(phrase)
                self.assertTrue(handled, f"Phrase '{phrase}' was not handled")
                self.assertIn("Без бою", res)
            self.assertEqual(mock_prev.call_count, 4)

        with patch.object(cp.speaker, "seek", return_value=True) as mock_seek:
            cp.speaker._playback_start_time = time.time() - 30
            cp.speaker._current_track_duration = 180
            cp.speaker.is_playing = MagicMock(return_value=True)

            handled, res = cp.execute("перемотай на 15 секунд вперед")
            self.assertTrue(handled)
            self.assertIn("Перемотано", res)

            handled2, res2 = cp.execute("перемотай на 10 секунд назад")
            self.assertTrue(handled2)
            self.assertIn("Перемотано", res2)

    def test_ai_tools_prev_and_seek_music_track(self):
        """Test AI tools execute_tool dispatches prev_music_track and seek_music_track."""
        from server.ai.tools import ToolDispatcher
        garage_mock = MagicMock()
        garage_mock.speaker.play_prev.return_value = (True, "Улюблені", "KAZKA - Плакала")
        garage_mock.speaker.name = "JX-BT"
        garage_mock.speaker.seek.return_value = True
        garage_mock.speaker.get_status.return_value = {"elapsed_seconds": 20, "duration_seconds": 180}

        td = ToolDispatcher(garage_mock)
        res_prev = td.execute("prev_music_track", {})
        self.assertTrue(res_prev.get("success"))
        self.assertIn("Плакала", res_prev.get("message", ""))

        res_seek = td.execute("seek_music_track", {"position": 60})
        self.assertTrue(res_seek.get("success"))
        garage_mock.speaker.seek.assert_called_with(60)


class TestOwnerSecurityConstraints(unittest.TestCase):
    """Rigorous regression tests for owner constraints:
    1. Gas sensor not installed: no gas rules, gas_ppm is None, status is not_installed.
    2. Door control disabled: read-only status is unknown, door toggle/open/close blocked.
    3. Tool allowlist enforcement: arbitrary tools/code execution blocked.
    """

    def setUp(self):
        from server.webapp import app, garage
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()
        self.garage = garage

    def test_door_control_fully_blocked_on_api(self):
        # 1. Door toggle endpoint
        res = self.client.post("/api/device/door/toggle")
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["door"], "unknown")
        self.assertIn("вимкнено", data["error"])

        # 2. Door open endpoint
        res_open = self.client.post("/api/door/open")
        data_open = res_open.get_json()
        self.assertFalse(data_open["success"])
        self.assertEqual(data_open["door"], "unknown")
        self.assertIn("вимкнено", data_open["error"])

        # 3. Door close endpoint
        res_close = self.client.post("/api/door/close")
        data_close = res_close.get_json()
        self.assertFalse(data_close["success"])
        self.assertEqual(data_close["door"], "unknown")
        self.assertIn("вимкнено", data_close["error"])

    def test_garage_state_door_and_gas_contract(self):
        res = self.client.get("/api/garage/state")
        data = res.get_json()
        self.assertTrue(data["success"])
        state = data["state"]
        # Door constraints
        self.assertEqual(state["door"], "unknown")
        self.assertFalse(state["door_installed"])
        self.assertEqual(state["door_status"], "unknown")
        # Gas constraints
        self.assertIsNone(state["gas_ppm"])
        self.assertFalse(state["gas_installed"])
        self.assertEqual(state["gas_status"], "not_installed")

    def test_automation_scenarios_door_and_gas_constraints(self):
        auto = self.garage.automation
        esp = self.garage.esp32

        # Car arrival does not open door
        success, msg = auto.scenario_car_arrival()
        self.assertTrue(success)
        self.assertNotIn("door", esp.state)
        self.assertNotIn("Ворота відкрито", msg)

        # Departure does not close door
        success, msg = auto.scenario_departure()
        self.assertTrue(success)
        self.assertNotIn("door", esp.state)
        self.assertNotIn("Ворота закрито", msg)

        # Gas alarm scenario is disabled
        success, msg = auto.scenario_gas_alarm()
        self.assertFalse(success)
        self.assertIn("не встановлений", msg)

    def test_strict_ai_tool_allowlist(self):
        from server.ai.tools import ToolDispatcher
        dispatcher = ToolDispatcher(self.garage)

        # Arbitrary / malicious tool execution blocked
        res_bad1 = dispatcher.execute("bash", {"command": "rm -rf /"})
        self.assertFalse(res_bad1["success"])
        self.assertIn("заборонено", res_bad1["error"])

        res_bad2 = dispatcher.execute("eval_python", {"code": "import os; os.system('ls')"})
        self.assertFalse(res_bad2["success"])
        self.assertIn("заборонено", res_bad2["error"])

        # Door device control blocked in AI tools
        res_door = dispatcher.execute("control_device", {"device": "door", "action": "open"})
        self.assertFalse(res_door["success"])
        self.assertIn("вимкнено", res_door["error"])

        # Safety gas scenario blocked in AI tools
        res_safety = dispatcher.execute("run_scenario", {"scenario": "safety"})
        self.assertFalse(res_safety["success"])
        self.assertIn("недоступний", res_safety["error"])

    def test_server_auth_enforcement_on_mutating_endpoints(self):
        """Mutating endpoints must reject unauthenticated requests with 401 when auth is enforced."""
        endpoints = [
            ("/api/device/light/toggle", "post", None),
            ("/api/device/fan/toggle", "post", None),
            ("/api/scenarios/night", "post", None),
            ("/api/media/delete", "post", {"filename": "test.mp4"}),
            ("/api/speaker/volume", "post", {"value": 40}),
            ("/api/esp32/clear_logs", "post", None),
            ("/api/presence/scan", "post", None),
            ("/api/presence/devices", "post", {"name": "Test"}),
            ("/api/presence/devices/test_dev", "put", {"absence_voice_message": "test"}),
            ("/api/radio/play", "post", {"url": "http://stream.example.com"}),
            ("/api/ytmusic/next", "post", None),
        ]
        headers = {"X-Enforce-Auth": "true"}
        for ep, method, body in endpoints:
            if method == "post":
                res = self.client.post(ep, json=body or {}, headers=headers)
            elif method == "put":
                res = self.client.put(ep, json=body or {}, headers=headers)
            elif method == "delete":
                res = self.client.delete(ep, headers=headers)
            self.assertEqual(res.status_code, 401, f"Endpoint {ep} did not return 401 without auth")
            data = res.get_json()
            self.assertFalse(data["success"])
            self.assertIn("авторизація", data["error"])

    def test_presence_api_crud_and_report_workflow(self):
        """Full CRUD and reporting workflow for guest presence."""
        admin_pin = os.getenv("ADMIN_PIN") or "9876"
        headers_pin = {"X-Admin-PIN": admin_pin}

        # 1. Register guest Max
        res_post = self.client.post("/api/presence/devices", json={
            "name": "Макс",
            "role": "guest",
            "ble_mac": "11:22:33:44:55:66",
            "absence_voice_message": "Макс, Юри в гаражі немає, гуляйте собі далі...",
            "telegram_chat_id": "987654321",
            "opt_in": True
        }, headers=headers_pin)
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.get_json()["success"])
        dev_id = res_post.get_json()["device"]["id"]

        # 2. Update guest Max
        res_put = self.client.put(f"/api/presence/devices/{dev_id}", json={
            "absence_voice_message": "Оновлена фраза"
        }, headers=headers_pin)
        self.assertEqual(res_put.status_code, 200)
        self.assertEqual(res_put.get_json()["device"]["absence_voice_message"], "Оновлена фраза")

        # 3. Get presence report
        res_rep = self.client.get("/api/presence/report?days=7", headers=headers_pin)
        self.assertEqual(res_rep.status_code, 200)
        self.assertTrue(res_rep.get_json()["success"])
        self.assertIn("report", res_rep.get_json())

        # 4. Delete guest Max
        res_del = self.client.delete(f"/api/presence/devices/{dev_id}", headers=headers_pin)
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

    def test_server_auth_with_valid_api_pin(self):
        """Valid PIN via header (X-Admin-PIN or Bearer) allows execution, forbidden PIN fails closed."""
        # Forbidden default PIN 7777 fails closed (401)
        res_forbidden = self.client.post("/api/device/light/toggle", headers={"X-Enforce-Auth": "true", "X-Admin-PIN": "7777"})
        self.assertEqual(res_forbidden.status_code, 401)

        # Configured admin PIN allows execution
        admin_pin = os.getenv("ADMIN_PIN") or "9876"
        headers_pin = {"X-Enforce-Auth": "true", "X-Admin-PIN": admin_pin}
        res = self.client.post("/api/device/light/toggle", headers=headers_pin)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

        headers_bearer = {"X-Enforce-Auth": "true", "Authorization": f"Bearer {admin_pin}"}
        res2 = self.client.post("/api/speaker/volume", json={"value": 35}, headers=headers_bearer)
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.get_json()["success"])

    def test_csrf_protection_with_session(self):
        """Session-authenticated requests must require a valid CSRF token."""
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["login_time"] = time.time()
            sess["csrf_token"] = "valid_csrf_token_12345"

        headers_enforce = {"X-Enforce-Auth": "true"}
        # 1. Missing CSRF token -> 403 Forbidden
        res_no_csrf = self.client.post("/api/device/light/toggle", headers=headers_enforce)
        self.assertEqual(res_no_csrf.status_code, 403)
        self.assertIn("CSRF", res_no_csrf.get_json()["error"])

        # 2. Invalid CSRF token -> 403 Forbidden
        headers_bad_csrf = {"X-Enforce-Auth": "true", "X-CSRF-Token": "bad_token"}
        res_bad_csrf = self.client.post("/api/device/light/toggle", headers=headers_bad_csrf)
        self.assertEqual(res_bad_csrf.status_code, 403)

        # 3. Valid CSRF token -> 200 OK
        headers_good_csrf = {"X-Enforce-Auth": "true", "X-CSRF-Token": "valid_csrf_token_12345"}
        res_good_csrf = self.client.post("/api/device/light/toggle", headers=headers_good_csrf)
        self.assertEqual(res_good_csrf.status_code, 200)
        self.assertTrue(res_good_csrf.get_json()["success"])

    def test_login_rate_limiting(self):
        """Rate limiter blocks brute-force login after 5 failed attempts."""
        from server.security import rate_limiter
        rate_limiter.reset("127.0.0.1")

        for i in range(5):
            res = self.client.post("/api/admin/verify", json={"pin": "wrong_pin"})
            self.assertEqual(res.status_code, 401)
            self.assertFalse(res.get_json()["authenticated"])

        # 6th attempt must be rate-limited (HTTP 429)
        res_blocked = self.client.post("/api/admin/verify", json={"pin": "wrong_pin"})
        self.assertEqual(res_blocked.status_code, 429)
        self.assertIn("Забагато невдалих спроб", res_blocked.get_json()["error"])

        rate_limiter.reset("127.0.0.1")

    def test_audit_logging_and_secret_redaction(self):
        """Audit logging must record actions without leaking secrets."""
        from server.security.audit import audit_log, sanitize_details
        raw = {
            "password": "super_secret_password",
            "pin": "7777",
            "token": "secret_token_abc",
            "api_key": "sk-123456",
            "normal_field": "visible_value"
        }
        sanitized = sanitize_details(raw)
        self.assertEqual(sanitized["password"], "[REDACTED]")
        self.assertEqual(sanitized["pin"], "[REDACTED]")
        self.assertEqual(sanitized["token"], "[REDACTED]")
        self.assertEqual(sanitized["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["normal_field"], "visible_value")

    def test_open_interpreter_disabled_by_default(self):
        """OpenInterpreter must not be enabled by default in production."""
        from server.ai.manager import ENABLE_OPEN_INTERPRETER, AIManager
        self.assertFalse(ENABLE_OPEN_INTERPRETER)
        ai = AIManager()
        res = ai.chat("test command without openrouter", context_info="")
        # Must not run arbitrary code or throw OpenInterpreter errors
        self.assertIsInstance(res, str)
        self.assertTrue(len(res) > 0)


class TestSensorFreshnessAndTelemetryTruth(unittest.TestCase):
    """Rigorous regression tests for Stage 2: Sensors & Telemetry Freshness/Authenticity:
    1. New measurement online
    2. Sensor goes offline (connection lost)
    3. Cache older than threshold (> 1200s)
    4. SQLite fallback contains only old historical value
    5. Sensor not configured / not installed
    6. Conflicting timestamps between ESP32 bridge & direct host BLE
    7. gas_ppm = None safety (no TypeError, safe status)
    8. Missing primary sensor when all sensors offline
    """

    def setUp(self):
        from server.sensors.freshness import (
            SENSOR_FRESHNESS_THRESHOLD_SECONDS,
            SOURCE_BLE_DIRECT,
            SOURCE_CACHE,
            SOURCE_ESP32_BRIDGE,
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
        from server.webapp import app, garage
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()
        self.garage = garage
        self.build_sensor_payload = build_sensor_payload
        self.merge_sensor_readings = merge_sensor_readings
        self.threshold = SENSOR_FRESHNESS_THRESHOLD_SECONDS

    def test_1_new_measurement_online(self):
        """Fresh online measurement must have status='online', current_temperature matching, and ISO-8601 timestamp."""
        now = time.time()
        payload = self.build_sensor_payload(
            floor="floor2",
            name="2-й поверх",
            installed=True,
            mac="A4:C1:38:00:11:22",
            temperature=21.5,
            humidity=55.0,
            battery=88,
            last_updated=now - 20,
            is_online_reported=True,
            source="ble_direct"
        )
        self.assertEqual(payload["status"], "online")
        self.assertTrue(payload["online"])
        self.assertFalse(payload["is_stale"])
        self.assertEqual(payload["current_temperature"], 21.5)
        self.assertEqual(payload["current_humidity"], 55.0)
        self.assertEqual(payload["last_known_temperature"], 21.5)
        self.assertEqual(payload["last_known_humidity"], 55.0)
        self.assertEqual(payload["battery"], 88)
        self.assertEqual(payload["source"], "ble_direct")
        self.assertEqual(payload["status_text"], "Актуально")
        self.assertIsNotNone(payload["last_successful_iso"])
        self.assertIn("T", payload["last_successful_iso"])

    def test_2_sensor_goes_offline(self):
        """When sensor connection fails, current_temperature must be None, online=False, and last_known_temperature preserved."""
        now = time.time()
        payload = self.build_sensor_payload(
            floor="basement",
            name="Підвал",
            installed=True,
            mac="A4:C1:38:00:33:44",
            temperature=18.2,
            humidity=62.0,
            battery=75,
            last_updated=now - 300,
            is_online_reported=False,
            source="ble_direct"
        )
        self.assertEqual(payload["status"], "offline")
        self.assertFalse(payload["online"])
        self.assertFalse(payload["is_stale"])
        # CRITICAL: Old temperature must never be reported as current!
        self.assertIsNone(payload["current_temperature"])
        self.assertIsNone(payload["current_humidity"])
        self.assertEqual(payload["last_known_temperature"], 18.2)
        self.assertEqual(payload["last_known_humidity"], 62.0)
        self.assertTrue(payload["status_text"].startswith("Офлайн — останній вимір"))

    def test_3_cache_older_than_threshold(self):
        """When cached data age exceeds threshold (2400s), status must be 'stale' and current_temperature None."""
        now = time.time()
        payload = self.build_sensor_payload(
            floor="floor2",
            name="2-й поверх",
            installed=True,
            mac="A4:C1:38:00:11:22",
            temperature=20.0,
            humidity=50.0,
            battery=80,
            last_updated=now - (self.threshold + 100),  # > 40 min threshold
            is_online_reported=True,
            source="cache"
        )
        self.assertEqual(payload["status"], "stale")
        self.assertFalse(payload["online"])
        self.assertTrue(payload["is_stale"])
        self.assertIsNone(payload["current_temperature"])
        self.assertEqual(payload["last_known_temperature"], 20.0)
        self.assertTrue(payload["status_text"].startswith("Дані застаріли"))

    def test_4_sqlite_fallback_only_old_value(self):
        """When reading from SQLite fallback history, source is 'sqlite_history' and stale value is never current."""
        now = time.time()
        payload = self.build_sensor_payload(
            floor="basement",
            name="Підвал",
            installed=True,
            mac="A4:C1:38:00:33:44",
            temperature=17.5,
            humidity=65.0,
            battery=None,
            last_updated=now - 7200,  # 2 hours old
            is_online_reported=False,
            source="sqlite_history"
        )
        self.assertEqual(payload["status"], "stale")
        self.assertFalse(payload["online"])
        self.assertTrue(payload["is_stale"])
        self.assertIsNone(payload["current_temperature"])
        self.assertEqual(payload["last_known_temperature"], 17.5)
        self.assertEqual(payload["source"], "sqlite_history")
        self.assertEqual(payload["source_name"], "Історія SQLite")

    def test_5_sensor_not_configured(self):
        """Unconfigured sensor (Floor 1 Garage) must report not_installed with current_temperature=None."""
        payload = self.build_sensor_payload(
            floor="floor1",
            name="1-й поверх (Гараж)",
            installed=False,
            mac=None,
            temperature=None,
            humidity=None,
            battery=None,
            last_updated=None,
            is_online_reported=False,
            source="none"
        )
        self.assertEqual(payload["status"], "not_installed")
        self.assertFalse(payload["installed"])
        self.assertFalse(payload["online"])
        self.assertFalse(payload["is_stale"])
        self.assertIsNone(payload["current_temperature"])
        self.assertIsNone(payload["last_known_temperature"])
        self.assertEqual(payload["status_text"], "Датчик не встановлено")

    def test_6_conflicting_timestamps_ble_and_esp32_merging(self):
        """Merging BLE direct and ESP32 bridge measurements must prevent older or offline polls from overwriting fresh data."""
        now = time.time()
        # Case A: BLE direct is fresh (60s ago), ESP32 poll is older (600s ago)
        ble_fresh = self.build_sensor_payload(
            floor="floor2",
            name="2-й поверх",
            installed=True,
            mac="A4:C1:38:00:11:22",
            temperature=22.0,
            humidity=55.0,
            battery=90,
            last_updated=now - 60,
            is_online_reported=True,
            source="ble_direct"
        )
        esp32_older = self.build_sensor_payload(
            floor="floor2",
            name="2-й поверх",
            installed=True,
            mac="A4:C1:38:00:11:22",
            temperature=20.5,
            humidity=50.0,
            battery=89,
            last_updated=now - 600,
            is_online_reported=False,
            source="esp32_bridge"
        )
        merged_a = self.merge_sensor_readings(ble_fresh, esp32_older)
        self.assertEqual(merged_a["status"], "online")
        self.assertEqual(merged_a["current_temperature"], 22.0)
        self.assertEqual(merged_a["source"], "ble_direct")

        # Reverse order argument test: offline/older first must still yield the fresh online one
        merged_a_rev = self.merge_sensor_readings(esp32_older, ble_fresh)
        self.assertEqual(merged_a_rev["status"], "online")
        self.assertEqual(merged_a_rev["current_temperature"], 22.0)

        # Case B: Direct BLE connection lost (800s ago), ESP32 bridge fresh (20s ago)
        ble_offline = self.build_sensor_payload(
            floor="basement",
            name="Підвал",
            installed=True,
            mac="A4:C1:38:00:33:44",
            temperature=18.0,
            humidity=60.0,
            battery=70,
            last_updated=now - 800,
            is_online_reported=False,
            source="ble_direct"
        )
        esp32_fresh = self.build_sensor_payload(
            floor="basement",
            name="Підвал",
            installed=True,
            mac="A4:C1:38:00:33:44",
            temperature=18.4,
            humidity=61.0,
            battery=72,
            last_updated=now - 20,
            is_online_reported=True,
            source="esp32_bridge"
        )
        merged_b = self.merge_sensor_readings(ble_offline, esp32_fresh)
        self.assertEqual(merged_b["status"], "online")
        self.assertEqual(merged_b["current_temperature"], 18.4)
        self.assertEqual(merged_b["source"], "esp32_bridge")

    def test_7_gas_ppm_none_safety(self):
        """gas_ppm=None must not cause TypeError in telemetry evaluation, state serialization, or scenario execution."""
        auto = self.garage.automation
        # 1. Telemetry evaluation with None gas_ppm
        try:
            auto.evaluate_telemetry({"gas_ppm": None, "car_present": False, "motion_detected": False})
        except TypeError as e:
            self.fail(f"evaluate_telemetry raised TypeError on gas_ppm=None: {e}")

        # 2. API state check
        res = self.client.get("/api/garage/state")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsNone(data["state"]["gas_ppm"])
        self.assertFalse(data["state"]["gas_installed"])
        self.assertEqual(data["state"]["gas_status"], "not_installed")

        # 3. Emergency gas scenario returns disabled/unavailable without crash
        ok, msg = auto.scenario_gas_alarm()
        self.assertFalse(ok)
        self.assertIn("не встановлений", msg)

    def test_8_missing_primary_sensor_when_all_offline(self):
        """When all climate sensors are offline or stale, state['temperature'] and state['current_temperature'] must be None."""
        now = time.time()
        mock_bt_telemetry = {
            "installed": True,
            "online": False,
            "primary_current_temperature": None,
            "primary_last_known_temperature": 19.5,
            "temperature": None,
            "floors": {
                "floor1": self.build_sensor_payload(floor="floor1", name="1-й поверх (Гараж)", installed=False, mac=None),
                "floor2": self.build_sensor_payload(floor="floor2", name="2-й поверх", installed=True, mac="A4:C1:38:00:11:22", temperature=19.5, last_updated=now - 3600, is_online_reported=False, source="sqlite_history"),
                "basement": self.build_sensor_payload(floor="basement", name="Підвал", installed=True, mac="A4:C1:38:00:33:44", temperature=16.0, last_updated=now - 5000, is_online_reported=False, source="sqlite_history")
            }
        }
        mock_esp_telemetry = {
            "online": False,
            "floors": {
                "floor1": self.build_sensor_payload(floor="floor1", name="1-й поверх (Гараж)", installed=False, mac=None),
                "floor2": self.build_sensor_payload(floor="floor2", name="2-й поверх", installed=True, mac="A4:C1:38:00:11:22", temperature=19.5, last_updated=now - 3600, is_online_reported=False, source="esp32_bridge"),
                "basement": self.build_sensor_payload(floor="basement", name="Підвал", installed=True, mac="A4:C1:38:00:33:44", temperature=16.0, last_updated=now - 5000, is_online_reported=False, source="esp32_bridge")
            }
        }
        with patch.object(self.garage.bt_sensors, "get_telemetry", return_value=mock_bt_telemetry), \
             patch.object(self.garage.esp32, "get_telemetry", return_value=mock_esp_telemetry):
            res = self.client.get("/api/garage/state")
            self.assertEqual(res.status_code, 200)
            st = res.get_json()["state"]

            # Current temperature must be None because no sensor is online
            self.assertIsNone(st["current_temperature"])
            self.assertIsNone(st["temperature"])
            # Historical last known temperature is preserved
            self.assertEqual(st["last_known_temperature"], 19.5)
            # Floors detail verification
            self.assertIsNone(st["floors"]["floor2"]["current_temperature"])
            self.assertEqual(st["floors"]["floor2"]["last_known_temperature"], 19.5)
            self.assertEqual(st["floors"]["floor2"]["status"], "stale")
            self.assertIsNone(st["floors"]["basement"]["current_temperature"])
            self.assertEqual(st["floors"]["basement"]["last_known_temperature"], 16.0)
            self.assertEqual(st["floors"]["basement"]["status"], "stale")
            self.assertEqual(st["floors"]["floor1"]["status"], "not_installed")
            self.assertEqual(st["last_known_temperature"], 19.5)
            # Floors detail verification
            self.assertIsNone(st["floors"]["floor2"]["current_temperature"])
            self.assertEqual(st["floors"]["floor2"]["last_known_temperature"], 19.5)
            self.assertEqual(st["floors"]["floor2"]["status"], "stale")
            self.assertIsNone(st["floors"]["basement"]["current_temperature"])
            self.assertEqual(st["floors"]["basement"]["last_known_temperature"], 16.0)
            self.assertEqual(st["floors"]["basement"]["status"], "stale")
            self.assertEqual(st["floors"]["floor1"]["status"], "not_installed")


class TestMusicStopRegression(unittest.TestCase):
    """Verifies complete fix for the regression:
    'грає радіо, кажу виключ музику, а він включає пісню, даю команду повторно він включає щось з ютуба'.
    """

    def setUp(self):
        from server.commands.processor import CommandProcessor
        from server.logger.logger import Logger
        self.mock_speaker = MagicMock()
        self.mock_projector = MagicMock()
        self.mock_esp32 = MagicMock()
        self.processor = CommandProcessor(
            logger=Logger(),
            speaker=self.mock_speaker,
            projector=self.mock_projector,
            esp32=self.mock_esp32
        )

    def test_stop_music_commands_do_not_trigger_youtube_fallback(self):
        """Commands like 'виключ музику' must immediately halt playback and never trigger play_youtube."""
        stop_variations = [
            "виключ музику",
            "виключи музику",
            "виключити музику",
            "вимкни музику",
            "зупини музику",
            "вируби музику",
            "заглуши музику",
            "стоп музика",
            "виключ радіо",
            "вимкни радіо",
            "зупини радіо",
            "виключ все",
            "тиша"
        ]

        for phrase in stop_variations:
            self.mock_speaker.reset_mock()
            self.mock_projector.reset_mock()

            handled, resp = self.processor.execute(phrase)
            self.assertTrue(handled, f"Phrase '{phrase}' was not handled by processor")
            self.assertIn("зупинено", resp.lower())

            # Speaker stop must be called
            self.mock_speaker.stop.assert_called_once()
            # YouTube or stream must NEVER be called
            self.mock_speaker.play_youtube.assert_not_called()
            self.mock_speaker.play_stream.assert_not_called()
            self.mock_speaker.play_song.assert_not_called()

    def test_repeated_stop_command_consistently_stops(self):
        """Repeated stop commands must not fall through to media search keywords."""
        for _ in range(3):
            self.mock_speaker.reset_mock()
            handled, resp = self.processor.execute("виключ музику")
            self.assertTrue(handled)
            self.assertIn("зупинено", resp.lower())
            self.mock_speaker.stop.assert_called_once()
            self.mock_speaker.play_youtube.assert_not_called()

    def test_ai_tools_stop_music_and_guard(self):
        """ToolDispatcher must provide stop_music and guard play_song against stop intents."""
        from server.ai.tools import ToolDispatcher
        mock_garage = MagicMock()
        mock_garage.speaker = MagicMock()
        mock_garage.projector = MagicMock()
        dispatcher = ToolDispatcher(mock_garage)

        # 1. Direct tool call stop_music
        res = dispatcher.execute("stop_music", {})
        self.assertTrue(res["success"])
        mock_garage.speaker.stop.assert_called_once()

        # 2. Guard in play_song if LLM mistakenly passes stop query
        mock_garage.speaker.reset_mock()
        res_guard = dispatcher.execute("play_song", {"query": "виключ музику"})
        self.assertTrue(res_guard["success"])
        self.assertEqual(res_guard["action"], "stop")
        mock_garage.speaker.stop.assert_called_once()
        mock_garage.speaker.play_youtube.assert_not_called()

        # 3. Projector control tool
        mock_garage.projector.is_reachable.return_value = True
        mock_garage.projector.get_status.return_value = {"ip": "192.168.100.191", "port": 57000}
        res_proj = dispatcher.execute("projector_control", {"action": "status"})
        self.assertTrue(res_proj["success"])
        self.assertTrue(res_proj["online"])
        self.assertIn("192.168.100.191", res_proj["message"])


class TestBleScanFiltering(unittest.TestCase):
    """Test get_bound_macs and only_new filtering in BLE scans."""

    def test_get_bound_macs(self):
        from server.webapp import get_bound_macs
        bound = get_bound_macs()
        self.assertIsInstance(bound, set)
        # Verify climate sensors and speakers are present
        self.assertIn("00:11:22:33:44:03", bound)
        self.assertIn("00:11:22:33:44:04", bound)
        self.assertIn("00:11:22:33:44:01", bound)
        self.assertIn("00:11:22:33:44:02", bound)
        from server.devices_config import get_owner_mac
        owner_mac = get_owner_mac()
        expected_phones = {"00:11:22:33:44:05"}
        if owner_mac:
            expected_phones.add(owner_mac)
        self.assertTrue(any(m in bound for m in expected_phones))

    @patch("server.webapp.garage")
    def test_scan_all_ble_filters_bound_devices(self, mock_garage):
        from server.webapp import _scan_all_ble

        # Mock ESP32 returning known sensor + new guest phone
        mock_esp = MagicMock()
        mock_esp.is_connected = True
        mock_esp.scan_ble.return_value = [
            {"mac": "00:11:22:33:44:03", "name": "Basement Temp", "rssi": -65},
            {"mac": "AA:BB:CC:DD:EE:11", "name": "Guest Phone", "rssi": -70}
        ]
        mock_garage.esp32 = mock_esp
        mock_garage.presence = MagicMock()

        # Patch bleak scanner host scan to return empty to isolate ESP32
        with patch("bleak.BleakScanner.discover", return_value=[]):
            # With only_new=True: only the unknown guest phone is returned
            new_devices = _scan_all_ble(duration=1, only_new=True)
            macs = [d["mac"] for d in new_devices]
            self.assertIn("AA:BB:CC:DD:EE:11", macs)
            self.assertNotIn("00:11:22:33:44:03", macs)

            # With only_new=False: all devices are returned
            all_devices = _scan_all_ble(duration=1, only_new=False)
            all_macs = [d["mac"] for d in all_devices]
            self.assertIn("AA:BB:CC:DD:EE:11", all_macs)
            self.assertIn("00:11:22:33:44:03", all_macs)


class TestTemperatureAndBatteryBehavior(unittest.TestCase):
    """Verifies that temperature queries do NOT output battery percentage,
    and dedicated battery inquiries DO output battery levels."""

    def setUp(self):
        self.mock_logger = MagicMock()
        self.mock_memory = MagicMock()
        self.mock_projector = MagicMock()
        self.mock_esp32 = MagicMock()
        self.mock_automation = MagicMock()
        self.mock_bt = MagicMock()
        self.mock_speaker = MagicMock()

        self.mock_bt.get_telemetry.return_value = {
            "floors": {
                "basement": {
                    "online": True,
                    "temperature": 18.5,
                    "humidity": 60.0,
                    "battery": 87,
                    "mac": "00:11:22:33:44:03"
                },
                "floor2": {
                    "online": True,
                    "temperature": 21.0,
                    "humidity": 52.0,
                    "battery": 92,
                    "mac": "00:11:22:33:44:04"
                },
                "floor1": {
                    "online": False,
                    "temperature": None,
                    "humidity": None,
                    "battery": None,
                    "mac": None
                }
            }
        }
        self.mock_esp32.get_telemetry.return_value = {
            "online": True,
            "relays_installed": False,
            "floors": {}
        }

        self.processor = CommandProcessor(
            self.mock_logger,
            self.mock_memory,
            self.mock_projector,
            self.mock_esp32,
            self.mock_automation,
            self.mock_bt,
            speaker=self.mock_speaker
        )

    def test_temperature_queries_do_not_contain_battery(self):
        # Basement temperature
        handled, resp = self.processor.execute("температура в підвалі")
        self.assertTrue(handled)
        self.assertIn("18.5°C", resp)
        self.assertIn("60.0%", resp)
        self.assertNotIn("батаре", resp.lower())
        self.assertNotIn("🔋", resp)

        # Floor 2 temperature
        handled, resp = self.processor.execute("яка температура на 2 поверсі")
        self.assertTrue(handled)
        self.assertIn("21.0°C", resp)
        self.assertIn("52.0%", resp)
        self.assertNotIn("батаре", resp.lower())
        self.assertNotIn("🔋", resp)

        # Sensor status / telemetry
        handled, resp = self.processor.execute("стан датчиків")
        self.assertTrue(handled)
        self.assertIn("18.5°C", resp)
        self.assertIn("21.0°C", resp)
        self.assertNotIn("батаре", resp.lower())
        self.assertNotIn("🔋", resp)

    def test_battery_inquiries_return_battery_percentage(self):
        # Basement battery query
        handled, resp = self.processor.execute("який заряд батареї в підвалі")
        self.assertTrue(handled)
        self.assertIn("87%", resp)
        self.assertIn("підвал", resp.lower())

        # Floor 2 battery query
        handled, resp = self.processor.execute("який заряд батарейки на другому поверсі")
        self.assertTrue(handled)
        self.assertIn("92%", resp)
        self.assertIn("2-му поверсі", resp)

        # General battery query
        handled, resp = self.processor.execute("стан батарейок у датчиках")
        self.assertTrue(handled)
        self.assertIn("87%", resp)
        self.assertIn("92%", resp)
        self.assertIn("Підвал", resp)
        self.assertIn("2-й поверх", resp)


if __name__ == "__main__":
    unittest.main()




