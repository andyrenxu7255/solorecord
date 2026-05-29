# SoloRecord 开发者手册

## 适用读者

本手册给继续开发 SoloRecord 的工程师看。你需要了解服务端、Web、Android、数据模型、测试和集成边界。

## 仓库结构

```text
D:\solo\solorecord
├── app/                         Android 原生 Java App
├── server/
│   ├── solorecord_server/        FastAPI 服务端
│   ├── static/                   Web 管理端静态页面
│   ├── tests/                    服务端测试
│   ├── requirements.txt
│   └── .env.example
├── docs/                         文档
├── scripts/                      本地启动/测试脚本
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 技术栈

服务端：

- Python 3.12
- FastAPI
- SQLite 默认持久化
- 本地文件存储
- httpx 调 LLM、Webhook、ES/OpenSearch
- python-docx、reportlab 导出

Web：

- 静态 HTML/CSS/JavaScript
- 无打包步骤
- 通过 FastAPI StaticFiles 提供

Android：

- 原生 Java
- Gradle Android Plugin
- MediaRecorder 录音
- Foreground Service 通知
- SharedPreferences 保存会话信息
- 本地 JSON 保存会议缓存

## 服务端模块

```text
server/solorecord_server/
├── main.py              API 路由和静态资源挂载
├── db.py                SQLite schema 和连接
├── auth.py              LDAP 登录、demo 登录、SSO、会话、外部 token
├── config.py            环境变量配置
├── processing.py        处理任务：ASR、纪要、转发、索引
├── asr_adapters.py      本地 ASR 命令适配器
├── llm_adapters.py      LLM/Ollama/OpenAI 兼容适配器
├── publisher.py         Hermes/Webhook 转发
├── repository.py        聚合会议文档
├── search_index.py      ES/OpenSearch 索引
├── exports.py           Markdown/JSON/SRT/DOCX/PDF 导出
├── schemas.py           Pydantic 请求模型
├── audit.py             审计日志
└── utils.py             通用工具
```

## 数据模型

核心表：

- `users`
- `sessions`
- `sso_states`
- `meetings`
- `meeting_members`
- `audio_segments`
- `processing_jobs`
- `transcript_segments`
- `speakers`
- `action_items`
- `exports`
- `apk_releases`
- `app_config`
- `audit_logs`

权威数据在服务端。Android 本地数据只是缓存和离线录音保护。

会议详情聚合逻辑在：

```text
server/solorecord_server/repository.py
```

如果要给新接口返回完整会议内容，优先复用 `meeting_document(meeting_id)`。

## API 约定

移动端：

```text
GET  /api/mobile/config
GET  /api/mobile/sync
POST /api/mobile/meetings
GET  /api/mobile/meetings
GET  /api/mobile/meetings/{meetingId}
POST /api/mobile/meetings/{meetingId}/segments
POST /api/mobile/meetings/{meetingId}/segments-json
GET  /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
POST /api/mobile/meetings/{meetingId}/finish
POST /api/mobile/meetings/{meetingId}/process
GET  /api/mobile/meetings/{meetingId}/status
GET  /api/mobile/meetings/{meetingId}/transcript
PUT  /api/mobile/meetings/{meetingId}/transcript
POST /api/mobile/meetings/{meetingId}/speakers/rename
GET  /api/mobile/releases/latest
```

Web：

```text
GET  /api/web/me
GET  /api/web/meetings
GET  /api/web/meetings/{meetingId}
PATCH /api/web/meetings/{meetingId}
GET  /api/web/meetings/{meetingId}/transcript
PUT  /api/web/meetings/{meetingId}/transcript
POST /api/web/meetings/{meetingId}/process
POST /api/web/meetings/{meetingId}/speakers/rename
POST /api/web/meetings/{meetingId}/exports
GET  /api/web/search
GET  /api/web/sync
GET  /api/web/releases/latest
```

管理：

```text
GET  /api/admin/providers
PUT  /api/admin/providers
GET  /api/admin/jobs
POST /api/admin/jobs/{jobId}/retry
POST /api/admin/releases
POST /api/admin/search/reindex
```

外部系统：

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

外部系统用 `SOLO_EXTERNAL_API_TOKENS` 中配置的 bearer token。

## 认证与权限

所有业务接口使用：

```text
Authorization: Bearer <access_token>
```

会话 token 原文只返回给客户端一次，服务端保存 hash。

权限判断在：

```text
server/solorecord_server/main.py
```

函数：

```text
_assert_access(meeting_id, user, write=False)
```

规则：

- admin 可访问所有会议。
- meeting member 可读。
- owner/editor 可写。

音频下载接口同样走 `_assert_access`。Android 重装后通过 `GET /api/mobile/sync`
恢复会议列表，再按 `audioSegments[].download_url` 下载服务器音频分段。

## ASR 适配

本地 ASR 命令适配器在：

```text
server/solorecord_server/asr_adapters.py
```

命令模板：

```text
python run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
```

stdout 必须是：

```json
{
  "segments": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "发言人 1",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "文本",
      "confidence": 0.91
    }
  ]
}
```

适配器不使用 shell 执行命令，避免 shell 注入。新增占位符时，要在 `_render_command` 中显式加入。

## LLM 适配

LLM 逻辑在：

```text
server/solorecord_server/llm_adapters.py
```

支持：

- `mock`
- `ollama`
- `openai-compatible`
- `internal`
- `remote-qwen`

LLM 返回必须能解析成 JSON：

```json
{
  "summary": "会议纪要",
  "role_notes": "分角色整理",
  "action_items": [
    {"owner": "张三", "task": "整理报价", "due": "下周一", "status": "open"}
  ]
}
```

如果 LLM 失败，系统回退 mock 纪要，不阻断会议处理闭环。

## ES/OpenSearch

ES 索引逻辑在：

```text
server/solorecord_server/search_index.py
```

触发场景：

- 处理完成后。
- 会议标题/纪要修改后。
- 转写修改后。
- 说话人改名后。
- 管理员手动重建索引。

ES 是可重建索引，不是权威数据源。不要只把数据写 ES。

## Web 开发

文件：

```text
server/static/index.html
server/static/styles.css
server/static/app.js
```

没有构建步骤，刷新浏览器即可看到修改。

注意：

- 用户输入必须通过 `escapeHtml` 或 `escapeAttr` 渲染。
- 密钥字段不回显真实值。
- 管理页新增字段时，需要同时改 `index.html`、`app.js` 和后端 `ProviderConfig`。

## Android 开发

入口：

```text
app/src/main/java/com/solorecord/MainActivity.java
```

关键模块：

```text
net/RollingAudioRecorder.java      滚动分段录音
service/RecordingService.java      前台录音通知
storage/MeetingStore.java          本地会议缓存
storage/SessionStore.java          会话和服务器地址
net/SoloServerClient.java          服务端 API 客户端
model/MeetingRecord.java           会议模型
model/AudioSegment.java            音频分段模型
model/TranscriptSegment.java       转写段模型
```

当前要求：

- 未登录不能录音和查看记录。
- 一次开始/结束是一个会议记录。
- 音频按段保存，默认 5 分钟轮转。
- 关闭 App 停止录音并保存最后一段。
- 角色改名按 speaker id 批量替换。
- 主登录按钮走服务端 LDAP 登录；浏览器 SSO 入口保留，回跳 scheme 为 `solorecord://auth/callback`。
- “从服务器恢复记录”会拉取 `/api/mobile/sync`，并保留服务器音频下载地址。

