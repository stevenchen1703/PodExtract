from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re

import httpx

from app.models import TranscriptResult, TranscriptSegment
from app.services.stt.base import STTProvider


class ElevenLabsSTTProvider(STTProvider):
    def __init__(self, api_key: str, model_id: str = "scribe_v1") -> None:
        self.api_key = api_key
        self.model_id = model_id

    async def transcribe(self, audio_path: Path, language_hint: str | None = None) -> TranscriptResult:
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY_MISSING")

        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {"xi-api-key": self.api_key}
        data = {
            "model_id": self.model_id,
            "diarize": "true",
            "tag_audio_events": "true",
        }
        if language_hint:
            data["language_code"] = language_hint

        async with httpx.AsyncClient(timeout=300) as client:
            with audio_path.open("rb") as f:
                files = {"file": (audio_path.name, f, "application/octet-stream")}
                resp = await client.post(url, headers=headers, data=data, files=files)
            resp.raise_for_status()
            payload = resp.json()

        return self._normalize(payload)

    def _normalize(self, payload: dict) -> TranscriptResult:
        language = payload.get("language_code") or payload.get("language") or "unknown"
        full_text = payload.get("text") or ""

        if isinstance(payload.get("segments"), list):
            segments = self._from_segments(payload["segments"])
        elif isinstance(payload.get("words"), list):
            segments = self._from_words(payload["words"])
        else:
            segments = []

        diarization = len({s.speaker_id for s in segments}) > 1
        duration = self._duration_from_segments(segments)
        text = full_text or "\n".join(seg.text for seg in segments)

        return TranscriptResult(
            language=language,
            duration_seconds=duration,
            diarization=diarization,
            full_text=text,
            segments=segments,
        )

    @staticmethod
    def _from_segments(raw_segments: Iterable[dict]) -> list[TranscriptSegment]:
        items: list[TranscriptSegment] = []
        for row in raw_segments:
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            items.append(
                TranscriptSegment(
                    speaker_id=str(row.get("speaker") or row.get("speaker_id") or "speaker_1"),
                    start_seconds=float(row.get("start") or row.get("start_time") or 0.0),
                    end_seconds=float(row.get("end") or row.get("end_time") or 0.0),
                    text=text,
                )
            )
        return items

    @staticmethod
    def _from_words(words: Iterable[dict]) -> list[TranscriptSegment]:
        rows = [w for w in words if isinstance(w, dict)]
        if not rows:
            return []

        merged: list[TranscriptSegment] = []
        speaker = str(rows[0].get("speaker_id") or rows[0].get("speaker") or "speaker_1")
        start = float(rows[0].get("start") or 0.0)
        end = float(rows[0].get("end") or start)
        tokens: list[str] = []

        for row in rows:
            token = str(row.get("text") or row.get("word") or "").strip()
            if not token:
                continue
            cur_speaker = str(row.get("speaker_id") or row.get("speaker") or speaker)
            cur_start = float(row.get("start") or end)
            cur_end = float(row.get("end") or cur_start)

            if cur_speaker != speaker and tokens:
                merged.append(
                    TranscriptSegment(
                        speaker_id=speaker,
                        start_seconds=start,
                        end_seconds=end,
                        text=ElevenLabsSTTProvider._join_tokens(tokens),
                    )
                )
                tokens = []
                start = cur_start

            speaker = cur_speaker
            end = cur_end
            tokens.append(token)

        if tokens:
            merged.append(
                TranscriptSegment(
                    speaker_id=speaker,
                    start_seconds=start,
                    end_seconds=end,
                    text=ElevenLabsSTTProvider._join_tokens(tokens),
                )
            )

        return merged

    @staticmethod
    def _duration_from_segments(segments: list[TranscriptSegment]) -> float:
        return max((x.end_seconds for x in segments), default=0.0)

    @staticmethod
    def _join_tokens(tokens: list[str]) -> str:
        clean = [x.strip() for x in tokens if str(x).strip()]
        if not clean:
            return ""

        cjk_count = sum(1 for x in clean if re.search(r"[\u4e00-\u9fff]", x))
        latin_count = sum(1 for x in clean if re.search(r"[A-Za-z0-9]", x))

        if cjk_count >= latin_count:
            return "".join(clean).strip()
        return " ".join(clean).strip()
