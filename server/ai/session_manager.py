"""Менеджер сесій, збереження контексту діалогів та механізм повторних дій (Pending Actions) для SmartGarage."""
from dataclasses import dataclass, field, asdict
import json
import logging
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Патерни для виявлення персональних даних або даних сенсорів у session ID
PERSONAL_DATA_PATTERNS = [
    re.compile(r"(?:yuri|yurko|юрій|юрко|admin|адмін|root)", re.IGNORECASE),
    re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),  # email
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),                      # IPv4
    re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"),         # MAC-адреса
]

SESSION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{8,64}$")

# Патерни наміру повторити дію («спробуй ще раз», «повтори», «так само», «не вийшло» тощо)
RETRY_INTENT_REGEX = re.compile(
    r"^(?:ну\s+)?(?:будь\s*ласка\s+)?"
    r"(?:спробуй|попробуй|зроби|повтори|повторити)?"
    r"\s*"
    r"(?:ще\s*раз(?:ок)?|знову|так\s+само|спробу|команду|дію|не\s+вийшло|не\s+спрацювало|не\s+вийшла|ще|retry|try\s+again)"
    r"[\s.!?]*$",
    re.IGNORECASE
)


# Заборонені загальні та глобальні ідентифікатори сесій
FORBIDDEN_GENERIC_IDS = {"web_console", "default", "global", "console", "all", "anonymous"}

def is_safe_session_id(session_id: str) -> bool:
    """Перевіряє валідність та безпечність ідентифікатора сесії.
    Забороняє довільні символи, загальні імена (web_console), небезпечну довжину та наявність персональних/присутніх даних.
    """
    if not session_id or not isinstance(session_id, str):
        return False
    if session_id.lower().strip() in FORBIDDEN_GENERIC_IDS:
        return False
    if not SESSION_ID_REGEX.match(session_id):
        return False
    for pat in PERSONAL_DATA_PATTERNS:
        if pat.search(session_id):
            return False
    return True


def is_retry_intent(prompt: str) -> bool:
    """Визначає, чи є запит користувача запитом на повторення останньої дії."""
    if not prompt or not isinstance(prompt, str):
        return False
    clean = prompt.strip().lower()
    if clean in (
        "ще раз", "ще разок", "повтори", "повторити", "так само",
        "не вийшло", "не спрацювало", "знову", "спробуй ще",
        "спробуй ще раз", "спробуй знову", "повтори спробу",
        "зроби так само", "це не вийшло", "воно не спрацювало"
    ):
        return True
    return bool(RETRY_INTENT_REGEX.match(clean))


