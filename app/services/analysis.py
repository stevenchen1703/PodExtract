from __future__ import annotations

import asyncio
import logging

from app.models import AnalysisResult, TranscriptResult
from app.services.kb import KnowledgeBaseClient
from app.services.llm_client import LLMClient
from app.services.memory import OpenClawMemoryClient

logger = logging.getLogger(__name__)


class AnalysisService:
    _retry_windows: tuple[tuple[int, int], ...] = ((30000, 4), (18000, 3), (12000, 2))
    _attempts_per_window: int = 2
    _retry_base_delay_seconds: float = 1.0

    def __init__(
        self,
        llm: LLMClient,
        memory_client: OpenClawMemoryClient,
        kb_client: KnowledgeBaseClient,
    ) -> None:
        self.llm = llm
        self.memory_client = memory_client
        self.kb_client = kb_client

    async def run(self, title: str, transcript: TranscriptResult) -> AnalysisResult:
        memory = await self.memory_client.get_context(topic=title)
        related = await self.kb_client.find_related(transcript.full_text)

        if not self.llm.api_key:
            return self._fallback(related)

        system_prompt = (
            "You are a bilingual CN/EN knowledge extraction assistant. "
            "Return strict JSON with keys: logic_outline, highlights, work_connections, kb_connections. "
            "Each key must map to an array of concise strings. "
            "All output strings must be Simplified Chinese."
        )

        for chunk_size, max_chunks in self._retry_windows:
            chunks = self._chunk_text(transcript.full_text, chunk_size=chunk_size, max_chunks=max_chunks)
            chunk_text = "\n\n".join(f"[Chunk {idx+1}]\n{part}" for idx, part in enumerate(chunks))
            user_prompt = self._build_user_prompt(title, memory, related, chunk_text)

            for attempt in range(1, self._attempts_per_window + 1):
                try:
                    payload = await self.llm.chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
                    return self._result_from_payload(payload, related)
                except Exception as exc:
                    logger.warning(
                        "analysis llm attempt failed (attempt=%s chunk_size=%s max_chunks=%s): %s",
                        attempt,
                        chunk_size,
                        max_chunks,
                        exc,
                    )
                    if attempt < self._attempts_per_window:
                        delay = self._retry_base_delay_seconds * attempt
                        await asyncio.sleep(delay)

        logger.error(
            "analysis llm failed after retries (windows=%s attempts_per_window=%s)",
            self._retry_windows,
            self._attempts_per_window,
        )
        return self._fallback(related)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, max_chunks: int) -> list[str]:
        clean = text.strip()
        if not clean:
            return [""]
        chunks = [clean[i : i + chunk_size] for i in range(0, len(clean), chunk_size)]
        return chunks[:max_chunks]

    @staticmethod
    def _build_user_prompt(title: str, memory: str, related: list[str], chunk_text: str) -> str:
        return (
            f"Title: {title}\n\n"
            "Output requirements:\n"
            "1) logic_outline: chapter-level argument flow only, avoid anecdotes.\n"
            "2) highlights: story/quote/insight with clear value.\n"
            "3) work_connections: concrete actions connected to memory context.\n"
            "4) kb_connections: connections to related notes and rationale.\n\n"
            "5) language: all four arrays must be written in Simplified Chinese.\n\n"
            f"Memory context:\n{memory or 'N/A'}\n\n"
            f"Related knowledge:\n{chr(10).join(related) if related else 'N/A'}\n\n"
            f"Transcript excerpt:\n{chunk_text}"
        )

    @staticmethod
    def _normalize_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if value is None:
            return []
        item = str(value).strip()
        return [item] if item else []

    @classmethod
    def _result_from_payload(cls, payload: dict, related: list[str]) -> AnalysisResult:
        logic_outline = cls._normalize_list(payload.get("logic_outline"))
        highlights = cls._normalize_list(payload.get("highlights"))
        work_connections = cls._normalize_list(payload.get("work_connections"))
        kb_connections = cls._normalize_list(payload.get("kb_connections")) or related

        return AnalysisResult(
            logic_outline=logic_outline,
            highlights=highlights,
            work_connections=work_connections,
            kb_connections=kb_connections,
        )

    @staticmethod
    def _fallback(related: list[str]) -> AnalysisResult:
        return AnalysisResult(
            logic_outline=["LLM 分析暂不可用，请人工复核。"],
            highlights=[],
            work_connections=[],
            kb_connections=related,
        )
