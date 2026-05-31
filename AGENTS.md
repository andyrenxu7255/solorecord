# SoloRecord 智能体指南

## 关键规则

- 不要把真实 ASR、LLM、LDAP、SSO、Hermes、ES 或外部 API 密钥写进源码、文档、APK、Docker 镜像或最终回复。
- 服务端是权威数据源。Android 本地数据只是缓存和离线录音保护。
- ES/OpenSearch 只是可选索引层。业务数据必须先写入数据库。
- 所有会议读写接口都必须做权限校验。
- 转写内容是企业知识整理的原始证据层，必须服务端持久化；非 admin 不允许删除转写段，替换/重处理前必须归档历史。
- Web 动态文本必须转义后渲染。
- Android 录音可靠性优先于端侧音频重处理。
- 不要删除用户改动或生成数据，除非用户明确要求。

## 构建与测试

服务端测试：

```powershell
scripts\run-tests.ps1
```

服务端本地运行：

```powershell
scripts\run-server.ps1
```

Android 调试 APK：

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug
```

APK 输出：

```text
app/build/outputs/apk/debug/app-debug.apk
```

Windows 客户端：

```powershell
cd clients\desktop
npm install
npm run pack
npm run portable:win
```

HTTP smoke：

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

## 架构速览

组件：

- Android App：`app/src/main/java/com/solorecord/`
- 多平台客户端：`clients/`
- FastAPI 服务端：`server/solorecord_server/`
- 静态 Web 端：`server/static/`
- 文档：`docs/`
- 测试：`server/tests/`

核心服务端文件：

- `main.py`：API 路由。
- `db.py`：SQLite schema 和迁移。
- `auth.py`：用户会话、LDAP、SSO、外部 token。
- `processing.py`：ASR、纪要、转发、索引工作流。
- `repository.py`：会议完整文档聚合。
- `search_index.py`：ES/OpenSearch 索引。
- `asr_adapters.py`：本地命令 ASR、OpenAI 兼容/FunASR 远程 STT。
- `llm_adapters.py`：LLM 纪要适配器。
- `publisher.py`：Hermes/Webhook 推送。
- `exports.py`：导出格式。

核心 Android 文件：

- `MainActivity.java`：三页签 UI 和主流程。
- `RollingAudioRecorder.java`：滚动分段录音。
- `RecordingService.java`：前台录音通知。
- `SoloServerClient.java`：服务端 API、移动端同步、服务器音频下载。
- `MeetingStore.java`：本地缓存。
- `SessionStore.java`：登录和服务器地址。

Android 上传可靠性：

- 录音分段先落盘到 App 私有目录。
- 主流程用 multipart 文件流上传 `/api/mobile/meetings/{meetingId}/segments`。
- 每个分段成功后立即将 `uploadStatus` 持久化为 `uploaded`。
- 弱网重试只补传未完成分段；`/finish` 重试应复用已有处理 job。
- 这是分段级断点续传，不是单文件字节 offset 续传。

多源同录可靠性：

- 1-8 个录音源通过同一 `join_code` 归入同一会议。
- `/api/mobile/meetings/discover` 和 `/api/web/meetings/discover` 只返回近期可加入会议元数据，加入前不得返回转写、纪要、音频、待办或成员详情。
- 证据键始终是 `(source_id, source_segment_no)`，不能只按本地分段号判断覆盖、替换或跳转。
- 最终处理会合并关键事实一致的重复多源片段并标记 `multi_source_merged`。
- 设备错峰起录但来源分段相邻、时间差和文本相似度满足保守阈值时，合并片段还会标记 `multi_source_time_aligned`。
- 日期、数量或负责人等关键事实冲突时必须保留多条 `multi_source_conflict` 证据，不得为了去重覆盖冲突。
- `summary_evidence_contradiction` 是知识入库阻塞项，表示纪要/分角色整理与同主题转写原文在完成、发送、确认等状态上相反。外部 Agent 必须以转写原文为准重建摘要，不能把该纪要沉淀为确定知识。

## 数据与权限

重要表：

- `users`
- `sessions`
- `meetings`
- `meeting_members`
- `audio_segments`
- `transcript_segments`
- `speakers`
- `action_items`
- `processing_jobs`
- `apk_releases`（兼容命名，实际保存 Android/Windows/macOS/iOS/HarmonyOS 发布包）
- `app_config`
- `audit_logs`

会议归属：

- `meetings.owner_id` 记录创建者。
- `meeting_members` 记录可读/可写用户。
- `audit_logs.actor_user_id` 记录操作人。

## 常用 API

移动端同步：

```text
GET /api/mobile/sync
```

会议：

```text
POST /api/mobile/meetings
GET  /api/mobile/meetings
GET  /api/mobile/meetings/discover
GET  /api/mobile/meetings/{meetingId}
POST /api/mobile/meetings/{meetingId}/segments
POST /api/mobile/meetings/{meetingId}/segments-json
GET  /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
POST /api/mobile/meetings/{meetingId}/finish
GET  /api/mobile/meetings/{meetingId}/transcript
PUT  /api/mobile/meetings/{meetingId}/actions
POST /api/mobile/meetings/{meetingId}/speakers/rename
```

外部集成：

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
GET /api/external/meetings/{meetingId}/transcript
```

