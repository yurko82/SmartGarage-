"""
Unit tests for 433 MHz RF button event detection, deduplication, zoned lighting (basement/floor2),
and idempotency guarantees (strictly action='off').
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.devices.rf_manager import RfManager, VALID_ZONES


class TestRfManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "test_rf_mappings.json"
        self.manager = RfManager(config_path=self.config_path, dedup_window_sec=0.5)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_mappings_initialization(self):
        """Initial creation should populate default schema and persist to disk."""
        self.assertTrue(self.config_path.exists())
        mappings = self.manager.get_mappings()
        self.assertIn("15835393", mappings)
        self.assertIn("15835394", mappings)
        self.assertEqual(mappings["15835393"]["zone"], "basement_light")
        self.assertEqual(mappings["15835393"]["action"], "off")
        self.assertEqual(mappings["15835394"]["zone"], "floor2_light")
        self.assertEqual(mappings["15835394"]["action"], "off")

    def test_strict_off_action_enforcement(self):
        """RF mappings must strictly enforce action='off' even if caller asks for 'on' or 'toggle'."""
        self.manager.set_mapping(code=99999, zone="basement_light", name="Test Btn", action="on")
        mapping = self.manager.get_mappings().get("99999")
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping["action"], "off")

        self.manager.set_mapping(code=88888, zone="floor2_light", name="Test Btn 2", action="toggle")
        mapping2 = self.manager.get_mappings().get("88888")
        self.assertEqual(mapping2["action"], "off")

    def test_invalid_zone_rejection(self):
        """Invalid zones must raise ValueError."""
        with self.assertRaises(ValueError):
            self.manager.set_mapping(code=123, zone="bedroom_light")

    def test_deduplication_burst_behavior(self):
        """
        When a button is pressed or held, 10 consecutive packets within the dedup window
        must trigger the action callback exactly ONCE.
        """
        callback = MagicMock(return_value=True)
        event = {"code": 15835393, "hex": "0xF1A101", "bits": 24, "protocol": 1, "delay": 320}

        # 1. First packet of the burst
        res1 = self.manager.process_rf_event(event, callback_zone_off=callback)
        self.assertEqual(res1["status"], "executed")
        self.assertTrue(res1["action_taken"])
        self.assertEqual(res1["zone"], "basement_light")
        callback.assert_called_once_with("basement_light")

        # 2. 9 subsequent packets within dedup window (< 0.5s)
        for _ in range(9):
            res_sub = self.manager.process_rf_event(event, callback_zone_off=callback)
            self.assertEqual(res_sub["status"], "deduplicated")
            self.assertFalse(res_sub["action_taken"])

        # Callback must still have been called only ONCE
        callback.assert_called_once_with("basement_light")

    def test_distinct_button_triggers_independent_zone(self):
        """Pressing Button B immediately after Button A must execute Floor 2 off."""
        callback = MagicMock(return_value=True)
        event_a = {"code": 15835393, "hex": "0xF1A101", "bits": 24}
        event_b = {"code": 15835394, "hex": "0xF1A102", "bits": 24}

        self.manager.process_rf_event(event_a, callback_zone_off=callback)
        callback.assert_called_with("basement_light")

        self.manager.process_rf_event(event_b, callback_zone_off=callback)
        callback.assert_called_with("floor2_light")
        self.assertEqual(callback.call_count, 2)

    def test_unmapped_code_does_not_trigger_action(self):
        """Unmapped RF signals must be ignored without altering light state."""
        callback = MagicMock(return_value=True)
        unmapped_event = {"code": 7777777, "hex": "0x76ADF1"}
        res = self.manager.process_rf_event(unmapped_event, callback_zone_off=callback)
        self.assertEqual(res["status"], "unmapped")
        self.assertFalse(res["action_taken"])
        callback.assert_not_called()

    def test_learning_mode_suppresses_execution(self):
        """During learning mode, events are captured in buffer but NO actions are executed."""
        callback = MagicMock(return_value=True)
        self.manager.start_learning(duration_sec=10)
        self.assertTrue(self.manager.is_learning())

        event = {"code": 15835393, "hex": "0xF1A101", "bits": 24, "protocol": 1, "delay": 320}
        res = self.manager.process_rf_event(event, callback_zone_off=callback)
        
        self.assertEqual(res["status"], "learning")
        self.assertFalse(res["action_taken"])
        callback.assert_not_called()

        status = self.manager.get_learning_status()
        self.assertTrue(status["learning_active"])
        self.assertEqual(status["captured_count"], 1)
        self.assertEqual(status["recent_events"][0]["code"], 15835393)

        self.manager.stop_learning()
        self.assertFalse(self.manager.is_learning())

    def test_persistence_across_reloads(self):
        """Mappings saved must persist when a new RfManager instance loads the file."""
        self.manager.set_mapping(code=445566, zone="main_light", name="Світло гараж")
        new_manager = RfManager(config_path=self.config_path)
        mappings = new_manager.get_mappings()
        self.assertIn("445566", mappings)
        self.assertEqual(mappings["445566"]["zone"], "main_light")
        self.assertEqual(mappings["445566"]["action"], "off")


class TestRfWebEndpoints(unittest.TestCase):
    def setUp(self):
        os.environ["TESTING"] = "true"
        from server.webapp import app
        self.app = app
        self.client = self.app.test_client()
        self.admin_pin = os.getenv("ADMIN_PIN") or "9876"
        self.auth_headers = {"X-Admin-PIN": self.admin_pin, "X-Enforce-Auth": "true"}

    def test_rf_mappings_crud_api(self):
        # 1. Get mappings (requires auth)
        unauth = self.client.get("/api/rf/mappings", headers={"X-Enforce-Auth": "true"})
        self.assertEqual(unauth.status_code, 401)

        res = self.client.get("/api/rf/mappings", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

        # 2. Add mapping
        post_data = {
            "code": 1234567,
            "zone": "basement_light",
            "name": "Тестова кнопка підвал"
        }
        res_post = self.client.post("/api/rf/mappings", json=post_data, headers=self.auth_headers)
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.get_json()["action"], "off")

        # 3. Delete mapping
        res_del = self.client.delete("/api/rf/mappings/1234567", headers=self.auth_headers)
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

    def test_rf_learning_endpoints(self):
        # Start learning
        res_start = self.client.post("/api/rf/learn/start", json={"duration": 15}, headers=self.auth_headers)
        self.assertEqual(res_start.status_code, 200)
        self.assertTrue(res_start.get_json()["learning"])

        # Status
        res_status = self.client.get("/api/rf/learn/status", headers=self.auth_headers)
        self.assertEqual(res_status.status_code, 200)
        self.assertTrue(res_status.get_json()["status"]["learning_active"])

        # Stop learning
        res_stop = self.client.post("/api/rf/learn/stop", headers=self.auth_headers)
        self.assertEqual(res_stop.status_code, 200)
        self.assertFalse(res_stop.get_json()["learning"])

    def test_light_zone_off_endpoint(self):
        res = self.client.post("/api/device/light/zone/off", json={"zone": "basement_light"}, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["zone"], "basement_light")
        self.assertEqual(data["action"], "off")

    def test_rf_diag_endpoint_auth_protected(self):
        unauth = self.client.get("/api/rf/diag", headers={"X-Enforce-Auth": "true"})
        self.assertEqual(unauth.status_code, 401)

        auth = self.client.get("/api/rf/diag", headers=self.auth_headers)
        self.assertEqual(auth.status_code, 200)
        self.assertTrue(auth.get_json()["success"])

    def test_automation_rules_endpoint(self):
        res = self.client.get("/api/automation/rules", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["rules"], list)


class TestZonedLightCommandsAndTools(unittest.TestCase):
    def setUp(self):
        from server.commands.processor import CommandProcessor
        from server.ai.tools import ToolDispatcher
        self.mock_garage = MagicMock()
        self.mock_esp32 = MagicMock()
        self.mock_garage.esp32 = self.mock_esp32
        self.mock_garage.turn_off_light_zone.side_effect = lambda z: self.mock_esp32.light_off_zone(z)
        
        self.processor = CommandProcessor(
            MagicMock(), MagicMock(), MagicMock(), self.mock_esp32, MagicMock(), MagicMock()
        )
        self.dispatcher = ToolDispatcher(self.mock_garage)

    def test_ukrainian_natural_commands_zone_off(self):
        # 1. Basement
        handled, resp = self.processor.execute("вимкни світло в підвалі")
        self.assertTrue(handled)
        self.assertIn("підвалі вимкнено", resp)
        self.mock_esp32.light_off_zone.assert_called_with("basement_light")

        # 2. Floor 2
        handled2, resp2 = self.processor.execute("вимкни світло на другому поверсі")
        self.assertTrue(handled2)
        self.assertIn("другому поверсі вимкнено", resp2)
        self.mock_esp32.light_off_zone.assert_called_with("floor2_light")

        # 3. All lights
        handled3, resp3 = self.processor.execute("вимкни все світло")
        self.assertTrue(handled3)
        self.assertIn("Усе світло у всіх зонах", resp3)
        self.mock_esp32.light_off_zone.assert_called_with("all")

    def test_ai_tool_control_device_zones(self):
        res_base = self.dispatcher.execute("control_device", {"device": "basement_light", "action": "off"})
        self.assertTrue(res_base["success"])
        self.assertIn("підвалі вимкнено", res_base["message"])
        self.mock_esp32.light_off_zone.assert_called_with("basement_light")

        res_f2 = self.dispatcher.execute("control_device", {"device": "floor2_light", "action": "off"})
        self.assertTrue(res_f2["success"])
        self.assertIn("2-му поверсі вимкнено", res_f2["message"])
        self.mock_esp32.light_off_zone.assert_called_with("floor2_light")


if __name__ == "__main__":
    unittest.main()
