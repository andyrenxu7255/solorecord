# SoloRecord 数据存储与 ES/OpenSearch

## 权威存储

登录后，服务端是会议记录的权威数据源。Android 本地存储只负责当前设备录音保护、离线播放和缓存。

服务端保存：

- `users`：群晖/demo 登录身份、显示名、邮箱、角色。
- `sessions`：短期服务端会话 token 的 hash。
- `meetings`：标题、owner user id、状态、时间、时长、纪要、分角色记录、转写版本。
- `meeting_members`：哪些登录用户可读/可写会议。
- `audio_segments`：上传音频分段元数据和存储路径。
- `transcript_segments`：带时间戳的转写行、稳定 speaker id、显示名、置信度、标记。
- `transcript_segment_history`：转写被重新处理或人工替换前的历史归档，用于审计和企业知识平台追溯。
- `speakers`：每场会议修正后的说话人名称映射。
- `action_items`：从会议中提取的负责人、任务、截止时间、状态。
- `processing_jobs`：ASR/LLM/索引/转发进度和失败信息。
- `audit_logs`：创建、更新、上传、处理、改名、导出、管理操作。

每场会议都有 `owner_id` 和 `meeting_members`，因此重装 APK 不会丢失服务器记录。重新登录后，App 可调用：

```text
GET /api/mobile/sync
GET /api/mobile/meetings
GET /api/mobile/meetings/{meetingId}
GET /api/mobile/meetings/{meetingId}/transcript
GET /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
```

来重建本地记录。

音频下载接口使用同一套会议读取权限。重装后的 APK 可按需下载服务器音频分段播放，而不是暴露原始存储路径。

## 转写持久化与删除规则

转写内容是会议后续知识整理的原始证据层，必须先持久化到服务端数据库。Web 或 App 上看到的是当前可见版本，但被重处理或人工替换前，旧转写行会归档到 `transcript_segment_history`。

规则：

- 非 admin 用户可以修正转写文本和说话人名称，但不能删除转写段。
- admin 可以通过完整转写更新删除段落；删除前旧段落仍会归档。
- 分段重传/重转写只替换对应 `source_segment_no` 的当前行，并把旧行归档。
- 外部系统不得直接读取 SQLite 或音频文件路径，必须走服务端 API。

## 登录用户记录

每个受保护 API 都会从 bearer token 解析当前用户。服务端在以下位置记录用户身份：

- `meetings.owner_id`
- `meeting_members.user_id`
- `audit_logs.actor_user_id`

会议详情响应包含 owner 和 members，便于其他系统知道记录归属。

## 外部业务 API

Hermes、CRM 或其他内部系统通过服务端到服务端 token 读取会议数据：

```text
SOLO_EXTERNAL_API_TOKENS=hermes:replace-with-long-random-token,crm:another-token
```

调用：

```http
GET /api/external/meetings
Authorization: Bearer replace-with-long-random-token
```

或：

```http
GET /api/external/meetings/{meetingId}
Authorization: Bearer replace-with-long-random-token
```

响应包含会议元数据、owner、members、转写段、说话人映射、待办和合并后的 `searchText`。

企业知识平台或知识整理 Agent 推荐调用专用转写接口：

```http
GET /api/external/meetings/{meetingId}/transcript?include_history=true
Authorization: Bearer replace-with-long-random-token
```

响应包含当前转写版本、结构化段落、纯文本 `plain_text`、说话人映射、音频分段证据、待办、`searchText`，以及可选历史归档 `history`。知识平台可以用当前段落生成知识条目，用历史归档做审计和冲突追溯。

## ES/OpenSearch

ES/OpenSearch 是可选检索层，不是唯一业务数据副本。

配置：

```text
SOLO_ES_ENABLED=true
SOLO_ES_URL=http://127.0.0.1:9200
SOLO_ES_INDEX=solorecord_meetings
SOLO_ES_API_KEY=
SOLO_ES_USERNAME=
SOLO_ES_PASSWORD=
```

索引触发：

- ASR/纪要处理成功。
- 手动编辑转写。
- 改说话人名称。
- 修改会议标题/纪要。

管理员可重建索引：

```text
POST /api/admin/search/reindex
```

推荐首台服务器先用 SQLite + 持久化 `var/` 验证和演示；生产再迁移 PostgreSQL、NAS/S3-compatible 存储，并按检索和下游分析需要启用 ES/OpenSearch。

## English

# SoloRecord Data Storage And ES/OpenSearch

## Authoritative Storage

The server is the authoritative source of record after login. Android local
storage is only a cache for current-device recording and offline playback.

Server-side stored data:

- `users`: Synology/demo login identity, display name, email, role.
- `sessions`: hashed short-lived server session tokens.
- `meetings`: title, owner user id, status, timestamps, duration, summary,
  role notes, transcript version.
- `meeting_members`: which logged-in users can read/write a meeting.
- `audio_segments`: uploaded audio segment metadata and storage path.
- `transcript_segments`: timestamped transcript rows, stable speaker id,
  display name, confidence, flags.
