# SoloRecord 开发者手册

## 适用读者

本手册给继续开发 SoloRecord 的工程师看。你需要了解服务端、Web、Android、数据模型、测试和集成边界。

## 仓库结构

```text
D:\solo\solorecord
├── app/                         Android 原生 Java App
├── clients/                     Windows/macOS/iOS/HarmonyOS 外壳工程
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
- 提供桌面/WebView 共享体验：录音、文件补传、记录、下载、管理

桌面与 WebView：

- `clients/desktop`：Electron Windows/macOS 外壳。
- `clients/ios`：SwiftUI + WKWebView iOS 外壳。
- `clients/macos`：SwiftUI + WKWebView macOS 备选外壳。
- `clients/harmony`：HarmonyOS Stage 模型 Web 外壳。
- 终端外壳不内置任何密钥，只配置服务器地址。

Android：

- 原生 Java
- Gradle Android Plugin
- AudioRecord 连续采集，WAV 滚动分段落盘
- 当前写入段定期写入本地索引，WAV 头部边录边刷新
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
├── ontology.py          本体抽槽、图谱节点/关系持久化
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
- `ontology_entities`
- `ontology_relations`
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
GET  /api/mobile/meetings/{meetingId}/ontology
POST /api/mobile/meetings/{meetingId}/ontology/extract
GET  /api/mobile/meetings/{meetingId}/transcript
PUT  /api/mobile/meetings/{meetingId}/transcript
PUT  /api/mobile/meetings/{meetingId}/actions
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
PUT  /api/web/meetings/{meetingId}/actions
POST /api/web/meetings/{meetingId}/process
GET  /api/web/meetings/{meetingId}/ontology
POST /api/web/meetings/{meetingId}/ontology/extract
POST /api/web/meetings/{meetingId}/speakers/rename
POST /api/web/meetings/{meetingId}/exports
GET  /api/web/search
GET  /api/web/sync
GET  /api/web/releases/latest?platform=android|windows|macos|ios|harmony
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
GET /api/external/meetings/{meetingId}/transcript
GET /api/external/meetings/{meetingId}/ontology
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

Android 录音和上传采用连续录音、重叠分段、分段级断点续传：

- 录音端使用 `AudioRecord` 连续采集 16 kHz mono PCM16，并写成 WAV。
- 默认按服务器 `/api/mobile/config.segmentMinutes` 滚动分段，当前默认约 5 分钟。
- 相邻分段保留约 2 秒音频重叠，降低切分边界丢词风险。
- 当前写入中的分段会以 `local_recording` 状态定期写入本地 JSON 索引，上传逻辑会跳过该状态，等分段关闭后再补传；App 下次启动会把异常遗留的开放段转为待上传状态。
- 录音分段先写入 App 私有目录。
- 客户端创建远端 meeting 后立即把本地记录 id 替换为服务端 id。
- 每个分段通过 multipart 文件流上传到 `/api/mobile/meetings/{meetingId}/segments`。
- 服务端确认后会立即触发 `segment_transcribe` 分段转写，并把阶段结果写入同一场会议的 `transcript_segments`。
- 客户端马上将该分段 `uploadStatus` 写为 `uploaded`，再刷新服务器会议内容。
- 重试同步时跳过已上传分段，只上传本地账本中仍未完成的分段。
- `/finish` 是可重试接口；已有 queued/running/succeeded job 时返回同一个 job id。
- 如果所有音频分段已经在线分段转写完成，`/finish` 会复用现有阶段转写生成整场纪要和待办，避免重复消耗 ASR。

`transcript_segments.source_segment_no` 用于分段重传时只替换该来源分段的阶段转写。不要用时间范围删除相邻段落，因为相邻分段存在约 2 秒重叠。

## 多源同录与多源校对

多源同录用于一个会议有 1-8 台设备同时录音的场景。用户可以在 Web、Windows 客户端或 Android 录音页填写相同 `join_code`，服务端会把这些录音源归入同一场会议。

核心约定：

- `meetings.join_code` 是加入同一会议的短编号，保存时会标准化为大写字母数字。
- `meetings.recording_mode` 可为 `single` 或 `multi_source`；`max_sources` 限制在 1-8。
- `recording_sources` 保存每个来源的 `source_id`、显示名、设备名和用户。
- `audio_segments.segment_no` 仍是会议内全局唯一编号，用于下载 URL 和旧客户端兼容。
- `audio_segments.source_id` + `source_segment_no` 表示某个设备自己的分段编号。多台设备都可以上传自己的第 1 段，服务端会分配不同的全局 `segment_no`，但保留各自的 `source_segment_no=1`。
- `transcript_segments.source_id` + `source_segment_no` 是证据追溯键。分段重传只替换同一来源、同一本地分段的转写行；`primary` 兼容旧数据里的空 `source_id`。
- 证据匹配分两层：`sourceCoverage`、重传和音频跳转按 `(source_id, source_segment_no)` 判断；`actionEvidence`、`summaryEvidence` 和知识入库风险如果引用里有 `segment_id`，必须按转写行精确判断 `multi_source_conflict`/`multi_source_majority`。只有缺少 `segment_id` 的旧式或探针模拟证据才退回来源分段键，避免同一 5 分钟来源分段内的正常待办被冲突行误伤。
- `/api/mobile/meetings/join` 和 `/api/web/meetings/join` 支持按会议编号或标题加入。重复加入时，同一用户、同一设备名和同一录音源名称会复用原 `source_id`；同一用户显式换录音源名称时仍可注册另一台设备。上传接口也会校验 `max_sources`，不能绕过来源上限。
- `/api/mobile/meetings/discover` 和 `/api/web/meetings/discover` 返回近期、未结束、未满员、仍在处理中的多源会议候选。返回内容只包含 `id/title/join_code/status/owner_name/source_count/max_sources/remaining_sources/created_at/updated_at`，用于录音页和文件补传页一键填入编号；加入前不能返回纪要、转写、音频、待办或成员详情。
- `processing._merge_multisource_segments()` 在整场 finish 前做保守多源校对：同一时间窗、不同来源、文本高度相近且关键事实一致的段落合并为一条，并写入 `multi_source_merged`、`multi_source_count:*` 和 `multi_source_refs:*` flags；如果不同设备起录时间错开，会在来源分段号相邻、起点差不超过保守窗口、文本高度相近且关键事实一致时做错峰对齐，并额外写入 `multi_source_time_aligned`。若多个来源各自漏掉不同非冲突短语，会从原始转写补足到合并段并写入 `multi_source_complemented`。当至少两个来源一致、且一致来源数量多于附近冲突来源数量时，合并段写入 `multi_source_majority`，作为多数源主结果；历史行若已有 `multi_source_merged` 和 `multi_source_count:*` 但缺少 `multi_source_majority`，`repository.with_derived_quality_flags()` 会在 API/质量报告返回层派生多数源标记，不重写数据库旧转写。少数冲突源仍保留 `multi_source_conflict` 和 `speaker_review` 供人工回听。同一时间只有两源冲突或没有多数时，日期、数量、负责人等关键事实冲突片段仍全部保守标记 `multi_source_conflict`；如果不同设备只是拾到不同人的并行发言，则保留为普通单源证据，不当成冲突。
- LLM 语义分段和纪要整理必须继续保留多源证据：`llm_adapters._parse_refined_segments()` 会继承 `multi_source_merged`、`multi_source_count:*`、`multi_source_refs:*`、`multi_source_time_aligned`、`multi_source_complemented`、`multi_source_majority`、`multi_source_conflict` 和 `speaker_review`，但不会把阶段性 `semantic_partial` 直接带入最终行。纪要 prompt 会把 `source_id/source_segment_no` 和多源 flags 暴露给模型；带 `multi_source_conflict` 的事实只能作为需复核的不确定信息，不能被 LLM 融合成确定结论。
- `qualityReport.metrics.recording_source_count`、`multi_source_merged_count`、`multi_source_majority_count`、`multi_source_complemented_count`、`multi_source_conflict_count` 和按 `(source_id, source_segment_no)` 计算的 `sourceCoverage` 用于 Web 和外部 Agent 判断证据质量。
- Web 时间线筛选、证据跳转和保存转写都必须保留 `source_id`。前端筛选值使用 `source_id::source_segment_no`，不能退回只按 `source_segment_no` 匹配；合并后的多源段落通过 `multi_source_refs:*` 继续计入各原始来源覆盖率。

目前“自动发现就近录制设备”尚未实现协议层，产品上先用共享会议编号加入；Web 会显示服务端可加入会议候选，但这不是局域网/Bluetooth 近场发现。后续如果增加局域网发现或二维码邀请，只应创建/传递 `join_code`，不要绕过服务端权限和来源上限。

转写是企业知识平台的原始证据层。服务端使用 `transcript_segment_history` 归档被重处理或人工替换前的旧行。非 admin 用户更新转写时不能减少段落数；admin 可以删除段落，但删除前同样归档。知识平台 Agent 应通过 `/api/external/meetings/{meetingId}/transcript?include_history=true` 拉取当前转写和历史，不要直接读 SQLite。待办事项通过 `/api/web/meetings/{meetingId}/actions` 或 `/api/mobile/meetings/{meetingId}/actions` 更新，字段为 `owner`、`task`、`due`、`status`，更新后会出现在同步、导出、外部 API、持久化本体图谱和可选 ES/OpenSearch 索引中。

本体图谱由 `ontology.py` 维护，实体表是 `ontology_entities`，关系表是 `ontology_relations`。实体类型固定为 `person`、`place`、`time`、`matter`、`action`；关系优先使用 `responsible_for`、`due_at`、`located_at`、`scheduled_at`、`discussed`、`related_to`、`depends_on`、`mentioned`。规则兜底抽槽也会根据“依赖、等待、需要、先”等上下文建立 `action -> action` 的 `depends_on` 关系，例如“接口联调依赖测试账号”应形成“完成接口联调 -> 提供测试账号”的边，并保留转写/待办证据。会议最终转写整理成功后会自动创建 `knowledge_graph` 任务并落库；也可以调用 `/api/web/meetings/{meetingId}/ontology/extract` 或移动端同名接口单独重建，不需要重跑 ASR。图谱结果通过 `ontologyGraph` 返回，外部知识平台可单独拉取 `/api/external/meetings/{meetingId}/ontology`。`knowledgeGraph` 仍保留为轻量主题图，`ontologyGraph` 才是面向“人员-地点-时间-事项-待办”对象抽槽和关系查询的持久化图谱。

`/segments-json` 仍保留作兼容和简单测试入口，Android 主流程不再使用它上传长会议音频。

## ASR 适配

ASR 适配器在：

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

命令适配器不使用 shell 执行命令，避免 shell 注入。新增占位符时，要在 `_render_command` 中显式加入。

远程 STT 适配器同在 `asr_adapters.py`。`transcribe_with_openai_compatible()` 支持 `openai-compatible`、`remote-stt` 和 `funasr` Provider，优先调用 `/audio/transcriptions`，如果返回 404 再尝试 `/asr`。它会规范化 `text`、`transcript`、`result`、`data`、`segments`、`sentence_info`、`sentences`，也支持嵌套在 `data/result/output` 内的 FunASR 原始结果。时间字段支持 `start/end`、`start_ms/end_ms`、`startMillis/endMillis`，以及 `timestamp`/`timestamps` 二元组或字词级二元组数组；原生说话人字段支持 `speaker_id`、`speaker`、`spk`、`spk_id`、`speakerLabel`。空文本不会让会议处理丢失状态，而是写入带 `empty_asr` 的占位转写。

## 语义分段与发言人推断

服务端后处理入口在：

```text
server/solorecord_server/processing.py
```

LLM 语义分段入口在：

```text
server/solorecord_server/llm_adapters.py
```

处理顺序：

1. `asr_adapters.py` 尽量保留 ASR 原生 `sentence_info`、`segments`、`timestamp`/`timestamps`、`speaker_id`、`speaker`、`spk`、`spk_id`、`speakerLabel` 等字段，并把原生说话人标记为 `asr_speaker`。
2. `processing._needs_semantic_segmentation()` 判断是否需要 LLM 重分段：如果 ASR 已经给出多个可靠 speaker id 且没有“某某你先说/某某你那个部分/我这边负责”等上下文线索，可以跳过重分段；只要出现点名、承接回应、被点名议题的后续延续、长文本单一发言人、多个“某某说/某某：”标记，或“某某负责/某某确认/某某后面看”这类未解析到人物的任务归属线索，仍会进入后处理。
3. `llm_adapters.refine_segments_with_llm()` 要求模型只返回 `{"segments":[...]}`，每段包含 `source_index`、`source_id`、`source_segment_no`、`speaker`、`speaker_id`、`start_ms`、`end_ms`、`text`、`confidence`、`scenario`、`reason`。`source_index`、`source_id` 和 `source_segment_no` 用于把模型输出追溯到原始 ASR/音频分段。
4. LLM 返回后，`processing._rule_refine_residual_mixed_segments()` 会再检查是否还残留明显的“某某说/某某：/某某你先说/某某后面看”混合段；如果有，会保守二次拆分并写入 `llm_residual_rule_refined` 和 `speaker_review`。即使只出现一个被点名人，只要同一段里紧跟“我这边/我负责/我会”等回应，也会拆成主持人点名段和被点名人回应段。点名前面的“先过整体节奏/我们看一下背景”这类主持人导语应保留给原始发言人，并写入 `source_prefix_before_callout`，不能并到第一个被点名人名下。
5. LLM 不可用或返回非法 JSON 时，`processing._rule_refine_segments()` 用规则兜底拆明显人名标记；`_split_inline_addressed_response()` 会处理 ASR 没有在“某某你先说”和“我这边/我负责”回应之间加标点的单段文本；`_apply_contextual_speaker_inference()` 会继续处理“被点名后下一段以我这边/我负责回应”以及“没有我字但继续同一议题、交付物、时间节点”的归属，但会写入 `speaker_review` 和 `reason:*`，让用户确认。
6. 分段上传会写入 `semantic_partial`，让用户在会议中先看到阶段草稿；结束会议后的 `/finish` 总是基于整场上下文再跑一次语义后处理，并写入 `semantic_final`。
7. `_insert_transcript_segments()` 持久化 `flags` 和 `source_segment_no`，供 Web 标记“需确认”“大模型分段”“规则分段”“上下文推断”，也供外部知识平台追踪来源。已人工保存为具体人名的 `speaker_id` 会优先覆盖后续同 ID 的泛化 ASR 名称；`发言人 1/2/3` 这类泛化旧名不会压住模型新识别的人名。
8. 如果 LLM 只是把同一个 ASR 原生 speaker 的长段拆成多个较短段落，并且输出仍使用同一个 `speaker_id` 与 `native_speaker` 场景，`llm_adapters._parse_refined_segments()` 会保留 `asr_speaker`。如果 LLM 通过 `context_bridge`、`dialogue_logic` 或 `task_ownership` 改了发言人，则不能保留 `asr_speaker`，必须继续用 `speaker_review` 表示“上下文推断待确认”。
9. 如果 LLM 把一个多源合并段拆成多个较短对话轮次，每个新段仍要继承 `multi_source_refs:*`，否则 `sourceCoverage` 会误判原始录音分段未覆盖。带 `multi_source_conflict` 的段落即使被 LLM 重排，也必须继续保留 `speaker_review` 或冲突标记，方便 Web 和外部知识 Agent 阻断自动入库。

质量检查：

- `repository.build_quality_report()` 会检查单一发言人、长段落、需人工确认的发言人、发言人是否缺少原文证据、原始音频分段是否被最终转写覆盖、泛化待办负责人、负责人过度集中、候选人名未成为发言人，以及待办是否能在转写文本中找到证据。
- `speaker_evidence_weak_count` 用于发现模型把议题、时间短语或误听词当成真实人名。`llm_adapters._parse_refined_segments()` 会在这类分段上降低 `confidence` 并写入 `speaker_review`、`speaker_evidence_weak` flags。即使人名有上下文证据，只要它不是原始 speaker/display_name，而是通过 `context_bridge`、`dialogue_logic` 或 `task_ownership` 推断出来，也会保留 `speaker_review` 并限制置信度，因为这不是声纹确认。
- `qualityReport.speakerEvidence` 会列出需要校对的发言人段落，包含 `segment_id`、`speaker`、`scenario_label`、`reason`、`risk` 和相邻上下文。Web 时间线用它展示“推断依据”，外部 Agent 可以用它决定是否等待人工校对。
- `speaker_alias_conflict_count` 用于发现同一个 `display_name` 对应多个 `speaker_id` 的情况。知识图谱会按非泛化姓名合并展示同一人员节点，并在节点上保留 `speaker_ids` 追溯原始标签。
- `knowledgeGraph` 现在包含 `topic` 节点。服务端从转写和待办里抽取轻量业务主题，连接“人员讨论主题”“主题产生待办”“待办截止时间”，用于缓解分段上下文断裂；topic 节点的 `evidence` 会保留 `segment_id`、`source_id`、`source_segment_no`、`start_ms`、`end_ms` 和原文片段。主题节点是辅助索引，不替代原始转写证据。
- `unsupported_action_count` 和 `action_evidence_coverage` 用于发现模型补写的待办。判定使用中文 2-4 字 ngram、英文 token 和 owner 线索做弱匹配，不要求逐字相同，但不能完全脱离转写原文。LLM 新生成的待办在保存前会删除 `unsupported` 项；若全部生成待办都缺证据，服务端保留一条带原文片段的“按转写原文复核待办”，作为人工复核入口，而不是可自动督办事项。LLM 不可用时，如果 ASR 已产生真实转写，`processing._summarize()` 只保存保守纪要并返回空待办列表；只有 `mock_asr`、`empty_asr` 或 `missing_audio` 占位转写才通过 `_llm_unavailable_fallback_actions()` 生成“检查转写结果并补充真实会议纪要”提醒。上述复核入口在 `qualityReport.actionEvidence` 中应输出 `status=system_review`、`action_kind=system_review`、`auto_actionable=false`、`reminder_safe=false`，并在 `actionItems` 中输出 `actionKind=system_review`、`autoActionable=false`、`reminderSafe=false`；`system_review_action_count` 不应计入 `generic_owner_count`、`unsupported_action_count` 或 `action_evidence_coverage` 分母。用户手工新增或编辑后的待办不被静默删除，仍通过质量报告暴露证据风险。已经判定为 `unsupported` 的待办不要再进入 `weakActionOwners`，否则前端会把一个“缺转写证据”问题重复展示成两个风险。
- 待办 owner 如果是“我、我们、他、这边、大家”等代词，`processing._normalize_action_owners()` 会先尝试从第一人称转写和任务关键词推断真实发言人；无法推断时降级为 `待确认`。`repository._is_generic_owner()` 也会把残留代词负责人视为泛化 owner，`qualityReport.actionEvidence` 应显示为 `weak_owner` 而不是 `supported`。
- LLM 返回的待办 owner 如果是“负责人、相关负责人、主持人、前端开发、某某负责人”等泛化角色，`llm_adapters._normalize_owner()` 会先降级为 `待确认`；后续 `processing._normalize_action_owners()` 只有在转写中找到明确人名、团队或任务归属证据时才会补回具体 owner。明确的组织 owner（如销售、法务、前端）仍可保留。
- 日期和截止时间短语只作为任务时间事实，不能被提升为发言人或负责人。规则分段、LLM 候选人名抽取和待办 owner 归因都会过滤“今天下午、下午、周三前、月底前”等候选，避免污染人物列表和待办负责人；如果历史数据里已经出现时间 owner，质量报告应标为泛化负责人并要求人工确认。
- 被点名后的发言人归属必须有明确证据：第一人称回应、任务承诺、同议题关键词承接或显式姓名前缀。不要仅因为 ASR `speaker_id` 在点名后发生变化，就把下一段自动归给被点名人；“好的，我们继续下一个议题”这类过渡话应保留原 ASR 发言人。
- 待办 owner 归因可以利用被点名句里的议题词：例如主持人说“翼天你先说自动测试”，后续匿名片段继续说“覆盖脚本明天补完”，`processing._normalize_action_owners()` 和 `repository._suggest_action_owner()` 应优先建议/归属“翼天”，不能把任务归给主持人。质量报告的建议负责人也要支持粗分段场景：即使当前行 speaker 还是主持人或 `发言人 1`，只要点名窗口里任务关键词匹配，就可以输出被点名人为 `suggested_owner`；但要继续过滤“舞台音响、自动测试、测试覆盖、数据源”等议题短语，不能把它们当人或团队。
- 销售、法务、前端、测试等组织角色可以作为待办 owner，但只有在同一短语窗口内出现明确动作或责任表达时才参与归属，例如“销售这边周五前跟进客户名单”“前端周三前改页面”。“自动测试、测试覆盖、数据源”等任务词不能被误判成团队负责人。
- `weak_action_owner_count` 用于发现“任务内容有证据，但负责人和该任务缺少上下文关联”的情况。例如文本中出现了李娜，也出现了错误样例任务，但只有翼天被点名负责错误样例时，李娜不能被视为有证据的负责人。
- `qualityReport.actionEvidence` 会为每条待办输出 `supported`、`majority`、`system_review`、`conflict`、`contradiction`、`weak_owner` 或 `unsupported`，并附带相关转写片段。证据片段必须带 `segment_id`、`source_id` 和 `source_segment_no`，便于 Web 的“定位转写”和外部 Agent 追溯原文。`majority` 表示待办由 `multi_source_majority` 主结果支撑，且 owner 不是泛化/待确认，`knowledgeSafe=true` 但 `requiresReview=true`，外部督办 Agent 可以作为主证据使用，同时保留抽查回听提示；`system_review` 表示该行只是系统复核入口，必须保持 `autoActionable=false`、`reminderSafe=false`、`knowledgeSafe=false`，Web 复制待办时会跳过，Android 离线记录页和 Markdown/Word/PDF/JSON 导出也必须显示为系统复核提醒；`conflict` 表示待办只由 `multi_source_conflict` 片段支撑，必须视为需人工回听，不能自动发送提醒或写入确定知识；`contradiction` 表示待办把同主题转写里的“先不要、暂缓、不能、取消”等阻止执行语义反写成了执行动作，必须 `knowledgeSafe=false` 并加入 `action_evidence_contradiction` 阻塞项。若 owner 是 `待确认`、代词、时间短语或泛化角色，应优先输出 `weak_owner`，即使任务文本有多数源证据也不能自动督办。若能从任务关键词和责任表述中找到更接近的人，还会输出 `suggested_owner`、`suggested_owner_reason` 和 `suggested_owner_evidence`。`actionItems` 同步带有驼峰命名的 `evidenceStatus`、`evidence`、`suggestedOwner`、`actionKind`、`autoActionable`、`reminderSafe`、`knowledgeSafe` 和 `requiresReview`，方便只消费待办列表的外部督办 Agent 使用。Web 待办区用这些证据展示“有转写依据”“多数源确认”“系统复核提醒”“多源冲突待核对”“待办与原文相反”“负责人证据弱”或“缺转写证据”，并提供“应用建议”按钮；复制待办时不包含证据文本，也不包含系统复核提醒。
- 对于 `actionEvidence` 和 `summaryEvidence`，一条证据如果带 `segment_id`，冲突/多数源状态只继承该转写行的 flags；不能因为同一 `source_id/source_segment_no` 里另有冲突行，就把当前证据也标成 `conflict`。这是多源 5 分钟分段内存在多个议题时的关键保护。
- `qualityReport.sourceCoverage` 会按 `(source_id, source_segment_no)` 检查当前转写是否覆盖每个音频分段。`mock_asr`、`empty_asr`、`missing_audio` 和 `source_coverage_gap` 只算复核占位，不算有效覆盖。最终 `/finish` 如果发现已上传音频完全没有对应转写行，会补一条 `source_coverage_gap` + `missing_audio` 的“系统复核”转写行，方便 Web 定位和外部 Agent 阻断入库；如果已有空语音/占位行，则不会重复补行。复核占位行只能进入覆盖率、复核入口和入库阻断，不得参与 `speakerEvidence`、候选人名、纪要证据、待办证据、说话人统计、LLM/规则分段统计或 `knowledgeGraph` 主题抽取。`source_segment_coverage_weak` 是知识入库阻塞项，通常说明 LLM 后处理丢段、分段重传缺失或 ASR 空结果，应先回听/重转写。
- `qualityReport.multiSourceConflicts` 会列出多源冲突片段明细，包含 `segment_id`、`source_id`、`source_segment_no`、发言人、时间、文本、flags 和同时间附近的其它冲突来源。Web 质量区会展示这些明细并提供“定位转写”，外部知识 Agent 应优先消费该字段做回听清单，而不是只看 `multi_source_conflict_count` 数量。
- `knowledgeReadiness.reviewEvidence` 会从质量报告中抽取外部 Agent 最需要复核的证据，包括 `multiSourceConflicts`、`sourceCoverageWeakSegments`、`speakerEvidence`、`speakerAliasConflicts`、`summaryClaims` 和 `actionEvidence`。它是入库门禁的复核入口，不能替代转写原文成为新的事实来源。Web“整理质量”区会渲染“知识入库复核”，展示 `ready/review_first/hold`、阻塞项、复核标签、说明和可定位的证据条目；覆盖不足分段如果暂缺转写，只提示回听或重转写，避免误导为已有原文。
- `processing._normalize_action_owners()` 会保留协作关系：如果主责人已经明确，但其他发言人说“我这边配合/协同/补充”且任务关键词匹配，会在 task 末尾追加 `协同：姓名`，避免后续 IM 督办漏掉配合人。
- `processing._grounded_summary_result()` 会在 LLM 生成纪要后立即跑一次证据检查，并在保存前用 `qualityReport.actionEvidence[].suggested_owner` 纠偏明显弱负责人。若 `summary_evidence_coverage` 不达标、存在缺证据要点、多源冲突事实被写成确定结论，或纪要把转写中的未完成/否定表达写成已完成/肯定结论，服务端会丢弃该版纪要，改用“基于转写原文的保守整理”。保守整理若引用 `multi_source_conflict` 片段，摘要和分角色整理都必须带“多源冲突待确认”这类复核语气，使 `summary_unqualified_conflict_count` 保持为 0。默认输出宁可朴素，也不能保存脱离转写原文、与原文相反或未保留复核语气的模型结论。
- `summaryEvidence.supportedClaims` 会列出纪要/分角色整理中已找到转写证据的要点及引用片段；引用片段也应带 `segment_id`、`source_id` 和 `source_segment_no`。每个 supported claim 还带 `status`：`supported` 表示普通转写证据，`majority` 表示多数源主结果支撑但需保留抽查回听提示，`conflict` 表示只由多源冲突片段支撑，纪要必须保留待确认语气，`contradiction` 表示同主题证据存在完成/否定状态反向，必须按转写原文改写后再入库。`contradictedClaims` 单独列出反向证据要点，`unsupportedClaims` 只列出缺证据要点。Web 质量区会同时展示“纪要有依据”“纪要多数源确认”“纪要多源冲突待核对”“纪要与原文相反”和“纪要待核对”。
- 新增 LLM 待办抽取逻辑时，要保证测试覆盖“有证据待办不误报、无证据待办会提示、反向待办会阻断、确认是否执行这类核对型待办不误判为反向执行”。

只读质量探测：

```powershell
$env:PYTHONPATH="server"
python -m solorecord_server.quality_probe --meeting-id <meeting_id>
python -m solorecord_server.quality_probe --meeting-id <meeting_id> --postprocess
python -m solorecord_server.quality_probe --meeting-id <meeting_id> --run-llm
```

`quality_probe` 用于真实会议效果复验。默认只读取当前数据库结果；`--postprocess` 会只跑本地规则后处理模拟，并用模拟后的分段重新归一化待办负责人；`--run-llm` 会调用当前 LLM 配置做语义重分段、纪要和负责人归因的模拟评估，但都不会替换 `transcript_segments`、`action_items` 或会议纪要。模拟输出也会通过 `preserve_uncovered_audio_rows()` 补出只读的 `source_gap_review_segment_count`，让探针和真实 `/finish` 对“缺失音频分段”的判断一致。`postprocess.delta` 或 `llm.delta` 会对比当前结果和模拟结果，重点看 `mixed_marker_segment_count` 是否下降、`speaker_count` 是否上升、`action_owner_changes` 是否把待办负责人从主持人/待确认纠偏到真实被点名人，以及 `suggested_owner_changes` 是否只剩需要人工应用的建议。输出包含 `quality_report` 和 `knowledge_readiness`，用于判断是否可进入知识库、是否应先人工复核。新增大模型逻辑时，请保证这个命令仍然只读，并补充测试覆盖质量报告中的关键指标。

注意事项：

- 分段上传路径 `process_uploaded_segment()` 会先做局部分段后处理，给用户即时反馈，输出带 `semantic_partial`。
- 完整 `/finish` 会再做整场上下文后处理，并把最终时间线写回数据库，输出带 `semantic_final`。这一步用于修复 5 分钟分片导致的上下文断裂，尤其是“前一段点名某人、后一段才说明交付物/时间”的场景。
- 新增规则时要保证不删除原文事实；只做切分、speaker/display_name 归一和明显前缀去除。
- 如果要接入真正的 diarization sidecar，优先让 sidecar 输出标准 `segments` JSON，不要把模型代码耦合进 FastAPI 主进程。

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

Windows 桌面客户端：

```powershell
cd clients\desktop
npm install
$env:SOLO_SERVER_URL="http://127.0.0.1:8000"
npm run pack
npm run portable:win
```

本机可验证 `clients/desktop/dist/win-unpacked/SoloRecord.exe` 是否能启动。NSIS 安装 EXE 需要当前 Windows 账号具备 electron-builder 解压 winCodeSign 所需的符号链接权限；若没有，使用 portable ZIP 发布。

iOS、macOS、HarmonyOS 签名包分别需要 Xcode 或 DevEco Studio 构建机，源码工程在 `clients/ios`、`clients/macos`、`clients/harmony`。

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
- 发布 Android APK 和 Windows/macOS/iOS/HarmonyOS 终端应用
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

- 不要把真实 ASR/LLM/SSO/Hermes 密钥写进 APK、EXE、DMG、IPA 或 HAP。
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

如果新增的是远程 STT Runtime，优先复用 `openai-compatible`/`funasr` 适配器；只有上游协议明显不同，才新增小而独立的 HTTP 适配函数，并补测试覆盖返回格式和空文本降级。

## English

### Audience

This manual is for engineers extending SoloRecord. It covers the server, Web UI, Android APK, desktop/WebView client shells, data model, tests, and integration boundaries.

### Repository Structure

```text
D:\solo\solorecord
├── app/                         Native Android Java app
├── clients/                     Windows/macOS/iOS/HarmonyOS client shells
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
- Shared desktop/WebView experience for recording, upload, records, downloads, and administration

