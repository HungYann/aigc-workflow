from __future__ import annotations

import asyncio
from typing import Optional

from models.task import VideoTask


class TaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, VideoTask] = {}
        self._lock = asyncio.Lock()

    async def save(self, task: VideoTask) -> None:
        async with self._lock:
            self._tasks[task.task_id] = task

    async def get(self, task_id: str) -> Optional[VideoTask]:
        async with self._lock:
            return self._tasks.get(task_id)

    async def list_all(self) -> list[VideoTask]:
        async with self._lock:
            return list(self._tasks.values())
