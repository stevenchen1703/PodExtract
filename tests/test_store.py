from __future__ import annotations

import tempfile
import unittest

from app.models import JobState, SourceInfo, SourcePlatform
from app.services.database import SQLiteStore


class StoreTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_get_and_dedupe_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.db"
            store = SQLiteStore(db_path)

            job = JobState(
                input_url="https://www.youtube.com/watch?v=abc123",
                source=SourceInfo(
                    platform=SourcePlatform.youtube,
                    original_url="https://youtu.be/abc123",
                    canonical_url="https://www.youtube.com/watch?v=abc123",
                ),
            )
            await store.create_job(job)

            fetched = await store.get_job(job.job_id)
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.job_id, job.job_id)

            dedup = await store.find_recent_by_canonical(job.source.canonical_url, within_hours=24)
            self.assertIsNotNone(dedup)
            self.assertEqual(dedup.job_id, job.job_id)


if __name__ == "__main__":
    unittest.main()
