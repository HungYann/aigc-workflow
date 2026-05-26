from __future__ import annotations

import asyncio
from collections import defaultdict


class QuotaNotEnoughError(Exception):
    pass


class AccountService:
    def __init__(self, initial_quota: dict[str, int] | None = None) -> None:
        self._quota = defaultdict(int)
        self._lock = asyncio.Lock()
        if initial_quota:
            for user_id, value in initial_quota.items():
                self._quota[user_id] = value

    async def check_and_consume(self, user_id: str, amount: int = 1) -> int:
        async with self._lock:
            remain = self._quota[user_id]
            if remain < amount:
                raise QuotaNotEnoughError(
                    f"user={user_id} quota not enough, remain={remain}, required={amount}"
                )
            self._quota[user_id] = remain - amount
            return self._quota[user_id]

    async def refund(self, user_id: str, amount: int = 1) -> int:
        async with self._lock:
            self._quota[user_id] += amount
            return self._quota[user_id]

    async def get_quota(self, user_id: str) -> int:
        async with self._lock:
            return self._quota[user_id]

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            return dict(self._quota)
