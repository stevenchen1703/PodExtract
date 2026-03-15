from __future__ import annotations

import unittest

from app.models import TranscriptResult
from app.services.analysis import AnalysisService


class StubMemoryClient:
    async def get_context(self, topic: str) -> str:
        return ""


class StubKBClient:
    async def find_related(self, text: str, top_k: int = 5) -> list[str]:
        return ["Sample Note: Related context"]


class StubLLMClient:
    def __init__(self, fail_times: int, payload: dict | None = None, api_key: str = "set") -> None:
        self.fail_times = fail_times
        self.payload = payload or {}
        self.api_key = api_key
        self.calls = 0

    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("temporary llm error")
        return self.payload


class AnalysisServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_retries_then_success(self) -> None:
        llm = StubLLMClient(
            fail_times=1,
            payload={
                "logic_outline": ["part-a", "part-b"],
                "highlights": ["h1"],
                "work_connections": ["w1"],
                "kb_connections": ["k1"],
            },
        )
        service = AnalysisService(llm=llm, memory_client=StubMemoryClient(), kb_client=StubKBClient())
        service._retry_windows = ((30000, 4),)
        service._attempts_per_window = 2
        service._retry_base_delay_seconds = 0.0

        transcript = TranscriptResult(full_text="hello world " * 100)
        result = await service.run("title", transcript)

        self.assertEqual(llm.calls, 2)
        self.assertEqual(result.logic_outline, ["part-a", "part-b"])
        self.assertEqual(result.highlights, ["h1"])

    async def test_all_retries_fail_then_fallback(self) -> None:
        llm = StubLLMClient(fail_times=999)
        service = AnalysisService(llm=llm, memory_client=StubMemoryClient(), kb_client=StubKBClient())
        service._retry_windows = ((30000, 4), (18000, 3))
        service._attempts_per_window = 2
        service._retry_base_delay_seconds = 0.0

        transcript = TranscriptResult(full_text="hello world " * 100)
        result = await service.run("title", transcript)

        self.assertEqual(llm.calls, 4)
        self.assertEqual(result.logic_outline, ["LLM 分析暂不可用，请人工复核。"])
        self.assertEqual(result.kb_connections, ["Sample Note: Related context"])

    async def test_missing_api_key_uses_fallback_without_call(self) -> None:
        llm = StubLLMClient(fail_times=0, payload={"logic_outline": ["x"]}, api_key="")
        service = AnalysisService(llm=llm, memory_client=StubMemoryClient(), kb_client=StubKBClient())

        transcript = TranscriptResult(full_text="hello")
        result = await service.run("title", transcript)

        self.assertEqual(llm.calls, 0)
        self.assertEqual(result.logic_outline, ["LLM 分析暂不可用，请人工复核。"])


if __name__ == "__main__":
    unittest.main()
