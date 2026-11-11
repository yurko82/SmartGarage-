"""Тести для вебдіалогу, збереження контексту, ізоляції сесій та механізму повторних дій (Pending Actions)."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.ai.manager import AIManager, ConversationBuffer
from server.ai.session_manager import (
    PendingAction,
    SessionContext,
    SessionManager,
    is_retry_intent,
    is_safe_session_id,
    validate_openrouter_messages,
)
from server.ai.tools import ToolDispatcher
from server.webapp import app, garage


class TestWebDialogSessionSecurity(unittest.TestCase):
    """Тести безпеки, валідації та ізоляції сесій вебдіалогу."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_missing_session_id_gets_server_generated_id(self):
        """Якщо session_id не передано, сервер створює унікальний ізольований ID (не web_console)."""
        res = self.client.post("/command", json={"command": "стан"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        sid = data.get("session_id")
        self.assertIsNotNone(sid)
        self.assertNotEqual(sid, "web_console")
        self.assertTrue(is_safe_session_id(sid))

    def test_never_use_global_web_console(self):
        """Сервер ніколи не повертає загальний 'web_console' для клієнтів."""
        res1 = self.client.post("/command", json={"command": "стан"})
        sid1 = res1.get_json().get("session_id")
        self.assertNotEqual(sid1, "web_console")

        res2 = self.client.post("/command", json={"command": "стан"})
        sid2 = res2.get_json().get("session_id")
        self.assertNotEqual(sid2, "web_console")

    def test_forbid_personal_data_in_session_id(self):
        """Ідентифікатор сесії не повинен містити персональних або присутніх даних."""
        # Тести на особисті імена та адмін маркери
        self.assertFalse(is_safe_session_id("yurko_session_123"))
        self.assertFalse(is_safe_session_id("admin_session_456"))
        self.assertFalse(is_safe_session_id("yuri_browser_789"))
        # Тест на IP-адресу
        self.assertFalse(is_safe_session_id("192.168.1.50_session"))
        # Тест на email
        self.assertFalse(is_safe_session_id("user@example.com_session"))
        # Тест на MAC-адресу датчика
        self.assertFalse(is_safe_session_id("A4:C1:38:12:34:56_session"))
        # Валідний випадковий токен
        self.assertTrue(is_safe_session_id("api_a1b2c3d4e5f67890"))
        self.assertTrue(is_safe_session_id("web_9876543210fedcba"))

        # Запит з небезпечним ID відхиляється сервером
        res = self.client.post("/command", json={"command": "стан", "session_id": "yurko_private_sid"})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["success"])

    def test_browser_session_prevents_session_hijacking(self):
        """Браузерна сесія не дозволяє клієнту підставити довільний чужий session ID."""
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["login_time"] = time.time()
            sess["dialog_session_id"] = "web_legitimate_session_123"
            sess["csrf_token"] = "valid_csrf_token_test"

        # 1. Запит з правильним або порожнім session_id успішний
        res_ok = self.client.post(
            "/command",
            headers={"X-CSRF-Token": "valid_csrf_token_test"},
            json={"command": "стан", "session_id": "web_legitimate_session_123"}
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.get_json()["session_id"], "web_legitimate_session_123")

        # 2. Спроба підмінити чужий session_id блокується (403 Forbidden)
        res_hijack = self.client.post(
            "/command",
            headers={"X-CSRF-Token": "valid_csrf_token_test"},
            json={"command": "стан", "session_id": "web_foreign_victim_session_999"}
        )
        self.assertEqual(res_hijack.status_code, 403)
        self.assertFalse(res_hijack.get_json()["success"])
        self.assertIn("підміна session_id заборонена", res_hijack.get_json()["response"])


class TestMultiSessionIsolation(unittest.TestCase):
    """Тести ізоляції контекстів різних браузерів та сесій."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.temp_dir.name) / "test_dialog_sessions.json"
        self.session_mgr = SessionManager(storage_path=self.storage_file)
        self.ai = AIManager(session_mgr=self.session_mgr)
        self.mock_garage = MagicMock()
        self.mock_garage.speaker.name = "JBL Clip 5"
        self.dispatcher = ToolDispatcher(self.mock_garage)
        self.ai.set_tool_dispatcher(self.dispatcher)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_contexts_of_different_sessions_do_not_bleed(self):
        """Контексти діалогів двох різних користувачів/сесій не перетинаються."""
        sid1 = "session_user_alpha_1"
        sid2 = "session_user_beta_2"

        # Користувач 1 веде діалог про вентиляцію
        self.ai.conversation_buffer.add_simple_turn(sid1, "увімкни вентиляцію", "Витяжну вентиляцію увімкнено.")
        # Користувач 2 веде діалог про освітлення
        self.ai.conversation_buffer.add_simple_turn(sid2, "увімкни світло", "Освітлення увімкнено.")

        msgs1 = self.ai.conversation_buffer.get_messages(sid1)
        msgs2 = self.ai.conversation_buffer.get_messages(sid2)

        # Переконуємося, що в сесії 1 немає даних про світло
        self.assertEqual(len(msgs1), 2)
        self.assertEqual(msgs1[0]["content"], "увімкни вентиляцію")
        self.assertEqual(msgs1[1]["content"], "Витяжну вентиляцію увімкнено.")

        # Переконуємося, що в сесії 2 немає даних про вентиляцію
        self.assertEqual(len(msgs2), 2)
        self.assertEqual(msgs2[0]["content"], "увімкни світло")
        self.assertEqual(msgs2[1]["content"], "Освітлення увімкнено.")

    def test_pending_actions_isolated_between_sessions(self):
        """Невдала дія в одній сесії не впливає на follow-up у іншій сесії."""
        sid1 = "session_client_one_1"
        sid2 = "session_client_two_2"

        # В сесії 1 колонка недоступна
        self.mock_garage.speaker.is_connected.return_value = False
        res1 = self.dispatcher.execute("play_song", {"query": "ADAM - Сильно Сильно"}, session_id=sid1)
        self.assertFalse(res1["success"])

        # В сесії 2 освітлення успішно увімкнено
        self.mock_garage.esp32.light_on.return_value = True
        res2 = self.dispatcher.execute("control_device", {"device": "light", "action": "on"}, session_id=sid2)
        self.assertTrue(res2["success"])

        # Користувач 1 пише «спробуй ще раз»
        ans1 = self.ai.chat("спробуй ще раз", session_id=sid1)
        self.assertIn("Повторна спроба не вдалася", ans1)
        self.assertIn("колонка", ans1.lower())

        # Користувач 2 пише «спробуй ще раз»
        ans2 = self.ai.chat("спробуй ще раз", session_id=sid2)
        # Для користувача 2 дія була успішною, тому не повторюємо побічну дію сліпо!
        self.assertIn("уже була успішно виконана", ans2)
        self.assertIn("light", ans2)


class TestSessionPersistenceAcrossRestarts(unittest.TestCase):
    """Тести збереження контексту та pending actions після перезапуску сервера."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.temp_dir.name) / "persistent_sessions.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persistence_of_history_and_pending_action(self):
        """Сесія та незавершена дія зберігаються на диску і доступні після перезавантаження."""
        sid = "persistent_web_session_77"

        # 1. Створюємо екземпляр менеджера до перезапуску
        mgr1 = SessionManager(storage_path=self.storage_file)
        ai1 = AIManager(session_mgr=mgr1)
        mock_garage = MagicMock()
        mock_garage.speaker.is_connected.return_value = False
        dispatcher1 = ToolDispatcher(mock_garage)
        ai1.set_tool_dispatcher(dispatcher1)

        # Виконуємо спробу відтворити пісню (невдала через відсутність колонки)
        ai1.handle_retry_followup(sid)  # Спочатку немає дій
        action_res = dispatcher1.execute("play_song", {"query": "Океан Ельзи - Обійми"}, session_id=sid)
        self.assertFalse(action_res["success"])
        mgr1.record_tool_action(sid, "play_song", {"query": "Океан Ельзи - Обійми"}, action_res)

        # 2. Симулюємо повний перезапуск сервера (новий екземпляр менеджера з тим самим файлом)
        mgr2 = SessionManager(storage_path=self.storage_file)
        ai2 = AIManager(session_mgr=mgr2)
        # Тепер колонка увімкнулась!
        mock_garage.speaker.is_connected.return_value = True
        mock_garage.speaker.play_youtube.return_value = True
        mock_garage.speaker.name = "JBL Clip 5"
        dispatcher2 = ToolDispatcher(mock_garage)
        ai2.set_tool_dispatcher(dispatcher2)

        # Перевіряємо, що pending_action збереглася після перезапуску
        pending = mgr2.get_pending_action(sid)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.arguments.get("query"), "Океан Ельзи - Обійми")
        self.assertFalse(pending.success)

        # Користувач після перезапуску пише «спробуй ще раз»
        retry_ans = ai2.chat("спробуй ще раз", session_id=sid)
        self.assertIn("Повторна спроба успішна", retry_ans)
        self.assertIn("Океан Ельзи - Обійми", retry_ans)


