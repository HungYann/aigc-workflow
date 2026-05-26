from __future__ import annotations

import asyncio


class ProductAgent:
    async def product_search(self, name: str, color: str) -> list[dict]:
        await asyncio.sleep(0.3)

        # Mock fallback when prompt asks unavailable item.
        if "缺货" in name:
            return [
                {
                    "id": "P404",
                    "imageUrl": "oss://products/p404.jpg",
                    "name": "缺货演示款",
                    "price": 199,
                }
            ]

        return [
            {
                "id": "P001",
                "imageUrl": "oss://products/p001-red-dress.jpg",
                "name": "玫瑰红连衣裙",
                "price": 299,
            }
        ]
