import time
import unittest

from server.devices.esp32 import ESP32Controller, format_relative_time
from server.webapp import app


class TestESP32Diagnostics(unittest.TestCase):

    def setUp(self):
        self.controller = ESP32Controller(mode="mock")

    def tearDown(self):
        self.controller.close()

    def test_format_relative_time(self):
        now = time.time()
        self.assertEqual(format_relative_time(None), "Ніколи")
        self.assertEqual(format_relative_time(now - 2), "щойно")
        self.assertIn("с тому", format_relative_time(now - 30))
        self.assertIn("хв тому", format_relative_time(now - 300))
        self.assertIn("год тому", format_relative_time(now - 7200))

    def test_activity_logging(self):
        self.controller.log_event("sensor_read", "success", "Зчитано датчик", "Тест повідомлення", {"temp": 20.5})
        logs = list(self.controller.activity_logs)
        self.assertTrue(len(logs) > 0)
        last_log = logs[-1]
        self.assertEqual(last_log["type"], "sensor_read")
        self.assertEqual(last_log["status"], "success")
        self.assertEqual(last_log["title"], "Зчитано датчик")
        self.assertEqual(last_log["details"]["temp"], 20.5)

    def test_diagnostics_structure(self):
        diag = self.controller.get_diagnostics()
        self.assertIn("online", diag)
        self.assertIn("host", diag)
        self.assertIn("port", diag)
        self.assertIn("transport", diag)
        self.assertIn("last_seen_formatted", diag)
        self.assertIn("last_seen_relative", diag)
        self.assertIn("logs", diag)
        self.assertIn("stats", diag)
        self.assertIn("sensors", diag)

    def test_update_from_webhook_records_events(self):
        fake_telemetry = {
            "online": True,
            "door": "closed",
            "floors": {
                "basement": {
                    "name": "Підвал",
                    "floor": "basement",
                    "mac": "00:11:22:33:44:03",
                    "online": True,
                    "temperature": 15.5,
                    "humidity": 70,
                    "battery": 95
                }
            }
        }
        res = self.controller.update_from_webhook(fake_telemetry, transport="http")
        self.assertTrue(res)
        diag = self.controller.get_diagnostics()
        self.assertTrue(diag["online"])
        self.assertIn("basement", diag["sensors"])
        self.assertEqual(diag["sensors"]["basement"]["temperature"], 15.5)

        # Check that log event was created
        sensor_logs = [l for l in diag["logs"] if l["type"] == "sensor_read"]
        self.assertTrue(len(sensor_logs) > 0)
        self.assertIn("Підвал", sensor_logs[0]["title"])

    def test_webapp_esp32_endpoints(self):
        client = app.test_client()
        # 1. Status
        res = client.get("/api/esp32/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("status", data)

        # 2. Ping
        res_ping = client.post("/api/esp32/ping")
        self.assertEqual(res_ping.status_code, 200)
        data_ping = res_ping.get_json()
        self.assertTrue(data_ping["success"])

        # 3. Poll
        res_poll = client.post("/api/esp32/poll")
        self.assertEqual(res_poll.status_code, 200)

        # 4. Clear logs
        res_clear = client.post("/api/esp32/clear_logs")
        self.assertEqual(res_clear.status_code, 200)

    def test_get_rf_diagnostics_calculation(self):
        # Setup sample CC1101 telemetry data
        self.controller.state["rf_diag"] = {
            "diag": "spi_active",
            "ver": "0x14",
            "marc": 13,
            "rssi": -138,
            "gdo0": 0,
            "edges": 1586,
            "bb_tw": 66,
            "f": [16, 176, 113],
            "m2": 48,
            "pk0": 50,
            "io0": 13,
            "csn": 10,
            "mosi": 11,
            "sck": 12,
            "miso": 13
        }
        self.controller.state["last_rf_sniffed"] = {
            "code": 15835393,
            "hex": "0xF1A101",
            "bits": 24,
            "protocol": 1,
            "delay": 320
        }

        rf_diag = self.controller.get_rf_diagnostics()
        self.assertTrue(rf_diag["success"])
        self.assertTrue(rf_diag["available"])
        self.assertAlmostEqual(rf_diag["frequency_mhz"], 433.92, places=2)
        self.assertEqual(rf_diag["marc_state_name"], "RX")
        self.assertIn("Прийом", rf_diag["marc_state_desc"])
        self.assertIn("ASK / OOK", rf_diag["modulation"])
        self.assertEqual(rf_diag["edge_count"], 1586)
        self.assertIn("Bit-Bang SPI", rf_diag["spi_status"])
        self.assertEqual(rf_diag["last_captured"]["code"], 15835393)

    def test_rf_status_endpoint_returns_diagnostics(self):
        client = app.test_client()
        res = client.get("/api/rf/status", headers={"X-Admin-PIN": "7777"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("diagnostics", data)
        self.assertIn("frequency_mhz", data["diagnostics"])
        self.assertIn("marc_state_name", data["diagnostics"])


if __name__ == "__main__":
    unittest.main()
