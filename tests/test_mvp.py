from __future__ import annotations

import asyncio
import unittest

from agents.script_agent import ScriptAgent
from agents.video_agent import VideoAgent
from models.task import TaskStatus
from repository.task_repository import TaskRepository
from services.account_service import AccountService, QuotaNotEnoughError
from services.workflow_engine import WorkflowEngine


class MVPTests(unittest.IsolatedAsyncioTestCase):
    """MVP 场景测试：配额、成功链路、失败补偿、进度流。"""

    async def asyncSetUp(self) -> None:
        self.account = AccountService({"U001": 1, "U002": 0, "U003": 1})
        self.repo = TaskRepository()
        self.engine = WorkflowEngine(
            account_service=self.account,
            task_repository=self.repo,
            script_agent=ScriptAgent(latency_sec=0.01),
            video_agent=VideoAgent(latency_sec=0.01),
            worker_count=2,
            max_retry=1,
            script_timeout_sec=2,
            video_timeout_sec=2,
            refund_on_failure=True,
        )
        await self.engine.start()

    async def asyncTearDown(self) -> None:
        await self.engine.stop()

    async def test_quota_not_enough_reject(self) -> None:
        with self.assertRaises(QuotaNotEnoughError):
            await self.account.check_and_consume("U002")

    async def test_success_flow(self) -> None:
        task = await self.engine.submit_task("U001", "demo")
        await self.engine.wait_until_idle()
        stored = await self.repo.get(task.task_id)
        assert stored is not None
        self.assertEqual(stored.status, TaskStatus.SUCCESS)
        self.assertTrue(stored.script)
        self.assertTrue(stored.video_url)

    async def test_video_failure_refunds_quota(self) -> None:
        before = await self.account.get_quota("U003")
        task = await self.engine.submit_task("U003", "demo [video_fail]")
        await self.engine.wait_until_idle()
        after = await self.account.get_quota("U003")

        stored = await self.repo.get(task.task_id)
        assert stored is not None
        self.assertEqual(stored.status, TaskStatus.FAILED)
        self.assertIn("VIDEO", stored.error_message)
        self.assertEqual(before, after)

    async def test_sse_progress_has_final(self) -> None:
        task = await self.engine.submit_task("U001", "demo")
        events = []

        async def consume():
            async for evt in self.engine.stream_progress(task.task_id):
                events.append(evt)
                if evt.get("final"):
                    break

        consumer = asyncio.create_task(consume())
        await self.engine.wait_until_idle()
        await consumer

        # Stream is best-effort: if you subscribe late you might miss intermediate events.\n+        # We only require the final event to be delivered.\n+        self.assertTrue(events[-1].get(\"final\"))\n+        self.assertEqual(events[-1].get(\"progress\"), 100)


if __name__ == "__main__":
    unittest.main()
