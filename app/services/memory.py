from __future__ import annotations

import httpx


class OpenClawMemoryClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def get_context(self, topic: str) -> str:
        if not self.base_url or not self.api_key:
            return ""

        url = f"{self.base_url}/memory/context"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"topic": topic}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        return str(data.get("context", ""))
