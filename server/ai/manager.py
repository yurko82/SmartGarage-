import os
import json
import logging
import time
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any
import requests
from server.config import config
from interpreter import interpreter

logger = logging.getLogger(__name__)
interpreter.auto_run = True
interpreter.safe_mode = "off"


class ConversationBuffer:
    """Maintains short-term rolling conversation turns for multi-turn AI dialogues."""

    def __init__(self, max_turns: int = 5, ttl_seconds: int = 1800):
        self.max_turns = max_turns
        self.ttl = ttl_seconds
        self._history: Dict[str, List[Dict[str, str]]] = {}
        self._last_active: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get_messages(self, session_id: str) -> List[Dict[str, str]]:
        with self._lock:
            now = time.time()
            if session_id in self._last_active and (now - self._last_active[session_id] > self.ttl):
                self._history[session_id] = []
            return list(self._history.get(session_id, []))

    def add_user_message(self, session_id: str, content: str):
        with self._lock:
            if session_id not in self._history:
                self._history[session_id] = []
            self._history[session_id].append({"role": "user", "content": content})
            self._last_active[session_id] = time.time()
            self._trim(session_id)

    def add_assistant_message(self, session_id: str, content: str):
        with self._lock:
            if session_id not in self._history:
                self._history[session_id] = []
            self._history[session_id].append({"role": "assistant", "content": content})
            self._last_active[session_id] = time.time()
            self._trim(session_id)

    def clear(self, session_id: str):
        with self._lock:
            self._history[session_id] = []

    def _trim(self, session_id: str):
        limit = self.max_turns * 2
        if len(self._history[session_id]) > limit:
            self._history[session_id] = self._history[session_id][-limit:]


