import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


@dataclass(order=True)
class VoiceCommand:
    """Represents a voice command with priority for the AI execution pipeline."""
    priority: int  # Lower number = higher priority (e.g. 1 for voice, 5 for background)
    timestamp: float = field(default_factory=time.time)
    text: str = field(compare=False, default="")
    source: str = field(compare=False, default="voice")
    session_id: str = field(compare=False, default="voice_session")
    metadata: Dict[str, Any] = field(compare=False, default_factory=dict)


class VoiceCommandQueue:
    """
    Asynchronous message queue for recognized voice commands.
    Allows voice_listener.py to submit commands and the main AI pipeline to process them
    with high priority over regular inputs.
    """

    def __init__(self, maxsize: int = 100):
        self.maxsize = maxsize
        self._async_queue: Optional[asyncio.PriorityQueue] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._total_received = 0
        self._total_processed = 0

    def _ensure_queue(self) -> asyncio.PriorityQueue:
        if self._async_queue is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            self._async_queue = asyncio.PriorityQueue(maxsize=self.maxsize)
        return self._async_queue

    async def put(self, text: str, source: str = "voice", priority: int = 1, metadata: Optional[Dict[str, Any]] = None):
        """Asynchronously enqueue a recognized voice command."""
        q = self._ensure_queue()
        cmd = VoiceCommand(
            priority=priority,
            timestamp=time.time(),
            text=text.strip(),
            source=source,
            session_id="voice",
            metadata=metadata or {}
        )
        with self._lock:
            self._total_received += 1
            self._history.append({
                "text": cmd.text,
                "source": cmd.source,
                "priority": cmd.priority,
                "timestamp": cmd.timestamp,
                "status": "queued"
            })
            if len(self._history) > 50:
                self._history.pop(0)

        logger.info(f"[VoiceQueue] Enqueued command (priority={priority}, source={source}): «{cmd.text}»")
        await q.put(cmd)

    def put_sync(self, text: str, source: str = "voice", priority: int = 1, metadata: Optional[Dict[str, Any]] = None):
        """Thread-safe synchronous enqueue method for background threads."""
        q = self._ensure_queue()
        cmd = VoiceCommand(
            priority=priority,
            timestamp=time.time(),
            text=text.strip(),
            source=source,
            session_id="voice",
            metadata=metadata or {}
        )
        with self._lock:
            self._total_received += 1
            self._history.append({
                "text": cmd.text,
                "source": cmd.source,
                "priority": cmd.priority,
                "timestamp": cmd.timestamp,
                "status": "queued"
            })
            if len(self._history) > 50:
                self._history.pop(0)

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(q.put_nowait, cmd)
        else:
            try:
                q.put_nowait(cmd)
            except Exception as e:
                logger.error(f"[VoiceQueue] Failed to put command sync: {e}")

    async def get(self) -> VoiceCommand:
        """Asynchronously get the next highest-priority command from the queue."""
        q = self._ensure_queue()
        cmd: VoiceCommand = await q.get()
        with self._lock:
            self._total_processed += 1
            for item in reversed(self._history):
                if item["text"] == cmd.text and item["status"] == "queued":
                    item["status"] = "processing"
                    break
        q.task_done()
        return cmd

    def empty(self) -> bool:
        if self._async_queue is None:
            return True
        return self._async_queue.empty()

    def qsize(self) -> int:
        if self._async_queue is None:
            return 0
        return self._async_queue.qsize()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "queue_size": self.qsize(),
                "total_received": self._total_received,
                "total_processed": self._total_processed,
                "recent_history": list(self._history[-10:])
            }


# Global shared instance
voice_command_queue = VoiceCommandQueue()
