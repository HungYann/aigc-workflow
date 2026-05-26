from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
from typing import Iterable

from agents.copy_agent import CopyAgent
from agents.image_agent import ImageAgent
from agents.inventory_agent import InventoryAgent
from agents.product_agent import ProductAgent
from agents.script_agent import ScriptAgent
from agents.video_agent import VIDEO_GENERATE_TOOL_SCHEMA, VideoAgent
from repository.task_repository import TaskRepository
from services.account_service import AccountService
from services.workflow_engine import WorkflowEngine


def build_requests_and_quota(
    *,
    user_count: int,
    fail_mode: str,
    fail_ratio: float,
    quota_shortage_ratio: float,
    seed: int,
) -> tuple[list[tuple[str, str]], dict[str, int]]:
    rng = random.Random(seed)
    requests: list[tuple[str, str]] = []
    quota: dict[str, int] = {}

    base_prompt = "帮我生成一个展示红色连衣裙的短视频"
    fail_tokens = {
        "script": " [script_fail]",
        "video": " [video_fail]",
        "inventory": "缺货商品演示",
    }

    for i in range(1, user_count + 1):
        user_id = f"U{i:03d}"
        quota[user_id] = 0 if rng.random() < quota_shortage_ratio else 1

        prompt = base_prompt
        if rng.random() < fail_ratio and fail_mode != "none":
            mode = fail_mode
            if fail_mode == "mixed":
                mode = rng.choice(["script", "video", "inventory"])
            prompt = fail_tokens[mode] if mode == "inventory" else prompt + fail_tokens[mode]

        requests.append((user_id, prompt))

    return requests, quota


async def consume_sse(engine: WorkflowEngine, task_id: str) -> None:
    async for event in engine.stream_progress(task_id):
        logging.info(
            "[sse] task_id=%s step=%s progress=%s status=%s msg=%s final=%s",
            event.get("taskId"),
            event.get("step", "-"),
            event.get("progress"),
            event.get("status"),
            event.get("message"),
            event.get("final", False),
        )


def parse_users(users: str) -> list[int]:
    return [int(x.strip()) for x in users.split(",") if x.strip()]


async def run_one_case(args: argparse.Namespace, user_count: int, case_idx: int) -> None:
    requests, quota = build_requests_and_quota(
        user_count=user_count,
        fail_mode=args.fail_mode,
        fail_ratio=args.fail_ratio,
        quota_shortage_ratio=args.quota_shortage_ratio,
        seed=args.seed + case_idx,
    )

    logging.info(
        "[case] id=%s users=%s fail_mode=%s fail_ratio=%.2f quota_shortage_ratio=%.2f script_sec=%.2f video_sec=%.2f",
        case_idx,
        user_count,
        args.fail_mode,
        args.fail_ratio,
        args.quota_shortage_ratio,
        args.script_sec,
        args.video_sec,
    )

    engine = WorkflowEngine(
        account_service=AccountService(quota),
        task_repository=TaskRepository(),
        product_agent=ProductAgent(),
        inventory_agent=InventoryAgent(),
        script_agent=ScriptAgent(latency_sec=args.script_sec),
        image_agent=ImageAgent(),
        video_agent=VideoAgent(latency_sec=args.video_sec),
        copy_agent=CopyAgent(),
        max_retry=args.max_retry,
        max_steps=8,
        worker_count=args.workers,
        script_timeout_sec=max(2, int(args.script_sec + args.timeout_buffer)),
        video_timeout_sec=max(5, int(args.video_sec + args.timeout_buffer)),
        refund_on_failure=True,
        dedup_ttl_days=7,
    )

    sse_tasks: list[asyncio.Task] = []
    started = time.perf_counter()

    await engine.start()
    try:
        accepted, rejected = await engine.submit_batch(requests)

        if args.sse:
            for task in accepted:
                sse_tasks.append(asyncio.create_task(consume_sse(engine, task.task_id)))

        await engine.wait_until_idle()
        if sse_tasks:
            await asyncio.gather(*sse_tasks)

        tasks = await engine.task_repository.list_all()
        tasks_sorted = sorted(tasks, key=lambda t: t.task_id)

        success = sum(1 for t in tasks_sorted if t.status.value == "SUCCESS")
        failed = sum(1 for t in tasks_sorted if t.status.value == "FAILED")
        durations = [(t.updated_at - t.created_at).total_seconds() for t in tasks_sorted]
        avg_cost = (sum(durations) / len(durations)) if durations else 0.0
        elapsed = time.perf_counter() - started

        logging.info(
            "[summary] case=%s total=%s accepted=%s rejected=%s success=%s failed=%s elapsed=%.2fs avg_task_cost=%.2fs",
            case_idx,
            len(requests),
            len(accepted),
            len(rejected),
            success,
            failed,
            elapsed,
            avg_cost,
        )

        for idx, t in enumerate(tasks_sorted[: args.show_tasks], start=1):
            duration = (t.updated_at - t.created_at).total_seconds()
            logging.info(
                "[task] #%s user=%s task=%s status=%s duration=%.2fs retries=%s error=%s",
                idx,
                t.user_id,
                t.task_id,
                t.status.value,
                duration,
                t.step_retry_count,
                t.error_message,
            )

        for user_id, reason in rejected[: args.show_tasks]:
            logging.info("[reject] user=%s reason=%s", user_id, reason)

    finally:
        await engine.stop()


async def run(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )

    logging.info("[schema] video_generate=%s", VIDEO_GENERATE_TOOL_SCHEMA)

    if args.matrix_users:
        users_list = parse_users(args.matrix_users)
    else:
        users_list = [args.users]

    for idx, count in enumerate(users_list, start=1):
        await run_one_case(args, count, idx)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIGC workflow scenario runner")
    parser.add_argument("--users", type=int, default=3, help="Number of users for a single case")
    parser.add_argument("--matrix-users", type=str, default="", help="Run multiple cases, e.g. 5,20,50")
    parser.add_argument(
        "--fail-mode",
        choices=["none", "script", "video", "inventory", "mixed"],
        default="none",
        help="Failure injection mode",
    )
    parser.add_argument("--fail-ratio", type=float, default=0.0, help="Ratio of requests to inject failure")
    parser.add_argument(
        "--quota-shortage-ratio",
        type=float,
        default=0.0,
        help="Ratio of users with zero quota",
    )
    parser.add_argument("--workers", type=int, default=3, help="Orchestrator worker count")
    parser.add_argument("--script-sec", type=float, default=5.0, help="Script step latency")
    parser.add_argument("--video-sec", type=float, default=30.0, help="Video step latency")
    parser.add_argument("--timeout-buffer", type=float, default=3.0, help="Timeout extra seconds")
    parser.add_argument("--max-retry", type=int, default=2, help="Max retry per step")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible scenarios")
    parser.add_argument("--show-tasks", type=int, default=20, help="How many task lines to print")
    parser.add_argument("--sse", action="store_true", help="Print SSE-like progress stream")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
