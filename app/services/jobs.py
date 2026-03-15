from __future__ import annotations

from app.config import Settings
from app.models import JobState, JobStatus, NotificationTarget, SourceInfo, SubmitLinkRequest
from app.services.database import SQLiteStore
from app.services.queue import JobQueue
from app.services.source import SourceResolver


class JobService:
    def __init__(self, settings: Settings, store: SQLiteStore, queue: JobQueue) -> None:
        self.settings = settings
        self.store = store
        self.queue = queue
        self.source_resolver = SourceResolver(max_rss_items_scan=settings.max_rss_items_scan)

    async def create_job(
        self,
        req: SubmitLinkRequest,
        notify_target: NotificationTarget | None = None,
    ) -> tuple[JobState, bool]:
        source: SourceInfo = await self.source_resolver.resolve(str(req.url), req.source_hint)

        existing = await self.store.find_recent_by_canonical(
            canonical_url=source.canonical_url,
            within_hours=self.settings.dedupe_window_hours,
        )
        if existing:
            if (
                notify_target
                and not existing.notify_target
                and existing.status in {JobStatus.queued, JobStatus.running}
            ):
                existing.notify_target = notify_target
                await self.store.save_job(existing)
            return existing, True

        job = JobState(
            input_url=str(req.url),
            source_hint=req.source_hint,
            language_hint=req.language_hint,
            from_channel=req.from_channel,
            source=source,
            notify_target=notify_target,
        )
        await self.store.create_job(job)
        await self.queue.enqueue(job.job_id)
        return job, False
