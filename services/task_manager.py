"""In-memory task registry for async generation with progress tracking.

Thread-safe: all _push calls go through call_soon_threadsafe on the stored event loop,
so update/fail/complete can be called safely from ThreadPoolExecutor threads.
"""
import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Task:
    task_id: str
    status: str = "pending"
    progress: int = 0
    message: str = ""
    events: list = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "events": list(self.events),
            "result": self.result,
            "error": self.error,
        }


class TaskManager:
    """Thread-safe task registry. Must call set_loop() once from the main event loop."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._ws: dict[str, list[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def create(self) -> Task:
        task = Task(task_id=uuid.uuid4().hex[:12])
        with self._lock:
            self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            for k, v in kwargs.items():
                if hasattr(task, k):
                    setattr(task, k, v)
            data = task.to_dict()
        self._push(task_id, data)

    def push_event(self, task_id: str, event: dict):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.events.append(event)
                data = task.to_dict()
            else:
                return
        self._push(task_id, data)

    def fail(self, task_id: str, error: str):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "failed"
                task.error = error
                data = task.to_dict()
            else:
                return
        self._push(task_id, data)

    def complete(self, task_id: str, result: dict):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "complete"
                task.progress = 100
                task.result = result
                data = task.to_dict()
            else:
                return
        self._push(task_id, data)

    # ---- WebSocket ----

    async def subscribe(self, task_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._ws.setdefault(task_id, []).append(q)
        task = self.get(task_id)
        if task:
            await q.put(task.to_dict())
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue):
        with self._lock:
            queues = self._ws.get(task_id, [])
            if q in queues:
                queues.remove(q)

    def _push(self, task_id: str, data: dict):
        """Thread-safe push to all WebSocket subscribers for a task."""
        loop = self._loop
        if loop is None:
            return
        with self._lock:
            queues = list(self._ws.get(task_id, []))
        for q in queues:
            loop.call_soon_threadsafe(self._put_nowait, q, data)

    @staticmethod
    def _put_nowait(q: asyncio.Queue, data: dict):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass

    def cleanup(self, max_age: float = 3600):
        now = time.time()
        with self._lock:
            stale = [tid for tid, t in self._tasks.items() if now - t.created_at > max_age]
            for tid in stale:
                del self._tasks[tid]
                self._ws.pop(tid, None)


# Global singleton
task_manager = TaskManager()
