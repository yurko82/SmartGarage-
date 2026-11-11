"""
tests/test_device_service.py — Юніт-тести для сервісу апаратного рівня DeviceService.
Перевіряє централізоване керування ESP32, BLE-датчиками, RF 433 МГц, подвійним аудіо, проєктором та присутністю.
"""
import unittest
from unittest.mock import MagicMock, patch

from server.services.device_service import DeviceService


class TestDeviceService(unittest.TestCase):
    def setUp(self):
        self.mock_esp32 = MagicMock()
        self.mock_bt_sensors = MagicMock()
        self.mock_speaker = MagicMock()
        self.mock_rf_manager = MagicMock()
        self.mock_projector = MagicMock()
        self.mock_presence = MagicMock()
        self.mock_telemetry_db = MagicMock()

        self.service = DeviceService(
            esp32=self.mock_esp32,
            bt_sensors=self.mock_bt_sensors,
            speaker=self.mock_speaker,
            rf_manager=self.mock_rf_manager,
            projector=self.mock_projector,
            presence=self.mock_presence,
            telemetry_db=self.mock_telemetry_db,
        )

    def test_init_with_defaults(self):
        ds = DeviceService()
        self.assertIsNotNone(ds)

    def test_get_telemetry_from_esp32(self):
        self.mock_esp32.get_status.return_value = {
            "online": True,
            "light": True,
            "fan": False,
            "temperature": 21.5,
            "humidity": 48.0,
            "floors": {
                "floor1": {"temperature": 21.5, "humidity": 48.0, "online": True}
            }
        }
        self.mock_bt_sensors.get_latest_data.return_value = {}
        data = self.service.get_telemetry()
        self.assertTrue(data["online"])
        self.assertTrue(data["light"])
        self.assertEqual(data["temperature"], 21.5)
        self.assertEqual(data["source"], "esp32")

    def test_get_telemetry_fallback_to_db(self):
        self.mock_esp32.get_status.side_effect = Exception("ESP32 timeout")
        self.mock_bt_sensors.get_latest_data.return_value = {}
        self.mock_telemetry_db.get_latest_by_floor.return_value = {
            "floor1": {"temperature": 18.0, "humidity": 55.0, "online": False}
        }
        data = self.service.get_telemetry()
        self.assertEqual(data["temperature"], 18.0)
        self.assertEqual(data["humidity"], 55.0)

    def test_trigger_door_success(self):
        self.mock_esp32.trigger_door.return_value = True
        res = self.service.trigger_door()
        self.assertTrue(res)
        self.mock_esp32.trigger_door.assert_called_once()

    def test_trigger_door_esp32_unavailable(self):
        ds = DeviceService(esp32=None)
        with patch.object(ds, "_esp32", None):
            res = ds.trigger_door()
            self.assertFalse(res)

    def test_set_light_main_relay(self):
        self.mock_esp32.set_light.return_value = True
        res = self.service.set_light(True, zone="main")
        self.assertTrue(res)
        self.mock_esp32.set_light.assert_called_with(True)
        # rf_light sent

    def test_set_light_rf_zone_floor2(self):
        self.mock_esp32.control_relay_zone.return_value = True
        res = self.service.set_light(True, zone="floor2")
        self.assertTrue(res)
        self.mock_esp32.control_relay_zone.assert_called_with("floor2", "on")

    def test_set_light_rf_zone_basement(self):
        self.mock_esp32.control_relay_zone.return_value = True
        res = self.service.set_light(False, zone="підвал")
        self.assertTrue(res)
        self.mock_esp32.control_relay_zone.assert_called_with("basement", "off")

    def test_set_fan_success(self):
        self.mock_esp32.set_fan.return_value = True
        res = self.service.set_fan(True)
        self.assertTrue(res)
        self.mock_esp32.set_fan.assert_called_with(True)

    def test_set_fan_failure(self):
        self.mock_esp32.set_fan.side_effect = Exception("GPIO error")
        res = self.service.set_fan(False)
        self.assertFalse(res)

    def test_send_rf_code_via_esp32_transmit(self):
        self.mock_esp32.rf_transmit.return_value = True
        res = self.service.send_rf_code(0x123456, protocol=1)
        self.assertTrue(res)
        self.mock_esp32.rf_transmit.assert_called_with(0x123456)

    def test_send_rf_code_fallback_to_send_command(self):
        mock_e = MagicMock(spec=["send_command"])
        mock_e.send_command.return_value = {"status": "ok"}
        ds = DeviceService(esp32=mock_e)
        res = ds.send_rf_code(0xABCDEF)
        self.assertTrue(res)
        mock_e.send_command.assert_called_with("RF_SEND:11259375")

    def test_get_rf_diagnostics_success(self):
        self.mock_esp32.get_rf_diagnostics.return_value = {
            "status": "ok",
            "marc": 13,
            "rssi": -65,
            "ver": "0x14"
        }
        diag = self.service.get_rf_diagnostics()
        self.assertEqual(diag["marc"], 13)
        self.assertEqual(diag["rssi"], -65)

    def test_get_rf_diagnostics_error(self):
        self.mock_esp32.get_rf_diagnostics.side_effect = Exception("I/O error")
        diag = self.service.get_rf_diagnostics()
        self.assertEqual(diag["status"], "error")

    def test_scan_ble(self):
        self.mock_esp32.scan_ble.return_value = [
            {"mac": "00:11:22:33:44:99", "name": "Guest Phone", "rssi": -70}
        ]
        devices = self.service.scan_ble(duration=5)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["mac"], "00:11:22:33:44:99")

    def test_speaker_play_jbl(self):
        self.mock_speaker.play_file.return_value = True
        res = self.service.speaker_play("hit_fm", device="jbl", title="Hit FM")
        self.assertTrue(res)
        self.mock_speaker.play_file.assert_called_with("hit_fm", track_title="Hit FM")

    def test_speaker_play_jxbt(self):
        self.mock_speaker.play_on_speaker.return_value = True
        res = self.service.speaker_play("radio_roks", device="floor1", title="Radio ROKS")
        self.assertTrue(res)
        self.mock_speaker.play_on_speaker.assert_called_with("floor1", "radio_roks", track_title="Radio ROKS")

    def test_speaker_stop(self):
        self.mock_speaker.stop.return_value = True
        res = self.service.speaker_stop()
        self.assertTrue(res)
        self.mock_speaker.stop.assert_called_once()

    def test_get_presence_status(self):
        self.mock_presence.devices = {"owner_phone": {"name": "Юрій", "status": "home"}}
        status = self.service.get_presence_status()
        self.assertEqual(status["status"], "active")
        self.assertEqual(status["total_devices"], 1)

    def test_projector_control_on_off(self):
        self.mock_projector.turn_on.return_value = True
        self.mock_projector.turn_off.return_value = True
        self.assertTrue(self.service.projector_control("on"))
        self.assertTrue(self.service.projector_control("off"))
        self.assertFalse(self.service.projector_control("invalid_action"))

    def test_garage_core_has_device_service(self):
        from server.core.core import SmartGarage
        garage = SmartGarage()
        self.assertTrue(hasattr(garage, "device_service"))
        self.assertIsInstance(garage.device_service, DeviceService)


if __name__ == "__main__":
    unittest.main()
