from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import asyncio

from app.config import Settings, get_settings
from app.models import (
    DigestRun,
    DigestRunStatus,
    HealthResponse,
    SubmitLinkRequest,
    SubmitLinkResponse,
    Subscription,
    SubscriptionCreateRequest,
    SubscriptionPatchRequest,
)
from app.services.database import SQLiteStore
from app.services.feishu import FeishuClient
from app.services.jobs import JobService
from app.services.queue import JobQueue


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings: Settings = get_settings()
    app = FastAPI(title=settings.app_name)

    store = SQLiteStore(settings.sqlite_path)
    queue = JobQueue(settings.redis_url, settings.redis_queue_key)
    jobs = JobService(settings=settings, store=store, queue=queue)
    feishu = FeishuClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        verification_token=settings.feishu_verification_token,
        bitable_app_token=settings.feishu_bitable_app_token,
        bitable_table_id=settings.feishu_bitable_table_id,
    )

    app.state.settings = settings
    app.state.store = store
    app.state.queue = queue
    app.state.jobs = jobs
    app.state.feishu = feishu

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await app.state.queue.close()

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/v1/health", response_model=HealthResponse)
    async def v1_health() -> HealthResponse:
        return HealthResponse()

    @app.post("/v1/jobs", response_model=SubmitLinkResponse)
    async def submit_link(req: SubmitLinkRequest) -> SubmitLinkResponse:
        try:
            job, dedup = await app.state.jobs.create_job(req=req)
            return SubmitLinkResponse(job_id=job.job_id, status=job.status, deduplicated=dedup)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/jobs")
    async def list_jobs(limit: int = 20):
        jobs = await app.state.store.list_jobs(limit=limit)
        return jobs

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str):
        job = await app.state.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/v1/jobs/{job_id}/logs")
    async def stream_job_logs(job_id: str):
        """SSE endpoint for real-time job logs."""
        async def event_generator():
            channel = f"podextract:logs:{job_id}"
            pubsub = app.state.queue.redis.pubsub()
            await pubsub.subscribe(channel)
            try:
                yield "data: connected\n\n"
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                    if message and message["type"] == "message":
                        yield f"data: {message['data']}\n\n"
                    job = await app.state.store.get_job(job_id)
                    if job and job.status in ("completed", "failed"):
                        yield f"data: [job_{job.status}]\n\n"
                        break
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/v1/feishu/events")
    async def feishu_events(req: Request):
        payload = await req.json()
        if not app.state.feishu.verify_event(payload):
            raise HTTPException(status_code=401, detail="invalid feishu token")
        parsed = app.state.feishu.parse_event(payload)
        event_type = parsed.get("event_type")
        if event_type == "url_verification":
            return JSONResponse({"challenge": parsed.get("challenge", "")})
        if event_type != "im.message.receive_v1":
            return JSONResponse({"ok": True, "ignored": event_type})
        url = str(parsed.get("url") or "")
        if not url:
            return JSONResponse({"ok": True, "ignored": "no_link"})
        notify = parsed.get("notify_target")
        req_model = SubmitLinkRequest(url=url, from_channel="feishu")
        try:
            job, dedup = await app.state.jobs.create_job(req=req_model, notify_target=notify)
        except Exception as exc:
            if notify:
                try:
                    await app.state.feishu.send_text(notify.receive_id_type, notify.receive_id, f"任务创建失败: {exc}")
                except Exception:
                    logger.exception("failed to send feishu error message")
            return JSONResponse({"ok": False, "error": str(exc)})
        if notify:
            if dedup:
                msg = f"发现重复任务，复用 Job: {job.job_id}"
                await app.state.feishu.send_text(notify.receive_id_type, notify.receive_id, msg)
            else:
                await app.state.feishu.send_ack(notify, job.job_id)
        return JSONResponse({"ok": True, "job_id": job.job_id, "deduplicated": dedup})

    @app.get("/sandbox", response_class=HTMLResponse)
    async def sandbox() -> HTMLResponse:
        html = '''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>PodExtract</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }
    .container { max-width: 1100px; margin: 0 auto; }
    h1 { margin: 0 0 20px; color: #333; }
    .input-wrap { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .input-row { display: flex; gap: 10px; }
    .input-row input { flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
    .input-row button { padding: 10px 20px; background: #3182ce; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
    .input-row button:hover { background: #2c5282; }
    .input-row button:disabled { background: #a0aec0; }
    #status { margin-top: 10px; font-size: 14px; }
    .main { display: flex; gap: 20px; }
    .left { width: 300px; }
    .right { flex: 1; }
    .card { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }
    .card-header { padding: 12px 16px; border-bottom: 1px solid #eee; font-weight: bold; font-size: 14px; }
    .card-body { padding: 12px 16px; max-height: 400px; overflow-y: auto; }
    .job-list { list-style: none; padding: 0; margin: 0; }
    .job-item { padding: 10px; border-bottom: 1px solid #eee; cursor: pointer; }
    .job-item:hover { background: #f7fafc; }
    .job-item.active { background: #ebf8ff; border-left: 3px solid #3182ce; }
    .job-title { font-weight: 500; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .job-meta { font-size: 12px; color: #718096; margin-top: 4px; }
    .status-badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; text-transform: uppercase; }
    .status-queued { background: #edf2f7; color: #4a5568; }
    .status-running { background: #fef3c7; color: #92400e; }
    .status-completed { background: #c6f6d5; color: #22543d; }
    .status-failed { background: #fed7d7; color: #822727; }
    .tabs { display: flex; border-bottom: 1px solid #eee; }
    .tab { padding: 10px 16px; cursor: pointer; font-size: 13px; border-bottom: 2px solid transparent; }
    .tab:hover { background: #f7fafc; }
    .tab.active { border-bottom-color: #3182ce; color: #3182ce; }
    .tab-content { display: none; padding: 16px; }
    .tab-content.active { display: block; }
    .segment { background: #f7fafc; padding: 10px; border-radius: 4px; margin-bottom: 8px; border-left: 3px solid #3182ce; }
    .segment-speaker { font-weight: 500; color: #3182ce; font-size: 12px; }
    .segment-text { margin-top: 4px; line-height: 1.6; }
    .segment-time { font-size: 11px; color: #718096; margin-top: 4px; }
    .outline-item, .highlight-item { background: #f7fafc; padding: 10px; border-radius: 4px; margin-bottom: 8px; border-left: 3px solid #3182ce; }
    .highlight-item { background: #fffbeb; border-left-color: #dd6b20; }
    .log-box { background: #1a202c; color: #e2e8f0; padding: 12px; font-family: monospace; font-size: 12px; max-height: 150px; overflow-y: auto; white-space: pre-wrap; }
    .empty { text-align: center; color: #a0aec0; padding: 40px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>PodExtract</h1>
    <div class="input-wrap">
      <div class="input-row">
        <input id="urlInput" placeholder="输入播客链接 (YouTube/Bilibili/RSS)">
        <button id="submitBtn" onclick="submitJob()">开始提取</button>
      </div>
      <div id="status"></div>
    </div>
    <div class="main">
      <div class="left">
        <div class="card">
          <div class="card-header">任务列表</div>
          <div class="card-body">
            <div id="debugStatus" style="font-size:12px; color:#666; padding:5px;">初始化中...</div>
            <div id="jobList"><div class="empty">加载中...</div></div>
          </div>
        </div>
      </div>
      <div class="right">
        <div class="card">
          <div class="card-header">处理日志</div>
          <div class="card-body"><div id="logBox" class="log-box">选择任务查看日志...</div></div>
        </div>
        <div class="card">
          <div class="card-header" id="resultTitle">选择任务查看结果</div>
          <div class="tabs">
            <div class="tab active" onclick="switchTab('transcript')">原文</div>
            <div class="tab" onclick="switchTab('outline')">大纲</div>
            <div class="tab" onclick="switchTab('highlights')">亮点</div>
          </div>
          <div id="tab-transcript" class="tab-content active">
            <div id="transcriptBox"><div class="empty">请选择任务</div></div>
          </div>
          <div id="tab-outline" class="tab-content">
            <div id="outlineBox"><div class="empty">请选择任务</div></div>
          </div>
          <div id="tab-highlights" class="tab-content">
            <div id="highlightsBox"><div class="empty">请选择任务</div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <script>
console.log('PodExtract UI script loaded');
var currentJobId = null;
var pollTimer = null;
var logSource = null;
var jobData = {};

function init() {
  try {
    document.getElementById('debugStatus').textContent = '正在加载任务列表...';
    loadJobs();
  } catch (e) {
    document.getElementById('debugStatus').textContent = '初始化错误: ' + e.message;
  }
}

function loadJobs() {
  document.getElementById('debugStatus').textContent = '正在请求 API...';
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/v1/jobs', true);
  xhr.onload = function() {
    if (xhr.status === 200) {
      var jobs = JSON.parse(xhr.responseText);
      document.getElementById('debugStatus').textContent = 'API 返回 ' + jobs.length + ' 个任务';
      renderJobs(jobs);
    } else {
      document.getElementById('debugStatus').textContent = '加载失败: ' + xhr.status;
      var el = document.getElementById('jobList');
      el.innerHTML = '<div class="empty">加载失败: ' + xhr.status + '</div>';
    }
  };
  xhr.onerror = function() {
    document.getElementById('debugStatus').textContent = '网络错误';
    var el = document.getElementById('jobList');
    el.innerHTML = '<div class="empty">网络错误</div>';
  };
  xhr.send();
}

function renderJobs(jobs) {
  var el = document.getElementById('jobList');
  if (!el) {
    document.getElementById('debugStatus').textContent = '错误: 找不到 jobList 元素';
    return;
  }
  if (!jobs || jobs.length === 0) {
    el.innerHTML = '<div class="empty">暂无任务</div>';
    document.getElementById('debugStatus').textContent = '没有任务';
    return;
  }
  document.getElementById('debugStatus').textContent = '正在渲染 ' + jobs.length + ' 个任务';
  var html = '';
  for (var i = 0; i < jobs.length; i++) {
    var job = jobs[i];
    var active = job.job_id === currentJobId ? ' active' : '';
    var title = job.source && job.source.title ? job.source.title : (job.input_url || 'Unknown');
    var stage = getStageLabel(job.stage);
    html += '<div class="job-item' + active + '" data-job-id="' + job.job_id + '">';
    html += '<span class="status-badge status-' + job.status + '">' + job.status + '</span>';
    html += '<div class="job-title">' + esc(title) + '</div>';
    html += '<div class="job-meta">' + stage + ' · ' + fmtTime(job.created_at) + '</div></div>';
  }
  el.innerHTML = html;
  // Add click handlers
  var items = el.querySelectorAll('.job-item');
  for (var i = 0; i < items.length; i++) {
    items[i].addEventListener('click', function() {
      selectJob(this.getAttribute('data-job-id'));
    });
  }
}

function selectJob(jobId) {
  currentJobId = jobId;
  loadJobs();
  fetchJob();
  connectLog(jobId);
}

function fetchJob() {
  if (!currentJobId) return;
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/v1/jobs/' + currentJobId, true);
  xhr.onload = function() {
    if (xhr.status === 200) {
      jobData = JSON.parse(xhr.responseText);
      showJob(jobData);
      if (jobData.status === 'completed' || jobData.status === 'failed') {
        clearInterval(pollTimer);
        pollTimer = null;
        if (logSource) { logSource.close(); logSource = null; }
      }
    }
  };
  xhr.send();
  if (!pollTimer) {
    pollTimer = setInterval(fetchJob, 3000);
  }
}

function showJob(job) {
  document.getElementById('resultTitle').textContent = job.source && job.source.title ? job.source.title : '处理结果';
  var tbox = document.getElementById('transcriptBox');
  if (job.transcript) {
    if (job.transcript.segments && job.transcript.segments.length > 0) {
      var html = '';
      for (var i = 0; i < job.transcript.segments.length; i++) {
        var seg = job.transcript.segments[i];
        html += '<div class="segment"><div class="segment-speaker">' + esc(seg.speaker_id || 'Speaker') + '</div>';
        html += '<div class="segment-text">' + esc(seg.text || '') + '</div>';
        html += '<div class="segment-time">' + fmtDur(seg.start_seconds) + ' - ' + fmtDur(seg.end_seconds) + '</div></div>';
      }
      tbox.innerHTML = html;
    } else if (job.transcript.full_text) {
      tbox.innerHTML = '<div class="segment"><div class="segment-text">' + esc(job.transcript.full_text) + '</div></div>';
    }
  } else {
    tbox.innerHTML = job.status === 'running' ? '<div class="empty">转写中...</div>' : '<div class="empty">无原文</div>';
  }
  var obox = document.getElementById('outlineBox');
  if (job.analysis && job.analysis.logic_outline && job.analysis.logic_outline.length > 0) {
    var html = '';
    for (var i = 0; i < job.analysis.logic_outline.length; i++) {
      // Convert newlines to <br> for proper display
      var content = String(job.analysis.logic_outline[i]).split('\\n').join('<br>');
      html += '<div class="outline-item">' + content + '</div>';
    }
    obox.innerHTML = html;
  } else {
    obox.innerHTML = '<div class="empty">无大纲</div>';
  }
  var hbox = document.getElementById('highlightsBox');
  if (job.analysis && job.analysis.highlights && job.analysis.highlights.length > 0) {
    var html = '';
    for (var i = 0; i < job.analysis.highlights.length; i++) {
      html += '<div class="highlight-item">' + esc(job.analysis.highlights[i]) + '</div>';
    }
    hbox.innerHTML = html;
  } else {
    hbox.innerHTML = '<div class="empty">无亮点</div>';
  }
}

function connectLog(jobId) {
  if (logSource) { logSource.close(); }
  var box = document.getElementById('logBox');
  box.textContent = '连接日志流...';
  var closed = false;
  logSource = new EventSource('/v1/jobs/' + jobId + '/logs');
  logSource.onmessage = function(e) {
    var msg = e.data;
    if (msg === 'connected') return;
    if (msg.indexOf('[job_') === 0) {
      logSource.close();
      closed = true;
      return;
    }
    box.textContent += '\\n' + msg;
    box.scrollTop = box.scrollHeight;
  };
  logSource.onerror = function() {
    if (!closed) {
      closed = true;
      logSource.close();
      box.textContent += '\\n日志连接断开';
    }
  };
}

function submitJob() {
  var url = document.getElementById('urlInput').value.trim();
  var btn = document.getElementById('submitBtn');
  var status = document.getElementById('status');
  if (!url) { alert('请输入播客链接'); return; }
  btn.disabled = true;
  btn.textContent = '提交中...';
  status.textContent = '正在提交...';
  status.style.color = '#92400e';
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/v1/jobs', true);
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.onload = function() {
    btn.disabled = false;
    btn.textContent = '开始提取';
    if (xhr.status === 200) {
      var data = JSON.parse(xhr.responseText);
      if (data.job_id) {
        currentJobId = data.job_id;
        status.textContent = '任务已提交! 等待处理...';
        status.style.color = '#22543d';
        loadJobs();
        fetchJob();
        connectLog(currentJobId);
      } else {
        status.textContent = '提交失败: ' + (data.detail || '');
        status.style.color = '#822727';
      }
    } else {
      status.textContent = '提交失败: ' + xhr.status;
      status.style.color = '#822727';
    }
  };
  xhr.onerror = function() {
    btn.disabled = false;
    btn.textContent = '开始提取';
    status.textContent = '提交失败';
    status.style.color = '#822727';
  };
  xhr.send(JSON.stringify({url: url}));
}

function switchTab(name) {
  var tabs = document.querySelectorAll('.tab');
  for (var i = 0; i < tabs.length; i++) { tabs[i].classList.remove('active'); }
  event.target.classList.add('active');
  var contents = document.querySelectorAll('.tab-content');
  for (var i = 0; i < contents.length; i++) { contents[i].classList.remove('active'); }
  document.getElementById('tab-' + name).classList.add('active');
}

function getStageLabel(stage) {
  var map = {queued: '等待中', extract: '下载', transcribe: '转写', analyze: '分析', publish: '发布', done: '完成'};
  return map[stage] || stage;
}

function fmtTime(iso) {
  if (!iso) return '';
  var d = new Date(iso);
  return d.toLocaleString('zh-CN', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
}

function fmtDur(s) {
  if (!s) return '';
  var h = Math.floor(s / 3600);
  var m = Math.floor((s % 3600) / 60);
  var sec = Math.floor(s % 60);
  if (h > 0) return h + ':' + m.toString().padStart(2,'0') + ':' + sec.toString().padStart(2,'0');
  return m + ':' + sec.toString().padStart(2,'0');
}

function esc(text) {
  if (!text) return '';
  var s = String(text);
  s = s.split('&').join('&amp;');
  s = s.split('<').join('&lt;');
  s = s.split('>').join('&gt;');
  s = s.split('"').join('&quot;');
  return s;
}

init();
  </script>
</body>
</html>'''
        return HTMLResponse(html)

    @app.post("/v1/subscriptions")
    async def create_subscription(req: SubscriptionCreateRequest):
        item = Subscription(
            source_url=req.source_url,
            source_type=req.source_type,
            author_name=req.author_name,
            frequency=req.frequency,
        )
        await app.state.store.create_subscription(item)
        return item

    @app.get("/v1/subscriptions")
    async def list_subscriptions():
        return await app.state.store.list_subscriptions()

    @app.patch("/v1/subscriptions/{subscription_id}")
    async def patch_subscription(subscription_id: str, req: SubscriptionPatchRequest):
        item = await app.state.store.get_subscription(subscription_id)
        if not item:
            raise HTTPException(status_code=404, detail="subscription not found")

        if req.status is not None:
            item.status = req.status

        await app.state.store.save_subscription(item)
        return item

    @app.get("/v1/subscriptions/{subscription_id}")
    async def get_subscription(subscription_id: str):
        item = await app.state.store.get_subscription(subscription_id)
        if not item:
            raise HTTPException(status_code=404, detail="subscription not found")
        return item

    @app.post("/v1/subscriptions/{subscription_id}/trigger")
    async def trigger_subscription(subscription_id: str):
        from datetime import datetime, timezone
        from app.models import DigestRun, DigestRunStatus

        sub = await app.state.store.get_subscription(subscription_id)
        if not sub:
            raise HTTPException(status_code=404, detail="subscription not found")

        digest = DigestRun(
            digest_id=f"digest-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            subscription_id=subscription_id,
            status=DigestRunStatus.pending,
            summary="",
        )
        await app.state.store.create_digest_run(digest)
        return {"ok": True, "digest_id": digest.digest_id}

    @app.get("/v1/digests/{digest_id}")
    async def get_digest(digest_id: str):
        digest = await app.state.store.get_digest_run(digest_id)
        if not digest:
            raise HTTPException(status_code=404, detail="digest not found")
        return digest

    return app


app = create_app()
