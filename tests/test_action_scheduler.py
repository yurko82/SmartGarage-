import time
import unittest
from unittest.mock import MagicMock

from server.commands.processor import CommandProcessor
from server.router.router import CommandRouter
from server.services.action_scheduler import ActionScheduler, action_scheduler


class TestActionScheduler(unittest.TestCase):

    def setUp(self):
        self.scheduler = ActionScheduler()

    def tearDown(self):
        self.scheduler.clear()

    def test_schedule_immediate(self):
        executed = []
        rec = self.scheduler.schedule(
            delay_seconds=0,
            action_fn=lambda: executed.append("done"),
            description="Тестова негайна дія"
        )
        time.sleep(0.05)
        self.assertEqual(len(executed), 1)
        self.assertEqual(rec["status"], "completed")

    def test_schedule_delayed_and_cancel(self):
        executed = []
        rec = self.scheduler.schedule(
            delay_seconds=10.0,
            action_fn=lambda: executed.append("should_not_run"),
            description="Відкладена дія для скасування"
        )
        self.assertEqual(len(self.scheduler.list_active()), 1)
        ok = self.scheduler.cancel(rec["id"])
        self.assertTrue(ok)
        self.assertEqual(len(self.scheduler.list_active()), 0)
        self.assertEqual(len(executed), 0)

    def test_schedule_delayed_execution(self):
        executed = []
        self.scheduler.schedule(
            delay_seconds=0.1,
            action_fn=lambda: executed.append("fired"),
            description="Швидка відкладена дія"
        )
        time.sleep(0.2)
        self.assertEqual(executed, ["fired"])


class TestTemporalCommandParsing(unittest.TestCase):

    def setUp(self):
        logger = MagicMock()
        self.proc = CommandProcessor(logger=logger)

    def test_extract_temporal_delay_variations(self):
        cases = [
            ("через півхвилини включи радіо", 30.0, "30 секунд", "включи радіо"),
            ("через хвилину включи світло", 60.0, "1 хвилину", "включи світло"),
            ("через 1 хвилину вимкни світло", 60.0, "1 хвилину", "вимкни світло"),
            ("через 45 секунд зроби тихіше", 45.0, "45 сек", "зроби тихіше"),
            ("вимкни світло в підвалі через 5 хвилин", 300.0, "5 хвилин", "вимкни світло в підвалі"),
            ("через півгодини вимкни все", 1800.0, "30 хвилин", "вимкни все"),
            ("просто увімкни світло", 0.0, "", "просто увімкни світло"),
        ]
        for text, exp_sec, exp_desc, exp_clean in cases:
            sec, desc, clean = self.proc._extract_temporal_delay(text)
            self.assertEqual(sec, exp_sec, f"Failed for {text}")
            if exp_sec > 0:
                self.assertEqual(desc, exp_desc, f"Failed desc for {text}")
            self.assertEqual(clean, exp_clean, f"Failed clean for {text}")

    def test_execute_delayed_light_command(self):
        action_scheduler.clear()
        handled, resp = self.proc.execute("через 1 хвилину вимкни світло")
        self.assertTrue(handled)
        self.assertIn("Заплановано дію", resp)
        self.assertIn("1 хвилину", resp)
        active = action_scheduler.list_active()
        self.assertEqual(len(active), 1)
        action_scheduler.clear()

    def test_delayed_command_does_not_execute_immediately(self):
        action_scheduler.clear()
        self.proc.speaker.play_stream = MagicMock()
        handled, resp = self.proc.execute("через 30 секунд включи Kiss FM")
        self.assertTrue(handled)
        # Колонка НЕ повинна починати грати негайно при відкладеній команді!
        self.proc.speaker.play_stream.assert_not_called()
        self.assertEqual(len(action_scheduler.list_active()), 1)
        action_scheduler.clear()


class TestToolDispatcherScheduling(unittest.TestCase):

    def test_schedule_delayed_command_tool(self):
        mock_garage = MagicMock()
        from server.ai.tools import ToolDispatcher
        dispatcher = ToolDispatcher(mock_garage)

        action_scheduler.clear()
        res = dispatcher.execute(
            "schedule_delayed_command",
            {"command": "увімкни світло", "delay_seconds": 60},
            session_id="session_timer_test"
        )
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("scheduled"))
        self.assertEqual(res.get("delay_seconds"), 60)
        self.assertIn("Заплановано", res.get("message", ""))
        self.assertEqual(len(action_scheduler.list_active()), 1)

        # List timers
        res_list = dispatcher.execute("list_active_timers", {}, session_id="session_timer_test")
        self.assertEqual(res_list.get("count"), 1)

        # Cancel timer
        timer_id = res["timer_id"]
        res_cancel = dispatcher.execute("cancel_timer", {"timer_id": timer_id}, session_id="session_timer_test")
        self.assertTrue(res_cancel.get("success"))
        self.assertEqual(len(action_scheduler.list_active()), 0)
        action_scheduler.clear()

    def test_play_radio_with_delay(self):
        mock_garage = MagicMock()
        mock_garage.speaker.is_connected.return_value = True
        from server.ai.tools import ToolDispatcher
        dispatcher = ToolDispatcher(mock_garage)

        action_scheduler.clear()
        res = dispatcher.execute(
            "play_radio",
            {"station": "Relax", "speaker": "jbl", "delay_seconds": 30},
            session_id="session_radio_delay"
        )
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("scheduled"))
        self.assertEqual(res.get("delay_seconds"), 30)
        self.assertIn("Relax", res.get("message", ""))
        self.assertEqual(len(action_scheduler.list_active()), 1)
        action_scheduler.clear()


class TestRouterConversationTurnSync(unittest.TestCase):

    def test_command_turn_synced_to_ai_buffer(self):
        mock_commands = MagicMock()
        mock_commands.execute.return_value = (True, "Освітлення гаража увімкнено.")

        mock_ai = MagicMock()
        mock_ai.conversation_buffer = MagicMock()

        router = CommandRouter(mock_commands, mock_ai)
        resp = router.execute("увімкни світло", session_id="test_session")

        self.assertEqual(resp, "Освітлення гаража увімкнено.")
        mock_ai.conversation_buffer.add_simple_turn.assert_called_once_with(
            "test_session", "увімкни світло", "Освітлення гаража увімкнено."
        )


if __name__ == "__main__":
    unittest.main()
