from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.models import AnalysisResult, DeliveryResult, JobState, NotificationTarget, TranscriptResult
from app.services.source import extract_first_url

logger = logging.getLogger(__name__)


@dataclass
class _TokenCache:
    token: str = ""
    expires_at: datetime = datetime.now(timezone.utc)


class FeishuClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        verification_token: str,
        bitable_app_token: str,
        bitable_table_id: str,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.bitable_app_token = bitable_app_token
        self.bitable_table_id = bitable_table_id
        self._cache = _TokenCache()

    def is_enabled(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def verify_event(self, payload: dict) -> bool:
        if not self.verification_token:
            return True

        token = payload.get("token")
        if token and token == self.verification_token:
            return True

        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        return bool(header.get("token") == self.verification_token)

    def parse_event(self, payload: dict) -> dict:
        if payload.get("type") == "url_verification":
            return {"event_type": "url_verification", "challenge": payload.get("challenge", "")}

        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        event_type = header.get("event_type") or payload.get("type")

        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        message_type = message.get("message_type")
        if event_type != "im.message.receive_v1" or message_type != "text":
            return {"event_type": str(event_type or "unknown")}

        content_raw = message.get("content")
        content = {}
        if isinstance(content_raw, str):
            try:
                content = json.loads(content_raw)
            except json.JSONDecodeError:
                content = {"text": content_raw}
        elif isinstance(content_raw, dict):
            content = content_raw

        text = str(content.get("text") or "")
        url = extract_first_url(text)
        if not url:
            return {"event_type": "im.message.receive_v1", "url": ""}

        chat_id = str(message.get("chat_id") or "")
        open_id = str(((event.get("sender") or {}).get("sender_id") or {}).get("open_id") or "")

        target = NotificationTarget(channel="feishu", receive_id_type="chat_id", receive_id=chat_id or open_id)

        return {
            "event_type": "im.message.receive_v1",
            "url": url,
            "notify_target": target,
        }

    async def send_ack(self, target: NotificationTarget, job_id: str) -> None:
        if not target.receive_id:
            return
        msg = f"任务已创建，正在处理中。Job ID: {job_id}"
        await self.send_text(target.receive_id_type or "chat_id", target.receive_id, msg)

    async def send_job_result(self, target: NotificationTarget, job: JobState) -> None:
        logger.info(f"send_job_result called for job {job.job_id}, status={job.status.value}")
        if not target.receive_id:
            logger.warning(f"No receive_id for job {job.job_id}, skipping notification")
            return

        if job.status.value == "completed":
            title = job.source.title or "Untitled"
            # Include web UI link instead of just doc URL
            web_url = f"http://127.0.0.1:8000/sandbox"
            highlights = ""
            if job.analysis and job.analysis.highlights:
                highlights = "\n".join([f"• {h}" for h in job.analysis.highlights[:3]])
                highlights = f"\n亮点：\n{highlights}"

            msg = f"✅ 处理完成：{title}\n\n查看详情：{web_url}{highlights}"
            logger.info(f"Sending completion message for job {job.job_id}")
        else:
            code = job.error.code or "UNKNOWN"
            msg = f"❌ 处理失败：{code}\n\n{job.error.message or '请稍后重试'}"
            logger.error(f"Job {job.job_id} failed: {code}")

        await self.send_text(target.receive_id_type or "chat_id", target.receive_id, msg)

    async def save(
        self,
        title: str,
        source_url: str,
        transcript: TranscriptResult,
        analysis: AnalysisResult,
    ) -> DeliveryResult:
        if not self.is_enabled():
            return DeliveryResult()

        token = await self._tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        doc_id = ""
        doc_url = ""
        record_id = ""

        async with httpx.AsyncClient(timeout=45) as client:
            doc_resp = await client.post(
                "https://open.feishu.cn/open-apis/docx/v1/documents",
                headers=headers,
                json={"title": title[:200]},
            )
            doc_resp.raise_for_status()
            doc_payload = doc_resp.json()
            doc_id = str((doc_payload.get("data") or {}).get("document", {}).get("document_id", ""))
            if doc_id:
                doc_url = f"https://feishu.cn/docx/{doc_id}"
                raw_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/raw_content"
                content = self._build_markdown(source_url, transcript, analysis)
                await client.post(raw_url, headers=headers, json={"content": content})

            if self.bitable_app_token and self.bitable_table_id:
                rec_resp = await client.post(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{self.bitable_table_id}/records",
                    headers=headers,
                    json={
                        "fields": {
                            "Title": title,
                            "SourceURL": source_url,
                            "DocURL": doc_url,
                            "Highlights": "\n".join(analysis.highlights[:20]),
                            "Logic": "\n".join(analysis.logic_outline[:20]),
                        }
                    },
                )
                if rec_resp.is_success:
                    rec_data = rec_resp.json()
                    record_id = str((rec_data.get("data") or {}).get("record", {}).get("record_id", ""))

        return DeliveryResult(feishu_doc_url=doc_url, feishu_doc_id=doc_id, bitable_record_id=record_id)

    async def send_text(self, receive_id_type: str, receive_id: str, text: str) -> None:
        if not self.is_enabled():
            return

        token = await self._tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }

        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type or 'chat_id'}"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

    async def _tenant_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._cache.token and self._cache.expires_at > now:
            return self._cache.token

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            resp.raise_for_status()
            payload = resp.json()

        token = str(payload.get("tenant_access_token", ""))
        expire = int(payload.get("expire", 0))
        self._cache = _TokenCache(
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=max(expire - 60, 60)),
        )
        return token

    @staticmethod
    def _build_markdown(source_url: str, transcript: TranscriptResult, analysis: AnalysisResult) -> str:
        transcript_text = "\n".join(
            f"[{s.start_seconds:.2f}-{s.end_seconds:.2f}] {s.speaker_id}: {s.text}" for s in transcript.segments
        )
        if not transcript_text:
            transcript_text = transcript.full_text

        parts = [
            f"# Source\n{source_url}",
            "# Logic Outline\n" + "\n".join(f"- {x}" for x in analysis.logic_outline),
            "# Highlights\n" + "\n".join(f"- {x}" for x in analysis.highlights),
            "# Work Connections\n" + "\n".join(f"- {x}" for x in analysis.work_connections),
            "# Knowledge Base Connections\n" + "\n".join(f"- {x}" for x in analysis.kb_connections),
            "# Transcript\n" + transcript_text,
        ]
        return "\n\n".join(parts)