class TestFollowUpAndMusicToolHandling(unittest.TestCase):
    """Тести для сценарію 'увімкни пісню' -> помилка -> 'спробуй ще раз'."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.temp_dir.name) / "test_sessions.json"
        self.session_mgr = SessionManager(storage_path=self.storage_file)
        self.ai = AIManager(session_mgr=self.session_mgr)
        self.mock_garage = MagicMock()
        self.mock_garage.speaker.name = "JBL Clip 5"
        self.dispatcher = ToolDispatcher(self.mock_garage)
        self.ai.set_tool_dispatcher(self.dispatcher)
        self.sid = "test_dialog_session_music_1"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_music_retry_preserves_query_and_checks_player_confirmation(self):
        """Агент пам’ятає трек, не стверджує що пісня грає до підтвердження, і повторює з тим самим запитом."""
        # 1. Колонка недоступна
        self.mock_garage.speaker.is_connected.return_value = False
        res1 = self.dispatcher.execute("play_song", {"query": "Бумбокс - Люди"}, session_id=self.sid)

        self.assertFalse(res1["success"])
        self.assertEqual(res1["status"], "device_unavailable")
        self.assertEqual(res1["query"], "Бумбокс - Люди")
        # Не стверджуємо, що грає!
        self.assertIn("не підключена", res1["error"])

        # Користувач пише «спробуй ще раз», колонка все ще недоступна
        retry_fail = self.ai.chat("спробуй ще раз", session_id=self.sid)
        self.assertIn("Повторна спроба не вдалася", retry_fail)
        self.assertIn("не підключена", retry_fail)

        # 2. Тепер користувач підключив колонку, програвач підтверджує успіх
        self.mock_garage.speaker.is_connected.return_value = True
        self.mock_garage.speaker.play_youtube.return_value = True
        self.mock_garage.speaker.name = "JBL Clip 5"

        retry_ok = self.ai.chat("повтори", session_id=self.sid)
        self.assertIn("Повторна спроба успішна", retry_ok)
        self.assertIn("Бумбокс - Люди", retry_ok)
        self.assertIn("JBL Clip 5", retry_ok)

        # 3. Тепер пісня вже грає. Користувач знову каже «ще раз»
        retry_already_playing = self.ai.chat("ще раз", session_id=self.sid)
        self.assertIn("уже успішно відтворюється", retry_already_playing)
        self.assertIn("Бумбокс - Люди", retry_already_playing)

    def test_safety_boundary_cannot_be_bypassed_via_retry(self):
        """Заблокована фізична дія (ворота) не може бути виконана чи обійдена через 'спробуй ще раз'."""
        # Користувач намагається відчинити ворота (привід відсутній / дія заблокована)
        res_gate = self.dispatcher.execute("control_device", {"device": "door", "action": "open"}, session_id=self.sid)
        self.assertFalse(res_gate["success"])
        self.assertTrue(res_gate.get("is_blocked"))

        # Користувач пише «спробуй ще раз»
        retry_gate = self.ai.chat("спробуй ще раз", session_id=self.sid)
        self.assertIn("заблоковано правилами безпеки", retry_gate)
        self.assertIn("приводом воріт", retry_gate)

    def test_russian_content_hard_taboo_cannot_be_retried(self):
        """Російськомовні треки суворо блокуються і не можуть бути запущені через 'ще раз'."""
        res_ru = self.dispatcher.execute("play_song", {"query": "русский трек"}, session_id=self.sid)
        self.assertFalse(res_ru["success"])
        self.assertTrue(res_ru.get("is_blocked"))
        self.assertEqual(res_ru["status"], "blocked")

        retry_ru = self.ai.chat("спробуй ще раз", session_id=self.sid)
        self.assertIn("заблоковано правилами безпеки", retry_ru)


class TestOpenRouterToolCallCycleAndFormat(unittest.TestCase):
    """Тести валідності циклу повідомлень для актуальних моделей OpenRouter (Gemini, Claude, GPT-4o)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.temp_dir.name) / "test_sessions_or.json"
        self.session_mgr = SessionManager(storage_path=self.storage_file)
        self.ai = AIManager(session_mgr=self.session_mgr)
        self.mock_garage = MagicMock()
        self.mock_garage.speaker.name = "JBL Clip 5"
        self.dispatcher = ToolDispatcher(self.mock_garage)
        self.ai.set_tool_dispatcher(self.dispatcher)
        self.sid = "test_openrouter_cycle_sid"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_multistep_tool_call_valid_cycle(self):
        """Багатокроковий виклик інструментів зберігає валідну структуру OpenRouter без осиротілих повідомлень."""
        # Симулюємо відповідь OpenRouter з 2 викликами інструментів
        tool_calls = [
            {
                "id": "call_light_001",
                "type": "function",
                "function": {
                    "name": "control_device",
                    "arguments": json.dumps({"device": "light", "action": "on"})
                }
            },
            {
                "id": "call_song_002",
                "type": "function",
                "function": {
                    "name": "play_song",
                    "arguments": json.dumps({"query": "ADAM - Сильно Сильно"})
                }
            }
        ]

        self.mock_garage.esp32.light_on.return_value = True
        self.mock_garage.speaker.is_connected.return_value = False  # Пісня не вдалась

        # Виконуємо через буфер
        assistant_tc_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls
        }

        res_light = self.dispatcher.execute("control_device", {"device": "light", "action": "on"}, session_id=self.sid)
        res_song = self.dispatcher.execute("play_song", {"query": "ADAM - Сильно Сильно"}, session_id=self.sid)

        tool_msgs = [
            {
                "role": "tool",
                "tool_call_id": "call_light_001",
                "name": "control_device",
                "content": json.dumps(res_light, ensure_ascii=False)
            },
            {
                "role": "tool",
                "tool_call_id": "call_song_002",
                "name": "play_song",
                "content": json.dumps(res_song, ensure_ascii=False)
            }
        ]

        final_answer = "Освітлення увімкнено. Але колонка JBL не підключена по Bluetooth, пісню не запущено."

        self.ai.conversation_buffer.add_tool_turn(
            session_id=self.sid,
            user_content="увімкни світло і пісню",
            assistant_tool_call_msg=assistant_tc_msg,
            tool_responses=tool_msgs,
            final_assistant_content=final_answer
        )

        messages = self.ai.conversation_buffer.get_messages(self.sid)

        # Перевірка валідатором формату OpenRouter
        is_valid, err = validate_openrouter_messages(messages)
        self.assertTrue(is_valid, f"Помилка формату OpenRouter: {err}")

        # Перевіряємо точний порядок:
        # 1. user
        # 2. assistant з tool_calls
        # 3. tool call_light_001
        # 4. tool call_song_002
        # 5. assistant фінальна відповідь
        self.assertEqual(len(messages), 5)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(len(messages[1]["tool_calls"]), 2)
        self.assertEqual(messages[2]["role"], "tool")
        self.assertEqual(messages[2]["tool_call_id"], "call_light_001")
        self.assertEqual(messages[3]["role"], "tool")
        self.assertEqual(messages[3]["tool_call_id"], "call_song_002")
        self.assertEqual(messages[4]["role"], "assistant")
        self.assertEqual(messages[4]["content"], final_answer)

    def test_validator_catches_invalid_tool_sequences(self):
        """Валідатор ловить відсутні tool відповіді або неправильні tool_call_id."""
        # 1. Повідомлення tool без попереднього assistant.tool_calls
        bad_orphan = [
            {"role": "user", "content": "тест"},
            {"role": "tool", "tool_call_id": "orphan_1", "name": "play_song", "content": "{}"}
        ]
        ok, err = validate_openrouter_messages(bad_orphan)
        self.assertFalse(ok)
        self.assertIn("Осиротіле повідомлення", err)

        # 2. Неспівпадіння id між tool_calls та tool відповідями
        bad_mismatch = [
            {"role": "user", "content": "тест"},
            {
                "role": "assistant",
                "tool_calls": [{"id": "call_A", "type": "function", "function": {"name": "test"}}]
            },
            {"role": "tool", "tool_call_id": "call_WRONG", "name": "test", "content": "{}"}
        ]
        ok, err = validate_openrouter_messages(bad_mismatch)
        self.assertFalse(ok)
        self.assertIn("невідомий tool_call_id", err)


if __name__ == "__main__":
    unittest.main()