Desktop and WebView clients:

- `clients/desktop`: Electron Windows/macOS wrapper.
- `clients/ios`: SwiftUI + WKWebView iOS shell.
- `clients/macos`: SwiftUI + WKWebView macOS alternative shell.
- `clients/harmony`: HarmonyOS Stage-model Web shell.
- Client shells embed no secrets; they only configure the server URL.

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
├── ontology.py          ontology slot extraction and persisted graph storage
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
- `ontology_entities`
- `ontology_relations`
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
GET  /api/mobile/meetings/{meetingId}/ontology
POST /api/mobile/meetings/{meetingId}/ontology/extract
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
GET  /api/web/meetings/{meetingId}/ontology
POST /api/web/meetings/{meetingId}/ontology/extract
POST /api/web/meetings/{meetingId}/process
POST /api/web/meetings/{meetingId}/speakers/rename
POST /api/web/meetings/{meetingId}/exports
GET  /api/web/search
GET  /api/web/sync
GET  /api/web/releases/latest?platform=android|windows|macos|ios|harmony
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
GET /api/external/meetings/{meetingId}/transcript
GET /api/external/meetings/{meetingId}/ontology
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

Android upload uses segment-level resume:

- Recording uses `AudioRecord` continuous 16 kHz mono PCM16 capture and writes WAV rolling segments.
- Segment duration comes from `/api/mobile/config.segmentMinutes`; the default is about five minutes.
- Adjacent segments keep about two seconds of overlap to reduce boundary word loss.
- The open segment is periodically stored in the local JSON index with `local_recording`; upload skips that state until the segment is closed, and next launch converts interrupted open segments into pending uploads.
- Recording segments are written to the app-private directory first.
- After the remote meeting is created, the client persists the server meeting id locally.
- Each segment is uploaded as a multipart file to `/api/mobile/meetings/{meetingId}/segments`.
- After server acknowledgement, the server runs a `segment_transcribe` job and writes partial transcript rows into the same meeting.
- The client immediately stores `uploadStatus=uploaded` for that segment, then refreshes the server meeting content.
- Retry sync skips uploaded segments and sends only pending local segments.
- `/finish` is retry-safe and returns the existing queued/running/succeeded job id when one already exists.
- If all uploaded audio segments already have online partial transcripts, `/finish` reuses those rows for the full summary and action items instead of spending ASR again.

