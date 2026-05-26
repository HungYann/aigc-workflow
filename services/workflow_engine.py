from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Sequence

from agents.script_agent import ScriptAgent
from agents.video_agent import VideoAgent
from models.task import TaskStatus, VideoTask
from repository.task_repository import TaskRepository
from services.account_service import AccountService


class WorkflowEngine:
    def __init__(
        self,
        account_service: AccountService,
        task_repository: TaskRepository,
        script_agent: ScriptAgent,
        video_agent: VideoAgent,
        *,
        worker_count: int = 3,
        max_retry: int = 2,
        script_timeout_sec: int = 8,
        video_timeout_sec: int = 35,
        refund_on_failure: bool = True,
    ) -> None:
        self.account_service = account_service
        self.task_repository = task_repository
        self.script_agent = script_agent
        self.video_agent = video_agent

        self.worker_count = worker_count
        self.max_retry = max_retry
        self.script_timeout_sec = script_timeout_sec
        self.video_timeout_sec = video_timeout_sec
        self.refund_on_failure = refund_on_failure

        self.task_queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []
        self._progress_channels: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

    async def start(self) -> None:
        from workers.workers import orchestrator_worker_loop

        for i in range(self.worker_count):
            self._worker_tasks.append(
                asyncio.create_task(orchestrator_worker_loop(self, f"worker-{i+1}"))
            )

    async def stop(self) -> None:
        for task in self._worker_tasks:
            task.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()

    async def submit_task(self, user_id: str, prompt: str) -> VideoTask:
        request_id = f"req-{uuid.uuid4().hex[:10]}"
        task_id = f"T{int(time.time() * 1000)}-{uuid.uuid4().hex[:5]}"

        remain = await self.account_service.check_and_consume(user_id, amount=1)
        task = VideoTask(task_id=task_id, request_id=request_id, user_id=user_id, prompt=prompt)
        await self.task_repository.save(task)
        await self.task_queue.put(task.task_id)

        logging.info(
            "[submit] request_id=%s task_id=%s user=%s quota_remain=%s",
            request_id,
            task_id,
            user_id,
            remain,
        )
        return task

    async def submit_batch(self, requests: Sequence[tuple[str, str]]) -> tuple[list[VideoTask], list[tuple[str, str]]]:
        accepted: list[VideoTask] = []
        rejected: list[tuple[str, str]] = []

        async def _submit_one(user_id: str, prompt: str) -> None:
            try:
                accepted.append(await self.submit_task(user_id, prompt))
            except Exception as exc:
                rejected.append((user_id, str(exc)))
                logging.error("[reject] user=%s reason=%s", user_id, exc)

        await asyncio.gather(*[_submit_one(u, p) for u, p in requests])
        return accepted, rejected

    async def wait_until_idle(self) -> None:
        await self.task_queue.join()

    async def stream_progress(self, task_id: str) -> AsyncGenerator[dict[str, Any], None]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._progress_channels.setdefault(task_id, []).append(queue)
        try:
            task = await self.task_repository.get(task_id)
            if task:
                yield {"taskId": task.task_id, "status": task.status.value, "progress": task.progress, "message": "subscribed"}
            while True:
                event = await queue.get()
                yield event
                if event.get("final"):
                    break
        finally:
            channels = self._progress_channels.get(task_id, [])
            if queue in channels:
                channels.remove(queue)

    async def _emit_progress(self, task: VideoTask, step: str, progress: int, message: str, *, final: bool = False) -> None:
        task.progress = progress
        task.touch()
        await self.task_repository.save(task)

        payload = {
            "taskId": task.task_id,
            "requestId": task.request_id,
            "step": step,
            "status": task.status.value,
            "progress": progress,
            "message": message,
            "time": datetime.now(timezone.utc).isoformat(),
            "final": final,
        }

        for channel in self._progress_channels.get(task.task_id, []):
            await channel.put(payload)

        logging.info(
            "[progress] request_id=%s task_id=%s step=%s progress=%s msg=%s",
            task.request_id,
            task.task_id,
            step,
            progress,
            message,
        )

    async def process_task(self, task: VideoTask, worker_name: str) -> None:
        if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
            return

        try:
            task.status = TaskStatus.SCRIPTING
            await self._emit_progress(task, "SCRIPTING", 30, f"{worker_name} generating script")
            script = await self._run_with_retry(
                task,
                step="SCRIPT",
                factory=lambda: asyncio.wait_for(self.script_agent.generate_script(task), timeout=self.script_timeout_sec),
            )
            task.script = script

            task.status = TaskStatus.RENDERING
            await self._emit_progress(task, "RENDERING", 70, f"{worker_name} generating video")
            video_url = await self._run_with_retry(
                task,
                step="VIDEO",
                factory=lambda: asyncio.wait_for(self.video_agent.generate_video(task, script), timeout=self.video_timeout_sec),
            )
            task.video_url = video_url
            task.status = TaskStatus.SUCCESS
            await self._emit_progress(task, "DONE", 100, "video generated", final=True)

        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error_message = str(exc)
            task.touch()
            await self.task_repository.save(task)

            if self.refund_on_failure:
                remain = await self.account_service.refund(task.user_id, amount=1) # 退款
                logging.warning("[compensate] task_id=%s user=%s quota_remain=%s", task.task_id, task.user_id, remain)

            await self._emit_progress(task, "FAILED", 100, f"failed: {exc}", final=True)

    async def _run_with_retry(self, task: VideoTask, step: str, factory):
        for attempt in range(1, self.max_retry + 2):
            try:
                return await factory()
            except Exception as exc:
                task.retry_count[step] = attempt
                if attempt > self.max_retry:
                    raise RuntimeError(f"{step} failed after retry: {exc}") from exc
                backoff = 2 ** (attempt - 1)
                logging.warning(
                    "[retry] task_id=%s step=%s attempt=%s wait=%ss reason=%s",
                    task.task_id,
                    step,
                    attempt,
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)
