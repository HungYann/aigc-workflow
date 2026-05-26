from __future__ import annotations

import asyncio

from models.task import VideoTask


VIDEO_GENERATE_TOOL_SCHEMA = {
    "name": "video_generate",
    "description": "根据商品图片和脚本生成营销短视频，返回 jobId（异步）",
    "parameters": {
        "type": "object",
        "properties": {
            "product_image_url": {"type": "string"},
            "script": {"type": "string", "maxLength": 200},
            "duration_seconds": {"type": "number", "enum": [15, 30, 60]},
        },
        "required": ["product_image_url", "script"],
    },
}


class VideoAgent:
    def __init__(self, latency_sec: int = 30) -> None:
        self.latency_sec = latency_sec

    async def generate_video_clip(
        self,
        task: VideoTask,
        product_image_url: str,
        script: str,
        duration_seconds: int,
    ) -> dict:
        # Minimal schema guard for demo.
        if not product_image_url:
            raise ValueError("product_image_url is required")
        if not script:
            raise ValueError("script is required")
        if len(script) > 200:
            raise ValueError("script too long (>200)")
        if duration_seconds not in (15, 30, 60):
            raise ValueError("duration_seconds must be one of 15, 30, 60")
        if "[video_fail]" in script:
            raise RuntimeError("VIDEO_TEMP_ERROR")

        await asyncio.sleep(self.latency_sec)
        return {
            "jobId": f"job-{task.task_id}",
            "videoUrl": f"oss://generated/{task.task_id}/clip.mp4",
            "duration": duration_seconds,
        }

    async def synthesize_final_video(self, task: VideoTask, assets: dict) -> dict:
        await asyncio.sleep(1)
        return {
            "finalUrl": f"oss://content/{task.task_id}.mp4",
            "duration": assets.get("duration", 30),
        }
