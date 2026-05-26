from __future__ import annotations

import asyncio
import unittest

from agents.copy_agent import CopyAgent
from agents.image_agent import ImageAgent
from agents.inventory_agent import InventoryAgent
from agents.product_agent import ProductAgent
from agents.script_agent import ScriptAgent
from agents.video_agent import VIDEO_GENERATE_TOOL_SCHEMA, VideoAgent
from models.task import TaskStatus
from repository.task_repository import TaskRepository
from services.account_service import AccountService
from services.workflow_engine import WorkflowEngine


class FastImageAgent(ImageAgent):
    async def generate_scene_image(self, task, product_image_url: str) -> str:
        await asyncio.sleep(0.01)
        return f"oss://generated/{task.task_id}/scene.jpg"


class FastCopyAgent(CopyAgent):
    async def generate_audio_and_subtitle(self, task, script: str) -> dict:
        await asyncio.sleep(0.01)
        return {
            "audioUrl": f"oss://generated/{task.task_id}/voice.wav",
            "subtitleUrl": f"oss://generated/{task.task_id}/subtitle.srt",
            "copy": script,
        }


class FastVideoAgent(VideoAgent):
    async def synthesize_final_video(self, task, assets: dict) -> dict:
        await asyncio.sleep(0.01)
        return {
            "finalUrl": f"oss://content/{task.task_id}.mp4",
            "duration": assets.get("duration", 30),
        }


class WorkflowEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.account_service = AccountService({"U001": 2, "U002": 0, "U003": 2, "U004": 1})
        self.repo = TaskRepository()
        self.engine = WorkflowEngine(
            account_service=self.account_service,
            task_repository=self.repo,
            product_agent=ProductAgent(),
            inventory_agent=InventoryAgent(),
            script_agent=ScriptAgent(latency_sec=0.01),
            image_agent=FastImageAgent(),
            video_agent=FastVideoAgent(latency_sec=0.01),
            copy_agent=FastCopyAgent(),
            max_retry=1,
            worker_count=3,
            script_timeout_sec=2,
            video_timeout_sec=2,
            refund_on_failure=True,
        )
        await self.engine.start()

    async def asyncTearDown(self) -> None:
        await self.engine.stop()

    async def test_multi_user_submit_and_quota_reject(self) -> None:
        accepted, rejected = await self.engine.submit_batch(
            [
                ("U001", "帮我生成一个展示红色连衣裙的短视频"),
                ("U002", "帮我生成一个展示红色连衣裙的短视频"),  # no quota
                ("U003", "帮我生成一个展示红色连衣裙的短视频"),
            ]
        )

        self.assertEqual(len(accepted), 2)
        self.assertEqual(len(rejected), 1)
        self.assertIn("quota not enough", rejected[0][1])

        await self.engine.wait_until_idle()
        tasks = await self.repo.list_all()
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t.status == TaskStatus.SUCCESS for t in tasks))

    async def test_success_task_returns_final_result(self) -> None:
        task = await self.engine.submit_task("U001", "帮我生成一个展示红色连衣裙的短视频")
        await self.engine.wait_until_idle()

        stored = await self.repo.get(task.task_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, TaskStatus.SUCCESS)
        self.assertIn("finalUrl", stored.result)
        self.assertIn(task.task_id, stored.result["finalUrl"])

    async def test_failed_inventory_will_refund_quota(self) -> None:
        before = await self.account_service.get_quota("U004")
        task = await self.engine.submit_task("U004", "缺货商品演示")
        await self.engine.wait_until_idle()
        after = await self.account_service.get_quota("U004")

        stored = await self.repo.get(task.task_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, TaskStatus.FAILED)
        self.assertIn("inventory not enough", stored.error_message)
        # one consume then one refund
        self.assertEqual(before, after)

    async def test_retry_logic_for_script_step(self) -> None:
        call_count = {"n": 0}
        original = self.engine.script_agent.generate_script

        async def flaky(task):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("SCRIPT_TEMP_ERROR")
            return await original(task)

        self.engine.script_agent.generate_script = flaky  # type: ignore[assignment]

        task = await self.engine.submit_task("U001", "帮我生成一个展示红色连衣裙的短视频")
        await self.engine.wait_until_idle()

        stored = await self.repo.get(task.task_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, TaskStatus.SUCCESS)
        self.assertGreaterEqual(stored.step_retry_count.get("SCRIPT", 0), 1)

    async def test_sse_progress_stream_contains_final_event(self) -> None:
        task = await self.engine.submit_task("U003", "帮我生成一个展示红色连衣裙的短视频")

        events = []

        async def consume():
            async for evt in self.engine.stream_progress(task.task_id):
                events.append(evt)
                if evt.get("final"):
                    break

        consumer = asyncio.create_task(consume())
        await self.engine.wait_until_idle()
        await consumer

        self.assertTrue(len(events) >= 2)
        self.assertTrue(any(isinstance(evt.get("step"), int) and evt.get("step") >= 1 for evt in events))
        self.assertTrue(events[-1].get("final"))
        self.assertIn("videoUrl", events[-1])

    async def test_dedup_cache_reuses_previous_result(self) -> None:
        calls = {"video_clip": 0}
        original = self.engine.video_agent.generate_video_clip

        async def counted(*args, **kwargs):
            calls["video_clip"] += 1
            return await original(*args, **kwargs)

        self.engine.video_agent.generate_video_clip = counted  # type: ignore[assignment]

        task1 = await self.engine.submit_task("U001", "帮我生成一个展示红色连衣裙的短视频")
        await self.engine.wait_until_idle()

        task2 = await self.engine.submit_task("U003", "帮我生成一个展示红色连衣裙的短视频")
        await self.engine.wait_until_idle()

        t1 = await self.repo.get(task1.task_id)
        t2 = await self.repo.get(task2.task_id)
        assert t1 is not None and t2 is not None

        self.assertEqual(t1.status, TaskStatus.SUCCESS)
        self.assertEqual(t2.status, TaskStatus.SUCCESS)
        self.assertEqual(calls["video_clip"], 1)
        self.assertEqual(t1.result["duration"], t2.result["duration"])

    async def test_loop_detection_guard(self) -> None:
        original_think = self.engine._think

        def loop_think(task, step):
            if step <= 4:
                return {
                    "type": "tool",
                    "thought": "重复调用同一个工具",
                    "tool": "product_search",
                    "args": {"name": "loop", "color": "红色"},
                }
            return {"type": "finish"}

        self.engine._think = loop_think  # type: ignore[assignment]

        task = await self.engine.submit_task("U001", "任意prompt")
        await self.engine.wait_until_idle()

        stored = await self.repo.get(task.task_id)
        assert stored is not None
        self.assertEqual(stored.status, TaskStatus.FAILED)
        self.assertIn("loop detected", stored.error_message)

        self.engine._think = original_think

    def test_tool_schema_contract(self) -> None:
        self.assertEqual(VIDEO_GENERATE_TOOL_SCHEMA["name"], "video_generate")
        required = VIDEO_GENERATE_TOOL_SCHEMA["parameters"]["required"]
        self.assertIn("product_image_url", required)
        self.assertIn("script", required)

    def test_default_latency_contract(self) -> None:
        self.assertEqual(ScriptAgent().latency_sec, 5)
        self.assertEqual(VideoAgent().latency_sec, 30)


if __name__ == "__main__":
    unittest.main()
