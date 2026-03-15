from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import dashscope
from dashscope import MultiModalConversation

from app.models import TranscriptResult, TranscriptSegment
from app.services.stt.base import STTProvider

logger = logging.getLogger(__name__)


class QwenASRProvider(STTProvider):
    """Qwen3-ASR-Flash provider using DashScope API."""

    def __init__(self, api_key: str, model: str = "qwen3-asr-flash") -> None:
        self.api_key = api_key
        self.model = model
        dashscope.api_key = api_key

    async def transcribe(self, audio_path: Path, language_hint: Optional[str] = None) -> TranscriptResult:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY_MISSING")

        logger.info(f"Qwen ASR: Starting transcription for {audio_path}")
        logger.info(f"Qwen ASR: File exists: {audio_path.exists()}, size: {audio_path.stat().st_size if audio_path.exists() else 0}")

        asr_options = {
            "enable_lid": True,  # Enable language detection
            "enable_itn": False,
        }
        if language_hint:
            asr_options["language"] = language_hint
            logger.info(f"Qwen ASR: Language hint: {language_hint}")

        # Qwen ASR expects a publicly accessible URL
        # For local files, we need to use file:// protocol or upload to OSS
        audio_url = f"file://{audio_path.absolute()}"
        logger.info(f"Qwen ASR: Using audio URL: {audio_url}")

        messages = [
            {
                "role": "system",
                "content": [{"text": ""}],
            },
            {
                "role": "user",
                "content": [
                    {"audio": audio_url},
                ],
            }
        ]

        try:
            logger.info(f"Qwen ASR: Calling API with model {self.model}...")
            response = MultiModalConversation.call(
                model=self.model,
                messages=messages,
                result_format="message",
                asr_options=asr_options,
            )
            logger.info(f"Qwen ASR: Response status: {response.status_code}")
        except Exception as e:
            logger.error(f"Qwen ASR call failed: {e}")
            raise RuntimeError(f"QWEN_ASR_FAILED: {e}")

        return self._normalize(response)

    def _normalize(self, response) -> TranscriptResult:
        """Normalize Qwen API response to TranscriptResult."""
        # Check for errors
        if response.status_code != 200:
            error_msg = response.message if hasattr(response, 'message') else "Unknown error"
            raise RuntimeError(f"QWEN_ASR_ERROR: {error_msg}")

        # Extract content from response
        try:
            content = response.output.choices[0].message.content
            if not content or not isinstance(content, list):
                raise ValueError("No content in response")

            # Find the text field in content
            text = ""
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    text = item["text"]
                    break

            if not text:
                raise ValueError("No text found in response")

            # Qwen ASR returns plain text, not segments
            # Create a single segment for the entire transcript
            segments = [
                TranscriptSegment(
                    speaker_id="speaker_1",
                    start_seconds=0.0,
                    end_seconds=0.0,  # Qwen doesn't provide timestamps
                    text=text,
                )
            ]

            return TranscriptResult(
                language="auto",  # Qwen detects language
                duration_seconds=0.0,
                diarization=False,
                full_text=text,
                segments=segments,
            )

        except Exception as e:
            logger.error(f"Failed to parse Qwen response: {e}")
            raise RuntimeError(f"QWEN_RESPONSE_PARSE_ERROR: {e}")
