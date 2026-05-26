from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    SCRIPTING = "SCRIPTING"
    RENDERING = "RENDERING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass
class VideoTask:
    task_id: str
    request_id: str
    user_id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    script: Optional[str] = None
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