`transcript_segments.source_segment_no` lets retries replace only the transcript rows from that segment. Do not delete by timestamp range because adjacent segments intentionally overlap by about two seconds.

### Multi-Source Recording And Cross-Check

Multi-source recording supports meetings recorded by 1-8 devices at the same time. Users enter the same `join_code` in Web, Windows, or Android to join the same meeting.

Key rules:

- `meetings.join_code` is normalized to uppercase letters and digits.
- `meetings.recording_mode` is `single` or `multi_source`; `max_sources` is clamped to 1-8.
- `recording_sources` stores source id, label, device name, and user.
- `audio_segments.segment_no` remains globally unique within the meeting for download URLs and backward compatibility.
- `audio_segments.source_id` plus `source_segment_no` records the device-local segment number. Multiple devices may upload local segment 1; the server allocates distinct global segment numbers while preserving `source_segment_no=1` for each source.
- `transcript_segments.source_id` plus `source_segment_no` is the evidence key. Segment re-upload replaces only rows for the same source and local segment. `primary` is compatible with older empty `source_id` rows.
- Evidence matching has two layers. `sourceCoverage`, retranscription, and audio navigation use `(source_id, source_segment_no)`. `actionEvidence`, `summaryEvidence`, and knowledge-ingestion risk checks must prefer exact `segment_id` matching for `multi_source_conflict` and `multi_source_majority` when `segment_id` exists. Fall back to the source-segment key only for legacy or probe-simulated evidence without a row id, so safe actions in the same five-minute source segment are not tainted by a different conflicting row.
- `/api/mobile/meetings/join` and `/api/web/meetings/join` join by code or title. Repeated joins reuse the existing `source_id` when the same user, device name, and source label match; the same user can still register another device by using a different source label. Upload endpoints also enforce `max_sources`, so clients cannot bypass the source limit.
- `/api/mobile/meetings/discover` and `/api/web/meetings/discover` return recent, unfinished, not-full, still-processing multi-source meeting candidates. The response is metadata-only: `id/title/join_code/status/owner_name/source_count/max_sources/remaining_sources/created_at/updated_at`. Recorder and file-upload screens use it to fill a shared meeting code; it must not expose summary, transcripts, audio, action items, or member details before the user joins.
- `processing._merge_multisource_segments()` runs before final semantic refinement. Near-overlapping, similar text from different sources is merged and marked with `multi_source_merged`, `multi_source_count:*`, and `multi_source_refs:*` only when key facts agree. If sources start at different times, the server can conservatively align rows by neighboring source-local segment numbers, start-time delta, and high text similarity; those merged rows also carry `multi_source_time_aligned`. When sources contain complementary non-conflicting clauses, the server can copy those clauses from original transcript evidence into the merged row and add `multi_source_complemented`. If at least two sources agree and the agreeing-source count is larger than nearby conflicting sources, the merged row gets `multi_source_majority` as the majority-source primary result while the minority source remains `multi_source_conflict` and `speaker_review` for replay. Legacy rows that already have `multi_source_merged` plus `multi_source_count:*` but lack `multi_source_majority` are upgraded at the API/quality-report layer by `repository.with_derived_quality_flags()` without rewriting stored transcript history. Two-source key-fact conflicts, or cases without a majority, remain fully conservative; parallel turns captured by different devices remain ordinary single-source evidence, not conflicts.
- LLM semantic refinement and summarization must preserve multi-source evidence. `llm_adapters._parse_refined_segments()` carries forward `multi_source_merged`, `multi_source_count:*`, `multi_source_refs:*`, `multi_source_time_aligned`, `multi_source_complemented`, `multi_source_majority`, `multi_source_conflict`, and `speaker_review`, but it does not carry transient `semantic_partial` into final rows. The summary prompt exposes `source_id/source_segment_no` and multi-source flags to the model; facts marked `multi_source_conflict` must remain reviewable uncertainty, not a single fused conclusion.
- `qualityReport.metrics.recording_source_count`, `multi_source_merged_count`, `multi_source_majority_count`, `multi_source_complemented_count`, `multi_source_conflict_count`, and source coverage by `(source_id, source_segment_no)` support Web review and external agent gating.
- Web timeline filters, evidence jumps, and transcript save payloads must preserve `source_id`. The frontend filter key is `source_id::source_segment_no`; do not match by `source_segment_no` alone. Merged multi-source rows still count toward original source coverage through `multi_source_refs:*`.

