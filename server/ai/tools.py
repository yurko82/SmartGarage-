"""Tools and Function Calling declarations for SmartGarage AI."""
import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

GARAGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "control_device",
            "description": "Керування фізичними виконавчими пристроями гаража через ESP32-S3 (ворота, освітлення, витяжна вентиляція).",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "enum": ["door", "light", "fan"],
                        "description": "Тип пристрою: door (гаражні ворота), light (основне освітлення), fan (витяжна вентиляція)."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["open", "close", "on", "off", "toggle"],
                        "description": "Дія: для door використовуй open/close/toggle, для light та fan використовуй on/off/toggle."
                    }
                },
                "required": ["device", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "Трансляція музики, відео, кліпів чи фільмів на проектор HY350MAX у гаражі.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Пошуковий запит YouTube, назва пісні, виконавця, кліпу або URL."
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
                        "enum": ["arrival", "departure", "night", "cinema", "safety"],
                        "description": "Сценарій: arrival (прибуття), departure (від'їзд), night (нічна охорона/блокування), cinema (кінотеатр/проектор), safety (екстрене провітрювання)."
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
            "description": "Керування Bluetooth-колонкою JBL Clip 5 (підключення / відключення / стан).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["connect", "disconnect", "status"],
                        "description": "Дія: connect (підключити), disconnect (відключити), status (перевірити стан)."
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
    }
]


class ToolDispatcher:
    """Dispatches and executes tool calls against SmartGarage hardware."""

    def __init__(self, garage=None):
        self.garage = garage

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call and return structured result dict."""
        if not self.garage:
            return {"success": False, "error": "SmartGarage instance not bound to ToolDispatcher"}

        try:
            if tool_name == "control_device":
                device = arguments.get("device")
                action = arguments.get("action")
                return self._control_device(device, action)

            elif tool_name == "play_media":
                query = arguments.get("query", "")
                if not query:
                    return {"success": False, "error": "Порожній пошуковий запит"}
                if hasattr(self.garage, "projector") and self.garage.projector:
                    ok = self.garage.projector.stream_online_video(query)
                    return {
                        "success": ok,
                        "message": f"Трансляцію '{query}' надіслано на проектор" if ok else f"Не вдалося запустити трансляцію '{query}' на проекторі"
                    }
                return {"success": False, "error": "Контролер проектора недоступний"}

            elif tool_name == "stop_media":
                if hasattr(self.garage, "projector") and self.garage.projector:
                    self.garage.projector.stop_video()
                    self.garage.projector.stop_mirroring()
                    return {"success": True, "message": "Відтворення на проекторі зупинено"}
                return {"success": False, "error": "Контролер проектора недоступний"}

            elif tool_name == "run_scenario":
                scenario = arguments.get("scenario")
                return self._run_scenario(scenario)

            elif tool_name == "speaker_control":
                action = arguments.get("action", "status")
                if not hasattr(self.garage, "speaker") or not self.garage.speaker:
                    return {"success": False, "error": "Контролер колонки недоступний"}
                if action == "connect":
                    ok = self.garage.speaker.connect()
                    return {"success": ok, "message": "Колонку JBL Clip 5 підключено" if ok else "Не вдалося підключити колонку JBL Clip 5"}
                elif action == "disconnect":
                    ok = self.garage.speaker.disconnect()
                    return {"success": ok, "message": "Колонку JBL Clip 5 відключено"}
                else:
                    st = self.garage.speaker.get_status()
                    return {"success": True, "status": st}

            elif tool_name == "get_climate_history":
                floor = arguments.get("floor", "basement")
                hours = float(arguments.get("hours", 24))
                if hasattr(self.garage, "telemetry_db") and self.garage.telemetry_db:
                    f_param = None if floor == "all" else floor
                    res = self.garage.telemetry_db.get_history(floor=f_param, hours=hours, limit=50)
                    stats = res.get("stats", {})
                    return {
                        "success": True,
                        "floor": floor,
                        "hours": hours,
                        "stats": stats,
                        "points_count": len(res.get("points", []))
                    }
                return {"success": False, "error": "База даних телеметрії недоступна"}

            else:
                return {"success": False, "error": f"Невідомий інструмент: {tool_name}"}

        except Exception as e:
            logger.error(f"Error executing tool {tool_name} with {arguments}: {e}")
            return {"success": False, "error": str(e)}

    def _control_device(self, device: str, action: str) -> Dict[str, Any]:
        if not hasattr(self.garage, "esp32") or not self.garage.esp32:
            return {"success": False, "error": "ESP32 контролер недоступний"}

        esp = self.garage.esp32
        if device == "door":
            if action in ("open", "on"):
                esp.door_open()
                return {"success": True, "message": "Ворота відчиняються (надіслано сигнал реле)"}
            elif action in ("close", "off"):
                esp.door_close()
                return {"success": True, "message": "Ворота зачиняються (надіслано сигнал реле)"}
            elif action == "toggle":
                esp.door_toggle()
                return {"success": True, "message": "Ворота перемкнено (сигнал реле)"}

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
            _, msg = auto.scenario_gas_alarm()
            return {"success": True, "message": msg}

        return {"success": False, "error": f"Невідомий сценарій '{scenario}'"}
