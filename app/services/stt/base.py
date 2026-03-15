from __future__ import annotations

from pathlib import Path

from app.models import TranscriptResult


class STTProvider:
    async def transcribe(self, audio_path: Path, language_hint: str | None = None) -> TranscriptResult:
        raise NotImplementedError