管理：

```text
GET  /api/admin/providers
PUT  /api/admin/providers
GET  /api/admin/jobs
POST /api/admin/jobs/{jobId}/retry
POST /api/admin/releases
GET  /api/web/releases/latest?platform=android|windows|macos|ios|harmony
POST /api/admin/search/reindex
```

认证：

```text
POST /api/auth/ldap-login
POST /api/auth/demo-login
GET  /api/auth/sso/start
GET  /api/auth/sso/callback
```

## 常见任务

服务器运维 Agent 自动部署：

- 先读 `docs/agents/README.md` 的“服务器运维 Agent 自动部署 Runbook”。
- 向操作者收集 `SOLO_BASE_URL`、LDAP、ASR、LLM、Hermes、ES、备份和终端应用分发信息；SSO/OIDC 仅在启用浏览器统一登录时必需。
- 密钥只写入服务器本地 `server/.env` 或密钥管理系统，不写入 Git、文档或最终回复。
- 自动完成部署、配置、APK 发布、健康检查和端到端 smoke 后再交付。
- Windows/macOS/iOS/HarmonyOS 终端应用发布也走 `/api/admin/releases`，必须设置 `platform`，不能把密钥写入任何终端包。

新增服务端字段：

1. 更新 `server/solorecord_server/db.py`。
2. 在 `init_db` 中加兼容迁移。
3. 如果完整会议文档需要该字段，更新 `repository.py`。
4. 如有展示需求，更新 Web/Android。
5. 扩展 `server/tests/test_api.py`。

新增 Provider 配置字段：

1. 更新 `schemas.ProviderConfig`。
2. 更新 `main.get_providers` 和 `main.update_providers`。
3. 更新 `server/static/index.html`。
4. 更新 `server/static/app.js`。
5. 不要把密钥回显给浏览器。

新增 ASR Runtime：

- 优先做成输出标准 JSON 的 sidecar 命令，避免把模型代码耦合进业务 API。
- 如果 ASR 已经提供 OpenAI 兼容 HTTP 服务，使用 `asr_provider=openai-compatible` 或 `funasr`，并只在服务器本地配置 `asr_endpoint`、`asr_api_key`、`asr_model`。
- 远程 STT 返回空文本时应保留可追踪的占位转写，不要让整场会议丢失状态。

新增外部系统：

- 推送走 `publisher.py`。
- 拉取走 `/api/external/*`。
- 搜索走 ES/OpenSearch。
- 不要让外部系统直接读取 SQLite。
- 企业知识平台 Agent 读取转写走 `/api/external/meetings/{meetingId}/transcript?include_history=true`；不要绕过 API 读数据库或文件。

## 文档地图

- 运维：`docs/human-ops/README.md`
- 开发：`docs/human-dev/README.md`
- 用户：`docs/user/README.md`
- 智能体：`docs/agents/README.md`、`llms.txt`
- 参考：`docs/meeting-app-prd-v2.md`、`docs/deployment.md`、`docs/data-storage-and-es.md`、`docs/local-asr-pipeline.md`、`docs/synology-bailian-architecture.md`、`docs/open-source-research.md`、`docs/security-audit.md`、`docs/ux-review-v0.7.md`、`docs/ux-user-story-acceptance.md`、`docs/multi-platform-clients.md`

## English

# SoloRecord Agent Guide

