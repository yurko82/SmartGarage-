QWERTY_TO_UA_MAP = {
    'q': 'й', 'w': 'ц', 'e': 'у', 'r': 'к', 't': 'е', 'y': 'н', 'u': 'г', 'i': 'ш', 'o': 'щ', 'p': 'з', '[': 'х', ']': 'ї',
    'a': 'ф', 's': 'і', 'd': 'в', 'f': 'а', 'g': 'п', 'h': 'р', 'j': 'о', 'k': 'л', 'l': 'д', ';': 'ж', "'": 'є',
    'z': 'я', 'x': 'ч', 'c': 'с', 'v': 'м', 'b': 'и', 'n': 'т', 'm': 'ь', ',': 'б', '.': 'ю', '`': "'",
    'Q': 'Й', 'W': 'Ц', 'E': 'У', 'R': 'К', 'T': 'Е', 'Y': 'Н', 'U': 'Г', 'I': 'Ш', 'O': 'Щ', 'P': 'З', '{': 'Х', '}': 'Ї',
    'A': 'Ф', 'S': 'І', 'D': 'В', 'F': 'А', 'G': 'П', 'H': 'Р', 'J': 'О', 'K': 'Л', 'L': 'Д', ':': 'Ж', '"': 'Є',
    'Z': 'Я', 'X': 'Ч', 'C': 'С', 'V': 'М', 'B': 'И', 'N': 'Т', 'M': 'Ь', '<': 'Б', '>': 'Ю', '~': "'",
}


def convert_qwerty_to_ua(text: str) -> str:
    """Convert accidental English layout keystrokes into Ukrainian Cyrillic."""
    return "".join(QWERTY_TO_UA_MAP.get(ch, ch) for ch in text)


class CommandRouter:

    def __init__(self, commands, ai, context_provider=None):
        self.commands = commands
        self.ai = ai
        self.context_provider = context_provider

    def execute(self, prompt, session_id: str = "default"):
        if prompt is None:
            return ""

        if not isinstance(prompt, str):
            prompt = str(prompt)

        prompt = prompt.strip()
        if not prompt:
            return ""

        # 1. ЖОРСТКЕ ТАБУ НА РОСІЙСЬКУ МОВУ ТА КОНТЕНТ
        import re
        RUSSIAN_CHARS = set("ёъыэЁЪЫЭ")
        RUSSIAN_MARKER_WORDS = {
            "свет", "пожалуйста", "открой", "закрой", "песня", "песню", "песни", "музыка", "музыку",
            "русский", "русская", "русское", "русские", "русскую", "вруби", "выключи", "привет", "спасибо",
            "дверь", "окно", "погода", "температуры", "комната"
        }
        tokens = set(re.findall(r'\b\w+\b', prompt.lower()))
        has_ru_chars = any(ch in RUSSIAN_CHARS for ch in prompt)
        has_ru_words = bool(tokens & RUSSIAN_MARKER_WORDS)
        has_ru_media_request = any(w in prompt.lower() for w in ("російськ", "русск", "по-русски", "російською", "російські")) and any(m in prompt.lower() for m in ("музик", "пісн", "трек", "радіо", "відео", "кліп", "пісню", "увімкни", "включи", "запусти"))

        if has_ru_chars or has_ru_words or has_ru_media_request:
            return "🚫 Російська мова та контент під суворим табу в цій системі. Будь ласка, звертайтесь виключно українською мовою."

        # 2. ШВИДКИЙ ЕКСТРЕНИЙ ШЛЯХ (FAST / EMERGENCY / WAKE PATH < 2ms)
        # Виконується миттєво ЛИШЕ для однозначних коротких команд зупинки, гучності, статусу та пробудження
        converted_prompt = convert_qwerty_to_ua(prompt)
        check_p = prompt.lower().rstrip("?!.,; ")
        check_converted = converted_prompt.lower().rstrip("?!.,; ")

        FAST_EXACT_WORDS = {
            "стоп", "пауза", "замовкни", "тихіше", "голосніше", "тихо",
            "наступний", "попередній", "stop", "pause",
            "стан", "статус", "status",
            "альо гараж", "ало гараж", "алло гараж", "альо, гараж", "ало, гараж", "алло, гараж",
            "гараж", "що тобі потрібно", "що тобі треба", "слухаю", "я слухаю"
        }

        if check_p in FAST_EXACT_WORDS or check_converted in FAST_EXACT_WORDS or re.fullmatch(r'(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?', check_p) or re.fullmatch(r'(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?', check_converted):
            eval_p = prompt if (check_p in FAST_EXACT_WORDS or re.fullmatch(r'(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?', check_p)) else converted_prompt
            try:
                handled, response = self.commands.execute(eval_p, session_id=session_id)
            except TypeError:
                handled, response = self.commands.execute(eval_p)
            if handled:
                if hasattr(self.ai, "conversation_buffer") and response:
                    self.ai.conversation_buffer.add_simple_turn(session_id, eval_p, response)
                return response

        # 3. ВСЕ ІНШЕ — В ШТУЧНИЙ ІНТЕЛЕКТ (AI-FIRST NLU)
        # ШІ обробляє запити людською мовою, розуміє контекст, час доби, таймери і викликає відповідні інструменти (Function Calling)
        prompt_for_ai = prompt
        clean_ai = re.sub(
            r'^(?:(?:(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?|гараж)|(?:що\s*(?:тобі|вам)?\s*(?:потрібно|треба)|слухаю|я\s*слухаю))\s*[,:;!?-]*\s*',
            '',
            prompt_for_ai,
            flags=re.IGNORECASE
        ).strip()
        if clean_ai:
            prompt_for_ai = clean_ai

        context_info = ""
        if callable(self.context_provider):
            try:
                context_info = self.context_provider()
            except Exception:
                context_info = ""

        try:
            ai_res = self.ai.chat(prompt_for_ai, context_info=context_info, session_id=session_id)
            if ai_res:
                return ai_res
        except TypeError:
            try:
                ai_res = self.ai.chat(prompt_for_ai, context_info=context_info)
                if ai_res:
                    return ai_res
            except Exception:
                pass
        except Exception:
            pass

        # 4. РЕЗЕРВНИЙ ШЛЯХ (OFFLINE / FALLBACK PATH)
        # Якщо ШІ не повернув відповідь (відсутня мережа/API), викликаємо локальний CommandProcessor
        try:
            handled, response = self.commands.execute(prompt, session_id=session_id)
        except TypeError:
            handled, response = self.commands.execute(prompt)

        if handled:
            if hasattr(self.ai, "conversation_buffer") and response:
                self.ai.conversation_buffer.add_simple_turn(session_id, prompt, response)
            return response

        if converted_prompt != prompt:
            try:
                handled, response = self.commands.execute(converted_prompt, session_id=session_id)
            except TypeError:
                handled, response = self.commands.execute(converted_prompt)
            if handled:
                if hasattr(self.ai, "conversation_buffer") and response:
                    self.ai.conversation_buffer.add_simple_turn(session_id, converted_prompt, response)
                return response

        return "Не вдалося виконати команду."

