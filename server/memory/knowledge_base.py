"""База знань з обслуговування велосипедів (Bicycle Maintenance Knowledge Base)."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.config import config

logger = logging.getLogger(__name__)


class BikeKnowledgeBase:
    """Забезпечує швидкий пошук технічних регламентів, моментів затяжки, допусків рідин та налаштувань підвіски."""

    def __init__(self, kb_dir: Path | None = None):
        if kb_dir is not None:
            self.kb_dir = Path(kb_dir)
        else:
            mem_path = config.get("memory", {}).get("path", "./memory")
            self.kb_dir = Path(mem_path) / "knowledge_base"

        self._cache: dict[str, Any] = {}
        self._load_all()

    def _load_all(self):
        """Завантажує всі файли бази знань у кеш."""
        self._cache.clear()
        if not self.kb_dir.exists():
            logger.debug(f"Директорія бази знань не знайдена: {self.kb_dir}")
            return

        for p in self.kb_dir.glob("*.json"):
            try:
                content = json.loads(p.read_text(encoding="utf-8"))
                cat = content.get("category", p.stem)
                self._cache[cat] = content
            except Exception as e:
                logger.warning(f"Не вдалося прочитати файл бази знань {p.name}: {e}")

    def list_categories(self) -> list[str]:
        """Повертає перелік доступних категорій бази знань."""
        if not self._cache:
            self._load_all()
        return list(self._cache.keys())

    def get_category(self, category: str) -> dict[str, Any] | None:
        """Отримує повний розділ бази знань."""
        if not self._cache:
            self._load_all()
        return self._cache.get(category.lower())

    def search(self, query: str, category: str | None = None) -> list[dict[str, Any]]:
        """Пошук у базі знань за ключовими словами."""
        if not self._cache:
            self._load_all()

        query_clean = query.lower().strip()
        tokens = [t for t in query_clean.split() if len(t) > 2]
        if not tokens:
            tokens = [query_clean]

        results = []

        categories_to_search = [category.lower()] if (category and category.lower() in self._cache) else list(self._cache.keys())

        for cat_name in categories_to_search:
            data = self._cache.get(cat_name, {})
            title = data.get("title", "")

            # 1. Спеціальний пошук для списку items (наприклад, torque_specs)
            if "items" in data and isinstance(data["items"], list):
                for item in data["items"]:
                    comp = str(item.get("component", "")).lower()
                    notes = str(item.get("notes", "")).lower()
                    score = sum(1 for t in tokens if (t in comp or t in notes))
                    if score > 0 or any(t in comp for t in tokens):
                        results.append({
                            "category": cat_name,
                            "type": "torque_spec",
                            "score": score,
                            "title": item.get("component"),
                            "data": item
                        })

            # 2. Пошук по вкладених словниках (brakes, suspension, drivetrain, standards)
            for section_key, section_val in data.items():
                if section_key in ("category", "title", "description", "items"):
                    continue
                sec_str = json.dumps(section_val, ensure_ascii=False).lower()
                score = sum(1 for t in tokens if t in sec_str)
                if score > 0:
                    results.append({
                        "category": cat_name,
                        "type": section_key,
                        "score": score,
                        "title": f"{title} - {section_key}",
                        "data": section_val
                    })

        # Сортування результатів за релевантністю
        results.sort(key=lambda r: r.get("score", 0), reverse=True)
        return results[:8]


# Глобальний екземпляр
bike_knowledge_base = BikeKnowledgeBase()
