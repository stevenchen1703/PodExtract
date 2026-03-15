from __future__ import annotations

import httpx


class KnowledgeBaseClient:
    def __init__(self, search_url: str, api_key: str) -> None:
        self.search_url = search_url
        self.api_key = api_key

    async def find_related(self, text: str, top_k: int = 5) -> list[str]:
        if not self.search_url:
            return []

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"query": text[:2000], "top_k": top_k}

        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(self.search_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items") or []
        results: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", ""))
            summary = str(item.get("summary", ""))
            if title or summary:
                results.append(f"{title}: {summary}".strip(": "))
        return results
