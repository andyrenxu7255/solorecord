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

响应包含当前转写版本、结构化段落、纯文本 `plain_text`、说话人映射、音频分段证据、待办、`searchText`、`qualityReport`、`knowledgeReadiness`、`knowledgeGraph`，以及可选历史归档 `history`。知识平台可以用当前段落生成知识条目，用历史归档做审计和冲突追溯。`actionItems` 会为每条待办附带 `evidenceStatus`、`evidenceReason`、`evidence`、`suggestedOwner`、`suggestedOwnerEvidence`、`knowledgeSafe` 和 `requiresReview`，方便只消费待办列表的督办 Agent 直接判断是否可自动发送提醒；证据明细仍以完整的 `qualityReport.actionEvidence` 为准。当 `evidenceStatus=majority` 时，待办由多数录音源一致的主结果支撑，`knowledgeSafe=true`，但仍带 `requiresReview=true` 作为抽查回听提示；知识平台可以作为主证据使用，并保留复核标记。多数源只代表任务文本证据更强，不能覆盖负责人不明确的风险；如果 owner 是 `待确认`、代词或泛化角色，`evidenceStatus` 必须保持 `weak_owner`、`knowledgeSafe=false`，可使用 `suggestedOwner` 做人工确认。当 `evidenceStatus=conflict` 时，待办虽然有转写依据，但只由多源冲突片段支撑，知识平台必须保留人工复核状态，不得自动督办或沉淀为确定知识。当 `evidenceStatus=contradiction` 时，待办与同主题转写证据表达相反，例如把“先不要发客户通知”写成“发送客户通知”；知识平台必须阻断自动督办，按原文改写或删除后再入库。

证据追溯有两层粒度：音频覆盖、分段重传和录音跳转按 `(source_id, source_segment_no)` 工作；待办、纪要和知识入库风险如果引用里有 `segment_id`，必须按该转写行精确判断 `multi_source_conflict` 或 `multi_source_majority`。只有缺少 `segment_id` 的旧式或探针模拟证据才退回来源分段键，避免同一 5 分钟来源分段里的其它正常议题被冲突片段误伤。

`knowledgeGraph` 是给人和外部 Agent 的辅助关系图，包含 meeting、speaker、topic、action、time 节点。topic 节点来自转写和待办文本的轻量抽取，用来连接“谁讨论了什么”“什么主题产生了哪些待办”“待办何时截止”。topic 节点的 `evidence` 会保留 `segment_id`、`source_id`、`source_segment_no`、`start_ms`、`end_ms` 和原文片段。它只能辅助上下文衔接和可视化查阅，不能替代 `transcript.segments`、`qualityReport.speakerEvidence`、`qualityReport.actionEvidence` 这些证据层字段。

`knowledgeReadiness` 是给外部 Agent 的入库建议：

