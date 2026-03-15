from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.database import SQLiteStore
from app.services.processor import JobProcessor
from app.services.queue import JobQueue


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger = logging.getLogger("podextract.worker")

    store = SQLiteStore(settings.sqlite_path)
    queue = JobQueue(settings.redis_url, settings.redis_queue_key)
    processor = JobProcessor(settings=settings, store=store, queue=queue)

    logger.info("worker started")

    try:
        while True:
            job_id = await queue.dequeue(timeout_seconds=5)
            if not job_id:
                continue
            logger.info("job dequeued", extra={"job_id": job_id})
            await processor.process(job_id)
    finally:
        await queue.close()


if __name__ == "__main__":
    asyncio.run(run())
