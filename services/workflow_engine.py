from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Sequence

from agents.copy_agent import CopyAgent
from agents.image_agent import ImageAgent
from agents.inventory_agent import InventoryAgent
from agents.product_agent import ProductAgent
from agents.script_agent import ScriptAgent
from agents.video_agent import VideoAgent
from models.task import ReactStep, TaskStatus, VideoTask
from repository.task_repository import TaskRepository
from services.account_service import AccountService
from services.trace_service import MockLangSmithTracer


class WorkflowEngine:
    def __init__(
        self,
        account_service: AccountService,
        task_repository: TaskRepository,
        product_agent: ProductAgent,
        inventory_agent: InventoryAgent,
        script_agent: ScriptAgent,
        image_agent: ImageAgent,
        video_agent: VideoAgent,
        copy_agent: CopyAgent,
        tracer: MockLangSmithTracer | None = None,
        *,
        max_retry: int = 2,
        max_steps: int = 8,
        worker_count: int = 3,
        script_timeout_sec: int = 8,
        video_timeout_sec: int = 35,
        refund_on_failure: bool = True,
        dedup_ttl_days: int = 7,
    ) -> None:
        self.account_service = account_service
        self.task_repository = task_repository
        self.product_agent = product_agent
        self.inventory_agent = inventory_agent
        self.script_agent = script_agent
        self.image_agent = image_agent
        self.video_agent = video_agent
        self.copy_agent = copy_agent
        self.tracer = tracer or MockLangSmithTracer()

        self.max_retry = max_retry
        self.max_steps = max_steps
        self.worker_count = worker_count
        self.script_timeout_sec = script_timeout_sec
        self.video_timeout_sec = video_timeout_sec
        self.refund_on_failure = refund_on_failure
        self.dedup_ttl_days = dedup_ttl_days

        self.task_queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []
        self._progress_channels: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._dedup_cache: dict[str, tuple[dict[str, Any], datetime]] = {}

    async def start(self) -> None:
        from workers.workers import orchestrator_worker_loop

        for i in range(self.worker_count):
            self._worker_tasks.append(
                asyncio.create_task(orchestrator_worker_loop(self, f"orchestrator-worker-{i+1}"))
            )

    async def stop(self) -> None:
        for task in self._worker_tasks:
            task.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()

    async def submit_task(self, user_id: str, prompt: str) -> VideoTask:
        request_id = f"req-{uuid.uuid4().hex[:10]}"
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        task_id = f"T{int(time.time() * 1000)}-{uuid.uuid4().hex[:5]}"

        remain = await self.account_service.check_and_consume(user_id, amount=1)
        task = VideoTask(
            task_id=task_id,
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            prompt=prompt,
        )
        await self.task_repository.save(task)
        await self.task_queue.put(task.task_id)

        logging.info(
            "[api] request_id=%s session_id=%s task_id=%s user_id=%s status=PENDING quota_remain=%s",
            request_id,
            session_id,
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
                logging.error("[api] user_id=%s submit rejected reason=%s", user_id, exc)

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
                yield {
                    "taskId": task.task_id,
                    "workflowTaskId": task.task_id,
                    "status": task.status.value,
                    "progress": task.progress,
                    "message": "订阅成功",
                }
            while True:
                event = await queue.get()
                yield event
                if event.get("final"):
                    break
        finally:
            channels = self._progress_channels.get(task_id, [])
            if queue in channels:
                channels.remove(queue)

    async def _emit_progress(
        self,
        task: VideoTask,
        *,
        step: int,
        progress: int,
        message: str,
        extra: dict[str, Any] | None = None,
        final: bool = False,
    ) -> None:
        task.progress = progress
        task.touch()
        await self.task_repository.save(task)

        payload = {
            "taskId": task.task_id,
            "workflowTaskId": task.task_id,
            "requestId": task.request_id,
            "sessionId": task.session_id,
            "step": step,
            "progress": progress,
            "status": task.status.value,
            "message": message,
            "time": datetime.now(timezone.utc).isoformat(),
            "final": final,
        }
        if extra:
            payload.update(extra)

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

        task.status = TaskStatus.RUNNING
        task.touch()
        await self.task_repository.save(task)

        try:
            await self._emit_progress(task, step=0, progress=5, message=f"{worker_name} 开始处理任务")
            result = await self._run_react_flow(task)
            task.status = TaskStatus.SUCCESS
            task.result = result
            await self._emit_progress(
                task,
                step=5,
                progress=100,
                message="视频已生成完成",
                extra={"videoUrl": result["finalUrl"]},
                final=True,
            )
        except Exception as exc:
            await self.mark_failed(task, "WORKFLOW_FAILED", str(exc))

    async def mark_failed(self, task: VideoTask, code: str, message: str) -> None:
        if task.status == TaskStatus.FAILED:
            return

        task.status = TaskStatus.FAILED
        task.error_code = code
        task.error_message = message
        task.touch()
        await self.task_repository.save(task)

        if self.refund_on_failure:
            remain = await self.account_service.refund(task.user_id, amount=1)
            logging.warning(
                "[workflow] request_id=%s task_id=%s step=COMPENSATE refund quota_remain=%s",
                task.request_id,
                task.task_id,
                remain,
            )

        await self._emit_progress(
            task,
            step=99,
            progress=100,
            message=f"任务失败: {message}",
            extra={"errorCode": code, "errorMessage": message},
            final=True,
        )

    async def _run_react_flow(self, task: VideoTask) -> dict[str, Any]:
        history: list[tuple[str, tuple[tuple[str, Any], ...]]] = []
        for step in range(1, self.max_steps + 1):
            action = self._think(task, step)
            if action["type"] == "finish":
                if task.context.get("final"):
                    return task.context["final"]
                raise RuntimeError("flow finished without final result")

            action_key = (action["tool"], tuple(sorted(action["args"].items())))
            if self._is_loop_detected(history, action_key):
                raise RuntimeError("loop detected in ReAct flow")
            history.append(action_key)

            react_step = ReactStep(
                seq=step,
                thought=action["thought"],
                action=action["tool"],
                action_args=action["args"],
            )
            task.react_steps.append(react_step)
            await self.task_repository.save(task)

            obs = await self._act(task, step, action)
            react_step.observation = obs
            react_step.status = "DONE"
            await self.task_repository.save(task)

        raise RuntimeError("exceed max steps, returning partial result")

    def _think(self, task: VideoTask, step: int) -> dict[str, Any]:
        if step == 1:
            return {
                "type": "tool",
                "thought": "需要先获取商品信息",
                "tool": "product_search",
                "args": {"name": task.prompt, "color": "红色"},
            }
        if step == 2:
            product = task.context.get("product")
            if not product:
                raise RuntimeError("product missing before inventory_query")
            return {
                "type": "tool",
                "thought": "检查库存是否充足",
                "tool": "inventory_query",
                "args": {"productId": product["id"]},
            }
        if step == 3:
            product = task.context.get("product")
            return {
                "type": "tool",
                "thought": "生成视频脚本",
                "tool": "llm_generate_script",
                "args": {"product": product["name"], "scene": "展示"},
            }
        if step == 4:
            product = task.context.get("product")
            script = task.context.get("script")
            return {
                "type": "tool",
                "thought": "并行生成视频、配音、字幕",
                "tool": "parallel_generate_assets",
                "args": {
                    "productImageUrl": product["imageUrl"],
                    "script": script,
                    "duration": 30,
                },
            }
        if step == 5:
            if task.context.get("final"):
                return {"type": "finish"}
            return {
                "type": "tool",
                "thought": "合成最终视频",
                "tool": "video_synthesize",
                "args": task.context.get("assets", {}),
            }
        return {"type": "finish"}

    async def _act(self, task: VideoTask, step: int, action: dict[str, Any]) -> Any:
        tool = action["tool"]

        if tool == "product_search":
            await self._emit_progress(task, step=1, progress=20, message="正在获取商品信息")
            obs = await self._execute_tool(
                task=task,
                tool_name=tool,
                call=lambda: self.product_agent.product_search(**action["args"]),
            )
            if not obs:
                raise RuntimeError("product not found")
            task.context["product"] = obs[0]
            return obs

        if tool == "inventory_query":
            await self._emit_progress(task, step=2, progress=35, message="正在检查库存")
            obs = await self._execute_tool(
                task=task,
                tool_name=tool,
                call=lambda: self.inventory_agent.inventory_query(action["args"]["productId"]),
            )
            if obs.get("available", 0) <= 0:
                raise RuntimeError("inventory not enough")
            return obs

        if tool == "llm_generate_script":
            await self._emit_progress(task, step=3, progress=50, message="正在生成视频脚本")
            script = await self._execute_tool(
                task=task,
                tool_name=tool,
                call=lambda: self._run_with_retry(
                    task,
                    step_key="SCRIPT",
                    coro_factory=lambda: asyncio.wait_for(
                        self.script_agent.generate_script(task),
                        timeout=self.script_timeout_sec,
                    ),
                ),
            )
            task.context["script"] = script
            return script

        if tool == "parallel_generate_assets":
            await self._emit_progress(task, step=4, progress=70, message="并行生成素材中")
            args = action["args"]
            dedup_key = self._build_dedup_key(task, duration=args["duration"])
            cached = self._get_dedup_cache(dedup_key)
            if cached:
                task.context["final"] = cached
                return {"cacheHit": True, **cached}

            image_url, video, copy_assets = await self._execute_tool(
                task=task,
                tool_name=tool,
                call=lambda: asyncio.gather(
                    self.image_agent.generate_scene_image(task, args["productImageUrl"]),
                    self._run_with_retry(
                        task,
                        step_key="VIDEO",
                        coro_factory=lambda: asyncio.wait_for(
                            self.video_agent.generate_video_clip(
                                task,
                                product_image_url=args["productImageUrl"],
                                script=args["script"],
                                duration_seconds=args["duration"],
                            ),
                            timeout=self.video_timeout_sec,
                        ),
                    ),
                    self.copy_agent.generate_audio_and_subtitle(task, args["script"]),
                ),
            )
            assets = {
                "imageUrl": image_url,
                "videoUrl": video["videoUrl"],
                "duration": video["duration"],
                "audioUrl": copy_assets["audioUrl"],
                "subtitleUrl": copy_assets["subtitleUrl"],
            }
            task.context["assets"] = assets
            task.context["dedupKey"] = dedup_key
            return assets

        if tool == "video_synthesize":
            await self._emit_progress(task, step=5, progress=90, message="正在合成最终视频")
            result = await self._execute_tool(
                task=task,
                tool_name=tool,
                call=lambda: self.video_agent.synthesize_final_video(task, action["args"]),
            )
            task.context["final"] = result
            dedup_key = task.context.get("dedupKey")
            if dedup_key:
                self._set_dedup_cache(dedup_key, result)
            return result

        raise RuntimeError(f"unknown tool: {tool}")

    async def _run_with_retry(self, task: VideoTask, step_key: str, coro_factory):
        for attempt in range(1, self.max_retry + 2):
            try:
                return await coro_factory()
            except Exception as exc:
                task.step_retry_count[step_key] = attempt
                if attempt > self.max_retry:
                    raise RuntimeError(f"{step_key} failed after retry: {exc}") from exc
                backoff = 2 ** (attempt - 1)
                logging.warning(
                    "[retry] request_id=%s task_id=%s step=%s attempt=%s backoff=%ss reason=%s",
                    task.request_id,
                    task.task_id,
                    step_key,
                    attempt,
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)

    async def _execute_tool(self, task: VideoTask, tool_name: str, call):
        start = time.perf_counter()
        try:
            result = await call()
            self.tracer.log_tool_call(
                request_id=task.request_id,
                session_id=task.session_id,
                workflow_task_id=task.task_id,
                tool=tool_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=True,
                retries=task.step_retry_count.get("SCRIPT", 0) + task.step_retry_count.get("VIDEO", 0),
            )
            return result
        except Exception:
            self.tracer.log_tool_call(
                request_id=task.request_id,
                session_id=task.session_id,
                workflow_task_id=task.task_id,
                tool=tool_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=False,
                retries=task.step_retry_count.get("SCRIPT", 0) + task.step_retry_count.get("VIDEO", 0),
            )
            raise

    def _is_loop_detected(
        self,
        history: list[tuple[str, tuple[tuple[str, Any], ...]]],
        current: tuple[str, tuple[tuple[str, Any], ...]],
    ) -> bool:
        if len(history) < 2:
            return False
        return history[-1] == history[-2] == current

    def _build_dedup_key(self, task: VideoTask, duration: int) -> str:
        product_id = task.context.get("product", {}).get("id", "unknown")
        style = "展示"
        raw = f"{product_id}|{style}|{duration}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"content:dedup:{digest}"

    def _get_dedup_cache(self, key: str) -> dict[str, Any] | None:
        item = self._dedup_cache.get(key)
        if not item:
            return None
        data, expire_at = item
        if datetime.now(timezone.utc) >= expire_at:
            self._dedup_cache.pop(key, None)
            return None
        return data

    def _set_dedup_cache(self, key: str, data: dict[str, Any]) -> None:
        expire_at = datetime.now(timezone.utc) + timedelta(days=self.dedup_ttl_days)
        self._dedup_cache[key] = (data, expire_at)
