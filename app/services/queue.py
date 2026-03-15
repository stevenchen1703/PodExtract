from __future__ import annotations

from redis.asyncio import Redis


class JobQueue:
    def __init__(self, redis_url: str, queue_key: str) -> None:
        self.queue_key = queue_key
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def enqueue(self, job_id: str) -> None:
        await self.redis.rpush(self.queue_key, job_id)

    async def dequeue(self, timeout_seconds: int = 5) -> str | None:
        data = await self.redis.blpop(self.queue_key, timeout=timeout_seconds)
        if not data:
            return None
        _, job_id = data
        return job_id

    async def publish_log(self, job_id: str, message: str) -> None:
        """Publish a log message to the job's log channel."""
        channel = f"podextract:logs:{job_id}"
        await self.redis.publish(channel, message)

    async def close(self) -> None:
        await self.redis.aclose()
