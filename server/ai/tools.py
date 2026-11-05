"""Tools and Function Calling declarations for SmartGarage AI."""
import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from server.security.audit import audit_log

logger = logging.getLogger(__name__)

GARAGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "control_device",
            "description": "Керування фізичними виконавчими пристроями гаража через ESP32-S3 (освітлення, витяжна вентиляція). Привід воріт не планується.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "enum": ["light", "fan"],
                        "description": "Тип пристрою: light (основне освітлення), fan (витяжна вентиляція)."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["on", "off", "toggle"],
                        "description": "Дія: on/off/toggle для light та fan."
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
    }
]


class ToolDispatcher:
    """Dispatches and executes tool calls against SmartGarage hardware."""

    def __init__(self, garage=None, session_mgr=None):
        self.garage = garage
        self.session_manager = session_mgr

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
            "run_scenario",
            "speaker_control",
            "get_climate_history",
            "show_climate_chart",
            "play_radio",
            "stop_radio",
            "stop_music",
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

        elif device == "light":
            if action == "on":
                esp.light_on()
                return {"success": True, "message": "Освітлення увімкнено"}
            elif action == "off":
                esp.light_off()
                return {"success": True, "message": "Освітлення вимкнено"}
            elif action == "toggle":
                esp.light_toggle()
                return {"success": True, "message": "Освітлення перемкнено"}

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


