import logging
import threading
import time
import uuid
from typing import Any, Callable

logger = logging.getLogger("smartgarage.scheduler")


class ActionScheduler:
    """Керує плануванням та відкладеним виконанням дій і команд (таймери, відкладений запуск)."""

    def __init__(self):
        self._actions: dict[str, dict[str, Any]] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def schedule(
        self,
        delay_seconds: float,
        action_fn: Callable[[], Any],
        description: str,
        session_id: str = "default",
        on_complete: Callable[[Any], None] | None = None
    ) -> dict[str, Any]:
        """Запланувати виконання функції через delay_seconds секунд."""
        if delay_seconds < 0:
            delay_seconds = 0.0

        action_id = f"timer_{uuid.uuid4().hex[:8]}"
        now = time.time()
        execute_at = now + delay_seconds

        record = {
            "id": action_id,
            "session_id": session_id,
            "description": description,
            "delay_seconds": round(delay_seconds, 1),
            "created_at": now,
            "execute_at": execute_at,
            "status": "pending",
            "result": None,
            "error": None
        }

        with self._lock:
            self._actions[action_id] = record

            if delay_seconds == 0:
                # Виконати негайно
                threading.Thread(
                    target=self._execute_action,
                    args=(action_id, action_fn, on_complete),
                    daemon=True,
                    name=f"ActionImmediate_{action_id}"
                ).start()
            else:
                timer = threading.Timer(
                    delay_seconds,
                    self._execute_action,
                    args=(action_id, action_fn, on_complete)
                )
                timer.daemon = True
                timer.name = f"ActionTimer_{action_id}"
                self._timers[action_id] = timer
                timer.start()
                logger.info(f"⏳ [SCHEDULER] Заплановано дію '{description}' через {delay_seconds:.1f} сек (ID: {action_id})")

        return record

    def cancel(self, action_id: str) -> bool:
        """Скасувати заплановану дію."""
        with self._lock:
            timer = self._timers.pop(action_id, None)
            if timer:
                timer.cancel()
            if action_id in self._actions:
                self._actions[action_id]["status"] = "cancelled"
                logger.info(f"🛑 [SCHEDULER] Скасовано дію {action_id}")
                return True
        return False

    def list_active(self) -> list[dict[str, Any]]:
        """Отримати список активних (очікуючих) дій."""
        with self._lock:
            return [
                dict(act) for act in self._actions.values()
                if act.get("status") == "pending"
            ]

    def clear(self):
        """Зупинити всі таймери та очистити чергу (для тестів або перезапуску)."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            self._actions.clear()

    def _execute_action(
        self,
        action_id: str,
        action_fn: Callable[[], Any],
        on_complete: Callable[[Any], None] | None = None
    ):
        with self._lock:
            self._timers.pop(action_id, None)
            if action_id in self._actions:
                if self._actions[action_id]["status"] == "cancelled":
                    return
                self._actions[action_id]["status"] = "running"
                desc = self._actions[action_id]["description"]
            else:
                desc = action_id

        logger.info(f"🚀 [SCHEDULER] Спрацював таймер! Виконую дію: '{desc}' (ID: {action_id})")
        res = None
        err = None
        try:
            res = action_fn()
            logger.info(f"✅ [SCHEDULER] Дію '{desc}' успішно виконано.")
        except Exception as e:
            err = str(e)
            logger.error(f"❌ [SCHEDULER] Помилка виконання дії '{desc}': {e}")

        with self._lock:
            if action_id in self._actions:
                self._actions[action_id]["status"] = "completed" if not err else "failed"
                self._actions[action_id]["result"] = res
                self._actions[action_id]["error"] = err

        if on_complete and callable(on_complete):
            try:
                on_complete(res if not err else err)
            except Exception as e_comp:
                logger.warning(f"[SCHEDULER] Помилка в on_complete callback: {e_comp}")


# Глобальний екземпляр планувальника
action_scheduler = ActionScheduler()
