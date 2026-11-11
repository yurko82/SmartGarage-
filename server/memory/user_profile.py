"""Менеджер довготривалого профілю користувача та веломайстерні Юрія."""
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from server.config import config

logger = logging.getLogger(__name__)


class UserProfileManager:
    """Керує довготривалою пам'яттю профілю користувача, веломайстерні, інструментів та велосипедів у ремонті."""

    @property
    def storage_path(self) -> Path:
        if getattr(self, "_custom_storage_path", None):
            return self._custom_storage_path
        from server.utils.paths import get_memory_dir
        return get_memory_dir() / "user_profile.json"

    @storage_path.setter
    def storage_path(self, val):
        self._custom_storage_path = Path(val) if val else None

    def __init__(self, storage_path: Optional[Path] = None):
        self._custom_storage_path = Path(storage_path) if storage_path is not None else None

        if not self.storage_path.exists():
            self._init_default_profile()

    def _init_default_profile(self):
        default_data = {
            "owner": {
                "name": "Власник",
                "callsign": "Майстер",
                "role": "Власник майстерні Smart Garage та майстер з обслуговування велосипедів"
            },
            "workshop": {
                "name": "Веломайстерня Smart Garage",
                "specialization": "Професійне технічне обслуговування (ТО), налаштування, ремонт та апгрейд велосипедів (MTB, Gravel, Road, E-Bike)",
                "not_servicing": "Автомобілі категорично НЕ ремонтуються і НЕ обслуговуються",
                "services": [
                  "Повне сезонне та планове ТО велосипедів",
                  "Прокачування та ремонт дискових гідравлічних гальм (Shimano, SRAM, Magura)",
                  "Обслуговування амортизаційних вилок та задніх амортизаторів (RockShox, Fox)",
                  "Налаштування трансмісій (Shimano Di2, SRAM AXS, 8-12 швидкостей)",
                  "Встановлення безкамерних покришок (Tubeless)",
                  "Збірка коліс та натяжка спиць за тензометром",
                  "Заміна підшипників, кареток (BSA, PressFit, DUB) та рульових колонок",
                  "Парафінування ланцюгів та контроль зносу трансмісії"
                ],
                "tools": [
                  "Ремонтний стенд для велосипедів",
                  "Динамометричні ключі (2-24 Нм, 10-60 Нм)",
                  "Комплекти для прокачування гальм (Mineral Oil та DOT 5.1)",
                  "Станок для виправлення коліс та тензометр",
                  "Преси підшипників та кареток DUB/PressFit",
                  "Tubeless компресор-бустер",
                  "Вирівнювач півника перемикача (DAG)",
                  "Калібри зносу ланцюга (0.5% та 0.75%)"
                ],
                "client_bikes": [],
                "notes": []
            },
            "preferences": {
                "radio_stations": ["Hit FM", "Radio ROKS", "Kiss FM", "Lounge FM"],
                "music_source": "YouTube Music на колонках JBL Clip 5 та JX-BT"
            }
        }
        self.save_profile(default_data)

    def load_profile(self) -> Dict[str, Any]:
        """Завантажує профіль з диска."""
        try:
            if not self.storage_path.exists():
                self._init_default_profile()
            text = self.storage_path.read_text(encoding="utf-8").strip()
            if not text:
                return {}
            return json.loads(text)
        except Exception as e:
            logger.warning(f"Не вдалося прочитати профіль користувача: {e}")
            return {}

    def save_profile(self, data: Dict[str, Any]):
        """Атомарно зберігає профіль на диск."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.storage_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.storage_path)
        except Exception as e:
            logger.error(f"Помилка збереження профілю користувача: {e}")

    def add_client_bike(self, model: str, client: str = "", work: str = "", status: str = "in_progress") -> Dict[str, Any]:
        """Додає велосипед клієнта в журнал ремонту."""
        data = self.load_profile()
        workshop = data.setdefault("workshop", {})
        client_bikes = workshop.setdefault("client_bikes", [])
        bike_id = f"bike_{uuid.uuid4().hex[:6]}"
        entry = {
            "id": bike_id,
            "model": model.strip(),
            "client": client.strip() or "Клієнт",
            "work": work.strip() or "Діагностика та ТО",
            "status": status,
            "created_at": time.strftime("%Y-%m-%d %H:%M")
        }
        client_bikes.append(entry)
        self.save_profile(data)
        return entry

    def update_bike_status(self, bike_id: str, status: str) -> bool:
        """Оновлює статус ремонту велосипеда (in_progress, completed, waiting_parts)."""
        data = self.load_profile()
        client_bikes = data.get("workshop", {}).get("client_bikes", [])
        for b in client_bikes:
            if b.get("id") == bike_id or bike_id.lower() in b.get("model", "").lower():
                b["status"] = status
                b["updated_at"] = time.strftime("%Y-%m-%d %H:%M")
                self.save_profile(data)
                return True
        return False

    def add_tool(self, tool_name: str) -> bool:
        """Додає новий інструмент до обладнання майстерні."""
        data = self.load_profile()
        tools = data.setdefault("workshop", {}).setdefault("tools", [])
        if tool_name not in tools:
            tools.append(tool_name.strip())
            self.save_profile(data)
            return True
        return False

    def add_note(self, note_text: str) -> bool:
        """Додає робочу нотатку до майстерні."""
        data = self.load_profile()
        notes = data.setdefault("workshop", {}).setdefault("notes", [])
        entry = f"[{time.strftime('%Y-%m-%d')}] {note_text.strip()}"
        notes.append(entry)
        self.save_profile(data)
        return True

    def get_summary_prompt(self) -> str:
        """Генерує стислий структурований опис профілю майстерні для системного промпту."""
        prof = self.load_profile()
        workshop = prof.get("workshop", {})
        spec = workshop.get("specialization", "Обслуговування велосипедів")
        tools = workshop.get("tools", [])
        client_bikes = [b for b in workshop.get("client_bikes", []) if b.get("status") != "completed"]
        notes = workshop.get("notes", [])

        lines = [
            "### ПРОФІЛЬ ВЕЛОМАЙСТЕРНІ ТА ВЛАСНИКА (Workshop Memory):",
            f"- Власник: Юрій. Роль: майстер з обслуговування велосипедів.",
            f"- Спеціалізація: {spec}.",
            f"- Важливе правило: Юрій категорично НЕ ремонтує і НЕ обслуговує автомобілі.",
        ]
        if tools:
            sample_tools = ", ".join(tools[:6])
            lines.append(f"- Наявне обладнання та інструменти: {sample_tools} тощо.")
        if client_bikes:
            active_bikes_str = "; ".join([f"{b['model']} ({b['work']}, статус: {b['status']})" for b in client_bikes[:4]])
            lines.append(f"- Велосипеди в роботі зараз: {active_bikes_str}.")
        if notes:
            lines.append(f"- Останні робочі нотатки: {notes[-1]}.")

        return "\n".join(lines)


# Глобальний екземпляр
user_profile_manager = UserProfileManager()
