"""Tools and Function Calling declarations for SmartGarage AI."""
import json
import logging
import uuid
from typing import Dict, Any, List, Optional, Tuple
from server.security.audit import audit_log

logger = logging.getLogger(__name__)

GARAGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "control_device",
            "description": "Керування фізичними виконавчими пристроями гаража через ESP32-S3 (освітлення по зонах: light, basement_light, floor2_light, main_light, витяжна вентиляція). Привід воріт не планується.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "enum": ["light", "fan", "basement_light", "floor2_light", "main_light"],
                        "description": "Тип пристрою: light (усе освітлення), basement_light (підвал), floor2_light (2-й поверх), main_light (гараж/1-й поверх), fan (витяжна вентиляція)."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["on", "off", "toggle"],
                        "description": "Дія: on/off/toggle для light, fan та окремих зон освітлення."
                    }
                },
                "required": ["device", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_song",
            "description": "Відтворення пісні або музики через YouTube Music на активній Bluetooth-колонці (JBL Clip 5 у гаражі або JX-BT на 1-му поверсі). Використовуй цей інструмент завжди, коли Юрій просить 'включи пісню', 'просто включи пісню', 'увімкни музику', 'включи трек', або називає виконавця чи пісню на YouTube Music.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Назва пісні, виконавець або пошуковий запит YouTube Music. Якщо Юрій просто сказав 'включи пісню' чи 'просто включи пісню' без назви, передай за замовчуванням 'Українські хіти' або 'ADAM - Сильно Сильно'."
                    },
                    "speaker": {
                        "type": "string",
                        "enum": ["jbl", "jx-bt"],
                        "description": "Опціонально: цільова Bluetooth-колонка: 'jbl' (JBL Clip 5 у гаражі) або 'jx-bt' (JX-BT на 1-му поверсі). За замовчуванням грає на поточній активній."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_user_playlist",
            "description": "Відтворення треків з особистих плейлистів або списку Улюблених (Liked Music) користувача в YouTube Music на Bluetooth-колонці. Використовуй, коли Юрій просить 'включи мої улюблені', 'включи плейлист рок', 'включи плейлист dnb' тощо.",
            "parameters": {
                "type": "object",
                "properties": {
                    "playlist": {
                        "type": "string",
                        "description": "Назва або ключове слово плейлиста (наприклад: 'улюблені', 'рок', 'dnb') або 'LM' для Улюблених."
                    },
                    "speaker": {
                        "type": "string",
                        "enum": ["jbl", "jx-bt"],
                        "description": "Опціонально: цільова колонка ('jbl' у гаражі або 'jx-bt' на 1-му поверсі)."
                    }
                },
                "required": ["playlist"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_user_playlists",
            "description": "Отримання списку збережених плейлистів та улюблених списків відтворення користувача в YouTube Music.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "next_music_track",
            "description": "Перемикання на наступний трек у поточному плейлісті або списку Улюблених (Liked Music) в YouTube Music на Bluetooth-колонці. Використовуй, коли користувач просить 'наступна пісня', 'пропусти трек', 'перемкни пісню', 'наступний' тощо.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prev_music_track",
            "description": "Повернення до попереднього треку в YouTube Music на Bluetooth-колонці. Використовуй, коли користувач просить 'попередня пісня', 'попередній трек', 'поверни пісню назад' тощо.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "seek_music_track",
            "description": "Перемотування поточної пісні вперед або назад на Bluetooth-колонці на вказану кількість секунд або до заданої позиції.",
            "parameters": {
                "type": "object",
                "properties": {
                    "position": {
                        "type": "integer",
                        "description": "Абсолютна позиція у секундах (наприклад: 60 для 1 хв)."
                    },
                    "delta": {
                        "type": "integer",
                        "description": "Зміщення у секундах від поточної позиції (+15 вперед, -15 назад)."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "Трансляція відео, фільмів чи кліпів на великий екран проектора HY350MAX у гаражі. Для відтворення пісень чи звичайного аудіо використовуй play_song (YouTube Music на Bluetooth-колонці).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Пошуковий запит YouTube, назва відео, кліпу або URL для проектора."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_media",
            "description": "Зупинка відтворення відео або трансляції на проекторі HY350MAX.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "projector_control",
            "description": "Перевірка стану зв'язку або керування проектором HY350MAX (status - перевірити зв'язок/онлайн, power_off - вимкнути, mirror_stop - зупинити трансляцію).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "power_off", "mirror_stop"],
                        "description": "Дія: status (перевірити доступність у мережі), power_off (вимкнути живлення), mirror_stop (зупинити трансляцію)."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_scenario",
            "description": "Активація комплексного автоматизованого сценарію розумного гаража.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario": {
                        "type": "string",
                        "enum": ["arrival", "departure", "night", "cinema"],
                        "description": "Сценарій: arrival (прибуття), departure (від'їзд), night (нічна охорона/блокування), cinema (кінотеатр/проектор)."
                    }
                },
                "required": ["scenario"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "speaker_control",
            "description": "Керування Bluetooth-колонками (JBL Clip 5 у гаражі або JX-BT на 1-му поверсі).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["connect", "disconnect", "status"],
                        "description": "Дія: connect (підключити), disconnect (відключити), status (перевірити стан)."
                    },
                    "speaker": {
                        "type": "string",
                        "enum": ["jbl", "jx-bt"],
                        "description": "Цільова колонка: jbl (JBL Clip 5 у гаражі) або jx-bt (JX-BT на 1-му поверсі)."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_climate_history",
            "description": "Отримання аналітики та історії клімату з бази даних SQLite за вказаний період.",
            "parameters": {
                "type": "object",
                "properties": {
                    "floor": {
                        "type": "string",
                        "enum": ["basement", "floor2", "floor1", "all"],
                        "description": "Поверх: basement (підвал), floor2 (2-й поверх), floor1 (1-й поверх)."
                    },
                    "hours": {
                        "type": "integer",
                        "enum": [24, 48, 168],
                        "description": "Період в годинах: 24, 48 або 168 (7 днів)."
                    }
                },
                "required": ["floor"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "show_climate_chart",
            "description": "Згенерувати графік (PNG зображення) динаміки температури та вологості і надіслати в чат користувачу (Telegram). Якщо користувач просить графік для гаража (1-го поверху), де датчик ще очікує встановлення, обирай floor='basement' і поясни, що надіслано графік підвалу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "floor": {
                        "type": "string",
                        "enum": ["basement", "floor2", "floor1"],
                        "description": "Поверх / приміщення: basement (підвал - активний датчик), floor2 (2-й поверх), floor1 (1-й поверх / гараж)."
                    },
                    "hours": {
                        "type": "integer",
                        "enum": [24, 48, 168],
                        "description": "Період часу в годинах: 24 (доба), 48 (2 доби) або 168 (тиждень). За замовчуванням 24."
                    }
                },
                "required": ["floor"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_radio",
            "description": "Увімкнення онлайн інтернет-радіостанції на Bluetooth-колонці (Hit FM, Radio ROKS, Kiss FM, Lounge FM, Радіо Байрактар, Люкс FM тощо).",
            "parameters": {
                "type": "object",
                "properties": {
                    "station": {
                        "type": "string",
                        "description": "Назва радіостанції або жанр (наприклад: 'Hit FM', 'Radio ROKS', 'Kiss FM', 'Радіо Байрактар', 'Люкс FM', 'Relax'). За замовчуванням 'Hit FM'."
                    },
                    "speaker": {
                        "type": "string",
                        "enum": ["jbl", "jx-bt"],
                        "description": "Цільова колонка: 'jbl' (JBL Clip 5 у гаражі) або 'jx-bt' (JX-BT на 1-му поверсі)."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_radio",
            "description": "Зупинка відтворення радіостанції або музичного потоку на Bluetooth-колонці.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_music",
            "description": "Зупинка будь-якої музики, треку, пісні, аудіо або радіо на активній Bluetooth-колонці (JBL Clip 5 у гаражі або JX-BT на 1-му поверсі). Використовуй цей інструмент ЗАВЖДИ, коли користувач просить 'виключ музику', 'вимкни музику', 'зупини музику', 'виключи пісню', 'вимкни пісню', 'стоп', 'тиша', 'виключ радіо', 'вимкни радіо'.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_bluetooth_devices",
            "description": "Активне сканування радіоефіру Bluetooth Classic та BLE (Bluetooth Low Energy) навколо гаража через ESP32-S3 та хост. Виявляє кліматичні датчики Xiaomi Mijia, смартфони, смарт-годинники, трекери, навушники, акустику. Повертає список знайдених пристроїв з їхніми назвами, MAC-адресами та силою сигналу (RSSI). Використовуй цей інструмент завжди, коли Юрій просить 'проскануй bluetooth', 'скануй ефір', 'які пристрої bluetooth ти бачиш', 'знайди датчики в ефірі' тощо.",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {
                        "type": "integer",
                        "description": "Тривалість сканування в секундах (від 3 до 15). За замовчуванням 5.",
                        "default": 5
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_workshop_profile",
            "description": "Керування профілем веломайстерні Юрія, інструментами, робочими нотатками та велосипедами в ремонті. Дозволяє переглядати поточний стан майстерні, записувати велосипеди клієнтів у журнал ремонту, оновлювати статус готовності, додавати нові інструменти або зберігати технічні нотатки.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "add_client_bike", "update_bike_status", "add_tool", "add_note"],
                        "description": "Дія: 'get' (перегляд профілю), 'add_client_bike' (додати велосипед у ремонт), 'update_bike_status' (оновити статус ремонту), 'add_tool' (додати інструмент), 'add_note' (додати нотатку)."
                    },
                    "bike_model": {
                        "type": "string",
                        "description": "Модель велосипеда (наприклад, 'Trek Marlin 7', 'Specialized Diverge', 'Cannondale Trail')."
                    },
                    "client_name": {
                        "type": "string",
                        "description": "Ім'я або контакт клієнта (наприклад, 'Олег', 'Андрій')."
                    },
                    "work_description": {
                        "type": "string",
                        "description": "Опис робіт (наприклад, 'Прокачування гальм Shimano Deore та заміна ланцюга')."
                    },
                    "bike_id": {
                        "type": "string",
                        "description": "ID або назва велосипеда для оновлення статусу."
                    },
                    "status": {
                        "type": "string",
                        "enum": ["in_progress", "completed", "waiting_parts"],
                        "description": "Статус ремонту: in_progress (в роботі), completed (готовий), waiting_parts (очікує запчастин)."
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "Назва інструменту для додавання (наприклад, 'Тензометр Park Tool TM-1')."
                    },
                    "note": {
                        "type": "string",
                        "description": "Текст робочої нотатки або нагадування."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_bike_knowledge",
            "description": "Пошук у технічній базі знань веломайстерні точних специфікацій: моменти затяжки різьбових з'єднань (Нм для карбону/алюмінію), типи та регламенти заміни рідин для гальм (мінеральне мастило Shimano vs DOT 5.1 SRAM), регулювання підвіски (розрахунок SAG, тиск, сервісні інтервали вилок RockShox/Fox), контроль зносу ланцюгів (0.5% / 0.75%), стандарти кареток (BSA, PressFit, DUB, T47) та барабанів втулок.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Пошуковий запит (наприклад: 'момент затяжки кермо карбон', 'гальма sram dot fluid', 'розрахунок sag вилка xc', 'допуск зносу ланцюга 12sp', 'каретка bsa різьба')."
                    },
                    "category": {
                        "type": "string",
                        "enum": ["torque", "brakes", "suspension", "drivetrain", "standards"],
                        "description": "Опціональна категорія для фільтрації: torque (моменти затяжки), brakes (гальма), suspension (підвіска), drivetrain (трансмісія і ланцюги), standards (стандарти)."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_presence_guest",
            "description": "Керування гостями та правилами присутності біля гаража. Дозволяє зареєструвати нового гостя (наприклад, Макс), оновити його налаштування, задати персональну голосову фразу динаміка, якщо Юрія немає (напр., 'Макс, Юри в гаражі немає, гуляйте собі далі...'), та вказати Telegram Chat ID для прямих повідомлень гостю про відсутність Юрія.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["register", "update", "delete", "list"],
                        "description": "Дія: 'register' (додати гостя), 'update' (оновити параметри/фразу), 'delete' (видалити з бази), 'list' (показати зареєстрованих осіб)."
                    },
                    "name": {
                        "type": "string",
                        "description": "Ім'я гостя (наприклад: 'Макс', 'Олег', 'Андрій')."
                    },
                    "mac": {
                        "type": "string",
                        "description": "Bluetooth MAC-адреса або BLE RPA пристрою гостя (наприклад: '62:FD:D0:F6:F2:CF')."
                    },
                    "device_name": {
                        "type": "string",
                        "description": "Модель або назва пристрою (наприклад: 'iPhone 15', 'Смартфон')."
                    },
                    "role": {
                        "type": "string",
                        "enum": ["guest", "family", "contractor"],
                        "description": "Роль: guest (гість), family (родина), contractor (майстер/кур'єр). За замовчуванням 'guest'."
                    },
                    "absence_voice_message": {
                        "type": "string",
                        "description": "Персональна фраза, яку промовить динамік у гаражі, коли гість наблизився, а Юрія немає в гаражі (наприклад: 'Макс, Юри в гаражі немає, гуляйте собі далі...')."
                    },
                    "telegram_chat_id": {
                        "type": "string",
                        "description": "Опціональний Telegram Chat ID гостя, щоб бот міг надіслати йому сповіщення про відсутність Юрія."
                    },
                    "notify_owner": {
                        "type": "boolean",
                        "description": "Чи надсилати Юрію сповіщення в Telegram при появі цього гостя біля гаража. За замовчуванням true."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_visitor_report",
            "description": "Отримання журналу та звіту про відвідування гаража гостями: хто приходив, коли, скільки разів, чи був присутній власник Юрій. Використовуй, коли питають 'хто приходив сьогодні', 'покажи звіт відвідувань', 'хто був біля гаража за тиждень'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Кількість днів для звіту (наприклад: 1 - за сьогодні, 7 - за тиждень). За замовчуванням 7."
                    }
                },
                "required": []
            }
        }
    }
]


class ToolDispatcher:
    """Dispatches and executes tool calls against SmartGarage hardware."""

    def __init__(self, garage=None, session_mgr=None):
        self.garage = garage
        self.session_manager = session_mgr

    def _validate_tool_arguments(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Strict validation of tool arguments against schema to prevent fallback to {} or defaults."""
        if not isinstance(args, dict):
            return False, "аргументи мають бути передані як JSON-об'єкт"

        if tool_name == "control_device":
            device = args.get("device")
            action = args.get("action")
            if device not in ("light", "fan", "door", "basement_light", "floor2_light", "main_light"):
                return False, f"неприпустимий пристрій '{device}' (дозволено: 'light', 'fan', 'basement_light', 'floor2_light', 'main_light')"
            if action not in ("on", "off", "toggle", "open", "close"):
                return False, f"неприпустима дія '{action}' (дозволено: 'on', 'off', 'toggle')"

        elif tool_name == "play_song":
            query = args.get("query")
            if not query or not str(query).strip():
                return False, "параметр 'query' є обов'язковим і не може бути порожнім"
            spk = args.get("speaker")
            if spk and str(spk).lower() not in ("jbl", "jx-bt", "jxbt", "xt-bt", "xtbt", "floor1", "garage", ""):
                return False, f"невідома колонка '{spk}'"

        elif tool_name == "play_user_playlist":
            playlist = args.get("playlist")
            if not playlist or not str(playlist).strip():
                return False, "параметр 'playlist' є обов'язковим і не може бути порожнім"

        elif tool_name == "run_scenario":
            sc = args.get("scenario")
            if not sc or str(sc).lower() not in ("arrival", "departure", "night", "cinema", "safety"):
                return False, f"невідомий сценарій '{sc}' (дозволено: arrival, departure, night, cinema, safety)"

        elif tool_name == "seek_music_track":
            pos = args.get("position")
            delta = args.get("delta")
            if pos is None and delta is None:
                return False, "необхідно вказати 'position' або 'delta'"
            if pos is not None:
                try:
                    if float(pos) < 0:
                        return False, "position не може бути від'ємною"
                except (ValueError, TypeError):
                    return False, "position має бути числовим значенням"
            if delta is not None:
                try:
                    float(delta)
                except (ValueError, TypeError):
                    return False, "delta має бути числовим значенням"

        elif tool_name == "play_radio":
            station = args.get("station")
            if not station or not str(station).strip():
                return False, "параметр 'station' є обов'язковим і не може бути порожнім"

        elif tool_name == "search_bike_knowledge":
            query = args.get("query")
            if not query or not str(query).strip():
                return False, "параметр 'query' є обов'язковим і не може бути порожнім"

        elif tool_name == "play_media":
            query = args.get("query")
            if not query or not str(query).strip():
                return False, "параметр 'query' є обов'язковим і не може бути порожнім"

        elif tool_name == "manage_presence_guest":
            action = args.get("action")
            if not action or str(action).lower() not in ("register", "list", "remove", "delete", "update"):
                return False, f"невідома дія '{action}' (дозволено: register, list, remove, delete, update)"
            if str(action).lower() == "register" and not args.get("name"):
                return False, "для реєстрації гостя обов'язкове поле 'name'"

        elif tool_name == "manage_workshop_profile":
            action = args.get("action")
            if not action or str(action).lower() not in ("get", "update", "clear", "add_client_bike", "remove_client_bike", "update_bike_status", "add_tool", "add_note"):
                return False, f"невідома дія '{action}'"

        elif tool_name == "get_visitor_report":
            days = args.get("days")
            if days is not None:
                try:
                    d_int = int(days)
                    if d_int < 1 or d_int > 365:
                        return False, "days має бути від 1 до 365"
                except (ValueError, TypeError):
                    return False, "days має бути цілим числом"

        return True, None

    def execute(self, tool_name: str, arguments: Dict[str, Any], session_id: str = "default") -> Dict[str, Any]:
        """Execute a tool call and return structured result dict with strict allowlist enforcement."""
        cid = f"ai_{uuid.uuid4().hex[:8]}"
        if not self.garage:
            res = {"success": False, "error": "SmartGarage instance not bound to ToolDispatcher"}
            audit_log("ai", f"tool_{tool_name}", "FAILED", {"error": res["error"]}, cid, session_id)
            return res

        ALLOWED_TOOLS = {
            "control_device",
            "play_song",
            "play_user_playlist",
            "list_user_playlists",
            "next_music_track",
            "prev_music_track",
            "seek_music_track",
            "play_media",
            "stop_media",
            "projector_control",
            "run_scenario",
            "speaker_control",
            "get_climate_history",
            "show_climate_chart",
            "play_radio",
            "stop_radio",
            "stop_music",
            "scan_bluetooth_devices",
            "manage_workshop_profile",
            "search_bike_knowledge",
            "manage_presence_guest",
            "get_visitor_report",
        }
        if tool_name not in ALLOWED_TOOLS:
            res = {
                "success": False,
                "is_blocked": True,
                "error": f"Виконання інструменту '{tool_name}' заборонено: відсутній у дозволеному переліку (allowlist)."
            }
            audit_log("ai", f"tool_blocked_{tool_name}", "BLOCKED", {"tool": tool_name}, cid, session_id)
            session_mgr = getattr(self, "session_manager", None)
            if not session_mgr:
                from server.ai.session_manager import session_manager as global_sm
                session_mgr = global_sm
            session_mgr.record_tool_action(session_id, tool_name, arguments, res)
            return res

        # Strict argument schema validation
        is_valid, val_err = self._validate_tool_arguments(tool_name, arguments)
        if not is_valid:
            res = {
                "success": False,
                "error": f"Помилка валідації аргументів інструменту '{tool_name}': {val_err}"
            }
            audit_log("ai", f"tool_val_failed_{tool_name}", "BLOCKED", {"error": val_err, "arguments": arguments}, cid, session_id)
            session_mgr = getattr(self, "session_manager", None)
            if not session_mgr:
                from server.ai.session_manager import session_manager as global_sm
                session_mgr = global_sm
            session_mgr.record_tool_action(session_id, tool_name, arguments, res)
            return res

        try:
            if tool_name == "control_device":
                device = arguments.get("device")
                action = arguments.get("action")
                res = self._control_device(device, action)

            elif tool_name == "play_song":
                query = str(arguments.get("query") or "").strip()
                spk = str(arguments.get("speaker") or "").lower()
                res = self._play_song(query, spk)

            elif tool_name == "play_user_playlist":
                pl = str(arguments.get("playlist") or "LM").strip()
                spk = str(arguments.get("speaker") or "").lower()
                res = self._play_user_playlist(pl, spk)

            elif tool_name == "list_user_playlists":
                res = self._list_user_playlists()

            elif tool_name == "next_music_track":
                res = self._next_music_track()

            elif tool_name == "prev_music_track":
                res = self._prev_music_track()

            elif tool_name == "seek_music_track":
                pos = arguments.get("position")
                delta = arguments.get("delta")
                res = self._seek_music_track(position=pos, delta=delta)

            elif tool_name == "play_media":
                query = arguments.get("query", "")
                if not query:
                    res = {"success": False, "error": "Порожній пошуковий запит"}
                elif hasattr(self.garage, "projector") and self.garage.projector and self.garage.projector.is_reachable():
                    ok, _ = self.garage.projector.stream_online_video(query)
                    res = {
                        "success": bool(ok),
                        "message": f"🎬 Трансляцію '{query}' надіслано на проектор" if ok else f"Не вдалося запустити трансляцію '{query}' на проекторі"
                    }
                elif hasattr(self.garage, "speaker") and self.garage.speaker:
                    res = self._play_song(query)
                else:
                    res = {"success": False, "error": "Проектор HY350MAX офлайн, а аудіосистема недоступна"}

            elif tool_name == "stop_media":
                if hasattr(self.garage, "projector") and self.garage.projector:
                    self.garage.projector.stop_video()
                    self.garage.projector.stop_mirroring()
                    res = {"success": True, "message": "Відтворення на проекторі зупинено"}
                else:
                    res = {"success": False, "error": "Контролер проектора недоступний"}

            elif tool_name == "projector_control":
                action = arguments.get("action", "status")
                if not hasattr(self.garage, "projector") or not self.garage.projector:
                    res = {"success": False, "error": "Контролер проектора недоступний"}
                else:
                    if action == "status":
                        alive = self.garage.projector.is_reachable()
                        status = self.garage.projector.get_status()
                        if alive:
                            res = {
                                "success": True,
                                "online": True,
                                "message": f"Проектор HY350MAX ({status['ip']}:{status['port']}) онлайн і доступний у мережі."
                            }
                        else:
                            res = {
                                "success": False,
                                "online": False,
                                "error": f"Проектор HY350MAX ({status['ip']}) зараз недосяжний у локальній мережі (вимкнено або не підключено до Wi-Fi)."
                            }
                    elif action == "power_off":
                        self.garage.projector.stop_mirroring()
                        self.garage.projector.stop_video()
                        self.garage.projector.send_rest_command("POWER")
                        res = {"success": True, "message": "Проектор HY350MAX вимкнено (надіслано сигнал POWER)."}
                    elif action == "mirror_stop":
                        self.garage.projector.stop_mirroring()
                        self.garage.projector.stop_video()
                        res = {"success": True, "message": "Трансляцію на проектор зупинено."}
                    else:
                        res = {"success": False, "error": f"Невідома дія: {action}"}

            elif tool_name == "run_scenario":
                scenario = arguments.get("scenario")
                res = self._run_scenario(scenario)

            elif tool_name == "speaker_control":
                action = arguments.get("action", "status")
                target = str(arguments.get("speaker") or "jbl").lower()
                if not hasattr(self.garage, "speaker") or not self.garage.speaker:
                    res = {"success": False, "error": "Контролер колонки недоступний"}
                else:
                    if target in ("jx-bt", "jxbt", "xt-bt", "xtbt", "floor1", "1 поверх"):
                        self.garage.speaker.set_active_speaker("41:42:62:69:51:9B", "JX-BT (1-й поверх)")
                    elif target in ("jbl", "garage", "гараж"):
                        self.garage.speaker.set_active_speaker("F8:5C:7E:EE:7D:CC", "Юрій: JBL Clip 5")

                    spk_name = self.garage.speaker.name or "Колонку"
                    if action == "connect":
                        ok = self.garage.speaker.connect()
                        res = {"success": ok, "message": f"{spk_name} підключено" if ok else f"Не вдалося підключити {spk_name}"}
                    elif action == "disconnect":
                        ok = self.garage.speaker.disconnect()
                        res = {"success": ok, "message": f"{spk_name} відключено"}
                    else:
                        st = self.garage.speaker.get_status()
                        res = {"success": True, "status": st}

            elif tool_name == "get_climate_history":
                floor = arguments.get("floor", "basement")
                hours = float(arguments.get("hours", 24))
                if hasattr(self.garage, "telemetry_db") and self.garage.telemetry_db:
                    f_param = None if floor == "all" else floor
                    res_db = self.garage.telemetry_db.get_history(floor=f_param, hours=hours, limit=50)
                    stats = res_db.get("stats", {})
                    res = {
                        "success": True,
                        "floor": floor,
                        "hours": hours,
                        "stats": stats,
                        "points_count": len(res_db.get("points", []))
                    }
                else:
                    res = {"success": False, "error": "База даних телеметрії недоступна"}

            elif tool_name == "show_climate_chart":
                floor = arguments.get("floor", "basement")
                hours = float(arguments.get("hours", 24))
                chat_id = None
                if session_id and str(session_id).startswith("tg_"):
                    try:
                        chat_id = int(str(session_id).replace("tg_", ""))
                    except Exception:
                        pass
                if not chat_id and hasattr(self.garage, "telegram") and self.garage.telegram.admin_chat_id:
                    chat_id = self.garage.telegram.admin_chat_id

                fallback = False
                if floor in ("floor1", "garage", "1"):
                    floor = "basement"
                    fallback = True

                if hasattr(self.garage, "telegram") and chat_id:
                    ok = self.garage.telegram.send_climate_chart(chat_id=chat_id, floor=floor, hours=hours)
                    res = {
                        "success": ok,
                        "floor": floor,
                        "hours": hours,
                        "fallback_to_basement": fallback,
                        "message": f"Графік клімату ({floor}, {int(hours)}г) успішно надіслано в Telegram." if ok else "Не вдалося згенерувати або надіслати графік в Telegram"
                    }
                else:
                    res = {"success": False, "error": "Telegram чат недоступний для надсилання графіка"}

            elif tool_name == "play_radio":
                station = arguments.get("station") or "Hit FM"
                spk = str(arguments.get("speaker") or "").lower()
                res = self._play_radio(station, spk)

            elif tool_name in ("stop_radio", "stop_music"):
                if hasattr(self.garage, "speaker") and self.garage.speaker:
                    self.garage.speaker.stop()
                    res = {"success": True, "message": "⏹️ Відтворення аудіо/радіо/музики зупинено"}
                else:
                    res = {"success": False, "error": "Контролер колонки недоступний"}

            elif tool_name == "scan_bluetooth_devices":
                duration = arguments.get("duration", 7)
                res = self._scan_bluetooth_devices(duration=duration)

            elif tool_name == "manage_workshop_profile":
                res = self._manage_workshop_profile(arguments)

            elif tool_name == "search_bike_knowledge":
                query = arguments.get("query", "")
                category = arguments.get("category")
                res = self._search_bike_knowledge(query, category)

            elif tool_name == "manage_presence_guest":
                res = self._manage_presence_guest(arguments)

            elif tool_name == "get_visitor_report":
                days = arguments.get("days", 7)
                res = self._get_visitor_report(days=days)

            else:
                res = {"success": False, "error": f"Невідомий інструмент: {tool_name}"}

        except Exception as e:
            logger.error(f"Error executing tool {tool_name} with {arguments}: {e}")
            res = {"success": False, "error": str(e)}

        status = "SUCCESS" if res.get("success") else "FAILED"
        audit_log("ai", f"tool_{tool_name}", status, {"args": arguments, "result": res.get("message") or res.get("error")}, cid, session_id)
        session_mgr = getattr(self, "session_manager", None)
        if not session_mgr:
            from server.ai.session_manager import session_manager as global_sm
            session_mgr = global_sm
        session_mgr.record_tool_action(session_id, tool_name, arguments, res, initial_query=arguments.get("query") or arguments.get("station") or tool_name)
        return res

    def _control_device(self, device: str, action: str) -> Dict[str, Any]:
        if not hasattr(self.garage, "esp32") or not self.garage.esp32:
            return {"success": False, "error": "ESP32 контролер недоступний"}

        esp = self.garage.esp32
        if device == "door":
            return {
                "success": False,
                "is_blocked": True,
                "error": "Керування воротами вимкнено: привід воріт не планується / не встановлений",
                "door": "unknown"
            }

        elif device in ("light", "main_light", "garage_light"):
            if action == "on":
                esp.light_on()
                return {"success": True, "message": "Освітлення гаража увімкнено"}
            elif action == "off":
                if hasattr(esp, "light_off_zone"):
                    esp.light_off_zone("main_light")
                else:
                    esp.light_off()
                return {"success": True, "message": "Освітлення гаража вимкнено"}
            elif action == "toggle":
                esp.light_toggle()
                return {"success": True, "message": "Освітлення перемкнено"}

        elif device in ("basement_light", "basement"):
            if action == "off":
                if hasattr(esp, "light_off_zone"):
                    esp.light_off_zone("basement_light")
                return {"success": True, "message": "Світло в підвалі вимкнено"}
            elif action == "on":
                # Відправка коду увімкнення світла підвалу
                if hasattr(esp, "_send_serial_command"):
                    esp._send_serial_command("CMD:RF_SEND:15835393:24:1:320")
                return {"success": True, "message": "Надіслано команду увімкнення світла в підвалі"}

        elif device in ("floor2_light", "floor2"):
            if action == "off":
                if hasattr(esp, "light_off_zone"):
                    esp.light_off_zone("floor2_light")
                return {"success": True, "message": "Світло на 2-му поверсі вимкнено"}
            elif action == "on":
                if hasattr(esp, "_send_serial_command"):
                    esp._send_serial_command("CMD:RF_SEND:15835394:24:1:320")
                return {"success": True, "message": "Надіслано команду увімкнення світла на 2-му поверсі"}

        elif device == "fan":
            if action == "on":
                esp.fan_on()
                return {"success": True, "message": "Витяжну вентиляцію увімкнено"}
            elif action == "off":
                esp.fan_off()
                return {"success": True, "message": "Витяжну вентиляцію вимкнено"}
            elif action == "toggle":
                esp.fan_toggle()
                return {"success": True, "message": "Витяжну вентиляцію перемкнено"}

        return {"success": False, "error": f"Непідтримувана дія '{action}' для пристрою '{device}'"}

    def _run_scenario(self, scenario: str) -> Dict[str, Any]:
        if not hasattr(self.garage, "automation") or not self.garage.automation:
            return {"success": False, "error": "Модуль автоматизації недоступний"}

        auto = self.garage.automation
        if scenario == "arrival":
            _, msg = auto.scenario_car_arrival()
            return {"success": True, "message": msg}
        elif scenario == "departure":
            _, msg = auto.scenario_departure()
            return {"success": True, "message": msg}
        elif scenario == "night":
            _, msg = auto.scenario_night_mode()
            return {"success": True, "message": msg}
        elif scenario == "cinema":
            _, msg = auto.scenario_cinema_mode()
            return {"success": True, "message": msg}
        elif scenario == "safety":
            return {"success": False, "error": "Сценарій 'safety' недоступний: газовий датчик не встановлений"}

        return {"success": False, "error": f"Невідомий сценарій '{scenario}'"}

    def _play_radio(self, station: str, speaker_target: str = "") -> Dict[str, Any]:
        initial_st = station
        st_name = (station or "Hit FM").strip()
        if not hasattr(self.garage, "speaker") or not self.garage.speaker:
            return {
                "success": False,
                "status": "device_unavailable",
                "error": "Контролер колонки недоступний",
                "station": st_name
            }

        from server.services.radio_service import radio_service
        if speaker_target in ("jx-bt", "jxbt", "floor1", "1 поверх"):
            self.garage.speaker.set_active_speaker("41:42:62:69:51:9B", "JX-BT (1-й поверх)")
        elif speaker_target in ("jbl", "garage", "гараж"):
            self.garage.speaker.set_active_speaker("F8:5C:7E:EE:7D:CC", "Юрій: JBL Clip 5")

        raw_name = getattr(self.garage.speaker, "name", None)
        spk_name = str(raw_name) if raw_name and not hasattr(raw_name, "_mock_return_value") else "Bluetooth-колонка"
        if hasattr(self.garage.speaker, "is_connected") and not self.garage.speaker.is_connected():
            return {
                "success": False,
                "status": "device_unavailable",
                "error": f"⚠️ Не вдалося запустити радіо: колонка {spk_name} не підключена по Bluetooth або вимкнена.",
                "speaker": spk_name,
                "station": st_name
            }

        stations = radio_service.search_stations(st_name, limit=3)
        if not stations:
            stations = radio_service.get_top_stations(limit=5)

        if stations:
            st = stations[0]
            ok = self.garage.speaker.play_stream(st["url"], track_title=st["name"])
            if ok:
                return {
                    "success": True,
                    "status": "playback_started",
                    "station": st["name"],
                    "speaker": spk_name,
                    "message": f"📻 Транслюю радіо '{st['name']}' на {spk_name}."
                }
            else:
                return {
                    "success": False,
                    "status": "playback_failed",
                    "station": st["name"],
                    "speaker": spk_name,
                    "error": f"Не вдалося запустити радіо '{st['name']}' на {spk_name} (помилка аудіопотоку)."
                }
        return {
            "success": False,
            "status": "not_found",
            "station": st_name,
            "speaker": spk_name,
            "error": f"Радіостанцію '{st_name}' не знайдено."
        }

    def _play_song(self, query: str, speaker_target: str = "") -> Dict[str, Any]:
        initial_q = query
        q = (query or "").strip()
        q_lower = q.lower()

        # Guard: if query is actually a stop/silence command, stop playback instead of playing music
        stop_words = ("виключ", "виключи", "вимкни", "зупини", "стоп", "тиша", "замовкни", "досить", "годі", "stop", "pause")
        if any(sw in q_lower for sw in stop_words):
            if hasattr(self.garage, "speaker") and self.garage.speaker:
                self.garage.speaker.stop()
            return {
                "success": True,
                "message": "⏹️ Відтворення музики та радіо зупинено.",
                "action": "stop",
                "query": q
            }

        if not q or q_lower in ("пісню", "пісня", "музику", "музика", "музон", "трек", "song", "music", "якусь пісню", "просто пісню"):
            resolved_query = "ADAM - Сильно Сильно"
        else:
            resolved_query = q

        if not hasattr(self.garage, "speaker") or not self.garage.speaker:
            return {
                "success": False,
                "status": "device_unavailable",
                "error": "Контролер колонки недоступний",
                "query": resolved_query,
                "initial_query": initial_q
            }

        if speaker_target in ("jx-bt", "jxbt", "floor1", "1 поверх"):
            self.garage.speaker.set_active_speaker("41:42:62:69:51:9B", "JX-BT (1-й поверх)")
        elif speaker_target in ("jbl", "garage", "гараж"):
            self.garage.speaker.set_active_speaker("F8:5C:7E:EE:7D:CC", "Юрій: JBL Clip 5")

        raw_name = getattr(self.garage.speaker, "name", None)
        spk_name = str(raw_name) if raw_name and not hasattr(raw_name, "_mock_return_value") else "Bluetooth-колонка"

        # ЖОРСТКЕ ТАБУ НА РОСІЙСЬКУ МУЗИКУ ТА КОНТЕНТ
        RUSSIAN_CHARS = set("ёъыэЁЪЫЭ")
        if any(ch in RUSSIAN_CHARS for ch in resolved_query) or any(w in resolved_query.lower() for w in ("російськ", "русск", "по-русски", "російською")):
            return {
                "success": False,
                "status": "blocked",
                "is_blocked": True,
                "error": "🚫 Російська музика та контент під суворим табу в цій системі. Будь ласка, обирайте українські треки.",
                "speaker": spk_name,
                "query": resolved_query,
                "initial_query": initial_q
            }

        if hasattr(self.garage.speaker, "is_connected") and not self.garage.speaker.is_connected():
            return {
                "success": False,
                "status": "device_unavailable",
                "error": f"⚠️ Не вдалося відтворити на YouTube Music: колонка {spk_name} не підключена по Bluetooth або вимкнена.",
                "speaker": spk_name,
                "query": resolved_query,
                "initial_query": initial_q
            }

        # Stop projector video if active
        if hasattr(self.garage, "projector") and self.garage.projector:
            try:
                self.garage.projector.stop_video()
            except Exception:
                pass

        ok = self.garage.speaker.play_youtube(resolved_query)
        if ok:
            return {
                "success": True,
                "status": "playback_started",
                "message": f"🔊 Відтворюю на YouTube Music ({spk_name}): {resolved_query}",
                "speaker": spk_name,
                "query": resolved_query,
                "initial_query": initial_q
            }
        else:
            return {
                "success": False,
                "status": "ytmusic_error",
                "error": f"Помилка YouTube Music: не вдалося запустити відтворення на {spk_name} для '{resolved_query}'.",
                "speaker": spk_name,
                "query": resolved_query,
                "initial_query": initial_q
            }

    def _play_user_playlist(self, playlist_name: str, speaker_target: str = "", shuffle: bool = False) -> Dict[str, Any]:
        if not hasattr(self.garage, "speaker") or not self.garage.speaker:
            return {"success": False, "error": "Контролер колонки недоступний"}

        if speaker_target in ("jx-bt", "jxbt", "floor1", "1 поверх"):
            self.garage.speaker.set_active_speaker("41:42:62:69:51:9B", "JX-BT (1-й поверх)")
        elif speaker_target in ("jbl", "garage", "гараж"):
            self.garage.speaker.set_active_speaker("F8:5C:7E:EE:7D:CC", "Юрій: JBL Clip 5")

        # Stop projector video if active
        if hasattr(self.garage, "projector") and self.garage.projector:
            try:
                self.garage.projector.stop_video()
            except Exception:
                pass

        ok, p_title, t_title = self.garage.speaker.play_playlist(playlist_name, shuffle=shuffle)
        spk_name = self.garage.speaker.name or "Bluetooth-колонці"
        if ok:
            return {"success": True, "message": f"🔊 Відтворюю з '{p_title}' на YouTube Music ({spk_name}): {t_title}"}
        return {"success": False, "error": f"Не вдалося знайти або відтворити плейлист '{playlist_name}' на {spk_name}"}

    def _list_user_playlists(self) -> Dict[str, Any]:
        from server.services.ytmusic_service import ytmusic_service
        pls = ytmusic_service.get_user_playlists()
        return {"success": True, "playlists": pls}

    def _next_music_track(self) -> Dict[str, Any]:
        if not hasattr(self.garage, "speaker") or not self.garage.speaker:
            return {"success": False, "error": "Контролер колонки недоступний"}
        ok, p_title, t_title = self.garage.speaker.play_next()
        spk_name = self.garage.speaker.name or "Bluetooth-колонці"
        if ok:
            return {"success": True, "message": f"⏭️ Наступний трек на YouTube Music ({spk_name}): {t_title} (з '{p_title}')"}
        return {"success": False, "error": f"Не вдалося перемкнути на наступний трек на {spk_name}"}

    def _prev_music_track(self) -> Dict[str, Any]:
        if not hasattr(self.garage, "speaker") or not self.garage.speaker:
            return {"success": False, "error": "Контролер колонки недоступний"}
        ok, p_title, t_title = self.garage.speaker.play_prev()
        spk_name = self.garage.speaker.name or "Bluetooth-колонці"
        if ok:
            return {"success": True, "message": f"⏮️ Попередній трек на YouTube Music ({spk_name}): {t_title} (з '{p_title}')"}
        return {"success": False, "error": f"Не вдалося повернутися до попереднього треку на {spk_name}"}

    def _seek_music_track(self, position: Optional[int] = None, delta: Optional[int] = None) -> Dict[str, Any]:
        if not hasattr(self.garage, "speaker") or not self.garage.speaker:
            return {"success": False, "error": "Контролер колонки недоступний"}
        target_pos = position
        if delta is not None:
            st = self.garage.speaker.get_status()
            cur = st.get("elapsed_seconds", 0)
            target_pos = max(0, cur + int(delta))
        if target_pos is None:
            return {"success": False, "error": "Не вказано секунди для перемотування"}
        ok = self.garage.speaker.seek(int(target_pos))
        if ok:
            return {"success": True, "message": f"⏩ Перемотано на позицію {int(target_pos)} сек"}
        return {"success": False, "error": "Не вдалося перемотати трек"}

    def _scan_bluetooth_devices(self, duration: int = 7) -> Dict[str, Any]:
        try:
            d = max(3, min(int(duration or 7), 15))
            from server.webapp import _scan_all_ble
            devs = _scan_all_ble(duration=d)

            known_devices = {
                "A4:C1:38:CC:CA:49": {"name": "Xiaomi Mijia (Підвал)", "type": "Кліматичний BLE-датчик", "location": "Підвал"},
                "A4:C1:38:EC:EC:6C": {"name": "Xiaomi Mijia (2-й поверх)", "type": "Кліматичний BLE-датчик", "location": "2-й поверх"},
                "41:42:62:69:51:9B": {"name": "JX-BT (1-й поверх)", "type": "Bluetooth-акустика", "location": "1-й поверх"},
                "F8:5C:7E:EE:7D:CC": {"name": "JBL Clip 5 (Гараж)", "type": "Bluetooth-колонка", "location": "Гараж"},
                "B8:7E:39:88:22:9B": {"name": "Motorola Edge 50 Pro (Юрій)", "type": "Смартфон власника (Bluetooth)", "location": "Присутність"},
            }

            formatted = []
            for dev in devs:
                mac = dev.get("mac", "").upper().strip()
                if not mac:
                    continue
                name = dev.get("name") or (known_devices.get(mac, {}).get("name") if mac in known_devices else "Невідомий BLE пристрій")
                if mac in known_devices:
                    name = known_devices[mac]["name"]
                dev_type = known_devices.get(mac, {}).get("type", "BLE-пристрій")
                is_conn = bool(dev.get("connected", False))
                formatted.append({
                    "mac": mac,
                    "name": name,
                    "type": dev_type,
                    "rssi": dev.get("rssi", -99),
                    "connected": is_conn,
                    "source": dev.get("source", "ble_live")
                })

            # Сортуємо: спочатку підключені пристрої, далі за рівнем сигналу
            formatted.sort(key=lambda x: (1 if x.get("connected") else 0, x.get("rssi", -99)), reverse=True)

            msg = f"Виявлено {len(formatted)} Bluetooth/BLE пристроїв у радіоефірі." if formatted else "У радіоефірі Bluetooth наразі не виявлено жодного активного пристрою."
            return {
                "success": True,
                "count": len(formatted),
                "devices": formatted,
                "message": msg
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Помилка сканування Bluetooth ефіру: {e}"
            }

    def _manage_workshop_profile(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from server.memory.user_profile import user_profile_manager
            action = arguments.get("action", "get")
            if action == "get":
                prof = user_profile_manager.load_profile()
                return {
                    "success": True,
                    "profile": prof,
                    "message": "Профіль веломайстерні успішно отримано."
                }
            elif action == "add_client_bike":
                model = arguments.get("bike_model") or "Невідомий велосипед"
                client = arguments.get("client_name") or "Клієнт"
                work = arguments.get("work_description") or "ТО та діагностика"
                status = arguments.get("status") or "in_progress"
                entry = user_profile_manager.add_client_bike(model=model, client=client, work=work, status=status)
                return {
                    "success": True,
                    "bike": entry,
                    "message": f"🚲 Велосипед '{model}' ({client}) успішно додано до журналу ремонту (ID: {entry['id']})."
                }
            elif action == "update_bike_status":
                bike_id = arguments.get("bike_id") or arguments.get("bike_model") or ""
                status = arguments.get("status") or "completed"
                ok = user_profile_manager.update_bike_status(bike_id, status)
                if ok:
                    return {
                        "success": True,
                        "message": f"Статус ремонту для '{bike_id}' змінено на '{status}'."
                    }
                return {
                    "success": False,
                    "error": f"Велосипед з ідентифікатором/назвою '{bike_id}' не знайдено в журналі."
                }
            elif action == "add_tool":
                tool_name = arguments.get("tool_name", "")
                if not tool_name:
                    return {"success": False, "error": "Не вказано назву інструменту"}
                user_profile_manager.add_tool(tool_name)
                return {
                    "success": True,
                    "message": f"🛠️ Інструмент '{tool_name}' додано до обладнання майстерні."
                }
            elif action == "add_note":
                note = arguments.get("note", "")
                if not note:
                    return {"success": False, "error": "Не вказано текст нотатки"}
                user_profile_manager.add_note(note)
                return {
                    "success": True,
                    "message": f"📝 Нотатку додано: '{note}'."
                }
            return {"success": False, "error": f"Невідома дія: {action}"}
        except Exception as e:
            return {"success": False, "error": f"Помилка роботи з профілем: {e}"}

    def _search_bike_knowledge(self, query: str, category: Optional[str] = None) -> Dict[str, Any]:
        try:
            from server.memory.knowledge_base import bike_knowledge_base
            results = bike_knowledge_base.search(query=query, category=category)
            return {
                "success": True,
                "count": len(results),
                "query": query,
                "category": category,
                "results": results,
                "message": f"Знайдено {len(results)} відповідностей у базі знань веломайстерні."
            }
        except Exception as e:
            return {"success": False, "error": f"Помилка пошуку в базі знань: {e}"}

    def _manage_presence_guest(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not hasattr(self.garage, "presence") or not self.garage.presence:
                return {"success": False, "error": "Менеджер присутності недоступний"}

            action = arguments.get("action", "list")
            if action == "list":
                status = self.garage.presence.get_status()
                return {
                    "success": True,
                    "devices": status.get("devices", {}),
                    "present_now": status.get("present_now", []),
                    "message": f"У базі зареєстровано {len(status.get('devices', {}))} пристроїв/осіб."
                }
            elif action == "register":
                name = arguments.get("name")
                if not name:
                    return {"success": False, "error": "Не вказано ім'я гостя"}
                mac = str(arguments.get("mac") or "").upper().strip()
                role = arguments.get("role") or "guest"
                clean_name = name.lower().replace(" ", "_")
                device_id = arguments.get("device_id") or (f"guest_{clean_name}" if role == "guest" else clean_name)
                dev_type = arguments.get("device_type") or "phone"
                dev_name = arguments.get("device_name") or f"Телефон {name}"
                absence_msg = arguments.get("absence_voice_message") or ""
                tg_id = arguments.get("telegram_chat_id")
                notify_owner = arguments.get("notify_owner", True)

                item = self.garage.presence.register_device(
                    device_id=device_id,
                    name=name,
                    role=role,
                    device_type=dev_type,
                    device_name=dev_name,
                    classic_mac=mac if not arguments.get("is_ble") else "",
                    ble_mac=mac if arguments.get("is_ble", True) else "",
                    auto_welcome=True,
                    telegram_chat_id=tg_id,
                    absence_voice_message=absence_msg,
                    notify_owner=notify_owner
                )
                display_msg = absence_msg if absence_msg else f"{name}, Юри в гаражі немає..."
                return {
                    "success": True,
                    "device": item,
                    "message": f"✅ Гостя '{name}' успішно додано до бази присутності. Фраза за відсутності: '{display_msg}'."
                }
            elif action == "update":
                raw_id = arguments.get("device_id") or (arguments.get("name") or "").lower().replace(" ", "_")
                dev_id = raw_id
                if dev_id not in self.garage.presence.devices and f"guest_{dev_id}" in self.garage.presence.devices:
                    dev_id = f"guest_{dev_id}"
                clean_args = {k: v for k, v in arguments.items() if k not in ("action", "device_id")}
                updated = self.garage.presence.update_device(dev_id, **clean_args)
                if not updated:
                    return {"success": False, "error": f"Пристрій '{dev_id}' не знайдено в базі"}
                return {
                    "success": True,
                    "device": updated,
                    "message": f"✅ Дані гостя '{updated.get('name')}' успішно оновлено."
                }
            elif action == "delete":
                raw_id = arguments.get("device_id") or (arguments.get("name") or "").lower().replace(" ", "_")
                dev_id = raw_id
                if dev_id not in self.garage.presence.devices and f"guest_{dev_id}" in self.garage.presence.devices:
                    dev_id = f"guest_{dev_id}"
                ok = self.garage.presence.remove_device(dev_id)
                if ok:
                    return {"success": True, "message": f"Пристрій/гостя '{dev_id}' видалено з бази."}
                return {"success": False, "error": f"Пристрій '{dev_id}' не знайдено для видалення."}
            return {"success": False, "error": f"Невідома дія: {action}"}
        except Exception as e:
            return {"success": False, "error": f"Помилка керування гостем: {e}"}

    def _get_visitor_report(self, days: Optional[int] = 7, limit: int = 50) -> Dict[str, Any]:
        try:
            if not hasattr(self.garage, "presence") or not self.garage.presence:
                return {"success": False, "error": "Менеджер присутності недоступний"}
            d = int(days or 7)
            rep = self.garage.presence.get_visitor_report(limit=limit, days=d)
            return {
                "success": True,
                "report": rep,
                "message": f"Звіт відвідувань сформовано: {rep.get('total_registered_guests')} зареєстрованих гостей, {rep.get('visits_today_count')} візитів за сьогодні."
            }
        except Exception as e:
            return {"success": False, "error": f"Помилка формування звіту відвідувань: {e}"}


