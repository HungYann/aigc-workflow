from __future__ import annotations

import asyncio

from models.task import VideoTask


class CopyAgent:
    async def generate_audio_and_subtitle(self, task: VideoTask, script: str) -> dict:
        await asyncio.sleep(2)
        return {
            "audioUrl": f"oss://generated/{task.task_id}/voice.wav",
            "subtitleUrl": f"oss://generated/{task.task_id}/subtitle.srt",
            "copy": script,
        }