Nearby device discovery is not implemented yet. Product flow currently uses a shared meeting code; Web can show server-side joinable meeting candidates, but this is not LAN/Bluetooth proximity discovery. Future LAN discovery or QR invites should only create or pass `join_code` and must still rely on server-side permission checks and source limits.

Transcripts are the evidence layer for enterprise knowledge platforms. The
server archives rows replaced by reprocessing or manual edits in
`transcript_segment_history`. Non-admin transcript updates cannot reduce segment
count; admin users may remove rows, but previous rows are still archived first.
Knowledge agents should use
`/api/external/meetings/{meetingId}/transcript?include_history=true` for the
evidence layer and `/api/external/meetings/{meetingId}/ontology` for the
persisted ontology graph. `ontology.py` stores entities in
`ontology_entities` and relations in `ontology_relations`. Entity types are
limited to `person`, `place`, `time`, `matter`, and `action`; relation types
prefer `responsible_for`, `due_at`, `located_at`, `scheduled_at`, `discussed`,
`related_to`, `depends_on`, and `mentioned`. The rule fallback also builds
`action -> action` `depends_on` edges from context markers such as "depends on",
"wait for", "need", or "first", for example "interface integration depends on
the test account" becomes "finish interface integration -> provide test
account" with transcript/action evidence attached. Final meeting processing
queues a `knowledge_graph` job automatically, and clients may rebuild only the
graph via `/api/web/meetings/{meetingId}/ontology/extract` without rerunning
ASR. The old `knowledgeGraph` field remains a lightweight topic graph;
`ontologyGraph` is the durable object-slot graph for people, places, times,
matters, and actions.
Knowledge agents should pull `/api/external/meetings/{meetingId}/transcript?include_history=true`
instead of reading SQLite directly.

