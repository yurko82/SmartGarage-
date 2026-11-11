"""
Smart Garage - Ukrainian Text Normalizer for Natural TTS
--------------------------------------------------------
Перетворює текст відповіді на природну розмовну українську мову:
- Очищення розмітки Markdown, HTML, емодзі, URL та лапок.
- Розгортання чисел, температур, відсотків, десяткових дробів та поверхів
  у правильні граматичні форми українських слів.
- Контроль довжини тексту з акуратним завершенням на межі речень.
"""

import re
from typing import Optional

# Українські числівники для чисел від 0 до 999
_ONES = {
    0: "нуль",
    1: "один",
    2: "два",
    3: "три",
    4: "чотири",
    5: "п'ять",
    6: "шість",
    7: "сім",
    8: "вісім",
    9: "дев'ять",
}

_ONES_FEMININE = {
    1: "одна",
    2: "дві",
}

_TEENS = {
    10: "десять",
    11: "одинадцять",
    12: "дванадцять",
    13: "тринадцять",
    14: "чотирнадцять",
    15: "п'ятнадцять",
    16: "шістнадцять",
    17: "сімнадцять",
    18: "вісімнадцять",
    19: "дев'ятнадцять",
}

_TENS = {
    20: "двадцять",
    30: "тридцять",
    40: "сорок",
    50: "п'ятдесят",
    60: "шістдесят",
    70: "сімдесят",
    80: "вісімдесят",
    90: "дев'яносто",
}

_HUNDREDS = {
    100: "сто",
    200: "двісті",
    300: "триста",
    400: "чотириста",
    500: "п'ятсот",
    600: "шістсот",
    700: "сімсот",
    800: "вісімсот",
    900: "дев'ятсот",
}


