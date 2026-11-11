"""Контрольований A/B тестовий набір та тести надійності для OpenRouter та моделей AI.
Всі фізичні дії та мережеві виклики моковані.
"""
import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from server.ai.manager import AIManager, ConversationBuffer
from server.ai.openrouter_client import (
    MODEL_PRICING,
    CostTracker,
    OpenRouterAuthError,
    OpenRouterBudgetExceededError,
    OpenRouterClient,
    OpenRouterError,
    OpenRouterPrivacyError,
    OpenRouterRateLimitError,
    OpenRouterServerError,
    OpenRouterTimeoutError,
    sanitize_context_snapshot,
)
from server.ai.session_manager import PendingAction, SessionManager
from server.ai.tools import ToolDispatcher


class TestOpenRouterConfigurationAndSecurity(unittest.TestCase):
    """Тести конфігурованості, безпеки ключів, контролю витрат та приватності."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.usage_file = Path(self.temp_dir.name) / "usage.json"
        self.cost_tracker = CostTracker(storage_path=self.usage_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_api_key_not_stored_in_yaml_or_exposed(self):
        """API-ключ не зберігається у config.yaml і не потрапляє у відкритий вигляд."""
        from server.config import CONFIG_PATH
        content = CONFIG_PATH.read_text(encoding="utf-8")
        # Ключ не повинен бути записаний у YAML
        self.assertNotIn("sk-or-v1-", content)
        import yaml
        cfg = yaml.safe_load(content)
        yaml_key = cfg.get("llm", {}).get("api_key", "")
        self.assertEqual(yaml_key, "", "API ключ не повинен зберігатися у файлі config.yaml!")

    def test_environment_override_config(self):
        """Параметри моделі, таймауту та бюджету конфігуруються через environment."""
        with patch.dict(os.environ, {
            "OPENROUTER_MODEL": "google/gemini-2.5-flash-lite",
            "OPENROUTER_TIMEOUT": "5.5",
            "OPENROUTER_MAX_TOKENS": "350",
            "OPENROUTER_DAILY_BUDGET": "2.50",
            "OPENROUTER_DATA_COLLECTION": "deny"
        }):
            client = OpenRouterClient(api_key="test_key_123")
            self.assertEqual(client.model, "google/gemini-2.5-flash-lite")
            self.assertEqual(client.timeout, 5.5)
            self.assertEqual(client.max_tokens, 350)
            self.assertEqual(client.daily_budget_usd, 2.50)
            self.assertEqual(client.provider_preferences.get("data_collection"), "deny")

    def test_cost_tracking_and_spending_limit(self):
        """Облік використання токенів та спрацювання ліміту витрат (Budget Exceeded)."""
        tracker = self.cost_tracker
        # Записуємо використання
        cost1 = tracker.add_usage("google/gemini-2.5-flash", prompt_tokens=1000, completion_tokens=200)
        self.assertGreater(cost1, 0)

        # Перевіряємо бюджет $0.0005
        low_budget = 0.0005
        self.assertTrue(tracker.is_budget_exceeded(low_budget))

        # Клієнт з низьким бюджетом блокує запит
        client = OpenRouterClient(
            api_key="test_key_123",
            daily_budget_usd=low_budget,
            cost_tracker=tracker
        )
        with self.assertRaises(OpenRouterBudgetExceededError) as ctx:
            client.send_chat_completion([{"role": "user", "content": "тест"}])
        self.assertIn("Досягнуто денного ліміту витрат", str(ctx.exception))

    def test_telemetry_sanitization_removes_ips_macs_and_secrets(self):
        """Функція санітизації контексту видаляє IP, MAC-адреси та паролі."""
        raw_telemetry = (
            "- Проектор HY350MAX (192.168.100.191): онлайн\n"
            "- Колонка JX-BT (00:11:22:33:44:01): підключено\n"
            "- Датчик підвалу (00:11:22:33:44:03): 18.2°C\n"
            "- Конфігурація: secret_token = 'super_secret_token_12345'\n"
            "- Клієнт: ip 10.0.0.15\n"
        )
        sanitized = sanitize_context_snapshot(raw_telemetry)
        # Перевірка відсутності IP
        self.assertNotIn("192.168.100.191", sanitized)
        self.assertNotIn("10.0.0.15", sanitized)
        # Перевірка відсутності MAC
        self.assertNotIn("00:11:22:33:44:01", sanitized)
        self.assertNotIn("00:11:22:33:44:03", sanitized)
        # Перевірка відсутності секрету
        self.assertNotIn("super_secret_token_12345", sanitized)

    def test_privacy_data_collection_rejection_not_silently_lifted(self):
        """Якщо провайдер відхиляє запит через data_collection: deny, обмеження не знімається мовчки."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = json.dumps({"error": {"message": "No available provider matching data_collection requirements"}})
        mock_resp.json.return_value = {"error": {"message": "No available provider matching data_collection requirements"}}

        client = OpenRouterClient(api_key="test_key_123", max_retries=0)
        with patch("requests.post", return_value=mock_resp):
            with self.assertRaises(OpenRouterPrivacyError) as ctx:
                client.send_chat_completion([{"role": "user", "content": "тест"}])
            self.assertIn("data_collection: deny", str(ctx.exception))
            # Переконуємося, що налаштування залишилося суворим
            self.assertEqual(client.provider_preferences.get("data_collection"), "deny")

    def test_rate_limit_and_server_error_retry_backoff(self):
        """При 429 та 5xx клієнт виконує обмежені повторні спроби з backoff."""
        client = OpenRouterClient(
            api_key="test_key_123",
            max_retries=2,
            retry_backoff=0.01  # Швидкий backoff для тестів
        )

        # 1. 429 Rate Limit: спочатку 429, потім 429, потім успіх
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0.01"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "id": "gen_test_success",
            "choices": [{"message": {"role": "assistant", "content": "Успіх після повтору"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10}
        }

        with patch("requests.post", side_effect=[resp_429, resp_429, resp_200]) as mock_post:
            res = client.send_chat_completion([{"role": "user", "content": "тест"}])
            self.assertEqual(mock_post.call_count, 3)
            self.assertIn("choices", res)

        # 2. Якщо 429 триває після вичерпання спроб -> OpenRouterRateLimitError
        with patch("requests.post", return_value=resp_429):
            with self.assertRaises(OpenRouterRateLimitError):
                client.send_chat_completion([{"role": "user", "content": "тест"}])

        # 3. Timeout -> OpenRouterTimeoutError
        with patch("requests.post", side_effect=requests.exceptions.Timeout("timed out")):
            with self.assertRaises(OpenRouterTimeoutError):
                client.send_chat_completion([{"role": "user", "content": "тест"}])

    def test_failure_does_not_execute_unsafe_code(self):
        """Збій OpenRouter не викликає OpenInterpreter чи виконання довільного коду."""
        client = OpenRouterClient(api_key="test_key_123", max_retries=0)
        ai = AIManager(openrouter_cli=client)
        # Локальний Ollama вимкнено для тесту чистого збою
        ai.config["local_llm"] = {"enabled": False}

        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Network down")):
            res = ai.chat("увімкни світло")
            # Повертає зрозуміле українське повідомлення, не запускаючи інтерпретатор
            self.assertIsInstance(res, str)
            self.assertIn("Тимчасова помилка зв'язку", res)

    def test_fallback_model_on_primary_failure(self):
        """Збій основної моделі автоматично перемикає запит на резервну модель (fallback_model)."""
        client = OpenRouterClient(
            api_key="test_key_123",
            model="google/gemini-2.5-flash",
            max_retries=0
        )
        client.fallback_model = "openai/gpt-4o-mini"

        resp_500 = MagicMock()
        resp_500.status_code = 500

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "id": "gen_fallback_success",
            "choices": [{"message": {"role": "assistant", "content": "Успішна відповідь резервної моделі"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 15}
        }

        with patch("requests.post", side_effect=[resp_500, resp_200]) as mock_post:
            res = client.send_chat_completion([{"role": "user", "content": "тест"}])
            self.assertEqual(mock_post.call_count, 2)
            first_call_body = mock_post.call_args_list[0][1]["json"]
            second_call_body = mock_post.call_args_list[1][1]["json"]
            self.assertEqual(first_call_body["model"], "google/gemini-2.5-flash")
            self.assertEqual(second_call_body["model"], "openai/gpt-4o-mini")
            self.assertEqual(res["choices"][0]["message"]["content"], "Успішна відповідь резервної моделі")


class TestABEvaluationSuite(unittest.TestCase):
    """Контрольований A/B набір тестів для 8 обов'язкових сценаріїв українських команд."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.temp_dir.name) / "test_ab_sessions.json"
        self.session_mgr = SessionManager(storage_path=self.storage_file)

        self.mock_client = MagicMock(spec=OpenRouterClient)
        self.mock_client.has_api_key.return_value = True

        self.ai = AIManager(session_mgr=self.session_mgr, openrouter_cli=self.mock_client)
        self.mock_garage = MagicMock()
        self.mock_garage.speaker.name = "JBL Clip 5"
        self.dispatcher = ToolDispatcher(self.mock_garage, session_mgr=self.session_mgr)
        self.ai.set_tool_dispatcher(self.dispatcher)
        self.sid = "ab_test_session_ua"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scenario_1_normal_dialogue(self):
        """Сценарій 1: Звичайний діалог без виклику фізичних дій."""
        self.mock_client.send_chat_completion.return_value = {
            "id": "gen_dialogue_1",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Привіт, Юрію! Я розумний асистент Smart Garage. Допомагаю керувати освітленням, вентиляцією, кліматом та музикою."
                }
            }],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}
        }

        reply = self.ai.chat("Привіт! Хто ти і що вмієш робити в гаражі?", session_id=self.sid)
        self.assertIn("Smart Garage", reply)
        self.assertIn("освітленням", reply)
        # Фізичні пристрої не викликалися
        self.mock_garage.esp32.light_on.assert_not_called()

    def test_scenario_2_music_search_and_playback(self):
        """Сценарій 2: Музичний пошук та відтворення через tool call play_song."""
        self.mock_garage.speaker.is_connected.return_value = True
        self.mock_garage.speaker.play_youtube.return_value = True

        # Модель викликає tool play_song
        self.mock_client.send_chat_completion.side_effect = [
            {
                "id": "gen_music_tc",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_music_123",
                            "type": "function",
                            "function": {
                                "name": "play_song",
                                "arguments": json.dumps({"query": "Океан Ельзи - Обійми"})
                            }
                        }]
                    }
                }],
                "usage": {"prompt_tokens": 150, "completion_tokens": 25}
            },
            # Підтвердження після виконання tool
            {
                "id": "gen_music_confirm",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Вмикаю пісню «Океан Ельзи - Обійми» на колонці JBL Clip 5."
                    }
                }],
                "usage": {"prompt_tokens": 200, "completion_tokens": 20}
            }
        ]

        reply = self.ai.chat("Увімкни пісню Океан Ельзи - Обійми", session_id=self.sid)
        self.assertIn("Океан Ельзи", reply)
        self.mock_garage.speaker.play_youtube.assert_called_once_with("Океан Ельзи - Обійми")

    def test_scenario_3_follow_up_retry(self):
        """Сценарій 3: Follow-up 'спробуй ще раз' після невдалої спроби."""
        # 1. Спроба, коли колонка вимкнена
        self.mock_garage.speaker.is_connected.return_value = False
        res1 = self.dispatcher.execute("play_song", {"query": "Скрябін - Спи собі сама"}, session_id=self.sid)
        self.assertFalse(res1["success"])

        # 2. Колонка ввімкнулась, користувач каже «спробуй ще раз»
        self.mock_garage.speaker.is_connected.return_value = True
        self.mock_garage.speaker.play_youtube.return_value = True

        reply = self.ai.chat("спробуй ще раз", session_id=self.sid)
        self.assertIn("Повторна спроба успішна", reply)
        self.assertIn("Скрябін - Спи собі сама", reply)
        self.mock_garage.speaker.play_youtube.assert_called_with("Скрябін - Спи собі сама")

    def test_scenario_4_ambiguous_query_asks_clarification(self):
        """Сценарій 4: Неоднозначний запит ставить уточнення і не виконує дію сліпо."""
        self.mock_client.send_chat_completion.return_value = {
            "id": "gen_clarify",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Уточніть, будь ласка: увімкнути світло, витяжку чи запустити музику?"
                }
            }],
            "usage": {"prompt_tokens": 140, "completion_tokens": 20}
        }

        reply = self.ai.chat("Увімкни щось", session_id=self.sid)
        self.assertIn("Уточніть", reply)
        # Жоден фізичний пристрій не було активовано
        self.mock_garage.esp32.light_on.assert_not_called()
        self.mock_garage.esp32.fan_on.assert_not_called()

    def test_scenario_5_unknown_or_stale_sensor_state_truthfulness(self):
        """Сценарій 5: Невідомий/офлайн стан сенсора повідомляється правдиво без галюцинацій."""
        context = (
            "- Клімат 1-й поверх (Гараж): очікує встановлення фізичного датчика\n"
            "- Клімат Підвал: 18.5°C, вологість 65%\n"
        )
        self.mock_client.send_chat_completion.return_value = {
            "id": "gen_climate_truth",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "На 1-му поверсі датчик температури ще очікує встановлення. У підвалі наразі 18.5°C."
                }
            }],
            "usage": {"prompt_tokens": 160, "completion_tokens": 25}
        }

        reply = self.ai.chat("Яка зараз температура на першому поверсі?", context_info=context, session_id=self.sid)
        self.assertIn("очікує встановлення", reply)

    def test_scenario_6_rejected_forbidden_action(self):
        """Сценарій 6: Відхилена заборонена дія (ворота) не виконується і не обходиться."""
        self.mock_client.send_chat_completion.return_value = {
            "id": "gen_gate_tc",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_gate_reject",
                        "type": "function",
                        "function": {
                            "name": "control_device",
                            "arguments": json.dumps({"device": "door", "action": "open"})
                        }
                    }]
                }
            }],
            "usage": {"prompt_tokens": 140, "completion_tokens": 20}
        }

        reply = self.ai.chat("Відчини ворота гаража", session_id=self.sid)
        self.assertIn("Керування воротами вимкнено", reply)

        # Спроба обійти через «ще раз»
        retry_reply = self.ai.chat("спробуй ще раз", session_id=self.sid)
        self.assertIn("заблоковано правилами безпеки", retry_reply)

    def test_scenario_7_erroneous_tool_result_handled_truthfully(self):
        """Сценарій 7: Помилковий результат інструменту не видається за успіх."""
        self.mock_garage.speaker.is_connected.return_value = False

        self.mock_client.send_chat_completion.side_effect = [
            {
                "id": "gen_err_tc",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_spk_err",
                            "type": "function",
                            "function": {
                                "name": "play_song",
                                "arguments": json.dumps({"query": "ADAM - Танцюй"})
                            }
                        }]
                    }
                }],
                "usage": {"prompt_tokens": 140, "completion_tokens": 20}
            },
            # Модель помилково намагається сказати «Команду виконано»
            {
                "id": "gen_err_confirm",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Команду виконано успішно, трек грає."
                    }
                }],
                "usage": {"prompt_tokens": 180, "completion_tokens": 15}
            }
        ]

        reply = self.ai.chat("Увімкни ADAM - Танцюй", session_id=self.sid)
        # Захист від галюцинацій перехоплює помилкове твердження моделі
        self.assertNotIn("успішно", reply.lower())
        self.assertIn("не підключена", reply.lower())

    def test_scenario_8_timeout_and_rate_limit_handled_gracefully(self):
        """Сценарій 8: Помилки Timeout/429 повертають зрозумілу українську відповідь."""
        # 1. 429 Rate limit
        self.mock_client.send_chat_completion.side_effect = OpenRouterRateLimitError(
            "⚠️ Перевищено ліміт частоти запитів до OpenRouter (Rate Limit / 429)."
        )
        reply_429 = self.ai.chat("яка температура в підвалі?", session_id=self.sid)
        self.assertIn("Rate Limit", reply_429)

        # 2. Timeout
        self.mock_client.send_chat_completion.side_effect = OpenRouterTimeoutError(
            "⚠️ Час очікування відповіді від OpenRouter вичерпано (Timeout)."
        )
        reply_timeout = self.ai.chat("увімкни витяжку", session_id=self.sid)
        self.assertIn("Timeout", reply_timeout)


if __name__ == "__main__":
    unittest.main()