- `transcript_segment_history`: archived transcript rows captured before
  reprocessing or manual replacement, used for audit and enterprise knowledge
  traceability.
- `speakers`: corrected speaker-name mapping per meeting.
- `action_items`: owner/task/due/status extracted from the meeting.
- `processing_jobs`: ASR/LLM/index/forwarding progress and failures.
- `audit_logs`: create/update/upload/process/rename/export/admin operations.

Because each meeting has `owner_id` and `meeting_members`, reinstalling the APK
does not lose server data. After login, the app can call:

```text
GET /api/mobile/sync
GET /api/mobile/meetings
GET /api/mobile/meetings/{meetingId}
GET /api/mobile/meetings/{meetingId}/transcript
GET /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
```

and rebuild its local records from the server.

The audio endpoint requires the same meeting read permission. It lets a
reinstalled APK download a server-side audio segment on demand before playback,
instead of exposing raw storage paths directly.

## Transcript Persistence And Deletion Rules

Transcripts are the evidence layer for downstream knowledge extraction, so they
must be persisted in the server database first. Web and Android show the current
visible version, but rows replaced by reprocessing or manual edits are archived
into `transcript_segment_history`.

Rules:

- Non-admin users can correct transcript text and speaker names, but cannot
  delete transcript segments.
- Admin users can remove segments through a full transcript update; previous
  rows are still archived first.
- Segment re-upload/re-transcription replaces only rows with the matching
  `source_segment_no`, and archives the previous rows.
- External systems must use server APIs instead of reading SQLite or raw audio
  paths directly.

## Login User Recording

Every protected API call resolves the current user from the bearer token. The
server records user identity in:

- `meetings.owner_id`
- `meeting_members.user_id`
- `audit_logs.actor_user_id`

Meeting detail responses include:

```json
{
  "owner": {
    "id": "usr_xxx",
    "display_name": "张三",
    "email": "zhangsan@example.com"
  },
  "members": [
    {
      "role": "owner",
      "id": "usr_xxx",
      "display_name": "张三",
      "email": "zhangsan@example.com"
    }
  ]
}
```

## External Business API

Other internal systems can read meeting data through a server-to-server token:

```text
SOLO_EXTERNAL_API_TOKENS=hermes:replace-with-long-random-token,crm:another-token
```

Then call:

```http
GET /api/external/meetings
Authorization: Bearer replace-with-long-random-token
```

or:

```http
GET /api/external/meetings/{meetingId}
Authorization: Bearer replace-with-long-random-token
```

The response contains meeting metadata, owner, members, transcript segments,
speaker mappings, action items, and merged `searchText`.

Enterprise knowledge platforms or knowledge-maintenance agents should call the
dedicated transcript endpoint:

```http
GET /api/external/meetings/{meetingId}/transcript?include_history=true
Authorization: Bearer replace-with-long-random-token
```

The response includes the current transcript version, structured segments,
`plain_text`, speaker mappings, audio-segment evidence, action items,
`searchText`, and optional archived `history`. Knowledge agents can use current
segments for extraction and history for audit/conflict tracing.

## ES/OpenSearch

ES/OpenSearch is optional and should be treated as a search/index layer, not the
only copy of business data.

Enable from `server/.env` or Web admin:

```text
SOLO_ES_ENABLED=true
SOLO_ES_URL=http://127.0.0.1:9200
SOLO_ES_INDEX=solorecord_meetings
SOLO_ES_API_KEY=
SOLO_ES_USERNAME=
SOLO_ES_PASSWORD=
```

The server indexes a meeting after:

- ASR/summary processing succeeds.
- Transcript is manually edited.
- Speaker is renamed.
- Meeting title/summary is edited.

Admin can rebuild the index:

```text
POST /api/admin/search/reindex
```

Indexed document shape:

```json
{
  "meeting_id": "mtg_xxx",
  "title": "客户复盘会",
  "status": "ready",
  "owner_id": "usr_xxx",
  "owner_name": "张三",
  "owner_email": "zhangsan@example.com",
  "summary": "会议纪要正文",
  "role_notes": "分角色整理",
  "speakers": [{"speaker_id": "SPEAKER_01", "display_name": "张三"}],
  "transcript": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "张三",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "我们今天确认报价。"
    }
  ],
  "action_items": [
    {"owner": "李四", "task": "整理报价单", "due": "下周一", "status": "open"}
  ],
  "search_text": "标题、纪要、转写、待办合并文本"
}
```

## Recommended Deployment

For tomorrow's first server:

- SQLite is acceptable for validation and demo.
- Mount `var/` to persistent disk.
- Enable external API token if Hermes needs to pull records.
- Enable ES/OpenSearch only if another system needs full-text search or the
  meeting volume is already large.

For production:

- Migrate business DB to PostgreSQL.
- Keep audio/object files on NAS/S3-compatible storage.
- Use ES/OpenSearch for search and downstream analytics.
- Back up DB and object storage separately.
