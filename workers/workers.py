from __future__ import annotations

import logging


async def orchestrator_worker_loop(engine, worker_name: str) -> None:
    while True:
        task_id = await engine.task_queue.get()
        try:
            task = await engine.task_repository.get(task_id)
            if task is None:
                continue
            await engine.process_task(task, worker_name)
        except Exception as exc:
            logging.exception("[%s] task_id=%s fatal error=%s", worker_name, task_id, exc)
        finally:
            engine.task_queue.task_done()