class AIManager:

    def __init__(self):
        self.config = config
        self.llm = self.config.get("llm", {})
        self.conversation_buffer = ConversationBuffer()

        raw_model = self.llm.get("model", "google/gemini-2.5-flash")
        interp_model = raw_model if raw_model.startswith("openrouter/") else f"openrouter/{raw_model}"
        
        interpreter.llm.model = interp_model
        interpreter.llm.api_key = self.llm.get("api_key")
        interpreter.llm.api_base = self.llm.get("api_base", "https://openrouter.ai/api/v1")
        interpreter.llm.temperature = self.llm.get("temperature", 0)

        prompt_file = Path(__file__).parent.parent.parent / "prompts" / "system.md"
        self.system_prompt = ""
        if prompt_file.exists():
            self.system_prompt = prompt_file.read_text(encoding="utf-8")
            interpreter.custom_instructions = self.system_prompt

        from server.ai.tools import GARAGE_TOOLS, ToolDispatcher
        self.tools = GARAGE_TOOLS
        self.tool_dispatcher: Optional[ToolDispatcher] = None

    def set_tool_dispatcher(self, dispatcher):
        self.tool_dispatcher = dispatcher

    def get_system_prompt(self) -> str:
        prompt_file = Path(__file__).parent.parent.parent / "prompts" / "system.md"
        if prompt_file.exists():
            try:
                return prompt_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        return self.system_prompt or "Ти розумний помічник Smart Garage. Твій власник Юрій. Відповідай коротко українською мовою."

    def info(self):
        llm = self.config.get("llm", {})
        print("========== AI ==========")
        print("Provider :", llm.get("provider"))
        print("Model    :", llm.get("model"))
        print("========================")

    def _chat_local_ollama(self, prompt: str, context_info: str = "", session_id: str = "default") -> Optional[str]:
        """Local offline LLM completion via Ollama with Function Calling and structured Ukrainian prompt."""
        local_cfg = self.config.get("local_llm", {})
        if not local_cfg.get("enabled", True):
            return None

        ollama_base = local_cfg.get("api_base", "http://localhost:11434").rstrip("/")
        ollama_model = local_cfg.get("model", "qwen2.5-coder:1.5b")

        sys_msg = (
            "Ти асистент Smart Garage. Твій власник Юрій. Відповідай коротко українською мовою.\n"
            "Якщо потрібно керувати обладнанням гаража, виведи ТІЛЬКИ JSON за такою схемою:\n"
            "{\"action\": \"control_device\", \"parameters\": {\"device\": \"door|light|fan\", \"action\": \"open|close|on|off\"}}\n"
            "{\"action\": \"get_climate_history\", \"parameters\": {\"floor\": \"basement|floor2\", \"hours\": 24}}\n"
            "{\"action\": \"play_media\", \"parameters\": {\"query\": \"назва пісні/відео\"}}\n"
            "{\"action\": \"stop_media\", \"parameters\": {}}\n"
            "{\"action\": \"play_radio\", \"parameters\": {\"station\": \"Hit FM|Radio ROKS|Kiss FM|Lounge FM|Байрактар|Люкс FM\"}}\n"
            "{\"action\": \"stop_radio\", \"parameters\": {}}\n"
            "{\"action\": \"run_scenario\", \"parameters\": {\"scenario\": \"arrival|departure|night|cinema|safety\"}}\n"
            "Приклади:\n"
            "Користувач: відчини ворота -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"door\", \"action\": \"open\"}}\n"
            "Користувач: зачини ворота -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"door\", \"action\": \"close\"}}\n"
            "Користувач: увімкни світло -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"light\", \"action\": \"on\"}}\n"
            "Користувач: вимкни світло -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"light\", \"action\": \"off\"}}\n"
            "Користувач: увімкни витяжку -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"fan\", \"action\": \"on\"}}\n"
            "Користувач: вимкни вентиляцію -> {\"action\": \"control_device\", \"parameters\": {\"device\": \"fan\", \"action\": \"off\"}}\n"
            "Користувач: включи радіо хіт фм -> {\"action\": \"play_radio\", \"parameters\": {\"station\": \"Hit FM\"}}\n"
            "Користувач: вкючи радіо хіт фм -> {\"action\": \"play_radio\", \"parameters\": {\"station\": \"Hit FM\"}}\n"
            "Користувач: вимкни радіо -> {\"action\": \"stop_radio\", \"parameters\": {}}\n"
            "Користувач: яка вологість у підвалі -> {\"action\": \"get_climate_history\", \"parameters\": {\"floor\": \"basement\", \"hours\": 24}}\n"
            "Користувач: привіт -> Привіт, Юрію! Чим можу допомогти?\n"
        )
        if context_info:
            sys_msg += f"\nПОТОЧНИЙ СТАН СИСТЕМИ:\n{context_info}\n"

        payload = {
            "model": ollama_model,
            "system": sys_msg,
            "prompt": f"Юрій: {prompt}",
            "stream": False,
            "options": {
                "temperature": 0.1,
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
                            msg = exec_res.get("message") or exec_res.get("error") or "Команду виконано."
                            self.conversation_buffer.add_user_message(session_id, prompt)
                            self.conversation_buffer.add_assistant_message(session_id, msg)
                            return f"[Локальний ШІ] {msg}"
                    except Exception as ej:
                        logger.debug(f"JSON parsing failed for local ollama output: {ej}")

                if raw_answer:
                    self.conversation_buffer.add_user_message(session_id, prompt)
                    self.conversation_buffer.add_assistant_message(session_id, raw_answer)
                    return f"[Локальний ШІ] {raw_answer}"
        except Exception as eo:
            logger.debug(f"Local Ollama generation failed: {eo}")
        return None

    def chat(self, prompt, context_info: str = "", session_id: str = "default"):
        """Fast direct chat completion via OpenRouter API (< 1s) with Function Calling & conversation buffer."""
        # Check if user wants to reset dialogue context
        clean_p = prompt.strip().lower()
        if clean_p in ("очисти контекст", "скинь контекст", "очисти діалог", "скинь діалог", "новий діалог", "clear context"):
            self.conversation_buffer.clear(session_id)
            return "Історію діалогу очищено."

        # 1. High-speed direct completion with Tool Calling
        api_key = (self.llm.get("api_key") or os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
        api_base = self.llm.get("api_base", "https://openrouter.ai/api/v1")
        clean_model = self.llm.get("model", "google/gemini-2.5-flash").replace("openrouter/", "")

        if not api_key:
            local_res = self._chat_local_ollama(prompt, context_info, session_id)
            if local_res:
                return local_res
            if context_info and any(w in clean_p for w in ("стан", "гараж", "світло", "ворот", "клімат", "температур", "датчик", "присутн", "хто", "де", "музик", "проектор")):
                return f"📋 Поточний стан системи:\n{context_info}\n\n💡 Підказка: для вільного діалогу з AI підключіть OPENROUTER_API_KEY у файлі .env або config/config.yaml."
            return (
                "⚠️ AI-асистент наразі не налаштований: відсутній ключ OPENROUTER_API_KEY у конфігурації.\n"
                "Будь ласка, вкажіть ваш ключ у файлі .env або config/config.yaml.\n"
                "Всі локальні команди (ворота, світло, вентиляція, клімат на поверхах, радіо) працюють у штатному режимі."
            )

        if api_key:
            try:
                sys_msg = self.get_system_prompt()
                if context_info:
                    sys_msg += f"\n\n### ПОТОЧНИЙ СТАН СИСТЕМИ (State Snapshot):\n{context_info}\n"

                messages = [{"role": "system", "content": sys_msg}]

                # Include past turns for this session
                past_turns = self.conversation_buffer.get_messages(session_id)
                messages.extend(past_turns)

                # Current user prompt
                messages.append({"role": "user", "content": prompt})

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": clean_model,
                    "messages": messages,
                    "temperature": self.llm.get("temperature", 0),
                    "max_tokens": 400
                }

                if self.tool_dispatcher and self.tools:
                    payload["tools"] = self.tools
                    payload["tool_choice"] = "auto"

                resp = requests.post(f"{api_base.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        tool_calls = msg.get("tool_calls")
                        if tool_calls:
                            # 1. Execute tools
                            tool_summaries = []
                            messages.append(msg)
                            for tc in tool_calls:
                                fn = tc.get("function", {})
                                fn_name = fn.get("name")
                                try:
                                    fn_args = json.loads(fn.get("arguments", "{}"))
                                except Exception:
                                    fn_args = {}

                                result = self.tool_dispatcher.execute(fn_name, fn_args, session_id=session_id)
                                tool_summaries.append(result.get("message") or result.get("error") or str(result))
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.get("id"),
                                    "name": fn_name,
                                    "content": json.dumps(result, ensure_ascii=False)
                                })

                            # 2. Natural language confirmation from LLM
                            final_answer = None
                            try:
                                followup_payload = {
                                    "model": clean_model,
                                    "messages": messages,
                                    "temperature": self.llm.get("temperature", 0),
                                    "max_tokens": 250
                                }
                                followup_resp = requests.post(f"{api_base.rstrip('/')}/chat/completions", headers=headers, json=followup_payload, timeout=6)
                                if followup_resp.status_code == 200:
                                    f_data = followup_resp.json()
                                    f_choices = f_data.get("choices", [])
                                    if f_choices:
                                        f_content = f_choices[0].get("message", {}).get("content", "").strip()
                                        if f_content:
                                            final_answer = f_content
                            except Exception as ef:
                                logger.debug(f"Follow-up tool completion failed: {ef}")

                            if not final_answer:
                                final_answer = "\n".join(tool_summaries)

                            self.conversation_buffer.add_user_message(session_id, prompt)
                            self.conversation_buffer.add_assistant_message(session_id, final_answer)
                            return final_answer

                        content = msg.get("content", "").strip()
                        if content:
                            self.conversation_buffer.add_user_message(session_id, prompt)
                            self.conversation_buffer.add_assistant_message(session_id, content)
                            return content
            except Exception as e:
                logger.warning(f"Fast OpenRouter direct completion failed: {e}. Falling back to local Ollama.")
                local_res = self._chat_local_ollama(prompt, context_info, session_id)
                if local_res:
                    return local_res
                logger.warning("Local Ollama fallback unavailable. Falling back to OpenInterpreter.")

        # 2. Fallback to OpenInterpreter
        try:
            interpreter.llm.api_key = api_key
            messages = interpreter.chat(prompt, display=False)
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
        except Exception as e:
            err_msg = str(e)
            if "401" in err_msg or "AuthenticationError" in err_msg or "No cookie auth" in err_msg or "Clerk" in err_msg:
                return "⚠️ Помилка авторизації AI: перевірте валідність ключа OPENROUTER_API_KEY у конфігурації."
            if "Name or service not known" in err_msg or "ConnectionError" in err_msg or "Errno -2" in err_msg:
                return "⚠️ Тимчасова помилка зв'язку з сервером AI (перевірте інтернет-з'єднання сервера)."
            if "timeout" in err_msg.lower():
                return "⚠️ Час очікування відповіді від AI вичерпано. Спробуйте ще раз."
            return f"⚠️ Помилка AI під час обробки запиту: {err_msg[:120]}"

