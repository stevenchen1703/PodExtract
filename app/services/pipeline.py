from __future__ import annotations

from app.config import Settings
from app.services.database import SQLiteStore
from app.services.processor import JobProcessor


class Pipeline:
    """Backward-compatible wrapper around JobProcessor."""

    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.processor = JobProcessor(settings=settings, store=store)

    async def run(self, job_id: str) -> None:
        await self.processor.process(job_id)