## 本地运行

服务端：

```powershell
scripts\run-server.ps1
```

测试：

```powershell
scripts\run-tests.ps1
```

Android 打包：

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug
```

APK：

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Docker 调试

常规：

```powershell
docker compose up -d --build solorecord
```

如果本机 Docker BuildKit 卡住：

```powershell
docker run --rm --name solorecord-smoke -d -p 8000:8000 `
  -w /app -v "${PWD}:/app" --env-file server/.env `
  -e PYTHONPATH=/app/server `
  python:3.12.13-slim `
  sh -c "pip install --disable-pip-version-check --timeout 120 --retries 5 --no-cache-dir -r /app/server/requirements.txt && uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000"
```

停止：

```powershell
docker stop solorecord-smoke
```

## 测试覆盖

当前主测试：

```text
server/tests/test_api.py
```

覆盖：

- LDAP 登录、demo 登录
- 创建会议
- 上传音频分段
- finish/process
- 拉取转写
- 角色改名
- 导出 Markdown
- 发布 APK
- 移动端同步
- 外部系统 token 调用
- 受权限保护的服务器音频下载

HTTP 运行态 smoke：

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

依赖漏洞扫描：

```powershell
.\.venv\Scripts\python.exe -m pip_audit -r server\requirements.txt --timeout 60
```

新增接口或关键状态时，请扩展这个测试。

## 开发约束

- 不要把真实 ASR/LLM/SSO/Hermes 密钥写进 APK。
- 不要把真实密钥写进文档或提交。
- 服务端接口必须做权限检查。
- Web 渲染动态文本必须转义。
- ES 只是索引，业务数据必须先入库。
- Android 录音可靠性优先于端侧重处理。

## 常见改动路径

### 新增会议字段

1. 改 `db.py` schema。
2. 在 `init_db` 添加兼容迁移。
3. 改 `repository.py` 聚合输出。
4. 改 Web/Android 展示。
5. 改测试。

### 新增导出格式

1. 改 `exports.py`。
2. 改 Web 按钮。
3. 增加测试断言。

### 新增外部系统

优先通过：

- `publisher.py` 推送。
- `/api/external/*` 拉取。
- ES/OpenSearch 检索。

不要让外部系统直接读 SQLite 文件。

### 新增本地 ASR Runtime

优先封装成命令行程序，保持 SoloRecord 只调用标准 JSON。这样后续替换模型不会影响业务 API。

## English

### Audience

This manual is for engineers extending SoloRecord. It covers the server, Web UI, Android APK, data model, tests, and integration boundaries.

### Repository Structure

```text
D:\solo\solorecord
├── app/                         Native Android Java app
├── server/
│   ├── solorecord_server/        FastAPI server
│   ├── static/                   Static Web admin UI
│   ├── tests/                    Server tests
│   ├── requirements.txt
│   └── .env.example
├── docs/                         Documentation
├── scripts/                      Local run/test scripts
├── Dockerfile
├── docker-compose.yml
└── README.md
```

### Technology Stack

Server:

- Python 3.12
- FastAPI
- SQLite by default
- Local file storage
- httpx for LLM, webhook, ES/OpenSearch
- python-docx and reportlab for exports

Web:

- Static HTML/CSS/JavaScript
- No build step
- Served by FastAPI static routes

Android:

- Native Java
- Gradle Android Plugin
- MediaRecorder
- Foreground Service notification
- SharedPreferences for session data
- Local JSON meeting cache

### Server Modules

```text
server/solorecord_server/
├── main.py              API routes and static mount
├── db.py                SQLite schema and migrations
├── auth.py              LDAP login, demo login, SSO, sessions, external tokens
├── config.py            environment settings
├── processing.py        ASR, summary, forwarding, indexing workflow
├── asr_adapters.py      local ASR command adapter
├── llm_adapters.py      LLM/Ollama/OpenAI-compatible adapters
├── publisher.py         Hermes/Webhook forwarding
├── repository.py        full meeting document aggregation
├── search_index.py      ES/OpenSearch indexing
├── exports.py           Markdown/JSON/SRT/DOCX/PDF exports
├── schemas.py           Pydantic request models
├── audit.py             audit logging
└── utils.py             shared utilities
```

### Data Model

Core tables:

- `users`
- `sessions`
- `sso_states`
- `meetings`
- `meeting_members`
- `audio_segments`
- `processing_jobs`
- `transcript_segments`
- `speakers`
- `action_items`
- `exports`
- `apk_releases`
- `app_config`
- `audit_logs`

The server is authoritative. Android local data is cache and offline recording protection. Use `meeting_document(meeting_id)` from `repository.py` when returning a complete meeting document.

### API Contract

Mobile:

```text
GET  /api/mobile/config
GET  /api/mobile/sync
POST /api/mobile/meetings
GET  /api/mobile/meetings
GET  /api/mobile/meetings/{meetingId}
POST /api/mobile/meetings/{meetingId}/segments
POST /api/mobile/meetings/{meetingId}/segments-json
GET  /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
POST /api/mobile/meetings/{meetingId}/finish
POST /api/mobile/meetings/{meetingId}/process
GET  /api/mobile/meetings/{meetingId}/status
GET  /api/mobile/meetings/{meetingId}/transcript
PUT  /api/mobile/meetings/{meetingId}/transcript
POST /api/mobile/meetings/{meetingId}/speakers/rename
GET  /api/mobile/releases/latest
```

Web:

```text
GET  /api/web/me
GET  /api/web/meetings
GET  /api/web/meetings/{meetingId}
PATCH /api/web/meetings/{meetingId}
GET  /api/web/meetings/{meetingId}/transcript
PUT  /api/web/meetings/{meetingId}/transcript
POST /api/web/meetings/{meetingId}/process
POST /api/web/meetings/{meetingId}/speakers/rename
POST /api/web/meetings/{meetingId}/exports
GET  /api/web/search
GET  /api/web/sync
GET  /api/web/releases/latest
```

Admin:

```text
GET  /api/admin/providers
PUT  /api/admin/providers
GET  /api/admin/jobs
POST /api/admin/jobs/{jobId}/retry
POST /api/admin/releases
POST /api/admin/search/reindex
```

External systems:

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

External systems authenticate with bearer tokens from `SOLO_EXTERNAL_API_TOKENS`.

### Authentication And Authorization

Business APIs use:

```text
Authorization: Bearer <access_token>
```

The raw session token is returned to the client once. The server stores only its hash.

Meeting authorization is enforced in `main.py` by `_assert_access(meeting_id, user, write=False)`:

- admin can access all meetings.
- meeting members can read.
- owner/editor can write.

The audio download endpoint uses the same authorization path. After APK reinstall, Android calls `GET /api/mobile/sync`, then downloads server audio through `audioSegments[].download_url`.

### ASR Adapter

The local ASR command adapter is in:

```text
server/solorecord_server/asr_adapters.py
```

Command template:

```text
python run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
```

stdout must be:

```json
{
  "segments": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "Speaker 1",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "Transcript text",
      "confidence": 0.91
    }
  ]
}
```

The adapter does not execute through a shell. Add new placeholders explicitly in `_render_command`.

### LLM Adapter

LLM logic is in:

```text
server/solorecord_server/llm_adapters.py
```

Supported providers:

- `mock`
- `ollama`
- `openai-compatible`
- `internal`
- `remote-qwen`

The LLM response should parse as JSON:

```json
{
  "summary": "Meeting summary",
  "role_notes": "Notes by role",
  "action_items": [
    {"owner": "Alice", "task": "Prepare the quote", "due": "Next Monday", "status": "open"}
  ]
}
```

If the LLM fails, the system falls back to a mock summary so the processing loop remains usable.

### ES/OpenSearch

Indexing logic lives in:

```text
server/solorecord_server/search_index.py
```

Indexing runs after processing, meeting edits, transcript edits, speaker rename, and admin reindex. ES/OpenSearch is rebuildable search infrastructure, not the authoritative business store.

### Web Development

Files:

```text
server/static/index.html
server/static/styles.css
server/static/app.js
```

There is no build step. Refresh the browser after edits.

Rules:

- Render user input through `escapeHtml` or `escapeAttr`.
- Never echo real saved secrets back to the browser.
- Provider config changes usually require `index.html`, `app.js`, and `ProviderConfig`.

### Android Development

Entry point:

```text
app/src/main/java/com/solorecord/MainActivity.java
```

Key modules:

```text
net/RollingAudioRecorder.java      rolling segmented recording
service/RecordingService.java      foreground recording notification
storage/MeetingStore.java          local meeting cache
storage/SessionStore.java          session and server endpoint
net/SoloServerClient.java          server API client
model/MeetingRecord.java           meeting model
model/AudioSegment.java            audio segment model
model/TranscriptSegment.java       transcript segment model
```

Current requirements:

- Users must sign in before recording or viewing records.
- One start/end cycle is one meeting.
- Audio rotates every 5 minutes by default.
- Closing the app stops recording and saves the last segment as far as possible.
- Speaker rename updates all transcript rows with the same speaker id.
- Main login uses server-side LDAP login. Browser SSO remains available with `solorecord://auth/callback`.
- Server recovery calls `/api/mobile/sync` and keeps server audio download URLs.

### Local Commands

Server:

```powershell
scripts\run-server.ps1
```

Tests:

```powershell
scripts\run-tests.ps1
```

Android build:

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug
```

APK output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

### Test Coverage

`server/tests/test_api.py` covers login, meeting create, audio upload, finish/process, transcript fetch, speaker rename, Markdown export, APK release publishing, mobile sync, external API token access, and protected server audio download.

Runtime smoke:

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

Dependency audit:

```powershell
.\.venv\Scripts\python.exe -m pip_audit -r server\requirements.txt --timeout 60
```

Extend tests whenever a new endpoint, state transition, or shared data contract is added.

### Development Constraints

- Do not put real ASR/LLM/SSO/Hermes secrets into the APK.
- Do not commit real secrets or write them into docs.
- Every server endpoint must enforce access control.
- Web dynamic text must be escaped.
- ES is only an index; persist business data to the database first.
- Android recording reliability is more important than heavy on-device audio processing.

### Common Change Paths

New meeting field:

1. Update `db.py` schema.
2. Add a backward-compatible migration in `init_db`.
3. Update `repository.py`.
4. Update Web/Android display if visible.
5. Update tests.

New export format:

1. Update `exports.py`.
2. Add a Web button.
3. Add a test assertion.

New external system:

- Prefer `publisher.py` for push.
- Prefer `/api/external/*` for pull.
- Use ES/OpenSearch for search.

Do not let external systems read SQLite directly.

New local ASR runtime:

- Wrap it as a command-line program.
- Keep SoloRecord calling standard JSON.
- This keeps future model changes outside the business API.