- `status=ready`：可自动入库。
- `status=review_first`：可入库但应保留风险标记或等待人工校对。
- `status=hold`：存在阻塞风险，建议暂缓自动入库。
- `blockers`：阻塞入库的问题类型，例如缺少转写证据的待办、`action_evidence_contradiction` 反向待办证据、缺证据纪要或 `summary_evidence_contradiction` 反向纪要证据。
- `reviewWarnings`：建议人工复核的问题类型，例如发言人证据弱、负责人归属弱。
- `qualityReport.summaryEvidence.contradictedClaims`：纪要/分角色整理与同主题转写证据在完成、发送、确认、启动等状态上相反。知识平台必须以 `transcript.segments` 原文为准，不能把这些结论写入确定知识。
- `actionItems[].evidenceStatus=majority`：待办由 `multi_source_majority` 主结果支撑，且负责人不是泛化/待确认；此时 `knowledgeSafe=true`、`requiresReview=true`，可以进入主证据链，但应保留抽查回听提示。
- `actionItems[].evidenceStatus=weak_owner`：任务文本可能有多数源或普通转写证据，但负责人是 `待确认`、代词、时间短语或缺少负责人-任务上下文；此时 `knowledgeSafe=false`，应先人工应用或确认 `suggestedOwner`。
- `actionItems[].evidenceStatus=conflict`：待办由 `multi_source_conflict` 片段支撑，通常表示不同录音源在日期、数量或负责人上不一致；此时 `knowledgeSafe=false`、`requiresReview=true`。
- `actionItems[].evidenceStatus=contradiction`：待办把原文中的“先不要、暂缓、不能、取消”等阻止执行表达写成了执行动作；此时 `knowledgeSafe=false`、`requiresReview=true`，并触发 `knowledgeReadiness.status=hold`。
- LLM 生成阶段会提示模型保留复核或暂缓语义，保存前也会移除反向执行型待办和完全缺少转写证据的待办。如果全部生成待办都缺证据，服务端只保留一条带原文片段的“按转写原文复核待办”，用于人工复核，外部督办 Agent 不得自动发送。若原文是“等法务确认后再说”，这只是前置条件，不代表法务就是待办 owner；只有“法务负责/确认/审批某事项”等同一短语窗口中的责任或动作证据，才能把法务作为组织 owner。

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
`searchText`, `qualityReport`, `knowledgeReadiness`, `knowledgeGraph`, and
optional archived `history`. Knowledge agents can use current segments for
extraction and history for audit/conflict tracing. Each `actionItems` entry
also carries `evidenceStatus`, `evidenceReason`, `evidence`,
`suggestedOwner`, `suggestedOwnerEvidence`, `knowledgeSafe`, and
`requiresReview`, so action/reminder agents that read only the action list can
still decide whether a reminder is grounded enough to send. The full evidence
table remains `qualityReport.actionEvidence`. If an action has
`evidenceStatus=majority`, it is backed by the `multi_source_majority` primary
row and has a non-generic owner; downstream systems may use it as primary
evidence while preserving the replay-review marker because `knowledgeSafe=true`
and `requiresReview=true`. Majority evidence strengthens the task text only; if
the owner is unknown, a pronoun, a time phrase, or otherwise weakly linked to
the task, the action must stay `weak_owner` with `knowledgeSafe=false`, and
`suggestedOwner` is only a human-review aid. If an action has
`evidenceStatus=conflict`, it is only backed by transcript evidence from
`multi_source_conflict` rows; downstream systems must keep it under human review
and must not auto-send or store it as confirmed knowledge while
`knowledgeSafe=false` and `requiresReview=true`.
If an action has `evidenceStatus=contradiction`, it matches transcript evidence
on the same topic but reverses the action meaning, such as turning "do not send
yet" into "send the customer notice". Downstream reminder and knowledge agents
must keep `knowledgeSafe=false`, require review, and rewrite or remove the
action before ingestion.
During LLM generation, unsupported new actions are also removed before storage.
If every generated action is unsupported, the server keeps one
transcript-referenced review action; downstream reminder agents must treat it as
human review work, not as an executable reminder.
`qualityReport.summaryEvidence.contradictedClaims` lists summary or role-note
claims that match transcript evidence on the same topic but reverse completion,
sending, confirmation, or launch status. This produces the
`summary_evidence_contradiction` blocker; knowledge agents must trust
`transcript.segments` and must not store those summary claims as confirmed
facts.

Evidence traceability has two granularities. Audio coverage, segment retry, and
audio navigation use `(source_id, source_segment_no)`. Action, summary, and
knowledge-ingestion risk checks must prefer exact `segment_id` matching for
`multi_source_conflict` or `multi_source_majority` when the reference includes
a row id. Fall back to the source-segment key only for legacy or probe-simulated
evidence without `segment_id`, so unrelated safe topics in the same five-minute
source segment are not marked as conflicting.

`knowledgeGraph` is an auxiliary relationship graph for people and agents. It
contains meeting, speaker, topic, action, and time nodes. Topic nodes are
lightly extracted from transcript/action text and connect who discussed what,
which topic produced which action, and when an action is due. Topic-node
`evidence` keeps `segment_id`, `source_id`, `source_segment_no`, `start_ms`,
`end_ms`, and the transcript snippet. It helps context bridging and
visualization, but it does not replace evidence-layer fields such
as `transcript.segments`, `qualityReport.speakerEvidence`, or
`qualityReport.actionEvidence`.

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
