from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def retry_async(
    fn: Callable[[], Awaitable],
    max_attempts: int,
    base_delay_seconds: float,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
):
    last_error: BaseException | None = None
    attempts = max(1, max_attempts)

    for idx in range(attempts):
        try:
            return await fn()
        except retry_on as exc:  # type: ignore[misc]
            last_error = exc
            if idx >= attempts - 1:
                break
            delay = base_delay_seconds * (2**idx)
            await asyncio.sleep(delay)

    if last_error:
        raise last_error
    raise RuntimeError("retry_async_failed_without_error")
