from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re

import httpx

from app.models import TranscriptResult, TranscriptSegment
from app.services.stt.base import STTProvider


class MiniMaxSTTProvider(STTProvider):
    def __init__(self, api_key: str, group_id: str, stt_url: str, model: str) -> None:
        self.api_key = api_key
        self.group_id = group_id
        self.stt_url = stt_url
        self.model = model

    async def transcribe(self, audio_path: Path, language_hint: str | None = None) -> TranscriptResult:
        if not self.api_key:
            raise RuntimeError("MINIMAX_API_KEY_MISSING")
        if not self.stt_url:
            raise RuntimeError("MINIMAX_STT_URL_MISSING")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.group_id:
            headers["Group-Id"] = self.group_id

        form = {
            "model": self.model,
        }
        if language_hint:
            form["language"] = language_hint

        async with httpx.AsyncClient(timeout=300) as client:
            with audio_path.open("rb") as f:
                files = {"file": (audio_path.name, f, "application/octet-stream")}
                resp = await client.post(self.stt_url, headers=headers, data=form, files=files)
            resp.raise_for_status()
            payload = resp.json()

        return self._normalize(payload)

    def _normalize(self, payload: dict) -> TranscriptResult:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        full_text = str(data.get("text") or data.get("transcript") or "")
        language = str(data.get("language") or data.get("language_code") or "unknown")

        raw_segments = data.get("segments") if isinstance(data.get("segments"), list) else None
        raw_words = data.get("words") if isinstance(data.get("words"), list) else None

        if raw_segments:
            segments = self._from_segments(raw_segments)
        elif raw_words:
            segments = self._from_words(raw_words)
        else:
            segments = []

        if not segments and full_text:
            segments = [
                TranscriptSegment(
                    speaker_id="speaker_1",
                    start_seconds=0.0,
                    end_seconds=0.0,
                    text=full_text,
                )
            ]

        diarization = len({s.speaker_id for s in segments}) > 1
        duration = max((s.end_seconds for s in segments), default=float(data.get("duration") or 0.0))
        merged_text = full_text or "\n".join(seg.text for seg in segments)

        return TranscriptResult(
            language=language,
            duration_seconds=duration,
            diarization=diarization,
            full_text=merged_text,
            segments=segments,
        )

    @staticmethod
    def _from_segments(items: Iterable[dict]) -> list[TranscriptSegment]:
        out: list[TranscriptSegment] = []
        for row in items:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            out.append(
                TranscriptSegment(
                    speaker_id=str(row.get("speaker_id") or row.get("speaker") or "speaker_1"),
                    start_seconds=float(row.get("start") or row.get("start_time") or 0.0),
                    end_seconds=float(row.get("end") or row.get("end_time") or 0.0),
                    text=text,
                )
            )
        return out

    @staticmethod
    def _from_words(items: Iterable[dict]) -> list[TranscriptSegment]:
        rows = [x for x in items if isinstance(x, dict)]
        if not rows:
            return []

        merged: list[TranscriptSegment] = []
        speaker_id = str(rows[0].get("speaker_id") or rows[0].get("speaker") or "speaker_1")
        start = float(rows[0].get("start") or 0.0)
        end = float(rows[0].get("end") or start)
        tokens: list[str] = []

        for row in rows:
            token = str(row.get("text") or row.get("word") or "").strip()
            if not token:
                continue
            cur_speaker = str(row.get("speaker_id") or row.get("speaker") or speaker_id)
            cur_start = float(row.get("start") or end)
            cur_end = float(row.get("end") or cur_start)

            if cur_speaker != speaker_id and tokens:
                merged.append(
                    TranscriptSegment(
                        speaker_id=speaker_id,
                        start_seconds=start,
                        end_seconds=end,
                        text=MiniMaxSTTProvider._join_tokens(tokens),
                    )
                )
                tokens = []
                start = cur_start

            speaker_id = cur_speaker
            end = cur_end
            tokens.append(token)

        if tokens:
            merged.append(
                TranscriptSegment(
                    speaker_id=speaker_id,
                    start_seconds=start,
                    end_seconds=end,
                    text=MiniMaxSTTProvider._join_tokens(tokens),
                )
            )

        return merged

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