def number_to_ukrainian_words(n: int, feminine: bool = False) -> str:
    """Перетворює ціле число від 0 до 999 у словесне представлення українською мовою."""
    if n < 0:
        return f"мінус {number_to_ukrainian_words(-n, feminine=feminine)}"
    if n == 0:
        return _ONES[0]

    parts = []
    # Сотні
    h = (n // 100) * 100
    if h in _HUNDREDS:
        parts.append(_HUNDREDS[h])

    rem = n % 100
    if rem in _TEENS:
        parts.append(_TEENS[rem])
    else:
        # Десятки
        t = (rem // 10) * 10
        if t in _TENS:
            parts.append(_TENS[t])
        # Одиниці
        u = rem % 10
        if u > 0:
            if feminine and u in _ONES_FEMININE:
                parts.append(_ONES_FEMININE[u])
            else:
                parts.append(_ONES[u])

    return " ".join(parts)


def format_temperature_ukrainian(sign_str: str, int_val: int, frac_val: int | None = None) -> str:
    """Формує природну українську фразу для температури (°C)."""
    sign_prefix = ""
    if sign_str == "-" or int_val < 0:
        sign_prefix = "мінус "
    elif sign_str == "+":
        sign_prefix = "плюс "

    abs_int = abs(int_val)
    int_words = number_to_ukrainian_words(abs_int)

    if frac_val is not None and frac_val > 0:
        if frac_val == 5:
            return f"{sign_prefix}{int_words} з половиною градусів"
        frac_words = number_to_ukrainian_words(frac_val)
        return f"{sign_prefix}{int_words} і {frac_words} десятих градуса"

    # Відмінювання слова 'градус'
    last_two = abs_int % 100
    last_one = abs_int % 10
    if 11 <= last_two <= 19:
        unit = "градусів"
    elif last_one == 1:
        unit = "градус"
    elif 2 <= last_one <= 4:
        unit = "градуси"
    else:
        unit = "градусів"

    return f"{sign_prefix}{int_words} {unit}"


def format_percentage_ukrainian(int_val: int) -> str:
    """Формує природну українську фразу для відсотків (%)."""
    abs_int = abs(int_val)
    int_words = number_to_ukrainian_words(abs_int)

    last_two = abs_int % 100
    last_one = abs_int % 10
    if 11 <= last_two <= 19:
        unit = "відсотків"
    elif last_one == 1:
        unit = "відсоток"
    elif 2 <= last_one <= 4:
        unit = "відсотки"
    else:
        unit = "відсотків"

    return f"{int_words} {unit}"


def clean_markdown_and_markup(text: str) -> str:
    """Видаляє Markdown, посилання, код, емодзі та лапки без втрати змісту."""
    if not text:
        return ""

    # 1. Видалення URL посилань
    clean = re.sub(r'https?://\S+', '', text)

    # 2. Видалення блоків коду ```code``` або inline `code`
    clean = re.sub(r'```.*?```', '', clean, flags=re.DOTALL)
    clean = re.sub(r'`([^`]+)`', r'\1', clean)

    # 3. Видалення Markdown-посилань [текст](url) -> текст
    clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)

    # 4. Видалення емодзі та спеціальних піктограм
    clean = re.sub(r'[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf\ufe00-\ufe0f\u200d]', '', clean)

    # 5. Видалення символів форматування (*, _, #, ~, |, •, ·)
    clean = re.sub(r'[*_#~|•·]', ' ', clean)

    # 6. Видалення лапок (подвійних, ялинок, одиночних на краях слів), але збереження апострофа всередині слів
    clean = re.sub(r'(?<=[а-яА-ЯіїєґІЇЄҐa-zA-Z])[\'’](?=[а-яА-ЯіїєґІЇЄҐa-zA-Z])', '__APOSTROPHE__', clean)
    clean = re.sub(r'[\'\"«»“”„”`]', '', clean)
    clean = clean.replace('__APOSTROPHE__', "'")

    return clean


def normalize_ukrainian_text(text: str, max_length: int = 500) -> str:
    """
    Повна нормалізація тексту для синтезу мовлення (TTS):
    - Очищення розмітки;
    - Заміна одиниць виміру та чисел на розмовні слова;
    - Адаптація специфічних термінів гаража (поверхи, радіо, статуси);
    - Обмеження максимальної довжини.
    """
    if not text:
        return ""

    clean = clean_markdown_and_markup(text)

    # 1. Температура: (+|-)?\d+([.,]\d+)?\s*°C
    def _replace_temp(match):
        sign = match.group(1) or ""
        int_str = match.group(2)
        frac_str = match.group(3)
        int_val = int(int_str)
        frac_val = int(frac_str[1:]) if frac_str else None
        return " " + format_temperature_ukrainian(sign, int_val, frac_val) + " "

    clean = re.sub(r'([+\-])?(\d+)([.,]\d+)?\s*°C', _replace_temp, clean)
    clean = clean.replace('°C', ' градусів ')

    # 2. Відсотки: \d+\s*%
    def _replace_percent(match):
        int_val = int(match.group(1))
        return " " + format_percentage_ukrainian(int_val) + " "

    clean = re.sub(r'(\d+)\s*%', _replace_percent, clean)
    clean = clean.replace('%', ' відсотків ')

    # 3. Десяткові дроби з половиною (2.5 -> два з половиною)
    clean = re.sub(r'\b(\d+)[.,]5\b', r'\1 з половиною', clean)

    # 4. Поверхи та локації
    clean = re.sub(r'1-й\s*поверх', 'перший поверх', clean, flags=re.IGNORECASE)
    clean = re.sub(r'2-й\s*поверх', 'другий поверх', clean, flags=re.IGNORECASE)
    clean = re.sub(r'1-му\s*поверсі', 'першому поверсі', clean, flags=re.IGNORECASE)
    clean = re.sub(r'2-му\s*поверсі', 'другому поверсі', clean, flags=re.IGNORECASE)
    clean = re.sub(r'на\s+музика\s+(?:1-й|перший|1)\s+поверх', 'на першому поверсі', clean, flags=re.IGNORECASE)
    clean = re.sub(r'на\s+музика\s+1', 'на першому поверсі', clean, flags=re.IGNORECASE)

    # 5. Статуси та одиниці
    clean = re.sub(r'\[онлайн\]', 'онлайн', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\[офлайн\]', 'офлайн', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bppm\b', 'часток на мільйон', clean, flags=re.IGNORECASE)
    clean = re.sub(r'(\d+)\s*(?:кВт|kW)\b', r'\1 кіловат', clean, flags=re.IGNORECASE)
    clean = re.sub(r'(\d+)\s*(?:Вт|W)\b', r'\1 ват', clean, flags=re.IGNORECASE)
    clean = re.sub(r'(\d+)\s*(?:В|V)\b', r'\1 вольт', clean, flags=re.IGNORECASE)
    clean = re.sub(r'(\d+)\s*(?:хв|min)\b', r'\1 хвилин', clean, flags=re.IGNORECASE)
    clean = re.sub(r'(\d+)\s*(?:сек|sec|с)\b', r'\1 секунд', clean, flags=re.IGNORECASE)

    # 6. Радіостанції та латинські бренди
    clean = re.sub(r'\bhit\s*fm\b', 'Хіт ФМ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bkiss\s*fm\b', 'Кіс ФМ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\blounge\s*fm\b', 'Лаундж ФМ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bradio\s*roks\b', 'Радіо Рокс', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bradio\s*jazz\b', 'Радіо Джаз', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bfm\b', 'ФМ', clean, flags=re.IGNORECASE)

    # 7. Конвертація окремих малих чисел у слова (до 20 для покращення природності мовлення)
    def _replace_small_numbers(match):
        val = int(match.group(1))
        if 0 <= val <= 20:
            return number_to_ukrainian_words(val)
        return match.group(1)

    clean = re.sub(r'\b(\d{1,2})\b', _replace_small_numbers, clean)

    # 8. Ритміка та пунктуація
    clean = re.sub(r'[:;]+', ', ', clean)
    clean = re.sub(r'\s+[-—–]\s+', ', ', clean)
    clean = re.sub(r'[-—–]+', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    clean = re.sub(r'\s+([.,!?])', r'\1', clean)

    # 9. Обмеження довжини тексту
    if len(clean) > max_length:
        clean = truncate_to_max_length(clean, max_length)

    # 10. Завершальний розділовий знак
    if clean and clean[-1] not in '.!?':
        clean += '.'

    return clean


def truncate_to_max_length(text: str, max_chars: int) -> str:
    """Обрізає текст до максимальної довжини акуратно на межі речень."""
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    # Шукаємо останнє закінчення речення
    last_punct = max(truncated.rfind('. '), truncated.rfind('! '), truncated.rfind('? '))
    if last_punct > max_chars * 0.5:
        return truncated[:last_punct + 1].strip()

    # Якщо закінчення речення не знайдено в другій половині, ріжемо по межі слів
    last_space = truncated.rfind(' ')
    if last_space > 0:
        truncated = truncated[:last_space].strip()

    return truncated + "..."
