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
                    "mac": "A4:C1:38:CC:CA:49",
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


if __name__ == "__main__":
    unittest.main()
