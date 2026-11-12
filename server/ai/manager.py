import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from server.ai.openrouter_client import (
    OpenRouterAuthError,
    OpenRouterBudgetExceededError,
    OpenRouterClient,
    OpenRouterError,
    OpenRouterPrivacyError,
    OpenRouterRateLimitError,
    OpenRouterServerError,
    OpenRouterTimeoutError,
    openrouter_client,
    sanitize_context_snapshot,
)
from server.ai.session_manager import (
    PendingAction,
    SessionManager,
    is_retry_intent,
    session_manager,
    validate_openrouter_messages,
)
from server.config import config

logger = logging.getLogger(__name__)

# OpenInterpreter is disabled by default in production to prevent arbitrary code execution
ENABLE_OPEN_INTERPRETER = os.getenv("ENABLE_OPEN_INTERPRETER", "").lower() in ("true", "1", "yes")


class ConversationBuffer:
    """Maintains short-term rolling conversation turns for multi-turn AI dialogues with session isolation & persistence."""

    def __init__(self, max_turns: int = 5, ttl_seconds: int = 1800, session_mgr: SessionManager | None = None):
        self.max_turns = max_turns
        self.ttl = ttl_seconds
        self.session_manager = session_mgr or session_manager
        self._lock = threading.Lock()

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        sc = self.session_manager.get_or_create_session(session_id)
        return sc.get_messages(max_turns=self.max_turns)

    def add_user_message(self, session_id: str, content: str):
        sc = self.session_manager.get_or_create_session(session_id)
        if sc.turns and not sc.turns[-1].assistant_message:
            sc.turns[-1].user_message = {"role": "user", "content": content}
        else:
            sc.add_simple_turn(user_content=content, assistant_content="")
        self.session_manager.save_to_disk()

    def add_assistant_message(self, session_id: str, content: str):
        sc = self.session_manager.get_or_create_session(session_id)
        if sc.turns and not sc.turns[-1].assistant_message.get("content"):
            sc.turns[-1].assistant_message = {"role": "assistant", "content": content}
        else:
            sc.add_simple_turn(user_content="", assistant_content=content)
        self.session_manager.save_to_disk()

    def add_simple_turn(self, session_id: str, user_content: str, assistant_content: str):
        sc = self.session_manager.get_or_create_session(session_id)
        sc.add_simple_turn(user_content, assistant_content)
        self.session_manager.save_to_disk()

    def add_tool_turn(
        self,
        session_id: str,
        user_content: str,
        assistant_tool_call_msg: dict[str, Any],
        tool_responses: list[dict[str, Any]],
        final_assistant_content: str
    ):
        sc = self.session_manager.get_or_create_session(session_id)
        sc.add_tool_turn(
            user_content=user_content,
            assistant_tool_call_msg=assistant_tool_call_msg,
            tool_responses=tool_responses,
            final_assistant_content=final_assistant_content
        )
        self.session_manager.save_to_disk()

    def clear(self, session_id: str):
        self.session_manager.clear_session(session_id)


