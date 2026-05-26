from __future__ import annotations

import asyncio

from models.task import VideoTask


class ImageAgent:
    async def generate_scene_image(self, task: VideoTask, product_image_url: str) -> str:
        await asyncio.sleep(1.5)
        return f"oss://generated/{task.task_id}/scene.jpg"