`/segments-json` remains for compatibility and simple tests. The Android main flow no longer uses it for long meeting audio.

### ASR Adapter

The ASR adapter is in:

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

The command adapter does not execute through a shell. Add new placeholders explicitly in `_render_command`.

The remote STT adapter also lives in `asr_adapters.py`.
`transcribe_with_openai_compatible()` supports `openai-compatible`,
`remote-stt`, and `funasr` providers. It calls `/audio/transcriptions` first,
then falls back to `/asr` on 404. It normalizes `text`, `transcript`, `result`,
`data`, `segments`, `sentence_info`, and `sentences` responses, including
FunASR-style raw output nested under `data`, `result`, or `output`. Timing
fields may be `start/end`, `start_ms/end_ms`, `startMillis/endMillis`, or
`timestamp`/`timestamps` as a two-item pair or word-level pairs. Native speaker
fields may be `speaker_id`, `speaker`, `spk`, `spk_id`, or `speakerLabel`.
Empty text does not lose the meeting state; it is stored as an `empty_asr`
placeholder transcript.

### Semantic Segmentation And Speaker Inference

Server-side post-processing starts in:

```text
server/solorecord_server/processing.py
```

LLM semantic segmentation lives in:

```text
server/solorecord_server/llm_adapters.py
```

Processing order:

