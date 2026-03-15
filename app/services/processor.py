from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.config import Settings
from app.models import JobError, JobStage, JobState, JobStatus
from app.services.analysis import AnalysisService
from app.services.database import SQLiteStore
from app.services.extractor import ExtractorService
from app.services.feishu import FeishuClient
from app.services.kb import KnowledgeBaseClient
from app.services.llm_client import LLMClient
from app.services.memory import OpenClawMemoryClient
from app.services.queue import JobQueue
from app.services.stt.base import STTProvider
from app.services.stt.elevenlabs import ElevenLabsSTTProvider
from app.services.stt.minimax import MiniMaxSTTProvider

if TYPE_CHECKING:
    from app.services.queue import JobQueue

logger = logging.getLogger(__name__)


@dataclass
class StageFailure(Exception):
    code: str
    message: str


class JobProcessor:
    def __init__(self, settings: Settings, store: SQLiteStore, queue: JobQueue | None = None) -> None:
        self.settings = settings
        self.store = store
        self.queue = queue
        self.extractor = ExtractorService(settings.work_dir, settings.max_rss_items_scan)

        llm = LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
        memory = OpenClawMemoryClient(settings.openclaw_base_url, settings.openclaw_api_key)
        kb = KnowledgeBaseClient(settings.kb_search_url, settings.kb_search_api_key)
        self.analysis = AnalysisService(llm, memory, kb)

        self.feishu = FeishuClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
            verification_token=settings.feishu_verification_token,
            bitable_app_token=settings.feishu_bitable_app_token,
            bitable_table_id=settings.feishu_bitable_table_id,
        )

    async def _log(self, job_id: str, message: str) -> None:
        """Publish log message if queue is available."""
        if self.queue:
            await self.queue.publish_log(job_id, message)

    async def process(self, job_id: str) -> None:
        job = await self.store.get_job(job_id)
        if not job:
            logger.warning("job not found", extra={"job_id": job_id})
            return

        try:
            await self._log(job_id, "开始处理任务...")
            job.status = JobStatus.running
            job.stage = JobStage.extract
            await self.store.save_job(job)

            await self._log(job_id, "阶段 1/4: 下载音视频...")
            audio_path, metadata, source = await self._run_extract(job)
            job.source = source
            job.debug["extractor"] = metadata
            job.stage = JobStage.transcribe
            await self.store.save_job(job)

            await self._log(job_id, "阶段 2/4: ASR 转写中...")
            transcript = await self._run_transcribe(job, audio_path)
            job.transcript = transcript
            job.stage = JobStage.analyze
            await self.store.save_job(job)

            await self._log(job_id, "阶段 3/4: AI 分析中...")
            analysis = await self.analysis.run(job.source.title or "Untitled", transcript)
            job.analysis = analysis
            job.stage = JobStage.publish
            await self.store.save_job(job)

            await self._log(job_id, "阶段 4/4: 发布结果...")
            delivery = await self._run_publish(job)
            job.delivery = delivery
            job.status = JobStatus.completed
            job.stage = JobStage.done
            await self.store.save_job(job)
            await self._log(job_id, "处理完成!")

        except StageFailure as exc:
            job.status = JobStatus.failed
            job.error = JobError(code=exc.code, message=exc.message)
            await self.store.save_job(job)
            logger.exception("job failed", extra={"job_id": job.job_id, "code": exc.code})
        except Exception as exc:
            job.status = JobStatus.failed
            job.error = JobError(code="UNHANDLED", message=str(exc))
            await self.store.save_job(job)
            logger.exception("job failed with unhandled error", extra={"job_id": job.job_id})
        finally:
            logger.info(f"Job {job.job_id} finished, notify_target={job.notify_target is not None}, status={job.status.value}")
            if job.notify_target:
                try:
                    await self.feishu.send_job_result(job.notify_target, job)
                except Exception:
                    logger.exception("failed to send feishu result", extra={"job_id": job.job_id})

    async def _run_extract(self, job: JobState):
        attempts = max(1, self.settings.stage_retry_extract)
        for idx in range(1, attempts + 1):
            job.attempts.extract = idx
            await self.store.save_job(job)
            try:
                return await asyncio.to_thread(self.extractor.fetch_audio, job.source, job.job_id)
            except Exception as exc:
                if idx >= attempts:
                    raise StageFailure("EXTRACT_FAILED", str(exc)) from exc
                await asyncio.sleep(self.settings.stage_retry_base_delay_seconds * (2 ** (idx - 1)))

        raise StageFailure("EXTRACT_FAILED", "unknown")

    async def _run_transcribe(self, job: JobState, audio_path):
        attempts = max(1, self.settings.stage_retry_stt)
        for idx in range(1, attempts + 1):
            job.attempts.transcribe = idx
            await self.store.save_job(job)
            try:
                primary = self._build_stt_provider(self.settings.stt_primary_provider)
                return await primary.transcribe(audio_path, job.language_hint)
            except Exception as primary_exc:
                fallback_name = self.settings.stt_fallback_provider
                if fallback_name and fallback_name != self.settings.stt_primary_provider:
                    try:
                        fallback = self._build_stt_provider(fallback_name)
                        result = await fallback.transcribe(audio_path, job.language_hint)
                        job.debug["stt_fallback"] = {
                            "from": self.settings.stt_primary_provider,
                            "to": fallback_name,
                            "reason": str(primary_exc),
                        }
                        await self.store.save_job(job)
                        return result
                    except Exception as fallback_exc:
                        if idx >= attempts:
                            message = f"primary={primary_exc}; fallback={fallback_exc}"
                            raise StageFailure("TRANSCRIBE_FAILED", message) from fallback_exc
                if idx >= attempts:
                    raise StageFailure("TRANSCRIBE_FAILED", str(primary_exc)) from primary_exc
                await asyncio.sleep(self.settings.stage_retry_base_delay_seconds * (2 ** (idx - 1)))

        raise StageFailure("TRANSCRIBE_FAILED", "unknown")

    async def _run_publish(self, job: JobState):
        if not job.transcript or not job.analysis:
            raise StageFailure("PUBLISH_INPUT_MISSING", "transcript or analysis missing")

        attempts = max(1, self.settings.stage_retry_publish)
        for idx in range(1, attempts + 1):
            job.attempts.publish = idx
            await self.store.save_job(job)
            try:
                title = job.source.title or f"Episode {job.job_id[:8]}"
                return await self.feishu.save(
                    title=title,
                    source_url=job.source.canonical_url,
                    transcript=job.transcript,
                    analysis=job.analysis,
                )
            except Exception as exc:
                if idx >= attempts:
                    raise StageFailure("PUBLISH_FAILED", str(exc)) from exc
                await asyncio.sleep(self.settings.stage_retry_base_delay_seconds * (2 ** (idx - 1)))

        raise StageFailure("PUBLISH_FAILED", "unknown")

    def _build_stt_provider(self, provider_name: str) -> STTProvider:
        name = (provider_name or "").lower().strip()
        if name == "minimax":
            return MiniMaxSTTProvider(
                api_key=self.settings.minimax_api_key,
                group_id=self.settings.minimax_group_id,
                stt_url=self.settings.minimax_stt_url,
                model=self.settings.minimax_stt_model,
            )
        if name == "elevenlabs":
            return ElevenLabsSTTProvider(
                api_key=self.settings.elevenlabs_api_key,
                model_id=self.settings.elevenlabs_model_id,
            )
        raise StageFailure("STT_PROVIDER_UNSUPPORTED", name)
