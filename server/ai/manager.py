import json
import logging
from pathlib import Path
import requests
from server.config import config
from interpreter import interpreter

logger = logging.getLogger(__name__)
interpreter.auto_run = True
interpreter.safe_mode = "off"


class AIManager:

    def __init__(self):
        self.config = config
        self.llm = self.config.get("llm", {})

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

    def info(self):
        llm = self.config.get("llm", {})
        print("========== AI ==========")
        print("Provider :", llm.get("provider"))
        print("Model    :", llm.get("model"))
        print("========================")

    def chat(self, prompt, context_info: str = ""):
        """Fast direct chat completion via OpenRouter API (< 1s), falling back to OpenInterpreter."""
        # 1. High-speed direct completion
        api_key = self.llm.get("api_key")
        api_base = self.llm.get("api_base", "https://openrouter.ai/api/v1")
        clean_model = self.llm.get("model", "google/gemini-2.5-flash").replace("openrouter/", "")

        if api_key:
            try:
                sys_msg = self.system_prompt or "Ти розумний помічник Smart Garage. Відповідай коротко українською мовою."
                if context_info:
                    sys_msg += f"\n\nКонтекст системи: {context_info}"

                messages = [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": prompt}
                ]
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": clean_model,
                    "messages": messages,
                    "temperature": self.llm.get("temperature", 0),
                    "max_tokens": 300
                }
                resp = requests.post(f"{api_base.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=7)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "").strip()
                        if content:
                            return content
            except Exception as e:
                logger.warning(f"Fast OpenRouter direct completion failed: {e}. Falling back to OpenInterpreter.")

        # 2. Fallback to OpenInterpreter
        try:
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
            return f"Помилка AI: {str(e)}"

