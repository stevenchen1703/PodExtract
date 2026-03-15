from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import DigestRun, JobState, Subscription


class SQLiteStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    input_url TEXT NOT NULL,
                    source_hint TEXT,
                    language_hint TEXT,
                    from_channel TEXT,
                    canonical_url TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    transcript_json TEXT,
                    analysis_json TEXT,
                    delivery_json TEXT,
                    notify_json TEXT,
                    attempts_json TEXT NOT NULL,
                    error_json TEXT NOT NULL,
                    debug_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_url)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS digest_runs (
                    digest_id TEXT PRIMARY KEY,
                    subscription_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_digest_subscription ON digest_runs(subscription_id)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    subscription_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_subscription ON episodes(subscription_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_canonical ON episodes(canonical_url)")
        conn.close()

    async def create_job(self, job: JobState) -> JobState:
        await asyncio.to_thread(self._create_job_sync, job)
        return job

    def _create_job_sync(self, job: JobState) -> None:
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, status, stage, input_url, source_hint, language_hint, from_channel,
                    canonical_url, source_json, transcript_json, analysis_json, delivery_json,
                    notify_json, attempts_json, error_json, debug_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.status.value,
                    job.stage.value,
                    job.input_url,
                    job.source_hint,
                    job.language_hint,
                    job.from_channel,
                    job.source.canonical_url,
                    job.source.model_dump_json(),
                    job.transcript.model_dump_json() if job.transcript else None,
                    job.analysis.model_dump_json() if job.analysis else None,
                    job.delivery.model_dump_json() if job.delivery else None,
                    job.notify_target.model_dump_json() if job.notify_target else None,
                    job.attempts.model_dump_json(),
                    job.error.model_dump_json(),
                    json.dumps(job.debug, ensure_ascii=False),
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
        conn.close()

    async def save_job(self, job: JobState) -> JobState:
        job.updated_at = datetime.now(timezone.utc)
        await asyncio.to_thread(self._save_job_sync, job)
        return job

    def _save_job_sync(self, job: JobState) -> None:
        conn = self._connect()
        with conn:
            conn.execute(
                """
                UPDATE jobs
                SET status=?, stage=?, source_json=?, transcript_json=?, analysis_json=?, delivery_json=?,
                    notify_json=?, attempts_json=?, error_json=?, debug_json=?, updated_at=?
                WHERE job_id=?
                """,
                (
                    job.status.value,
                    job.stage.value,
                    job.source.model_dump_json(),
                    job.transcript.model_dump_json() if job.transcript else None,
                    job.analysis.model_dump_json() if job.analysis else None,
                    job.delivery.model_dump_json() if job.delivery else None,
                    job.notify_target.model_dump_json() if job.notify_target else None,
                    job.attempts.model_dump_json(),
                    job.error.model_dump_json(),
                    json.dumps(job.debug, ensure_ascii=False),
                    job.updated_at.isoformat(),
                    job.job_id,
                ),
            )
        conn.close()

    async def get_job(self, job_id: str) -> JobState | None:
        return await asyncio.to_thread(self._get_job_sync, job_id)

    def _get_job_sync(self, job_id: str) -> JobState | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_job(row)

    async def list_jobs(self, limit: int = 20) -> list[JobState]:
        return await asyncio.to_thread(self._list_jobs_sync, limit)

    def _list_jobs_sync(self, limit: int = 20) -> list[JobState]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [self._row_to_job(row) for row in rows]

    async def find_recent_by_canonical(self, canonical_url: str, within_hours: int) -> JobState | None:
        return await asyncio.to_thread(self._find_recent_by_canonical_sync, canonical_url, within_hours)

    def _find_recent_by_canonical_sync(self, canonical_url: str, within_hours: int) -> JobState | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
        conn = self._connect()
        row = conn.execute(
            """
            SELECT * FROM jobs
            WHERE canonical_url=?
              AND created_at>=?
              AND status IN ('queued', 'running', 'completed')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (canonical_url, cutoff),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_job(row)

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobState:
        debug_json = row["debug_json"] or "{}"
        source = json.loads(row["source_json"])
        transcript = json.loads(row["transcript_json"]) if row["transcript_json"] else None
        analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else None
        delivery = json.loads(row["delivery_json"]) if row["delivery_json"] else None
        notify = json.loads(row["notify_json"]) if row["notify_json"] else None
        attempts = json.loads(row["attempts_json"] or "{}")
        error = json.loads(row["error_json"] or "{}")

        return JobState.model_validate(
            {
                "job_id": row["job_id"],
                "status": row["status"],
                "stage": row["stage"],
                "input_url": row["input_url"],
                "source_hint": row["source_hint"],
                "language_hint": row["language_hint"],
                "from_channel": row["from_channel"],
                "source": source,
                "transcript": transcript,
                "analysis": analysis,
                "delivery": delivery,
                "notify_target": notify,
                "attempts": attempts,
                "error": error,
                "debug": json.loads(debug_json),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    async def create_subscription(self, item: Subscription) -> Subscription:
        await asyncio.to_thread(self._create_subscription_sync, item)
        return item

    def _create_subscription_sync(self, item: Subscription) -> None:
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO subscriptions(
                    subscription_id, source_url, source_type, author_name, frequency, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.subscription_id,
                    item.source_url,
                    item.source_type,
                    item.author_name,
                    item.frequency,
                    item.status.value,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                ),
            )
        conn.close()

    async def list_subscriptions(self) -> list[Subscription]:
        return await asyncio.to_thread(self._list_subscriptions_sync)

    def _list_subscriptions_sync(self) -> list[Subscription]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()
        conn.close()
        return [self._row_to_subscription(row) for row in rows]

    async def get_subscription(self, subscription_id: str) -> Subscription | None:
        return await asyncio.to_thread(self._get_subscription_sync, subscription_id)

    def _get_subscription_sync(self, subscription_id: str) -> Subscription | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (subscription_id,)).fetchone()
        conn.close()
        return self._row_to_subscription(row) if row else None

    async def save_subscription(self, item: Subscription) -> Subscription:
        item.updated_at = datetime.now(timezone.utc)
        await asyncio.to_thread(self._save_subscription_sync, item)
        return item

    def _save_subscription_sync(self, item: Subscription) -> None:
        conn = self._connect()
        with conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET source_url=?, source_type=?, author_name=?, frequency=?, status=?, updated_at=?
                WHERE subscription_id=?
                """,
                (
                    item.source_url,
                    item.source_type,
                    item.author_name,
                    item.frequency,
                    item.status.value,
                    item.updated_at.isoformat(),
                    item.subscription_id,
                ),
            )
        conn.close()

    @staticmethod
    def _row_to_subscription(row: sqlite3.Row) -> Subscription:
        return Subscription.model_validate(
            {
                "subscription_id": row["subscription_id"],
                "source_url": row["source_url"],
                "source_type": row["source_type"],
                "author_name": row["author_name"],
                "frequency": row["frequency"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    async def create_digest_run(self, item: DigestRun) -> DigestRun:
        await asyncio.to_thread(self._create_digest_run_sync, item)
        return item

    def _create_digest_run_sync(self, item: DigestRun) -> None:
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO digest_runs(
                    digest_id, subscription_id, status, summary, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.digest_id,
                    item.subscription_id,
                    item.status.value,
                    item.summary,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                ),
            )
        conn.close()

    async def get_digest_run(self, digest_id: str) -> DigestRun | None:
        return await asyncio.to_thread(self._get_digest_run_sync, digest_id)

    def _get_digest_run_sync(self, digest_id: str) -> DigestRun | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM digest_runs WHERE digest_id=?", (digest_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return DigestRun.model_validate(
            {
                "digest_id": row["digest_id"],
                "subscription_id": row["subscription_id"],
                "status": row["status"],
                "summary": row["summary"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
