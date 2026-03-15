# PodExtract 架构说明（一期 + 二期预留）

## 一期运行形态

- `api`：FastAPI，对外提供 `/v1` API、飞书回调、测试页面
- `worker`：后台消费者，从 Redis 队列拉取任务执行处理链路
- `redis`：任务队列
- `sqlite`：任务与订阅元数据持久化

## 一期处理链路

1. 用户提交链接（网页或飞书机器人）
2. 统一做来源识别和 canonical URL 归一化
3. 幂等去重（同 canonical URL 在窗口期内复用任务）
4. 入队后由 worker 执行：
   - `extract`：YouTube/Bilibili 用 yt-dlp；RSS/Apple 用 feed 解析 + 音频下载
   - `transcribe`：MiniMax 主通道，失败后 ElevenLabs 兜底
   - `analyze`：输出四类结构化结果
   - `publish`：写飞书 Doc + 多维表，并回发机器人结果
5. API 查询可返回完整作业状态与产物

## 数据结构（核心）

- Job
  - `status`: queued/running/failed/completed
  - `stage`: queued/extract/transcribe/analyze/publish/done
  - `source`: platform/canonical_url/title/author/published_at
  - `transcript`: language/duration_seconds/diarization/full_text/segments[]
  - `analysis`: logic_outline/highlights/work_connections/kb_connections
  - `delivery`: feishu_doc_url/bitable_record_id
  - `error`: code/message

## 二期预留（不实现调度）

- 订阅接口：
  - `POST /v1/subscriptions`
  - `GET /v1/subscriptions`
  - `PATCH /v1/subscriptions/{id}`
  - `POST /v1/subscriptions/{id}/run`
  - `GET /v1/digests/{id}`
- 预留表：`subscriptions`, `episodes`, `digest_runs`
- 目标：后续接入定时抓新 + 汇总推送