1. `asr_adapters.py` preserves native ASR `sentence_info`, `segments`, `timestamp`/`timestamps`, `speaker_id`, `speaker`, `spk`, `spk_id`, `speakerLabel`, and related fields when present, and marks native speaker output with `asr_speaker`.
2. `processing._needs_semantic_segmentation()` decides whether LLM refinement is needed. Multiple reliable native speaker IDs skip refinement only when there are no contextual call-outs. Long single-speaker text, multiple “name said/name:” markers, named call-outs, first-person replies, or same-topic continuations after a call-out enter refinement.
3. `llm_adapters.refine_segments_with_llm()` asks the model to return only `{"segments":[...]}`, with `source_index`, `source_id`, `source_segment_no`, `speaker`, `speaker_id`, `start_ms`, `end_ms`, `text`, `confidence`, `scenario`, and `reason`.
4. After the LLM returns, `processing._rule_refine_residual_mixed_segments()` checks whether clear mixed-person markers remain, such as “name said/name:/name please cover/name handle later”. If so, it applies a conservative second-pass split and writes `llm_residual_rule_refined` plus `speaker_review`. Even when there is only one named call-out, a same-segment reply like “I will handle it” is split into the host call-out and the called person's reply. Host preface text before the call-out, such as “let's review the agenda/background”, stays with the original speaker and carries `source_prefix_before_callout`; it must not be assigned to the first called person.
5. If the LLM is unavailable or returns invalid JSON, `processing._rule_refine_segments()` falls back to clear speaker-marker splitting. `_split_inline_addressed_response()` also handles ASR text that omits punctuation between a named call-out and a reply such as “I will handle it”. `_apply_contextual_speaker_inference()` can conservatively link first-person or same-topic continuation replies to the previously called person. It always keeps `speaker_review` and `reason:*` flags for human review.
6. Segment uploads write `semantic_partial` so users can see an in-meeting draft. The final `/finish` flow always runs full-meeting semantic post-processing and writes `semantic_final`.
7. `_insert_transcript_segments()` persists `flags`, `source_id`, and `source_segment_no`, letting Web show “needs review”, “LLM segmented”, and “rule segmented”, and letting external knowledge agents trace evidence back to source segments. Concrete manually saved names for a `speaker_id` take precedence over later generic ASR names; generic names such as `Speaker 1` do not block new model-inferred names.
8. If the LLM only splits a long row from the same native ASR speaker and keeps the same `speaker_id` with `native_speaker`, `llm_adapters._parse_refined_segments()` preserves `asr_speaker`. If the LLM changes the speaker through `context_bridge`, `dialogue_logic`, or `task_ownership`, it must not preserve `asr_speaker`; keep `speaker_review` so reviewers know the attribution is contextual.
9. If the LLM splits one multi-source merged row into shorter turns, every derived row must still inherit `multi_source_refs:*`; otherwise `sourceCoverage` may falsely report missing original audio segments. Rows with `multi_source_conflict` must keep the conflict or `speaker_review` flag after LLM refinement so Web and external knowledge agents can block automatic ingestion.

