"""
Unit tests for 433 MHz RF button event detection, deduplication, zoned controls
(basement: light/ventilation, floor2: kitchen/living room, garage), radio relay management,
and live RF activity logging.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.devices.rf_manager import VALID_ZONES, ZONE_DESCRIPTIONS, RfManager


class TestRfManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "test_rf_mappings.json"
        self.manager = RfManager(config_path=self.config_path, dedup_window_sec=0.5)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_mappings_and_relays_initialization(self):
        """Initial creation should populate default schema (mappings and relays) and persist to disk."""
        self.assertTrue(self.config_path.exists())
        mappings = self.manager.get_mappings()
        self.assertIn("15835393", mappings)
        self.assertIn("15835394", mappings)
        self.assertEqual(mappings["15835393"]["zone"], "basement_light")
        self.assertEqual(mappings["15835393"]["action"], "off")

        relays = self.manager.get_relays()
        self.assertIn("relay_basement_light", relays)
        self.assertIn("relay_basement_fan", relays)
        self.assertIn("relay_floor2_kitchen", relays)
        self.assertIn("relay_floor2_living_room", relays)
        self.assertEqual(relays["relay_basement_fan"]["zone"], "basement_fan")
        self.assertEqual(relays["relay_floor2_kitchen"]["zone"], "floor2_kitchen")
        self.assertEqual(relays["relay_floor2_living_room"]["zone"], "floor2_living_room")

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
        with self.assertRaises(ValueError):
            self.manager.set_relay(relay_id="r1", zone="bedroom_light", name="Bad", code_on=1, code_off=2)

    def test_new_zones_validity(self):
        """Verify that basement_fan, floor2_kitchen, and floor2_living_room are valid zones."""
        self.assertIn("basement_fan", VALID_ZONES)
        self.assertIn("floor2_kitchen", VALID_ZONES)
        self.assertIn("floor2_living_room", VALID_ZONES)

        self.manager.set_mapping(code=112233, zone="basement_fan", name="Кнопка витяжки")
        mapping = self.manager.get_mappings().get("112233")
        self.assertEqual(mapping["zone"], "basement_fan")
        self.assertEqual(mapping["action"], "off")

    def test_relays_crud_and_lookup(self):
        """Test adding, querying, and deleting radio relays."""
        self.manager.set_relay(
            relay_id="custom_kitchen_relay",
            zone="floor2_kitchen",
            name="Реле над плитою",
            code_on=778899,
            code_off=778890
        )
        r = self.manager.get_relay("custom_kitchen_relay")
        self.assertIsNotNone(r)
        self.assertEqual(r["code_on"], 778899)
        self.assertEqual(r["code_off"], 778890)

        by_zone = self.manager.get_relay_by_zone("floor2_kitchen")
        self.assertIsNotNone(by_zone)

        deleted = self.manager.delete_relay("custom_kitchen_relay")
        self.assertTrue(deleted)
        self.assertIsNone(self.manager.get_relay("custom_kitchen_relay"))

    def test_activity_log_and_metrics(self):
        """Test logging TX/RX activity and telemetry metrics."""
        self.manager.log_activity("TX", 15835393, action="on", zone="basement_light", details="Test TX")
        self.manager.log_activity("RX", 15835394, action="off", zone="floor2_light", details="Test RX")

        metrics = self.manager.get_metrics()
        self.assertEqual(metrics["tx_count"], 1)
        self.assertEqual(metrics["rx_count"], 1)
        self.assertEqual(metrics["last_tx_code"], 15835393)
        self.assertEqual(metrics["last_rx_code"], 15835394)

        log = self.manager.get_activity_log(limit=10)
        self.assertGreaterEqual(len(log), 2)
        self.assertEqual(log[0]["direction"], "RX")
        self.assertEqual(log[1]["direction"], "TX")

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
        """Mappings and relays saved must persist when a new RfManager instance loads the file."""
        self.manager.set_mapping(code=445566, zone="main_light", name="Світло гараж")
        self.manager.set_relay(relay_id="r_test", zone="basement_fan", name="Вентилятор", code_on=111, code_off=222)

        new_manager = RfManager(config_path=self.config_path)
        mappings = new_manager.get_mappings()
        self.assertIn("445566", mappings)
        self.assertEqual(mappings["445566"]["zone"], "main_light")

        relays = new_manager.get_relays()
        self.assertIn("r_test", relays)
        self.assertEqual(relays["r_test"]["code_on"], 111)


class TestRfWebEndpoints(unittest.TestCase):
    def setUp(self):
        os.environ["TESTING"] = "true"
        from server.webapp import app
        self.app = app
        self.client = self.app.test_client()
        self.admin_pin = os.getenv("ADMIN_PIN") or "9876"
        self.auth_headers = {"X-Admin-PIN": self.admin_pin, "X-Enforce-Auth": "true"}

    def test_rf_mappings_crud_api(self):
        unauth = self.client.get("/api/rf/mappings", headers={"X-Enforce-Auth": "true"})
        self.assertEqual(unauth.status_code, 401)

        res = self.client.get("/api/rf/mappings", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

        post_data = {
            "code": 1234567,
            "zone": "basement_light",
            "name": "Тестова кнопка підвал"
        }
        res_post = self.client.post("/api/rf/mappings", json=post_data, headers=self.auth_headers)
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.get_json()["action"], "off")

        res_del = self.client.delete("/api/rf/mappings/1234567", headers=self.auth_headers)
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

    def test_rf_status_and_activity_api(self):
        res_status = self.client.get("/api/rf/status", headers=self.auth_headers)
        self.assertEqual(res_status.status_code, 200)
        data = res_status.get_json()
        self.assertTrue(data["success"])
        self.assertIn("metrics", data)
        self.assertIn("activity", data)

        res_act = self.client.get("/api/rf/activity?limit=10", headers=self.auth_headers)
        self.assertEqual(res_act.status_code, 200)
        act_data = res_act.get_json()
        self.assertTrue(act_data["success"])
        self.assertIsInstance(act_data["activity"], list)

    def test_rf_zones_api(self):
        res = self.client.get("/api/rf/zones", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        zone_ids = [z["id"] for z in data["zones"]]
        self.assertIn("basement_light", zone_ids)
        self.assertIn("basement_fan", zone_ids)
        self.assertIn("floor2_kitchen", zone_ids)
        self.assertIn("floor2_living_room", zone_ids)

    def test_rf_relays_crud_and_actions(self):
        # 1. Get relays
        res = self.client.get("/api/rf/relays", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

        # 2. Add relay
        new_relay = {
            "id": "relay_test_kitchen",
            "zone": "floor2_kitchen",
            "name": "Кухня люстра",
            "code_on": 989801,
            "code_off": 989802
        }
        res_post = self.client.post("/api/rf/relays", json=new_relay, headers=self.auth_headers)
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.get_json()["success"])

        # 3. Test relay ON & OFF
        res_test = self.client.post("/api/rf/relays/relay_test_kitchen/test", json={"action": "on"}, headers=self.auth_headers)
        self.assertEqual(res_test.status_code, 200)
        self.assertTrue(res_test.get_json()["success"])

        # 4. Pair relay
        res_pair = self.client.post("/api/rf/relays/relay_test_kitchen/pair", json={"action": "on", "duration": 5}, headers=self.auth_headers)
        self.assertEqual(res_pair.status_code, 200)
        self.assertTrue(res_pair.get_json()["success"])

        # 5. Delete relay
        res_del = self.client.delete("/api/rf/relays/relay_test_kitchen", headers=self.auth_headers)
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

    def test_device_zone_control_endpoint(self):
        # Test unified zone control endpoint
        payload = {"zone": "basement_fan", "action": "on"}
        res = self.client.post("/api/device/zone/control", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["zone"], "basement_fan")
        self.assertEqual(data["action"], "on")

    def test_rf_transmit_endpoint(self):
        payload = {"code": 15835393, "zone": "basement_light", "action": "on"}
        res = self.client.post("/api/rf/transmit", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])


class TestZonedCommandsAndTools(unittest.TestCase):
    def setUp(self):
        from server.ai.tools import ToolDispatcher
        from server.commands.processor import CommandProcessor
        self.mock_garage = MagicMock()
        self.mock_esp32 = MagicMock()
        self.mock_garage.esp32 = self.mock_esp32
        self.mock_garage.turn_off_light_zone.side_effect = lambda z: self.mock_esp32.light_off_zone(z)
        self.mock_garage.control_zone.side_effect = lambda z, a: self.mock_esp32.control_zone(z, a)

        self.processor = CommandProcessor(
            MagicMock(), MagicMock(), MagicMock(), self.mock_esp32, MagicMock(), MagicMock()
        )
        self.dispatcher = ToolDispatcher(self.mock_garage)

    def test_ukrainian_commands_basement(self):
        # Basement light
        h_on, r_on = self.processor.execute("увімкни світло в підвалі")
        self.assertTrue(h_on)
        self.assertIn("підвалі увімкнено", r_on)
        self.mock_esp32.control_zone.assert_called_with("basement_light", "on")

        h_off, r_off = self.processor.execute("вимкни світло в підвалі")
        self.assertTrue(h_off)
        self.assertIn("підвалі вимкнено", r_off)
        self.mock_esp32.control_zone.assert_called_with("basement_light", "off")

        # Basement fan / ventilation
        h_fan_on, r_fan_on = self.processor.execute("увімкни вентиляцію в підвалі")
        self.assertTrue(h_fan_on)
        self.assertIn("Вентиляцію в підвалі увімкнено", r_fan_on)
        self.mock_esp32.control_zone.assert_called_with("basement_fan", "on")

        h_fan_off, r_fan_off = self.processor.execute("вимкни витяжку в підвалі")
        self.assertTrue(h_fan_off)
        self.assertIn("Вентиляцію в підвалі вимкнено", r_fan_off)
        self.mock_esp32.control_zone.assert_called_with("basement_fan", "off")

    def test_ukrainian_commands_floor2_rooms(self):
        # Kitchen (Room 1)
        h_k_on, r_k_on = self.processor.execute("увімкни світло на кухні")
        self.assertTrue(h_k_on)
        self.assertIn("кухні (2-й поверх) увімкнено", r_k_on)
        self.mock_esp32.control_zone.assert_called_with("floor2_kitchen", "on")

        h_k_off, r_k_off = self.processor.execute("вимкни світло на кухні")
        self.assertTrue(h_k_off)
        self.assertIn("кухні (2-й поверх) вимкнено", r_k_off)
        self.mock_esp32.control_zone.assert_called_with("floor2_kitchen", "off")

        # Living room (Room 2)
        h_l_on, r_l_on = self.processor.execute("увімкни світло у вітальні")
        self.assertTrue(h_l_on)
        self.assertIn("вітальні (2-й поверх) увімкнено", r_l_on)
        self.mock_esp32.control_zone.assert_called_with("floor2_living_room", "on")

        h_l_off, r_l_off = self.processor.execute("вимкни світло у вітальні")
        self.assertTrue(h_l_off)
        self.assertIn("вітальні (2-й поверх) вимкнено", r_l_off)
        self.mock_esp32.control_zone.assert_called_with("floor2_living_room", "off")

        # Floor 2 general
        h_f2_on, r_f2_on = self.processor.execute("увімкни світло на другому поверсі")
        self.assertTrue(h_f2_on)
        self.assertIn("другому поверсі увімкнено", r_f2_on)
        self.mock_esp32.control_zone.assert_called_with("floor2_light", "on")

        h_f2_off, r_f2_off = self.processor.execute("вимкни світло на другому поверсі")
        self.assertTrue(h_f2_off)
        self.assertIn("другому поверсі вимкнено", r_f2_off)
        self.mock_esp32.control_zone.assert_called_with("floor2_light", "off")

    def test_ai_tool_control_device_all_zones(self):
        # Basement light
        res = self.dispatcher.execute("control_device", {"device": "basement_light", "action": "on"})
        self.assertTrue(res["success"])
        self.assertIn("підвалі увімкнено", res["message"])
        self.mock_esp32.control_zone.assert_called_with("basement_light", "on")

        # Basement fan
        res_fan = self.dispatcher.execute("control_device", {"device": "basement_fan", "action": "on"})
        self.assertTrue(res_fan["success"])
        self.assertIn("підвалі увімкнено", res_fan["message"])
        self.mock_esp32.control_zone.assert_called_with("basement_fan", "on")

        # Floor 2 Kitchen
        res_k = self.dispatcher.execute("control_device", {"device": "floor2_kitchen", "action": "off"})
        self.assertTrue(res_k["success"])
        self.assertIn("кухні (2-й поверх) вимкнено", res_k["message"])
        self.mock_esp32.control_zone.assert_called_with("floor2_kitchen", "off")

        # Floor 2 Living room
        res_liv = self.dispatcher.execute("control_device", {"device": "floor2_living_room", "action": "on"})
        self.assertTrue(res_liv["success"])
        self.assertIn("вітальні (2-й поверх) увімкнено", res_liv["message"])
        self.mock_esp32.control_zone.assert_called_with("floor2_living_room", "on")


if __name__ == "__main__":
    unittest.main()
