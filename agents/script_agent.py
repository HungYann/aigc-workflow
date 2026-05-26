from __future__ import annotations

import asyncio

from models.task import VideoTask


class ScriptAgent:
    def __init__(self, latency_sec: int = 5) -> None:
        self.latency_sec = latency_sec

    async def generate_script(self, task: VideoTask) -> str:
        await asyncio.sleep(self.latency_sec)

        # Controlled failure flag for testing retry behavior.
        if "[script_fail]" in task.prompt:
            raise RuntimeError("SCRIPT_TEMP_ERROR")

        return f"Script for {task.prompt}"
