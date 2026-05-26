from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any


class MockLangSmithTracer:
    """A lightweight local tracer to simulate LangSmith-style observability."""

    def __init__(self) -> None:
        self.tool_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "fail": 0})

    def log_tool_call(
        self,
        *,
        request_id: str,
        session_id: str,
        workflow_task_id: str,
        tool: str,
        latency_ms: int,
        success: bool,
        retries: int,
    ) -> None:
        key = "ok" if success else "fail"
        self.tool_stats[tool][key] += 1
        logging.info(
            "[trace] request_id=%s session_id=%s workflow_task_id=%s tool=%s latency_ms=%s success=%s retries=%s",
            request_id,
            session_id,
            workflow_task_id,
            tool,
            latency_ms,
            success,
            retries,
        )

    def summary(self) -> dict[str, Any]:
        return {tool: dict(stats) for tool, stats in self.tool_stats.items()}