class AIManager:

    def __init__(self, session_mgr: SessionManager | None = None, openrouter_cli: OpenRouterClient | None = None):
        self.config = config
        self.llm = self.config.get("llm", {})
        self.session_manager = session_mgr or session_manager
        self.conversation_buffer = ConversationBuffer(session_mgr=self.session_manager)
        self.openrouter_client = openrouter_cli or openrouter_client

        raw_model = self.llm.get("model", "google/gemini-2.5-flash")
        interp_model = raw_model if raw_model.startswith("openrouter/") else f"openrouter/{raw_model}"

        prompt_file = Path(__file__).parent.parent.parent / "prompts" / "system.md"
        self.system_prompt = ""
        if prompt_file.exists():
            self.system_prompt = prompt_file.read_text(encoding="utf-8")

        if ENABLE_OPEN_INTERPRETER:
            try:
                from interpreter import interpreter
                interpreter.auto_run = False
                interpreter.safe_mode = "ask"
                interpreter.llm.model = interp_model
                interpreter.llm.api_key = self.llm.get("api_key")
                interpreter.llm.api_base = self.llm.get("api_base", "https://openrouter.ai/api/v1")
                interpreter.llm.temperature = self.llm.get("temperature", 0)
                if self.system_prompt:
                    interpreter.custom_instructions = self.system_prompt
            except ImportError:
                logger.debug("OpenInterpreter package not installed.")

        from server.ai.tools import GARAGE_TOOLS, ToolDispatcher
        self.tools = GARAGE_TOOLS
        self.tool_dispatcher: ToolDispatcher | None = None

    def set_tool_dispatcher(self, dispatcher):
        self.tool_dispatcher = dispatcher
        if dispatcher and hasattr(self, "session_manager"):
            dispatcher.session_manager = self.session_manager

    def get_system_prompt(self) -> str:
        prompt_file = Path(__file__).parent.parent.parent / "prompts" / "system.md"
        base_prompt = ""
        if prompt_file.exists():
            try:
                base_prompt = prompt_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        if not base_prompt:
            base_prompt = self.system_prompt or "Ти розумний помічник Smart Garage. Твій власник Юрій. Відповідай коротко українською мовою."

        try:
            from server.memory.user_profile import user_profile_manager
            profile_summary = user_profile_manager.get_summary_prompt()
            if profile_summary:
                base_prompt += f"\n\n{profile_summary}\n"
        except Exception as ep:
            logger.debug(f"Не вдалося завантажити профіль веломайстерні в системний промпт: {ep}")

        return base_prompt

    def info(self):
        llm = self.config.get("llm", {})
        print("========== AI ==========")
        print("Provider :", llm.get("provider"))
        print("Model    :", llm.get("model"))
        print("========================")

    def _chat_local_ollama(self, prompt: str, context_info: str = "", session_id: str = "default") -> str | None:
        """Local offline LLM completion via Ollama with Function Calling and structured Ukrainian prompt."""
        local_cfg = self.config.get("local_llm", {})
        if not local_cfg.get("enabled", True):
            return None

        ollama_base = local_cfg.get("api_base", "http://localhost:11434").rstrip("/")
        ollama_model = local_cfg.get("model", "qwen2.5-coder:1.5b")

        sys_msg = (
            "Ти асистент Smart Garage. Твій власник Юрій. Відповідай коротко українською мовою.\n"
            "Якщо потрібно керувати обладнанням гаража, виведи ТІЛЬКИ JSON за такою схемою:\n"
            "{\"action\": \"control_device\", \"parameters\": {\"device\": \"light|fan\", \"action\": \"on|off\"}}\n"
            "{\"action\": \"get_climate_history\", \"parameters\": {\"floor\": \"basement|floor2\", \"hours\": 24}}\n"
            "{\"action\": \"play_media\", \"parameters\": {\"query\": \"назва пісні/відео\"}}\n"
            "{\"action\": \"stop_media\", \"parameters\": {}}\n"
            "{\"action\": \"play_radio\", \"parameters\": {\"station\": \"Hit FM|Radio ROKS|Kiss FM|Lounge FM|Байрактар|Люкс FM\"}}\n"
            "{\"action\": \"stop_radio\", \"parameters\": {}}\n"
            "{\"action\": \"run_scenario\", \"parameters\": {\"scenario\": \"arrival|departure|night|cinema\"}}\n"
            "Якщо користувач запитує з 'чому' (наприклад: 'чому не грає радіо', 'чому не грає хіт фм', 'чому мовчить колонка'):\n"
            "Уважно проаналізуй ПОТОЧНИЙ СТАН СИСТЕМИ та поясни причину коротко українською мовою:\n"
            "- Якщо радіо насправді транслюється на якусь колонку (наприклад, 1-й поверх), поясни, що воно грає на тій колонці, а колонка в гаражі, можливо, відключена, або слід перевірити гучність.\n"
            "- Якщо колонка відключена або офлайн, зазнач це.\n"
            "- Якщо радіо зупинено або вимкнено, повідом, що воно зараз вимкнено, і запропонуй увімкнути.\n"
            "Приклади:\n"
            "Користувач: відчини ворота -> Керування воротами вимкнено: привід воріт не встановлений.\n"
            "Користувач: зачини ворота -> Керування воротами вимкнено: привід воріт не встановлений.\n"
            "Користувач: увімкни світло -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"light\", \"action\": \"on\"}}\n"
            "Користувач: вимкни світло -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"light\", \"action\": \"off\"}}\n"
            "Користувач: увімкни витяжку -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"fan\", \"action\": \"on\"}}\n"
            "Користувач: вимкни вентиляцію -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"fan\", \"action\": \"off\"}}\n"
            "Користувач: включи радіо хіт фм -> {\"action\": \"play_radio\", \"parameters\": {\"station\": \"Hit FM\"}}\n"
            "Користувач: вкючи радіо хіт фм -> {\"action\": \"play_radio\", \"parameters\": {\"station\": \"Hit FM\"}}\n"
            "Користувач: вимкни радіо -> {\"action\": \"stop_radio\", \"parameters\": {}}\n"
            "Користувач: яка вологість у підвалі -> {\"action\": \"get_climate_history\", \"parameters\": {\"floor\": \"basement\", \"hours\": 24}}\n"
            "Користувач: альо гараж -> Що тобі потрібно?\n"
            "Користувач: ало гараж -> Що тобі потрібно?\n"
            "Користувач: привіт -> Привіт, Юрію! Чим можу допомогти?\n"
            "Користувач: чому не грає хіт фм -> Хіт FM транслюється на колонку 1-го поверху. Колонка в гаражі зараз відключена.\n"
            "Користувач: чому не грає хід фм -> Хіт FM грає на колонці 1-го поверху. Перевірте гучність або увімкніть колонку в гаражі.\n"
            "Користувач: чому не грає радіо -> Радіо наразі вимкнено. Скажіть «увімкни Хіт FM», щоб запустити.\n"
            "Користувач: чому колонка мовчить -> Активна колонка відключена по Bluetooth або звук вимкнено.\n"
        )
        if context_info:
            sys_msg += f"\nПОТОЧНИЙ СТАН СИСТЕМИ:\n{context_info}\n"

        payload = {
            "model": ollama_model,
            "system": sys_msg,
            "prompt": f"Юрій: {prompt}",
            "stream": False,
            "options": {
                "temperature": 0.85,
                "num_ctx": 2048
            }
        }

        try:
            resp = requests.post(f"{ollama_base}/api/generate", json=payload, timeout=6)
            if resp.status_code == 200:
                raw_answer = resp.json().get("response", "").strip()
                clean_json = raw_answer
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()

                if "{" in clean_json and "}" in clean_json:
                    start_idx = clean_json.find("{")
                    end_idx = clean_json.rfind("}") + 1
                    json_str = clean_json[start_idx:end_idx]
                    try:
                        tool_call = json.loads(json_str)
                        action_name = tool_call.get("action") or tool_call.get("name")
                        params = tool_call.get("parameters") or tool_call.get("arguments") or {}
                        if action_name and self.tool_dispatcher:
                            exec_res = self.tool_dispatcher.execute(action_name, params, session_id=session_id)
                            self.session_manager.record_tool_action(session_id, action_name, params, exec_res, initial_query=prompt)
                            if exec_res.get("success"):
                                msg = exec_res.get("message") or "Команду виконано."
                            else:
                                msg = exec_res.get("error") or "Не вдалося виконати команду."

                            fake_id = f"ollama_{uuid.uuid4().hex[:8]}"
                            tc_msg = {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{
                                    "id": fake_id,
                                    "type": "function",
                                    "function": {"name": action_name, "arguments": json.dumps(params, ensure_ascii=False)}
                                }]
                            }
                            t_msg = {
                                "role": "tool",
                                "tool_call_id": fake_id,
                                "name": action_name,
                                "content": json.dumps(exec_res, ensure_ascii=False)
                            }
                            self.conversation_buffer.add_tool_turn(
                                session_id=session_id,
                                user_content=prompt,
                                assistant_tool_call_msg=tc_msg,
                                tool_responses=[t_msg],
                                final_assistant_content=f"[Локальний ШІ] {msg}"
                            )
                            return f"[Локальний ШІ] {msg}"
                    except Exception as ej:
                        logger.debug(f"JSON parsing failed for local ollama output: {ej}")

                if raw_answer:
                    self.conversation_buffer.add_simple_turn(session_id, prompt, f"[Локальний ШІ] {raw_answer}")
                    return f"[Локальний ШІ] {raw_answer}"
        except Exception as eo:
            logger.debug(f"Local Ollama generation failed: {eo}")
        return None

    def handle_retry_followup(self, session_id: str, prompt: str = "спробуй ще раз") -> str:
        """Обробляє намір повторення останньої дії для конкретної сесії."""
        pending = self.session_manager.get_pending_action(session_id)
        if not pending:
            return "Немає попередньої дії для повторення в цій сесії. Уточніть, будь ласка, яку команду або дію треба виконати."

        # 1. Межі безпеки: відхилені/заблоковані дії не можна обійти через «ще раз»
        if pending.is_blocked:
            return "🚫 Цю дію заблоковано правилами безпеки гаража і її не можна повторити (керування приводом воріт відсутнє / дія заборонена)."

        # 2. Якщо дія вже успішна: не повторювати побічну дію сліпо!
        if pending.success:
            if pending.tool_name == "play_song":
                q = pending.arguments.get("query", "музика")
                spk = pending.arguments.get("speaker") or "Bluetooth-колонці"
                return f"Пісня '{q}' уже успішно відтворюється на {spk}. Що саме ви хочете повторити чи змінити?"
            elif pending.tool_name == "play_radio":
                st = pending.arguments.get("station", "радіо")
                return f"Радіостанція '{st}' уже успішно транслюється. Що саме ви бажаєте змінити?"
            elif pending.tool_name == "control_device":
                dev = pending.arguments.get("device", "пристрій")
                act = pending.arguments.get("action", "стан")
                return f"Попередня команда ({dev}: {act}) уже була успішно виконана. Що саме потрібно повторити?"
            desc = pending.message or "попередня команда"
            return f"Попередня дія ({desc}) уже була успішно виконана. Уточніть, будь ласка, що саме треба повторити."

        # 3. Невдала / незавершена дія: виконуємо контрольований повтор
        tool_name = pending.tool_name
        tool_args = dict(pending.arguments)

        if not self.tool_dispatcher:
            return "⚠️ Виконавчий модуль інструментів недоступний для повторення дії."

        res = self.tool_dispatcher.execute(tool_name, tool_args, session_id=session_id)
        success = bool(res.get("success", False))
        pending.success = success
        pending.status = res.get("status", "playback_started" if success else "failed")
        pending.message = res.get("message")
        pending.error = res.get("error")
        pending.retry_count += 1
        pending.timestamp = time.time()
        self.session_manager.set_pending_action(session_id, pending)

        if success:
            final_reply = f"Повторна спроба успішна: {res.get('message')}"
        else:
            final_reply = f"Повторна спроба не вдалася: {res.get('error') or 'помилка виконання'}"

        tool_call_id = f"retry_{uuid.uuid4().hex[:8]}"
        assistant_tc = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(tool_args, ensure_ascii=False)
                }
            }]
        }
        tool_msg = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": json.dumps(res, ensure_ascii=False)
        }
        self.conversation_buffer.add_tool_turn(
            session_id=session_id,
            user_content=prompt,
            assistant_tool_call_msg=assistant_tc,
            tool_responses=[tool_msg],
            final_assistant_content=final_reply
        )

        return final_reply

    def chat(self, prompt, context_info: str = "", session_id: str = "default"):
        """Fast direct chat completion via OpenRouter API (< 1s) with Function Calling & conversation buffer."""
        # Check if user wants to reset dialogue context
        clean_p = prompt.strip().lower()
        if clean_p in ("очисти контекст", "скинь контекст", "очисти діалог", "скинь діалог", "новий діалог", "clear context"):
            self.conversation_buffer.clear(session_id)
            return "Історію діалогу очищено."

        # Follow-up retry handling
        if is_retry_intent(prompt):
            return self.handle_retry_followup(session_id=session_id, prompt=prompt)

        # 1. High-speed direct completion with Tool Calling via OpenRouter
        if not self.openrouter_client.has_api_key():
            clean_context = sanitize_context_snapshot(context_info)
            local_res = self._chat_local_ollama(prompt, clean_context, session_id)
            if local_res:
                return local_res
            if context_info and any(w in clean_p for w in ("стан", "гараж", "світло", "ворот", "клімат", "температур", "датчик", "присутн", "хто", "де", "музик", "проектор", "радіо", "колонк", "звук", "мовчить", "грає", "хіт", "hit")):
                return f"📋 Поточний стан системи:\n{clean_context}\n\n💡 Підказка: для вільного діалогу з AI підключіть OPENROUTER_API_KEY у файлі .env або config/config.yaml."
            return (
                "⚠️ AI-асистент наразі не налаштований: відсутній ключ OPENROUTER_API_KEY у конфігурації.\n"
                "Будь ласка, вкажіть ваш ключ у файлі .env або config/config.yaml.\n"
                "Всі локальні команди (світло, вентиляція, клімат на поверхах, радіо) працюють у штатному режимі (привід воріт не встановлений)."
            )

        try:
            sys_msg = self.get_system_prompt()
            clean_context = sanitize_context_snapshot(context_info)
            if clean_context:
                sys_msg += f"\n\n### ПОТОЧНИЙ СТАН СИСТЕМИ (State Snapshot):\n{clean_context}\n"

            messages = [{"role": "system", "content": sys_msg}]

            # Include past turns for this session
            past_turns = self.conversation_buffer.get_messages(session_id)
            messages.extend(past_turns)

            # Current user prompt with untrusted framing
            user_content = prompt
            messages.append({"role": "user", "content": user_content})

            MAX_TOOL_ROUNDS = 3
            tools_param = self.tools if (self.tool_dispatcher and self.tools) else None
            first_assistant_tc_msg = None
            all_tool_responses = []
            final_answer = None

            for round_idx in range(MAX_TOOL_ROUNDS):
                # Validate message sequence before sending to OpenRouter
                val_ok, val_err = validate_openrouter_messages(messages)
                if not val_ok:
                    logger.warning(f"OpenRouter message sequence validation warning: {val_err}")
                    break

                allow_tools = tools_param if (round_idx < MAX_TOOL_ROUNDS - 1) else None
                data = self.openrouter_client.send_chat_completion(
                    messages,
                    tools=allow_tools,
                    tool_choice="auto" if allow_tools else None
                )

                choices = data.get("choices", [])
                if not choices:
                    break

                msg = choices[0].get("message", {})
                tool_calls = msg.get("tool_calls")

                if tool_calls and allow_tools:
                    assistant_tc_msg = {
                        "role": "assistant",
                        "content": msg.get("content") or None,
                        "tool_calls": tool_calls
                    }
                    if first_assistant_tc_msg is None:
                        first_assistant_tc_msg = assistant_tc_msg
                    messages.append(assistant_tc_msg)

                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name")
                        tc_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"

                        raw_args = fn.get("arguments", "{}")
                        try:
                            fn_args = json.loads(raw_args)
                            if not isinstance(fn_args, dict):
                                raise ValueError("аргументи мають бути передані як JSON-об'єкт")
                            result = self.tool_dispatcher.execute(fn_name, fn_args, session_id=session_id)
                        except Exception as e_parse:
                            result = {
                                "success": False,
                                "error": f"Помилка валідації аргументів інструменту '{fn_name}': {e_parse}"
                            }

                        t_msg = {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": fn_name,
                            "content": json.dumps(result, ensure_ascii=False)
                        }
                        messages.append(t_msg)
                        all_tool_responses.append(t_msg)
                    # Next round for natural language synthesis
                    continue
                else:
                    raw_content = msg.get("content")
                    content = (raw_content or "").strip() if isinstance(raw_content, str) else ""
                    if content:
                        final_answer = content
                    break

            if first_assistant_tc_msg and all_tool_responses:
                has_error = False
                summaries = []
                for tr in all_tool_responses:
                    try:
                        c = json.loads(tr.get("content", "{}"))
                        if not c.get("success", False):
                            has_error = True
                        summaries.append(c.get("message") or c.get("error") or str(c))
                    except Exception:
                        pass

                if not final_answer:
                    final_answer = "\n".join(summaries) or "Дію виконано."
                elif has_error:
                    clean_final = final_answer.lower()
                    if any(w in clean_final for w in ("команду виконано", "успішно", "грає", "відтворюється")) and not any(e in clean_final for e in ("помилк", "не вдалося", "не підключен", "вимкнен", "недоступн")):
                        final_answer = "\n".join(summaries)

                self.conversation_buffer.add_tool_turn(
                    session_id=session_id,
                    user_content=prompt,
                    assistant_tool_call_msg=first_assistant_tc_msg,
                    tool_responses=all_tool_responses,
                    final_assistant_content=final_answer
                )
                return final_answer

            if final_answer:
                self.conversation_buffer.add_simple_turn(session_id, prompt, final_answer)
                return final_answer

        except OpenRouterError as oe:
            logger.warning(f"OpenRouter client handled error: {oe}")
            clean_context = sanitize_context_snapshot(context_info)
            local_res = self._chat_local_ollama(prompt, clean_context, session_id)
            if local_res:
                return local_res
            return str(oe)

        except Exception as e:
            logger.warning(f"Fast OpenRouter direct completion failed: {e}. Falling back to local Ollama.")
            clean_context = sanitize_context_snapshot(context_info)
            local_res = self._chat_local_ollama(prompt, clean_context, session_id)
            if local_res:
                return local_res
            logger.warning("Local Ollama fallback unavailable.")
            return f"⚠️ Помилка AI під час обробки запиту: {str(e)[:120]}"

        # 2. In production, OpenInterpreter is disabled by default to prevent arbitrary code execution
        if not ENABLE_OPEN_INTERPRETER:
            if context_info:
                return f"📋 Поточний стан системи:\n{context_info}"
            return "Всі системи Smart Garage працюють у штатному режимі (виклик зовнішніх інструментів наразі недоступний)."

        # Fallback to OpenInterpreter in isolated dev mode only
        try:
            from interpreter import interpreter
            interpreter.llm.api_key = getattr(self.openrouter_client, "api_key", None) or os.getenv("OPENROUTER_API_KEY", "")
            result_container = []

            def _run_interpreter():
                try:
                    msgs = interpreter.chat(prompt, display=False)
                    result_container.append(msgs)
                except Exception as ei:
                    result_container.append(ei)

            th = threading.Thread(target=_run_interpreter, daemon=True, name="OpenInterpreterWorker")
            th.start()
            th.join(timeout=5.0)

            if not result_container:
                logger.warning("OpenInterpreter timed out after 5s.")
                if context_info:
                    return f"📋 Поточний стан системи:\n{context_info}"
                return "Готово. Всі системи Smart Garage працюють у штатному режимі."

            messages = result_container[0]
            if isinstance(messages, Exception):
                raise messages

            if not messages:
                return "Немає відповіді від AI."

            if isinstance(messages, str):
                return messages.strip()

            # Extract assistant verbal messages
            text_responses = []
            for msg in messages:
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    if msg.get("type") == "message" and msg.get("content"):
                        text_responses.append(msg["content"].strip())

            if text_responses:
                return "\n".join(text_responses).strip()

            fallback_responses = []
            for msg in messages:
                if isinstance(msg, dict) and msg.get("content"):
                    fallback_responses.append(str(msg["content"]).strip())

            if fallback_responses:
                return "\n".join(fallback_responses).strip()

            return "AI завершив обробку."
        except ImportError:
            logger.info("OpenInterpreter не встановлено, виконання коду недоступне.")
            if context_info:
                return f"📋 Поточний стан системи:\n{context_info}"
            return "Всі системи Smart Garage працюють у штатному режимі."
        except Exception as e:
            err_msg = str(e)
            if "401" in err_msg or "AuthenticationError" in err_msg or "No cookie auth" in err_msg or "Clerk" in err_msg:
                return "⚠️ Помилка авторизації AI: перевірте валідність ключа OPENROUTER_API_KEY у конфігурації."
            if "Name or service not known" in err_msg or "ConnectionError" in err_msg or "Errno -2" in err_msg:
                return "⚠️ Тимчасова помилка зв'язку з сервером AI (перевірте інтернет-з'єднання сервера)."
            if "timeout" in err_msg.lower():
                return "⚠️ Час очікування відповіді від AI вичерпано. Спробуйте ще раз."
            return f"⚠️ Помилка AI під час обробки запиту: {err_msg[:120]}"

