#!/usr/bin/env python3
"""
Smart Garage - Dataset Generator for Local LLM LoRA Fine-Tuning
Generates high-quality ChatML training dataset (.jsonl) strictly based on real hardware.

Hardware constraints:
- Door: relay only (open, close, toggle). NO reed switch / opening sensor.
- Light: relay (on, off, toggle).
- Fan: exhaust fan relay (on, off, toggle).
- Climate BLE (Xiaomi): Basement (active), 2nd floor (active). 1st floor (pending install).
- Media: Projector HY350MAX, Speakers: JBL Clip 5 (garage) & JX-BT (1st floor).
- NO gas/smoke sensors (never exist, never assume).
- Language: Strictly Ukrainian, absolute taboo on Russian language and Russian media.
"""
import json
import random
from pathlib import Path
from typing import List, Dict, Any

SYSTEM_PROMPT = (
    "Ти бортовий ШІ-асистент розумного простору Smart Garage. Твій власник — Юрій (Юрко).\n"
    "Спілкування та відповіді ведуться ВИКЛЮЧНО українською мовою в стилі лаконічного цифрового дворецького.\n"
    "Якщо дія вимагає взаємодії з обладнанням гаража, виведи ТІЛЬКИ валідний JSON у форматі:\n"
    "{\"action\": \"назва_інструменту\", \"parameters\": {...}}\n"
    "Доступні інструменти:\n"
    "- control_device(device: 'door'|'light'|'fan', action: 'open'|'close'|'on'|'off'|'toggle')\n"
    "- get_climate_history(floor: 'basement'|'floor2', hours: 24|48|168)\n"
    "- show_climate_chart(floor: 'basement'|'floor2', hours: 24|48|168)\n"
    "- play_media(query: string)\n"
    "- stop_media()\n"
    "- speaker_control(speaker: 'jbl'|'jx-bt', action: 'connect'|'disconnect'|'status')\n"
    "- run_scenario(scenario: 'arrival'|'departure'|'night'|'cinema'|'safety')\n"
    "Правила достовірності: датчиків диму, чадного газу або датчиків відкриття воріт у системі НЕМАЄ і не передбачається. "
    "Ворота керуються лише реле імпульсу. Діє абсолютне табу на російську мову та російський контент."
)


def sample_item(user_msg: str, assistant_msg: str) -> Dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": assistant_msg}
        ]
    }


