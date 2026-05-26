from __future__ import annotations

import unittest

from repository.task_repository import TaskRepository
from services.account_service import AccountService, QuotaNotEnoughError
from models.task import VideoTask


class RepoAndAccountTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_repository_save_and_get(self) -> None:
        repo = TaskRepository()
        task = VideoTask(
            task_id="T-test",
            request_id="req-test",
            session_id="sess-test",
            user_id="U001",
            prompt="demo",
        )
        await repo.save(task)
        got = await repo.get("T-test")
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.task_id, "T-test")

    async def test_account_consume_and_refund(self) -> None:
        account = AccountService({"U001": 1})
        remain = await account.check_and_consume("U001")
        self.assertEqual(remain, 0)

        with self.assertRaises(QuotaNotEnoughError):
            await account.check_and_consume("U001")

        remain2 = await account.refund("U001")
        self.assertEqual(remain2, 1)


if __name__ == "__main__":
    unittest.main()
