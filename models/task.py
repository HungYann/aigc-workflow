from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass
class ReactStep:
    seq: int
    thought: str
    action: str
    action_args: dict[str, Any]
    observation: Any = None
    status: str = "PENDING"


@dataclass
class VideoTask:
    task_id: str
    request_id: str
    session_id: str
    user_id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    result: Optional[dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    step_retry_count: dict[str, int] = field(default_factory=dict)
    react_steps: list[ReactStep] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
