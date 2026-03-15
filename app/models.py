from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    failed = "failed"
    completed = "completed"


class JobStage(str, Enum):
    queued = "queued"
    extract = "extract"
    transcribe = "transcribe"
    analyze = "analyze"
    publish = "publish"
    done = "done"


class SourcePlatform(str, Enum):
    youtube = "youtube"
    bilibili = "bilibili"
    rss = "rss"
    apple_podcast = "apple_podcast"
    unknown = "unknown"


class SubscriptionStatus(str, Enum):
    active = "active"
    paused = "paused"


class DigestRunStatus(str, Enum):
    queued = "queued"
    not_implemented = "not_implemented"


class SourceInfo(BaseModel):
    platform: SourcePlatform = SourcePlatform.unknown
    original_url: str
    canonical_url: str
    title: str = ""
    author: str = ""
    published_at: str = ""
    duration_seconds: float = 0.0
    feed_url: str = ""
    entry_url: str = ""


class TranscriptSegment(BaseModel):
    speaker_id: str = "speaker_1"
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    text: str = ""


class TranscriptResult(BaseModel):
    language: str = "unknown"
    duration_seconds: float = 0.0
    diarization: bool = False
    full_text: str = ""
    segments: list[TranscriptSegment] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    logic_outline: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    work_connections: list[str] = Field(default_factory=list)
    kb_connections: list[str] = Field(default_factory=list)


class DeliveryResult(BaseModel):
    feishu_doc_url: str = ""
    feishu_doc_id: str = ""
    bitable_record_id: str = ""


class NotificationTarget(BaseModel):
    channel: str = ""
    receive_id_type: str = ""
    receive_id: str = ""


class JobError(BaseModel):
    code: str = ""
    message: str = ""


class JobAttempts(BaseModel):
    extract: int = 0
    transcribe: int = 0
    analyze: int = 0
    publish: int = 0


class JobState(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.queued
    stage: JobStage = JobStage.queued
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    input_url: str
    source_hint: str | None = None
    language_hint: str | None = None
    from_channel: str | None = None

    source: SourceInfo
    transcript: TranscriptResult | None = None
    analysis: AnalysisResult | None = None
    delivery: DeliveryResult | None = None

    notify_target: NotificationTarget | None = None

    attempts: JobAttempts = Field(default_factory=JobAttempts)
    error: JobError = Field(default_factory=JobError)
    debug: dict[str, Any] = Field(default_factory=dict)


class SubmitLinkRequest(BaseModel):
    url: HttpUrl | str
    source_hint: str | None = None
    language_hint: str | None = None
    from_channel: str | None = None


class SubmitLinkResponse(BaseModel):
    job_id: str
    status: JobStatus
    deduplicated: bool = False


class HealthResponse(BaseModel):
    status: str = "ok"


class SubscriptionCreateRequest(BaseModel):
    source_url: str
    source_type: str = "rss"
    author_name: str = ""
    frequency: str = "daily"


class SubscriptionPatchRequest(BaseModel):
    status: SubscriptionStatus | None = None
    frequency: str | None = None


class Subscription(BaseModel):
    subscription_id: str = Field(default_factory=lambda: str(uuid4()))
    source_url: str
    source_type: str = "rss"
    author_name: str = ""
    frequency: str = "daily"
    status: SubscriptionStatus = SubscriptionStatus.active
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DigestRun(BaseModel):
    digest_id: str = Field(default_factory=lambda: str(uuid4()))
    subscription_id: str
    status: DigestRunStatus = DigestRunStatus.queued
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Episode(BaseModel):
    episode_id: str = Field(default_factory=lambda: str(uuid4()))
    subscription_id: str
    title: str = ""
    canonical_url: str = ""
    published_at: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