def validate_openrouter_messages(messages: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """Перевіряє відповідність послідовності повідомлень стандарту Function Calling OpenRouter / OpenAI.
    Вимоги:
    1. Повідомлення assistant з tool_calls має одразу супроводжуватися повідомленнями з role='tool'
       для кожного id з tool_calls.
    2. Кожне role='tool' повідомлення повинно мати tool_call_id, ім'я та рядковий контент.
    3. Заборонені осиротілі tool повідомлення.
    4. Після відповідей інструментів має йти фінальне повідомлення assistant.
    """
    if not isinstance(messages, list):
        return False, "Список повідомлень має бути списком."

    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        role = msg.get("role")
        if role not in ("system", "user", "assistant", "tool"):
            return False, f"Непідтримувана роль повідомлення: {role}"

        if role == "tool":
            return False, f"Осиротіле повідомлення інструменту на позиції {i} без попереднього виклику tool_calls."

        if role == "assistant" and msg.get("tool_calls"):
            tool_calls = msg.get("tool_calls")
            if not isinstance(tool_calls, list) or not tool_calls:
                return False, f"Повідомлення assistant на позиції {i} містить порожній або некоректний tool_calls."

            expected_ids = []
            for tc in tool_calls:
                tc_id = tc.get("id")
                fn = tc.get("function", {})
                if not tc_id or not fn.get("name"):
                    return False, f"Виклик інструменту не містить валідного id або імені функції."
                expected_ids.append(tc_id)

            # Наступні повідомлення повинні бути відповідями цих інструментів
            matched_ids = []
            j = i + 1
            while j < n and messages[j].get("role") == "tool":
                t_msg = messages[j]
                t_id = t_msg.get("tool_call_id")
                if not t_id or t_id not in expected_ids:
                    return False, f"Повідомлення інструменту на позиції {j} має невідомий tool_call_id '{t_id}'."
                if not isinstance(t_msg.get("content"), str):
                    return False, f"Контент повідомлення інструменту на позиції {j} має бути рядком."
                matched_ids.append(t_id)
                j += 1

            if len(matched_ids) != len(expected_ids) or set(matched_ids) != set(expected_ids):
                return False, f"Кількість або ідентифікатори повідомлень інструментів ({matched_ids}) не відповідають tool_calls ({expected_ids})."

            i = j
            continue

        i += 1

    return True, None


@dataclass
class PendingAction:
    """Зберігає останню виконану чи незавершену дію для конкретної сесії."""
    session_id: str
    tool_name: str
    arguments: Dict[str, Any]
    initial_query: str
    success: bool
    status: str
    error: Optional[str] = None
    message: Optional[str] = None
    is_blocked: bool = False
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0

    def is_expired(self, ttl_seconds: int = 300) -> bool:
        """Перевіряє, чи не застаріла незавершена дія (за замовчуванням 5 хвилин)."""
        return (time.time() - self.timestamp) > ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingAction":
        return cls(
            session_id=data.get("session_id", "default"),
            tool_name=data.get("tool_name", "unknown"),
            arguments=data.get("arguments", {}),
            initial_query=data.get("initial_query", ""),
            success=bool(data.get("success", False)),
            status=data.get("status", "unknown"),
            error=data.get("error"),
            message=data.get("message"),
            is_blocked=bool(data.get("is_blocked", False)),
            timestamp=float(data.get("timestamp", time.time())),
            retry_count=int(data.get("retry_count", 0)),
        )


@dataclass
class Turn:
    """Атомарний цикл одного раунду діалогу користувача та помічника."""
    user_message: Dict[str, Any]
    assistant_tool_call: Optional[Dict[str, Any]] = None
    tool_responses: List[Dict[str, Any]] = field(default_factory=list)
    assistant_message: Dict[str, Any] = field(default_factory=dict)

    def to_messages(self) -> List[Dict[str, Any]]:
        """Повертає валідну послідовність повідомлень для передачі в LLM."""
        res = [self.user_message]
        if self.assistant_tool_call:
            res.append(self.assistant_tool_call)
            res.extend(self.tool_responses)
        if self.assistant_message:
            res.append(self.assistant_message)
        return res

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_message": self.user_message,
            "assistant_tool_call": self.assistant_tool_call,
            "tool_responses": self.tool_responses,
            "assistant_message": self.assistant_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Turn":
        return cls(
            user_message=data.get("user_message", {}),
            assistant_tool_call=data.get("assistant_tool_call"),
            tool_responses=data.get("tool_responses", []),
            assistant_message=data.get("assistant_message", {}),
        )


class SessionContext:
    """Контекст окремої ізольованої браузерної або API сесії."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.turns: List[Turn] = []
        self.pending_action: Optional[PendingAction] = None
        self.created_at: float = time.time()
        self.last_active: float = time.time()

    def add_simple_turn(self, user_content: str, assistant_content: str):
        turn = Turn(
            user_message={"role": "user", "content": user_content},
            assistant_message={"role": "assistant", "content": assistant_content}
        )
        self.turns.append(turn)
        self.last_active = time.time()

    def add_tool_turn(
        self,
        user_content: str,
        assistant_tool_call_msg: Dict[str, Any],
        tool_responses: List[Dict[str, Any]],
        final_assistant_content: str
    ):
        turn = Turn(
            user_message={"role": "user", "content": user_content},
            assistant_tool_call=assistant_tool_call_msg,
            tool_responses=tool_responses,
            assistant_message={"role": "assistant", "content": final_assistant_content}
        )
        self.turns.append(turn)
        self.last_active = time.time()

    def get_messages(self, max_turns: int = 5) -> List[Dict[str, Any]]:
        recent_turns = self.turns[-max_turns:] if len(self.turns) > max_turns else self.turns
        messages = []
        for t in recent_turns:
            messages.extend(t.to_messages())
        return messages

    def clear(self):
        self.turns.clear()
        self.pending_action = None
        self.last_active = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "turns": [t.to_dict() for t in self.turns],
            "pending_action": self.pending_action.to_dict() if self.pending_action else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContext":
        sc = cls(data.get("session_id", "default"))
        sc.created_at = float(data.get("created_at", time.time()))
        sc.last_active = float(data.get("last_active", time.time()))
        sc.turns = [Turn.from_dict(t) for t in data.get("turns", [])]
        p_data = data.get("pending_action")
        if p_data:
            try:
                sc.pending_action = PendingAction.from_dict(p_data)
            except Exception:
                sc.pending_action = None
        return sc


class SessionManager:
    """Централізоване потокобезпечне керування ізольованими сесіями з персистентністю."""

    def __init__(self, storage_path: Optional[Path] = None, session_ttl: int = 1800, action_ttl: int = 300):
        if storage_path is not None:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = Path(__file__).resolve().parent.parent.parent / "memory" / "dialog_sessions.json"
        self.session_ttl = session_ttl
        self.action_ttl = action_ttl
        self._sessions: Dict[str, SessionContext] = {}
        self._lock = threading.Lock()
        self.load_from_disk()

    def get_or_create_session(self, session_id: str) -> SessionContext:
        with self._lock:
            now = time.time()
            if session_id in self._sessions:
                s = self._sessions[session_id]
                if now - s.last_active > self.session_ttl:
                    s.clear()
                s.last_active = now
                return s
            s = SessionContext(session_id)
            self._sessions[session_id] = s
            return s

    def get_pending_action(self, session_id: str) -> Optional[PendingAction]:
        with self._lock:
            s = self._sessions.get(session_id)
            if not s or not s.pending_action:
                return None
            if s.pending_action.is_expired(self.action_ttl):
                s.pending_action = None
                return None
            return s.pending_action

    def set_pending_action(self, session_id: str, action: PendingAction):
        with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                s = SessionContext(session_id)
                self._sessions[session_id] = s
            s.pending_action = action
            s.last_active = time.time()
        self.save_to_disk()

    def record_tool_action(
        self,
        session_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Dict[str, Any],
        initial_query: str = ""
    ) -> PendingAction:
        """Реєструє результат виконання виклику інструменту в pending_action сесії."""
        success = bool(result.get("success", False))
        is_blocked = bool(result.get("is_blocked", False))
        status = result.get("status")
        if not status:
            if is_blocked:
                status = "blocked"
            elif success:
                status = "playback_started" if "song" in tool_name or "radio" in tool_name else "success"
            else:
                status = "failed"

        action = PendingAction(
            session_id=session_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            initial_query=initial_query or str(arguments.get("query") or arguments.get("station") or tool_name),
            success=success,
            status=status,
            error=result.get("error"),
            message=result.get("message"),
            is_blocked=is_blocked,
            timestamp=time.time()
        )
        self.set_pending_action(session_id, action)
        return action

    def record_command_action(
        self,
        session_id: str,
        command: str,
        response: str,
        success: bool,
        is_blocked: bool = False
    ) -> PendingAction:
        """Реєструє дію прямих команд (наприклад, через CommandProcessor)."""
        action = PendingAction(
            session_id=session_id,
            tool_name="direct_command",
            arguments={"command": command},
            initial_query=command,
            success=success,
            status="blocked" if is_blocked else ("success" if success else "failed"),
            error=None if success else response,
            message=response if success else None,
            is_blocked=is_blocked,
            timestamp=time.time()
        )
        self.set_pending_action(session_id, action)
        return action

    def clear_session(self, session_id: str):
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].clear()
        self.save_to_disk()

    def reset_all(self):
        """Очищує всі сесії (використовується в тестах)."""
        with self._lock:
            self._sessions.clear()
        if self.storage_path.exists():
            try:
                self.storage_path.unlink()
            except Exception:
                pass

    def load_from_disk(self):
        """Завантажує збережені сесії з диска з очищенням застарілих."""
        if not self.storage_path.exists():
            return
        try:
            content = self.storage_path.read_text(encoding="utf-8").strip()
            if not content:
                return
            data = json.loads(content)
            now = time.time()
            loaded: Dict[str, SessionContext] = {}
            for sid, sdata in data.items():
                if not is_safe_session_id(sid):
                    continue
                sc = SessionContext.from_dict(sdata)
                # Відсіюємо повністю застарілі сесії
                if now - sc.last_active <= self.session_ttl:
                    # Якщо pending_action застаріла, скидаємо її
                    if sc.pending_action and sc.pending_action.is_expired(self.action_ttl):
                        sc.pending_action = None
                    loaded[sid] = sc
            with self._lock:
                self._sessions = loaded
        except Exception as e:
            logger.warning(f"Не вдалося завантажити сесії з {self.storage_path}: {e}")

    def save_to_disk(self):
        """Зберігає активні сесії на диск атомарно."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                now = time.time()
                payload = {}
                for sid, s in self._sessions.items():
                    if now - s.last_active <= self.session_ttl:
                        payload[sid] = s.to_dict()
            tmp_file = self.storage_path.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_file.replace(self.storage_path)
        except Exception as e:
            logger.debug(f"Помилка збереження сесій у {self.storage_path}: {e}")


# Глобальний екземпляр для всієї системи
session_manager = SessionManager()
