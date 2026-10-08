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

        handled, response = self.commands.execute(prompt)

        if handled:
            return response

        # Try converting accidental English keyboard layout to Ukrainian for command execution
        converted_prompt = convert_qwerty_to_ua(prompt)
        if converted_prompt != prompt:
            handled, response = self.commands.execute(converted_prompt)
            if handled:
                return response

        prompt_for_ai = prompt

        import re
        clean_ai = re.sub(
            r'^(?:(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?|гараж)\s*[,:;!?-]*\s*',
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
            return self.ai.chat(prompt_for_ai, context_info=context_info, session_id=session_id)
        except TypeError:
            try:
                return self.ai.chat(prompt_for_ai, context_info=context_info)
            except TypeError:
                return self.ai.chat(prompt_for_ai)