Quality checks:

- `repository.build_quality_report()` detects single-speaker meetings, long transcript rows, speaker-review rows, speakers that lack source evidence, generic action owners, over-concentrated owners, candidate people that are not represented as speakers, and action items that lack transcript evidence.
- `speaker_evidence_weak_count` catches cases where the model turns topics, time phrases, or misheard words into apparent names. `llm_adapters._parse_refined_segments()` lowers confidence and writes `speaker_review` plus `speaker_evidence_weak` flags for these rows.
- `speaker_alias_conflict_count` catches one `display_name` mapped to multiple `speaker_id` values. The knowledge graph merges non-generic display names into one person node and keeps `speaker_ids` for traceability.
- `knowledgeGraph` now includes `topic` nodes. The server extracts lightweight business topics from transcripts and action items, then links speakers to topics, topics to actions, and actions to due dates. Topic-node `evidence` keeps `segment_id`, `source_id`, `source_segment_no`, `start_ms`, `end_ms`, and the transcript snippet. Topic nodes are an auxiliary context layer, not a replacement for transcript evidence.
- `unsupported_action_count` and `action_evidence_coverage` help catch hallucinated action items. Matching uses Chinese 2-4 character ngrams, English tokens, and owner hints, so it is tolerant of wording changes but still grounded in the transcript. Newly generated LLM actions with `unsupported` evidence are removed before saving. If every generated action is unsupported, the server keeps one transcript-referenced review action as a human-review entry point, not as an auto-reminder item. When no LLM is available but ASR produced real transcript text, `processing._summarize()` saves the conservative summary and returns no actions; `_llm_unavailable_fallback_actions()` creates the "check transcript result" reminder only for `mock_asr`, `empty_asr`, or `missing_audio` placeholder rows. These review entries should appear as `status=system_review`, `action_kind=system_review`, `auto_actionable=false`, and `reminder_safe=false` in `qualityReport.actionEvidence`, and as camelCase `actionKind`, `autoActionable`, and `reminderSafe` in `actionItems`. They do not count toward generic-owner risk, unsupported-action risk, or action-evidence coverage. User-edited action items are not silently deleted; they remain visible with quality-report evidence risk. Once an action is classified as `unsupported`, do not also include it in `weakActionOwners`; the UI should show one clear missing-evidence risk instead of two overlapping risks.
- If an action owner is a pronoun such as “I”, “we”, “he”, “this side”, or “everyone”, `processing._normalize_action_owners()` first tries to infer the real speaker from first-person transcript evidence and task keywords. If it cannot, the owner is downgraded to `待确认`; `repository._is_generic_owner()` treats any remaining pronoun owner as generic, and `qualityReport.actionEvidence` should mark the item as `weak_owner` rather than `supported`.
- If the LLM returns a generic action owner such as "owner", "related owner", "host", "frontend developer", or a label ending with "owner", `llm_adapters._normalize_owner()` first downgrades it to `待确认`. `processing._normalize_action_owners()` may then restore a concrete owner only when transcript evidence supports a person, team, or assignment. Clear organizational owners such as sales, legal, or frontend may still be preserved.
- Date and deadline phrases are time facts only, not speakers or owners. Rule segmentation, LLM named-person extraction, and action-owner attribution filter candidates such as "this afternoon", "afternoon", "before Wednesday", and "by month end" so they do not pollute the speaker or action-owner lists. Historical time-like owners should be reported as generic owners and require human review.
- Named-callout speaker attribution requires evidence: a first-person response, task commitment, same-topic keyword continuation, or explicit speaker prefix. Do not treat an ASR `speaker_id` change after a callout as enough evidence by itself; transition lines such as "okay, let's continue to the next topic" should keep the original ASR speaker.
- Action-owner attribution may use topic words from a named callout. For example, if the host says "Yitian, talk about automated testing" and a later anonymous segment continues with "coverage scripts will be finished tomorrow", `processing._normalize_action_owners()` and `repository._suggest_action_owner()` should prefer Yitian and must not assign the task to the host just because the host said the callout. The quality report should also work before a coarse row is split: if the row speaker is still the host or a generic speaker label, a matching callout window may produce `suggested_owner`, while topic nouns such as stage audio, automated testing, test coverage, or data source must still be filtered out as owners.
- Organizational roles such as sales, legal, frontend, and QA may be action owners, but only when the same short phrase contains an explicit assignment or action, such as "sales follows up by Friday" or "frontend updates the page by Wednesday". Task phrases such as automated testing, test coverage, or data source must not be treated as team owners by themselves.
- `qualityReport.actionEvidence` can report `supported`, `majority`, `system_review`, `conflict`, `contradiction`, `weak_owner`, or `unsupported`. `majority` means the action is grounded in a `multi_source_majority` primary row and the owner is not generic or unknown, so `knowledgeSafe=true` while `requiresReview=true`; downstream reminder agents may use it as primary evidence while preserving the replay hint. `system_review` means the row is only a human-review entry; keep `autoActionable=false`, `reminderSafe=false`, and `knowledgeSafe=false`, and skip it when copying or syncing reminders. Android local records and Markdown/Word/PDF/JSON exports must keep the system-review label so users do not mistake it for a normal meeting task. `conflict` means the action is only backed by `multi_source_conflict` rows; downstream reminder agents must require human replay and must not send reminders or store the action as confirmed knowledge automatically. `contradiction` means the action turns same-topic transcript blockers such as "do not send yet", "pause", or "cannot publish" into an executable task; it is a hard ingestion blocker and must stay `knowledgeSafe=false`. Review tasks such as "confirm whether to send" should not be treated as contradictory send commands. If the owner is unknown, a pronoun, a time phrase, or a generic role, `weak_owner` takes precedence even when the task text has majority-source evidence. Evidence references must include `segment_id`, `source_id`, and `source_segment_no`. `qualityReport.actionEvidence` can also include `suggested_owner`, `suggested_owner_reason`, and `suggested_owner_evidence` when another speaker is better supported by task keywords and assignment wording. `actionItems` also carries camelCase `evidenceStatus`, `evidence`, `suggestedOwner`, `actionKind`, `autoActionable`, `reminderSafe`, `knowledgeSafe`, and `requiresReview` fields for downstream action agents that only consume the action list. Web shows an "apply suggestion" button, but users still save the action list explicitly.
- For `actionEvidence` and `summaryEvidence`, evidence with a `segment_id` inherits conflict or majority status only from that exact transcript row. Do not mark it as `conflict` merely because another row in the same `source_id/source_segment_no` is conflicting; a five-minute source segment can contain multiple unrelated topics.
- `qualityReport.sourceCoverage` checks effective transcript coverage for every audio segment by `(source_id, source_segment_no)`. `mock_asr`, `empty_asr`, `missing_audio`, and `source_coverage_gap` are review placeholders, not effective coverage. Final `/finish` may add a `source_coverage_gap` + `missing_audio` "system review" transcript row when an uploaded audio segment has no transcript row at all; this keeps the segment locatable while still blocking knowledge ingestion. Placeholder rows must only feed coverage, review navigation, and ingestion blocking; they must not feed `speakerEvidence`, candidate people, summary evidence, action evidence, speaker counts, LLM/rule segment counts, or `knowledgeGraph` topic extraction. If an empty-speech placeholder already exists, do not add a duplicate review row.
- LLM prompts must tell the model not to turn pause/blocker language into executable actions, and `processing._grounded_summary_result()` must drop contradictory executable action items before saving generated summaries. It must also drop newly generated unsupported actions before saving. If every generated action is contradictory or unsupported, keep a transcript-referenced review fallback action instead of saving unsafe reminders.
- Condition phrases such as "wait for legal approval before sending" are prerequisites, not owner assignments. Keep tests for both sides: do not infer legal as owner from the condition phrase, but still infer legal from explicit assignments such as "legal approves the contract attachment".
- `qualityReport.multiSourceConflicts` lists concrete multi-source conflict rows with `segment_id`, `source_id`, `source_segment_no`, speaker, time range, text, flags, and nearby conflicting source snippets. The Web quality panel renders this list with "jump to transcript" links. External knowledge agents should use this field as the replay checklist instead of relying only on `multi_source_conflict_count`.
- `knowledgeReadiness.reviewEvidence` extracts the most important review targets from the quality report: `multiSourceConflicts`, `sourceCoverageWeakSegments`, `speakerEvidence`, `speakerAliasConflicts`, `summaryClaims`, and `actionEvidence`. It is the review entry point for the ingestion gate, not a replacement fact source for the transcript. The Web quality panel renders a "knowledge ingestion review" block with `ready/review_first/hold`, blockers, review tags, notes, and jumpable evidence rows. Weak coverage rows may have no transcript target yet, so the UI should ask users to replay or re-transcribe instead of pretending a transcript row exists.
- `processing._grounded_summary_result()` checks the LLM summary against transcript evidence before saving it and applies stronger `qualityReport.actionEvidence[].suggested_owner` values to clearly weak generated owners. If summary evidence coverage is too low, any summary claim lacks transcript evidence, a multi-source conflict is written as a definite conclusion without review language, or the summary reverses transcript completion/negation evidence, the server replaces it with a conservative transcript-grounded summary. When that fallback references `multi_source_conflict` rows, both summary and role notes must keep explicit review wording such as "multi-source conflict pending confirmation" so `summary_unqualified_conflict_count` stays 0. Default saved output should be plain but grounded, not polished but hallucinated.
- `summaryEvidence.supportedClaims` lists grounded summary or role-note claims with transcript references. Each supported claim carries `status`: `supported` for ordinary transcript evidence, `majority` for a majority-source primary row with a replay-review hint, `conflict` when the claim is only supported by multi-source conflict rows and must keep review language, and `contradiction` when same-topic evidence reverses completion/negation. `contradictedClaims` lists those hard-blocked claims separately, and `unsupportedClaims` lists unsupported claims only.
- When changing LLM action extraction, keep tests for supported, weak-owner, suggested-owner, unsupported, contradictory, and review-question action evidence.
- Use `python -m solorecord_server.quality_probe --meeting-id <meeting_id> --postprocess` before calling a paid or remote LLM. The `postprocess.delta` block compares persisted quality with simulated local post-processing, including mixed-marker reduction, speaker-count changes, issue changes, concrete `action_owner_changes`, remaining `suggested_owner_changes`, and simulated `source_gap_review_segment_count` for missing audio-segment coverage. `--run-llm` adds the same delta under `llm.delta` after simulated LLM refinement and summary extraction. Both modes are read-only.

