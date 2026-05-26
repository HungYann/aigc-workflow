from __future__ import annotations

import asyncio

from models.task import VideoTask


class VideoAgent:
    def __init__(self, latency_sec: float = 30.0) -> None:
        self.latency_sec = latency_sec

    async def generate_video(self, task: VideoTask, script: str) -> str:
        if not script:
            raise ValueError("script is required")
        if "[video_fail]" in task.prompt:
            raise RuntimeError("VIDEO_TEMP_ERROR")

        await asyncio.sleep(self.latency_sec)
        return f"oss://content/{task.task_id}.mp4"