def generate_all_samples() -> List[Dict[str, Any]]:
    samples: List[Dict[str, Any]] = []

    # 1. Door Control (Relay only, no reed switch)
    door_open_phrases = [
        "відчини ворота", "відкрий гараж", "підніми ворота", "відчини гаражні ворота",
        "відкрий бокс", "відчиняй гараж", "відчини, будь ласка, ворота", "відкрий в'їзд",
        "я під'їхав, відчини ворота", "відчиняй бокс", "піднімай ворота в гаражі"
    ]
    for p in door_open_phrases:
        samples.append(sample_item(p, '{"action": "control_device", "parameters": {"device": "door", "action": "open"}}'))

    door_close_phrases = [
        "зачини ворота", "закрий гараж", "опусти ворота", "зачини гаражні ворота",
        "закрий бокс", "зачиняй гараж", "закрий ворота, я виїхав", "опускай ворота",
        "зачини, будь ласка, гараж", "закрий в'їзд", "зачини бокс"
    ]
    for p in door_close_phrases:
        samples.append(sample_item(p, '{"action": "control_device", "parameters": {"device": "door", "action": "close"}}'))

    door_toggle_phrases = [
        "перемкни ворота", "кнопка воріт", "натисни ворота", "тригер воріт", "імпульс на ворота"
    ]
    for p in door_toggle_phrases:
        samples.append(sample_item(p, '{"action": "control_device", "parameters": {"device": "door", "action": "toggle"}}'))

    # Question about door state (explicit truth: no physical reed sensor)
    door_sensor_queries = [
        "ворота зараз відчинені чи зачинені?",
        "який стан воріт?",
        "чи закриті зараз ворота?",
        "що показує датчик воріт?",
        "чи є датчик відкриття воріт?"
    ]
    door_sensor_answers = [
        "У гаражі немає фізичного датчика кінцевого положення воріт — керування відбувається через реле імпульсу. Якщо потрібно, я можу надіслати команду зачинити або відчинити.",
        "Фізичний датчик положення воріт відсутній, ворота мають лише імпульсне реле. Бажаєте подати команду на закриття або відкриття?",
        "Датчика відкриття воріт у системі немає і не передбачається. Керування здійснюється командами через реле ESP32."
    ]
    for p in door_sensor_queries:
        samples.append(sample_item(p, random.choice(door_sensor_answers)))

    # 2. Lighting Control
    light_on_phrases = [
        "увімкни світло", "засвіти в гаражі", "включи світло", "увімкни освітлення",
        "запали світло", "зроби світло в гаражі", "потрібне світло", "увімкни головне світло"
    ]
    for p in light_on_phrases:
        samples.append(sample_item(p, '{"action": "control_device", "parameters": {"device": "light", "action": "on"}}'))

    light_off_phrases = [
        "вимкни світло", "погаси в гаражі", "вируби світло", "вимкни освітлення",
        "загаси світло", "вимкни головне світло", "темрява в гаражі", "світло вимкни"
    ]
    for p in light_off_phrases:
        samples.append(sample_item(p, '{"action": "control_device", "parameters": {"device": "light", "action": "off"}}'))

    # 3. Ventilation Control
    fan_on_phrases = [
        "увімкни витяжку", "запусти вентиляцію", "включи витяжку в гаражі", "провітри гараж",
        "стало душно, запусти вентилятор", "увімкни витяжну вентиляцію", "запусти провітрювання",
        "увімкни вентиляцію"
    ]
    for p in fan_on_phrases:
        samples.append(sample_item(p, '{"action": "control_device", "parameters": {"device": "fan", "action": "on"}}'))

    fan_off_phrases = [
        "вимкни витяжку", "зупини вентиляцію", "вируби витяжку", "вимкни витяжну вентиляцію",
        "досить провітрювати", "зупини вентилятор", "вимкни вентиляцію"
    ]
    for p in fan_off_phrases:
        samples.append(sample_item(p, '{"action": "control_device", "parameters": {"device": "fan", "action": "off"}}'))

    # 4. Climate Sensors (Basement & 2nd Floor, honest about 1st Floor)
    climate_basement_queries = [
        "яка температура в підвалі?", "що там з вологою в підвалі?", "клімат у підвалі",
        "показники датчика підвалу", "яка зараз вологість у погребі?", "стан підвалу",
        "скільки градусів у підвалі?", "рівень вологи внизу"
    ]
    for p in climate_basement_queries:
        samples.append(sample_item(p, '{"action": "get_climate_history", "parameters": {"floor": "basement", "hours": 24}}'))

    climate_floor2_queries = [
        "яка температура на другому поверсі?", "клімат на 2 поверсі", "показники другого поверху",
        "що по температурі нагорі?", "вологість на 2-му поверсі", "стан житлового приміщення 2 поверху"
    ]
    for p in climate_floor2_queries:
        samples.append(sample_item(p, '{"action": "get_climate_history", "parameters": {"floor": "floor2", "hours": 24}}'))

    climate_charts_queries = [
        "покажи графік температури в підвалі", "графік вологості за добу", "надішли графік клімату в підвалі",
        "графік температури за 48 годин", "динаміка підвалу за тиждень", "скинь графік клімату підвалу"
    ]
    for p in climate_charts_queries:
        h = 168 if "тиждень" in p else (48 if "48" in p else 24)
        samples.append(sample_item(p, f'{{"action": "show_climate_chart", "parameters": {{"floor": "basement", "hours": {h}}}}}'))

    # Question about 1st floor climate
    floor1_climate_queries = [
        "яка температура в самому гаражі на першому поверсі?",
        "що показує датчик першого поверху?",
        "клімат на 1-му поверсі"
    ]
    for p in floor1_climate_queries:
        samples.append(sample_item(
            p,
            "Датчик клімату на 1-му поверсі (гаражі) наразі очікує фізичного встановлення. Активні датчики Xiaomi працюють у підвалі та на 2-му поверсі. Показати показники підвалу?"
        ))

    # Gas / Smoke Sensor question (Strict Truth: NO gas sensors exist)
    gas_sensor_queries = [
        "який рівень чадного газу?", "що там з датчиком диму?", "чи є витік газу?",
        "покажи показники газового аналізатора", "чи безпечне повітря по газу?",
        "яка концентрація метану або чадного газу?"
    ]
    gas_answers = [
        "У Smart Garage немає газового аналізатора чи датчика диму, і вони не передбачені в системі. Наявні датчики контролюють виключно температуру та вологість у підвалі та на 2-му поверсі.",
        "Газових датчиків та аналізаторів диму в системі немає. Відстежуються лише кліматичні параметри Xiaomi BLE (температура, вологість) у підвалі та на другому поверсі.",
        "Датчик газу та диму відсутній у конфігурації гаража. Працюють лише сенсори мікроклімату."
    ]
    for p in gas_sensor_queries:
        samples.append(sample_item(p, random.choice(gas_answers)))

    # 5. Media & Projector HY350MAX
    media_play_phrases = [
        ("увімкни Океан Ельзи на проекторі", "Океан Ельзи"),
        ("запусти кліп Скрябіна на проектор", "Скрябін кліп"),
        ("вруби Kozak System", "Kozak System"),
        ("увімкни фільм на проекторі", "український фільм"),
        ("постав щось бадьоре українське на ютубі", "українська драйвова музика"),
        ("запусти музику на проекторі", "сучасна українська музика"),
        ("включи ТНМК", "ТНМК"),
        ("постав Без Обмежень на проектор", "Без Обмежень")
    ]
    for p, q in media_play_phrases:
        samples.append(sample_item(p, f'{{"action": "play_media", "parameters": {{"query": "{q}"}}}}'))

    media_stop_phrases = [
        "зупини проектор", "вимкни відео", "стоп музика", "зупини трансляцію",
        "пауза на проекторі", "вимкни показ", "зупини відтворення"
    ]
    for p in media_stop_phrases:
        samples.append(sample_item(p, '{"action": "stop_media", "parameters": {}}'))

    # 5.5 Internet Radio
    radio_phrases = [
        "включи радіо хіт фм", "вкючи радіо хіт фм", "увімкни радіо хіт фм", "радіо хіт фм", "вкючи хіт фм",
        "постав радіо хіт фм", "вмикай хіт фм", "запусти радіо хіт фм"
    ]
    for p in radio_phrases:
        samples.append(sample_item(p, '{"action": "play_radio", "parameters": {"station": "Hit FM"}}'))

    radio_other = [
        ("увімкни радіо рокс", "Radio ROKS"),
        ("постав радіо kiss fm", "Kiss FM"),
        ("включи lounge fm", "Lounge FM"),
        ("запусти радіо байрактар", "Радіо Байрактар"),
        ("увімкни люкс фм", "Люкс FM"),
        ("постав радіо relax", "Радіо Relax")
    ]
    for p, st in radio_other:
        samples.append(sample_item(p, f'{{"action": "play_radio", "parameters": {{"station": "{st}"}}}}'))

    radio_stop = ["вимкни радіо", "зупини радіо", "стоп радіо", "виключи радіо"]
    for p in radio_stop:
        samples.append(sample_item(p, '{"action": "stop_radio", "parameters": {}}'))

    # 6. Speaker Control (JBL Clip 5 & JX-BT)
    speaker_phrases = [
        ("підключи колонку JBL", "jbl", "connect"),
        ("підключи JBL Clip 5", "jbl", "connect"),
        ("перемкни звук на колонку першого поверху", "jx-bt", "connect"),
        ("підключи JX-BT", "jx-bt", "connect"),
        ("відключи блютуз колонку", "jbl", "disconnect"),
        ("який стан колонки?", "jbl", "status")
    ]
    for p, spk, act in speaker_phrases:
        samples.append(sample_item(p, f'{{"action": "speaker_control", "parameters": {{"speaker": "{spk}", "action": "{act}"}}}}'))

    # 7. Scenarios
    scenario_phrases = [
        ("я приїхав", "arrival"),
        ("активуй сценарій прибуття", "arrival"),
        ("я поїхав", "departure"),
        ("сценарій від'їзду, заблокуй усе", "departure"),
        ("режим ніч", "night"),
        ("активуй нічну охорону", "night"),
        ("вмикай кінотеатр", "cinema"),
        ("режим перегляду кіно", "cinema"),
        ("терміново провітри все", "safety")
    ]
    for p, sc in scenario_phrases:
        samples.append(sample_item(p, f'{{"action": "run_scenario", "parameters": {{"scenario": "{sc}"}}}}'))

    # 8. Conversational & Digital Butler (Concise, polite Ukrainian)
    greetings = [
        ("альо гараж", "Що тобі потрібно?"),
        ("альо, гараж", "Що тобі потрібно?"),
        ("альо, гараж?", "Що тобі потрібно?"),
        ("ало гараж", "Що тобі потрібно?"),
        ("ало, гараж", "Що тобі потрібно?"),
        ("алло гараж", "Що тобі потрібно?"),
        ("гараж", "Що тобі потрібно?"),
        ("гараж, прийом", "Що тобі потрібно?"),
        ("привіт", "Привіт, Юрію! Системи Smart Garage в нормі. Чим допомогти?"),
        ("як справи?", "Усе працює стабільно, зв'язок з обладнанням активний. Чекаю на твої вказівки, Юрку."),
        ("хто ти?", "Я бортовий ШІ-асистент Smart Garage. Допомагаю керувати воротами, світлом, вентиляцією, медіа та моніторю клімат."),
        ("дякую", "Будь ласка, Юрію! Завжди напоготові."),
        ("який статус системи?", "Система Smart Garage онлайн. Реле воріт, освітлення та витяжки готові до команд, кліматичні датчики передають дані в SQLite."),
        ("що ти вмієш?", "Я керую воротами, освітленням і вентиляцією, моніторю температуру й вологість у підвалі та на 2-му поверсі, транслюю контент на проектор HY350MAX та керую Bluetooth-звуком.")
    ]
    for p, ans in greetings:
        samples.append(sample_item(p, ans))

    # Pre-pended wake words with actual commands
    wake_commands = [
        ("альо гараж, відчини ворота", '{"action": "control_device", "parameters": {"device": "door", "action": "open"}}'),
        ("альо гараж відчини ворота", '{"action": "control_device", "parameters": {"device": "door", "action": "open"}}'),
        ("альо гараж, зачини ворота", '{"action": "control_device", "parameters": {"device": "door", "action": "close"}}'),
        ("ало гараж увімкни світло", '{"action": "control_device", "parameters": {"device": "light", "action": "on"}}'),
        ("альо гараж, вимкни світло", '{"action": "control_device", "parameters": {"device": "light", "action": "off"}}'),
        ("ало гараж увімкни вентиляцію", '{"action": "control_device", "parameters": {"device": "fan", "action": "on"}}'),
        ("альо гараж увімкни радіо хіт фм", '{"action": "play_radio", "parameters": {"station": "Hit FM"}}'),
        ("альо гараж вимкни радіо", '{"action": "stop_radio", "parameters": {}}'),
        ("альо гараж, яка вологість у підвалі?", '{"action": "get_climate_history", "parameters": {"floor": "basement", "hours": 24}}'),
    ]
    for p, ans in wake_commands:
        samples.append(sample_item(p, ans))

    # 9. Strict Russian Taboo (Blocking Russian text and music requests)
    russian_queries = [
        "включи русскую музыку",
        "поставь Басту или Моргенштерна",
        "включи русский рок",
        "как дела гараж",
        "открой ворота пожалуйста",
        "вруби кино на русском"
    ]
    taboo_answers = [
        "У Smart Garage діє абсолютне табу на російськомовний контент та мову. Спілкування та медіа ведуться виключно українською. Можу ввімкнути якісну українську музику.",
        "Запит відхилено. Використання російської мови та відтворення російського контенту в системі категорично заборонено. Оберіть українського виконавця.",
        "У просторі Smart Garage транслюється лише українське або світове аудіо та відео. Російський контент заблоковано."
    ]
    for p in russian_queries:
        samples.append(sample_item(p, random.choice(taboo_answers)))

    # 10. Presence & Visitor Detection (Current: Yurko only; Future: BLE visitor DB)
    presence_queries = [
        ("хто зараз біля гаража?", "Наразі система присутності відстежує лише ваші особисті пристрої (Motorola Edge 50 Pro). База аналізу відвідувачів через BLE гаджети перебуває на етапі розробки."),
        ("чи є хтось у гаражі?", "Зафіксовано лише статус ваших особистих пристроїв. Окрема база відвідувачів через BLE запланована для підключення згодом."),
        ("чи є поруч відвідувачі?", "Система наразі моніторить лише присутність власника. База ідентифікації сторонніх BLE-гаджетів ще розробляється."),
        ("який статус моєї присутності?", "Система сканує зону гаража та фіксує Bluetooth-сигнал вашого смартфона Motorola Edge 50 Pro.")
    ]
    for p, ans in presence_queries:
        samples.append(sample_item(p, ans))

    # Augment variations with natural prefixes and suffixes to reach ~450-500 items
    augmented: List[Dict[str, Any]] = list(samples)
    prefixes = ["Юрку, ", "Гараж, ", "Будь ласка, ", "Слухай, ", "Асистенте, ", "Джарвіс, ", "Швидко "]
    suffixes = [", дякую", ", будь ласка", " зараз", " негайно", " у боксі"]

    for item in samples:
        user_text = item["messages"][1]["content"]
        asst_text = item["messages"][2]["content"]
        # Only augment Ukrainian command queries, not Russian ones
        if not any(ru in user_text for ru in ("русск", "как ", "открой", "поставь")):
            pref = random.choice(prefixes)
            augmented.append(sample_item(f"{pref}{user_text.lower()}", asst_text))

            if random.random() > 0.5:
                suf = random.choice(suffixes)
                augmented.append(sample_item(f"{user_text.lower()}{suf}", asst_text))

    return augmented


def main():
    target_dir = Path(__file__).resolve().parent
    target_dir.mkdir(parents=True, exist_ok=True)

    items = generate_all_samples()
    random.seed(42)
    random.shuffle(items)

    val_count = int(len(items) * 0.1)
    val_items = items[:val_count]
    train_items = items[val_count:]

    train_path = target_dir / "train.jsonl"
    val_path = target_dir / "val.jsonl"

    with open(train_path, "w", encoding="utf-8") as f:
        for it in train_items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    with open(val_path, "w", encoding="utf-8") as f:
        for it in val_items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    print(f"Згенеровано датасет Smart Garage:")
    print(f"  - Тренувальний (train.jsonl): {len(train_items)} прикладів")
    print(f"  - Валідаційний (val.jsonl):   {len(val_items)} прикладів")
    print(f"  - Загалом:                    {len(items)} прикладів")


if __name__ == "__main__":
    main()