## Critical Rules

- Do not put real ASR, LLM, LDAP, SSO, Hermes, ES, or external API secrets in source, docs, APK, Docker image, or final answers.
- Server is the authoritative data source. Android local data is cache/offline recording protection.
- ES/OpenSearch is an optional index only. Always persist business data to DB first.
- Every meeting read/write endpoint must enforce access control.
- Transcripts are the evidence layer for enterprise knowledge agents. Persist them server-side; non-admin users must not delete transcript segments, and replacements/reprocessing must archive prior rows first.
- Web dynamic text must be escaped before rendering.
- Android recording reliability has priority over on-device audio processing.
- Do not remove user changes or generated data unless explicitly requested.

## Build And Test

Server tests:

```powershell
scripts\run-tests.ps1
```

Server dev run:

```powershell
scripts\run-server.ps1
```

Android debug APK:

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug
```

APK output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

Windows client:

```powershell
cd clients\desktop
npm install
npm run pack
npm run portable:win
```

Docker smoke fallback:

```powershell
docker run --rm --name solorecord-smoke -d -p 8000:8000 `
  -w /app -v "${PWD}:/app" --env-file server/.env `
  -e PYTHONPATH=/app/server `
  python:3.12.13-slim `
  sh -c "pip install --disable-pip-version-check --timeout 120 --retries 5 --no-cache-dir -r /app/server/requirements.txt && uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000"
```

Stop smoke container:

```powershell
docker stop solorecord-smoke
```

HTTP smoke:

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

## Architecture

Components:

- Android app: `app/src/main/java/com/solorecord/`
- Multi-platform clients: `clients/`
- FastAPI server: `server/solorecord_server/`
- Static Web app: `server/static/`
- Docs: `docs/`
- Tests: `server/tests/`

Core server files:

- `main.py`: API routes.
- `db.py`: SQLite schema and migrations.
- `auth.py`: user sessions, LDAP, SSO, external token auth.
- `processing.py`: ASR, summary, forwarding, indexing workflow.
- `repository.py`: full meeting document aggregation.
- `search_index.py`: ES/OpenSearch indexing.
- `asr_adapters.py`: local command ASR and OpenAI-compatible/FunASR remote STT.
- `llm_adapters.py`: LLM summary adapters.
- `publisher.py`: Hermes/Webhook push.
- `exports.py`: export formats.

Android files:

- `MainActivity.java`: hand-built three-tab UI.
- `RollingAudioRecorder.java`: rolling local recording.
- `RecordingService.java`: foreground recording notification.
- `SoloServerClient.java`: server API calls, mobile sync, server audio download.
- `MeetingStore.java`: local cache.
- `SessionStore.java`: login/server settings.

Android upload reliability:

- Recording segments are written to app-private storage first.
- The main flow uploads multipart files to `/api/mobile/meetings/{meetingId}/segments`.
- After each segment succeeds, `uploadStatus` is persisted as `uploaded`.
- Weak-network retry sends only pending segments; `/finish` retry should reuse an existing processing job.
- This is segment-level resume, not byte-offset resume inside one file.

Multi-source recording reliability:

- 1-8 recording sources join the same meeting through one `join_code`.
- `/api/mobile/meetings/discover` and `/api/web/meetings/discover` return recent joinable meeting metadata only; they must not expose transcripts, summaries, audio, action items, or member details before the user joins.
- The evidence key is always `(source_id, source_segment_no)`; never use the local segment number alone for coverage, replacement, or navigation.
- Final processing merges duplicate multi-source rows only when key facts agree and marks them with `multi_source_merged`.
- If devices start at different times but neighboring source-local segment numbers, start-time delta, and text similarity pass conservative checks, merged rows also carry `multi_source_time_aligned`.
- If sources conflict on dates, amounts, or owners, keep separate `multi_source_conflict` evidence rows instead of deduplicating away the disagreement.
- `summary_evidence_contradiction` is a knowledge-ingestion blocker. It means a summary or role-note claim reverses same-topic transcript evidence around completion, sending, confirmation, or similar status. External agents must rebuild the summary from transcript evidence instead of storing that summary as confirmed knowledge.

## Data Model

Important tables:

- `users`
- `sessions`
- `meetings`
- `meeting_members`
- `audio_segments`
- `transcript_segments`
- `speakers`
- `action_items`
- `processing_jobs`
- `apk_releases` (legacy name; stores Android/Windows/macOS/iOS/HarmonyOS release packages)
- `app_config`
- `audit_logs`

Meeting ownership:

- `meetings.owner_id` records creator.
- `meeting_members` records readable/writable users.
- `audit_logs.actor_user_id` records who performed actions.

## API Index

Mobile sync after APK reinstall:

```text
GET /api/mobile/sync
```

Meeting:

```text
POST /api/mobile/meetings
GET  /api/mobile/meetings
GET  /api/mobile/meetings/discover
GET  /api/mobile/meetings/{meetingId}
POST /api/mobile/meetings/{meetingId}/segments
POST /api/mobile/meetings/{meetingId}/segments-json
GET  /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
POST /api/mobile/meetings/{meetingId}/finish
GET  /api/mobile/meetings/{meetingId}/transcript
PUT  /api/mobile/meetings/{meetingId}/actions
POST /api/mobile/meetings/{meetingId}/speakers/rename
```

External integration:

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
GET /api/external/meetings/{meetingId}/transcript
```

