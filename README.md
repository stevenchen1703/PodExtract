# PodExtract

一个“贴链接就出笔记”的后端系统：支持 `YouTube/Bilibili/RSS/Apple Podcast`，完成音频提取、语音转写、结构化总结，并写入飞书 Doc + 多维表。

## 一期已实现

- `/v1/jobs`：提交链接任务（支持幂等去重）
- `/v1/jobs/{job_id}`：查询任务状态与结果
- `/v1/feishu/events`：飞书机器人事件回调（贴链接自动触发）
- `/sandbox`：测试页面（输入链接、轮询状态、展示结果）
- Worker 异步处理链路：extract -> transcribe -> analyze -> publish
- SQLite 持久化（重启后可查历史任务）
- Redis 队列（API 与 Worker 解耦）
- MiniMax 主转写 + ElevenLabs 兜底
- 二期接口预留：subscriptions / digests（仅契约，不含调度器）
- 二期数据表预留：subscriptions / episodes / digest_runs

## 快速启动（Docker）

1. 准备环境变量

```bash
cp .env.example .env
```

2. 启动

```bash
docker compose up -d --build
```

3. 打开测试页面

- [http://localhost:8000/sandbox](http://localhost:8000/sandbox)

## 本地启动（不使用 Docker）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
python -m app.worker
```

## API 概览

### 1) 提交任务

```bash
curl -X POST http://localhost:8000/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

### 2) 查询任务

```bash
curl http://localhost:8000/v1/jobs/<job_id>
```

### 3) 二期预留接口（一期返回占位结果）

- `POST /v1/subscriptions`
- `GET /v1/subscriptions`
- `PATCH /v1/subscriptions/{id}`
- `POST /v1/subscriptions/{id}/run`
- `GET /v1/digests/{id}`

## 关键配置

- `STT_PRIMARY_PROVIDER=minimax`
- `STT_FALLBACK_PROVIDER=elevenlabs`
- `MINIMAX_STT_URL`（需替换为你账户可用 ASR endpoint）
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_VERIFICATION_TOKEN`
- `FEISHU_BITABLE_APP_TOKEN` / `FEISHU_BITABLE_TABLE_ID`

## 注意事项

- Apple Podcast 支持“页面链接自动解析公开 RSS”；私有/付费 feed 不支持。
- Spotify/小宇宙直连抓取暂未纳入一期（建议二期处理）。
- MiniMax 返回结构在不同租户可能有差异，已做通用映射，建议用真实样本回归验证。
