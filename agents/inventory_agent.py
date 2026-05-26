from __future__ import annotations

import asyncio


class InventoryAgent:
    def __init__(self) -> None:
        self._inventory = {
            "P001": 23,
            "P404": 0,
        }

    async def inventory_query(self, product_id: str) -> dict:
        await asyncio.sleep(0.2)
        return {"available": self._inventory.get(product_id, 0)}