Admin:

```text
GET  /api/admin/providers
PUT  /api/admin/providers
GET  /api/admin/jobs
POST /api/admin/jobs/{jobId}/retry
POST /api/admin/releases
GET  /api/web/releases/latest?platform=android|windows|macos|ios|harmony
POST /api/admin/search/reindex
```

Auth:

```text
POST /api/auth/ldap-login
POST /api/auth/demo-login
GET  /api/auth/sso/start
GET  /api/auth/sso/callback
```

## Common Tasks

Server operations agent auto-deployment:

- First read the "Server Operations Agent Auto-Deployment Runbook" in `docs/agents/README.md`.
- Collect `SOLO_BASE_URL`, LDAP, ASR, LLM, Hermes, ES, backup, and client distribution inputs from the operator; SSO/OIDC is required only when browser unified login is enabled.
- Store secrets only in server-local `server/.env` or a secret manager, never in Git, docs, or final responses.
- Complete deployment, configuration, APK publishing, health checks, and end-to-end smoke before handoff.
- Windows/macOS/iOS/HarmonyOS packages also use `/api/admin/releases` with `platform`; never embed secrets in any client package.

### Add A Server Field

1. Update `server/solorecord_server/db.py`.
2. Add backward-compatible migration in `init_db`.
3. Update `repository.py` if the field appears in full meeting documents.
4. Update Web/Android clients if visible.
5. Extend `server/tests/test_api.py`.

### Add A Provider Config Field

1. Update `schemas.ProviderConfig`.
2. Update `main.get_providers` and `main.update_providers` if needed.
3. Update `server/static/index.html`.
4. Update `server/static/app.js`.
5. Do not echo secrets back to browser.

### Add ASR Runtime

Prefer a sidecar command that prints standard JSON. Avoid coupling model code to the business API.
If ASR is already exposed through an OpenAI-compatible HTTP service, use
`asr_provider=openai-compatible` or `funasr`, and store `asr_endpoint`,
`asr_api_key`, and `asr_model` only in server-local configuration.
When remote STT returns empty text, keep a traceable placeholder transcript
instead of losing the meeting processing state.

### Add Export Format

1. Update `exports.py`.
2. Add Web button in `app.js`.
3. Add test assertion.

### Add External System

Use one of:

- `publisher.py` for push.
- `/api/external/*` for pull.
- ES/OpenSearch for full-text search.

Do not let external systems read SQLite directly.
Enterprise knowledge agents should read transcripts through `/api/external/meetings/{meetingId}/transcript?include_history=true`; never bypass the API to read SQLite or files directly.

## Documentation Map

Human operations:

- `docs/human-ops/README.md`

Human development:

- `docs/human-dev/README.md`

End users:

- `docs/user/README.md`

Agent maintenance:

- `docs/agents/README.md`
- `llms.txt`

Reference:

- `docs/meeting-app-prd-v2.md`
- `docs/deployment.md`
- `docs/data-storage-and-es.md`
- `docs/local-asr-pipeline.md`
- `docs/synology-bailian-architecture.md`
- `docs/open-source-research.md`
- `docs/security-audit.md`
- `docs/multi-platform-clients.md`
- `docs/ux-review-v0.7.md`