Notes:

- The segment-upload path `process_uploaded_segment()` runs local post-processing first so users get immediate feedback, marked with `semantic_partial`.
- The final `/finish` flow runs full-meeting context post-processing and writes the final timeline back to the database, marked with `semantic_final`. This repairs context broken by five-minute chunks, especially when one chunk names a person and a later chunk contains the deliverable or deadline.
- New rules must preserve original facts; limit them to splitting, speaker/display-name normalization, and obvious prefix removal.
- For a true diarization sidecar, prefer standard `segments` JSON output instead of coupling model runtime into the FastAPI process.

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

Windows desktop client:

```powershell
cd clients\desktop
npm install
$env:SOLO_SERVER_URL="http://127.0.0.1:8000"
npm run pack
npm run portable:win
```

Validate that `clients/desktop/dist/win-unpacked/SoloRecord.exe` starts. The NSIS EXE target requires Windows symlink privileges for electron-builder's winCodeSign extraction. If that is unavailable, publish the portable ZIP.

iOS, macOS, and HarmonyOS signed packages require Xcode or DevEco Studio build machines. Source projects live in `clients/ios`, `clients/macos`, and `clients/harmony`.

### Test Coverage

`server/tests/test_api.py` covers login, meeting create, audio upload, finish/process, transcript fetch, speaker rename, Markdown export, multi-platform release publishing, mobile sync, external API token access, and protected server audio download.

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

- Do not put real ASR/LLM/SSO/Hermes secrets into APK, EXE, DMG, IPA, or HAP packages.
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
