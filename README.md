# SoloRecord

SoloRecord 是公司内部会议记录系统，用来通过 Android App 可靠录音，并由服务器生成和保存：

- 分角色转写文本
- 分角色会议记录
- 会议纪要
- 待办事项
- 对 Hermes Agent、OpenClaw Agent、企业微信云文档、飞书云文档等外部系统的推送

## 当前版本：V0.7

这是面向公司内部使用的一体化会议记录系统，当前发布版为 V0.7，包含 Android App、服务端网关、Web 管理/PC 端，以及 Windows/macOS/iOS/HarmonyOS 终端外壳工程。

- Android App：LDAP 登录、可选统一登录跳转与回跳、连续 WAV 滚动分段录音、约 2 秒分段重叠、本地记录、本地播放、分段自动上传、重装后恢复服务器记录、查看转写/纪要/待办、批量修改角色名。
- 服务端：登录会话、会议/音频/转写/转写历史/角色/纪要/待办、ASR/LLM 配置、导出、多平台终端发布下载、Hermes/Webhook 转发、外部知识平台读取接口。
- Web 端：PC 实时录音、PC 上传录音、会议查看编辑、角色重命名、导出、模型配置、任务管理、多平台终端发布。
- 多平台客户端：Windows Electron 可运行包，macOS Electron/SwiftUI 外壳，iOS WKWebView 外壳，HarmonyOS Web 外壳。iOS/macOS/HarmonyOS 签名安装包需在对应官方构建机生成。
- 模型密钥保存在服务端，APK 默认只需要服务器地址和短期会话 token。
- 转写是企业知识整理的原始证据层，当前版本和历史归档都持久化在服务端；非 admin 不能删除转写段，知识平台 Agent 通过外部 API 拉取。

## 文档入口

按读者分：

- 运维/部署/排障：[docs/human-ops/README.md](docs/human-ops/README.md)
- 开发/二次开发/API：[docs/human-dev/README.md](docs/human-dev/README.md)
- 普通使用者：[docs/user/README.md](docs/user/README.md)
- 智能体维护：[AGENTS.md](AGENTS.md)、[docs/agents/README.md](docs/agents/README.md)、[llms.txt](llms.txt)

背景资料：

- 完整 PRD：[docs/meeting-app-prd-v2.md](docs/meeting-app-prd-v2.md)
- 数据存储与 ES：[docs/data-storage-and-es.md](docs/data-storage-and-es.md)
- 本地 ASR 流水线：[docs/local-asr-pipeline.md](docs/local-asr-pipeline.md)
- 群晖 SSO 与 ASR 架构：[docs/synology-bailian-architecture.md](docs/synology-bailian-architecture.md)
- 开源调研：[docs/open-source-research.md](docs/open-source-research.md)
- 安全审计：[docs/security-audit.md](docs/security-audit.md)
- 用户体验审计：[docs/ux-review-v0.7.md](docs/ux-review-v0.7.md)
- 用户故事线与体验验收：[docs/ux-user-story-acceptance.md](docs/ux-user-story-acceptance.md)
- UI/UE 设计系统：[docs/ui-ue-design-system.md](docs/ui-ue-design-system.md)
- 多终端客户端：[docs/multi-platform-clients.md](docs/multi-platform-clients.md)
- V0.7 发布说明：[docs/release-v0.7.md](docs/release-v0.7.md)

## 打开方式

1. 用 Android Studio 打开本目录。
2. 等待 Android Studio 下载 Gradle 插件和 Android SDK 依赖。
3. 运行 `app` 到安卓手机或模拟器。

本机已验证 `assembleDebug` 可以通过。调试 APK 输出位置：

```text
app/build/outputs/apk/debug/app-debug.apk
```

## 一体化系统运行

服务端和 Web 管理端已经放在 `server/` 下，默认使用 SQLite 和本地文件存储，方便明天先部署跑通闭环：

```powershell
scripts\run-server.ps1
```

打开：

```text
http://127.0.0.1:8000
```

演示管理员账号可用 `admin@example.com` 登录。正式部署前请按 `docs/deployment.md` 配置 LDAP、密钥、HTTPS、ASR Provider 和 APK 发布。

当前已验证：

- 服务端主流程测试通过
- API/Web smoke 测试通过
- Android `assembleDebug` 通过，包含滚动录音改动
- Windows Electron `win-unpacked/SoloRecord.exe` 启动 smoke 通过，portable ZIP 已生成
- APK 输出：`app/build/outputs/apk/debug/app-debug.apk`

## 接口约定

转写接口、纪要接口、推送接口均使用 HTTP JSON。默认采用 OpenAI-compatible Chat Completions 风格的大模型请求；若厂商协议不同，可以在 `app/src/main/java/com/solorecord/net` 下替换对应客户端。

详细协议见：

- `docs/meeting-app-prd-v2.md`（完整 PRD，文件名沿用原版本名）
- `docs/integration-contract.md`
- `docs/synology-bailian-architecture.md`
- `docs/local-asr-pipeline.md`
- `docs/open-source-research.md`
- `docs/data-storage-and-es.md`
- `docs/roadmap.md`
- `docs/deployment.md`
- `docs/security-audit.md`

## 群晖 SSO 与百炼 Qwen ASR 结论

面向正式分发的 APK，不建议把百炼/DashScope Key、LLM Key、群晖 OIDC Client Secret 或 Hermes 工作区凭证写进 APK。APK 反编译后这些值有泄露风险。

推荐模式是：APK 只配置你自己的网关地址；网关负责群晖 LDAP/SSO 登录校验、保存百炼 Key、保存大模型 Key、调用 `qwen3-asr-flash-filetrans`、生成纪要、转发到销售工作区。

`qwen3-asr-flash-filetrans` 的“离线转写”是云端长音频文件转写，不是手机本地无网转写。它通常需要先把音频放到公网可访问地址，再提交异步任务、轮询任务状态、下载临时转写结果。因此只给 APK 配 URL、Key 和 Model ID 可以做短音频原型，但不适合作为正式长会议录音方案。

如果采用自建本地 ASR，推荐 APK 仍然只负责可靠录音、滚动分段、本地播放和网络恢复后上传；本地网关/ASR 服务负责格式统一、VAD、质量检测、可选轻量降噪/去混响、可选说话人分离、ASR、纪要整理和转发。这样录音稳定性最好，也方便后续替换模型。

## 使用流程

1. 用户在 App 登录。
2. 点击“开始录音”，授权麦克风权限。
3. 录音期间 App 连续采集音频并按服务器配置的时长滚动保存，默认约 5 分钟一段；相邻分段保留约 2 秒重叠，降低边界丢词风险。
4. 在线时，每个分段完成后会自动上传并触发一次分段转写，阶段结果持续写回同一条会议记录。
5. 点击“结束录音”后，最后一段也会保存并上传，然后服务端对整场会议生成完整转写、纪要、待办、外部系统转发和可选 ES/OpenSearch 索引。
6. 网络不稳定时，同步采用分段级断点续传；已上传分段会在本地账本中标记，下次只补传未完成分段。
7. 用户在 App、Web 或桌面客户端查看转写、纪要、待办，也可以改说话人名称、下载播放服务器音频和导出文件。

Windows、macOS、iOS、HarmonyOS 终端共享服务器 Web 体验。Android 仍是长会议最可靠的采集端；桌面和 WebView 端可直接录音或补传文件，录音能力取决于系统 WebView/浏览器麦克风权限。

APK 体积较小是预期现象：它不内置 ASR/LLM 模型和三方重 SDK，只负责登录、录音、分段落盘、文件流式上传、播放和展示。当前上传边界默认是 5 分钟左右一个音频分段，可由服务端配置；如果网络中断，最多重传当前未确认分段，而不是整场会议。

## App 预配置

APK 正式分发时只建议预配置服务器地址，不预置任何 token/key：

```properties
SOLO_SERVER_ENDPOINT=https://record.example.com
```

如果构建时没有传入 `SOLO_SERVER_ENDPOINT`，App 首次打开会在“登录状态”页要求填写服务器地址；填写后使用 LDAP 用户名密码登录。GitHub 公开 Release 附带的 APK 不包含真实服务器地址和密钥，适合初装/联调；公司正式分发时，建议用实际域名重新构建后上传到服务器 Web 管理端的“发布 APK”。

ASR、LLM、LDAP、SSO、Hermes、ES 等密钥都放在服务器 `server/.env` 或 Web 管理页，不写进 APK。

Android 默认通过服务端 LDAP 登录接口换取短期 SoloRecord 会话 token。可选浏览器统一登录仍保留：

```text
https://record.example.com/api/auth/sso/start?redirect_after=solorecord://auth/callback
```

浏览器登录完成后服务端会回跳 `solorecord://auth/callback`，APK 只保存服务端短期会话 token。

构建可预配置服务器地址的 APK：

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug -PSOLO_SERVER_ENDPOINT=https://record.example.com
```

构建产物：

```text
app/build/outputs/apk/debug/app-debug.apk
```

## ASR 接入

Web 管理页选择 `command` 后，可接入任何本地 ASR 脚本/二进制，只要它向 stdout 输出标准 JSON：

```text
python /opt/solorecord-asr/run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
```

如果自建 ASR 已经提供 OpenAI 兼容 HTTP 服务，可以在 Web 管理页选择 `openai-compatible` 或 `funasr`，并在服务器端配置 Endpoint、API Key 和 Model。服务端优先调用 `/audio/transcriptions`，必要时回退尝试 `/asr`；空语音会保留可追踪占位转写，避免会议记录变成不可用。

ASR 返回原生说话人字段时，服务端会优先使用；如果只返回单段文本、单一发言人，或虽有多个原始 speaker 但文本中出现点名和承接回应，服务端会再调用配置好的 LLM 做语义重分段和发言人推断。分段上传后的阶段结果标记为 `semantic_partial`，结束会议后服务端会基于整场上下文再生成标记为 `semantic_final` 的最终时间线，避免 5 分钟分片割裂“点名、回应、交付物、截止时间”之间的关系。LLM 不可用时会用规则兜底拆分“张三说”“李四：”，并保守处理“翼天你先说”后接“我这边负责”，包括 ASR 没有在点名句和回应句之间加标点的场景，以及被点名议题后续继续围绕同一交付物、时间节点展开的上下文归属。Web 时间线会显示“需确认”“大模型分段”“规则分段”等校对提示；需要校对的行会展示推断依据和相邻上下文。整理质量区会显示发言人证据风险、纪要证据率、待办证据率和待办归属风险；纪要区会列出“纪要有依据”的引用片段、“纪要与原文相反”的高风险结论和“纪要待核对”的缺证据结论。`summaryEvidence.status=contradiction` 会阻断知识入库，并触发服务端把 LLM 纪要降级为“基于转写原文的保守整理”。如果保守整理引用了 `multi_source_conflict` 片段，摘要和分角色整理会自动写入“多源冲突待确认”，让用户和知识平台明确这是回听复核项，不是确定结论。待办区会逐条显示“有转写依据/多数源确认/系统复核提醒/多源冲突待核对/负责人证据弱/待办与原文相反/缺转写证据”。`actionEvidence.status=contradiction` 用于拦截把“先不要发、暂缓、不能上线”等原文反写成执行待办的情况，此时 `knowledgeSafe=false` 且知识入库为 `hold`；“确认是否发送”这类核对型待办不会被当成执行发送。LLM 新生成的待办若完全缺少转写证据，会在保存前被移除；如果全部生成待办都缺证据，系统会保留一条带原文片段的“按转写原文复核待办”，提示人工检查而不是自动督办。若 LLM 没有配置但 ASR 已产生真实转写，服务端只生成保守纪要，不会凭空创建“检查转写结果”类系统待办；只有 `mock_asr`、`empty_asr` 或 `missing_audio` 这类占位转写才会保留复核提醒。这两类复核入口在 API 中会标记为 `evidenceStatus=system_review`、`actionKind=system_review`、`autoActionable=false`、`reminderSafe=false`，Web 复制待办时会跳过，外部督办系统不得自动发送。用户手工或历史遗留的缺证据待办会集中标成 `unsupported`，不会再额外重复报“负责人证据弱”。多数源证据只能增强任务文本可信度；如果负责人仍是 `待确认`、代词、时间短语或泛化角色，待办仍会优先标记为 `weak_owner`、`knowledgeSafe=false`，并给出可人工应用的 `suggestedOwner`。即使当前转写还没拆开、说话人仍是主持人或“发言人 1”，系统也会从“翼天你说自动测试”“围城你那个部分讲数据源”等点名句里生成建议负责人；但会过滤“舞台音响、自动测试、数据源”等议题短语，避免把任务词当成人。用户手动把某个发言人改成具体人名后，后续同一 `speaker_id` 会优先保留人工校正；普通 `发言人 N` 泛化旧名不会阻止模型识别新名字。

系统复核提醒不是会议待办。Web 复制待办、Android 离线记录页和 Markdown/Word/PDF/JSON 导出都会保留“系统复核提醒”标记；外部督办系统必须同时检查 `actionKind=system_review`、`autoActionable=false` 和 `reminderSafe=false`，并跳过自动提醒。

复核占位转写不是会议事实。`mock_asr`、`empty_asr`、`missing_audio` 和 `source_coverage_gap` 行只用于定位需要回听或重转写的音频分段，并阻断自动入库；它们不会进入发言人统计、人物校对证据、纪要证据、待办证据或知识图谱主题。

语义重分段会把每个模型输出段继续关联回 `source_index`/`source_segment_no`，所以 UI、导出和外部知识平台都能追溯到原始音频分段。如果 LLM 只是把同一个 ASR 原生 speaker 的长段拆成多段，并且仍使用同一个 `speaker_id` 与 `native_speaker` 场景，最终段会保留 `asr_speaker`，表示它仍来自 ASR 原生说话人证据。通过上下文、任务归属或议题延续推断出的发言人会保留 `speaker_review`、`scenario:*` 和 `reason:*` 标记，但不会伪装成 `asr_speaker`；这表示“可用的会议上下文推断”，不是声纹确认。若 ASR 已经返回多个原生 speaker，但仍存在“李波后面看登录界面”“围城负责外接数据源”等未落到具体人物的线索，服务端也会触发语义后处理，而不是简单相信 ASR 粗分段。

多源同录会在最终整理前做保守校对：不同录音源同一时间窗里文本高度相近且关键事实一致时合并并标记 `multi_source_merged`；两个及以上来源一致且没有被附近冲突压过时，同时标记 `multi_source_majority`，在 Web 质量区和外部 API 中显示为多数源确认。历史会议中已经存在 `multi_source_merged` 和 `multi_source_count:*` 但缺少 `multi_source_majority` 的旧行，服务端会在返回层派生这个可信标记，不需要重处理音频或改写数据库审计历史。如果某台设备晚几十秒开始录音，服务端还会结合该设备自己的分段号、时间差和文本相似度做错峰对齐，合并后额外标记 `multi_source_time_aligned`，避免把同一段发言重复展示。若多个来源各自漏掉不同短语，服务端可把来自原始转写的短语补到同一条证据里，并标记 `multi_source_complemented`；这不是模型编写新内容，而是多源证据互补。若时间、数量或负责人等关键事实冲突，例如一个源听成“周三三类”、另一个源听成“周五五类”，系统会保留两条证据并标记 `multi_source_conflict` 和 `speaker_review`，交给用户回听确认，不会为了去重抹掉冲突。

详见 `docs/deployment.md` 的 Local ASR Command Adapter。

## 公开仓库边界

本仓库可以公开共享源码和文档，但不能提交任何公司真实密钥、SSO secret、模型 key、Hermes token、ES 凭证、`server/.env`、运行数据、数据库、缓存、APK 构建产物或客户会议音频。生产部署仍按公司内部系统管理，外部访问由 HTTPS、SSO、服务器权限和内部网络策略控制。

## English

SoloRecord is an internal company meeting recorder. V0.7 is the first deployable release and includes an Android app, FastAPI server, Web admin/PC UI, Windows/macOS/iOS/HarmonyOS client shells, documentation, and verification scripts.

### What V0.7 Includes

- Android app: LDAP login, optional SSO login handoff, continuous WAV rolling recording with about two seconds of overlap between adjacent segments, local records, playback, segment auto-upload, server record recovery after reinstall, transcript/summary/action-item viewing, and batch speaker rename.
- Server: login sessions, meetings, audio segments, transcripts, speaker names, summaries, action items, ASR/LLM configuration, exports, multi-platform client publishing, Hermes/Webhook forwarding, external API, and optional ES/OpenSearch indexing.
- Transcript persistence: current transcript rows and archived history are stored server-side; non-admin users cannot delete transcript segments, and enterprise knowledge agents read transcript evidence through the external API.
- Web app: PC live recording, file upload, meeting review/editing, transcript editing, speaker rename, exports, model configuration, job management, and multi-platform client publishing.
- Multi-platform clients: Windows Electron package, macOS Electron/SwiftUI shell, iOS WKWebView shell, and HarmonyOS Web shell. Signed iOS/macOS/HarmonyOS packages require their official build machines.
- Secrets are stored server-side. The APK only needs the server endpoint and a short-lived session token.
- The public GitHub Release APK contains no real server URL or secret. Users can enter the server URL on first run; for company distribution, rebuild with `-PSOLO_SERVER_ENDPOINT=https://record.example.com` and publish that APK from the server Web admin.
- The Android app records to local rolling audio files first and uses segment-level resume for upload. Confirmed segments are skipped on retry; only pending segments are uploaded again. While online, each completed segment is uploaded and transcribed into the same meeting record before final summary processing.
- Review-only `system_review` action rows are labelled as system review reminders in Web, Android local records, and Markdown/Word/PDF/JSON exports; reminder agents must skip them because `autoActionable=false` and `reminderSafe=false`.

### Quick Start

Run the server:

```powershell
scripts\run-server.ps1
```

Open:

```text
http://127.0.0.1:8000
```

Build the Android debug APK:

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug
```

### Documentation

- Operations: [docs/human-ops/README.md](docs/human-ops/README.md)
- Development: [docs/human-dev/README.md](docs/human-dev/README.md)
- User manual: [docs/user/README.md](docs/user/README.md)
- Agent maintenance: [AGENTS.md](AGENTS.md), [docs/agents/README.md](docs/agents/README.md), [llms.txt](llms.txt)
- UX review: [docs/ux-review-v0.7.md](docs/ux-review-v0.7.md)
- User story acceptance: [docs/ux-user-story-acceptance.md](docs/ux-user-story-acceptance.md)
- UI/UE design system: [docs/ui-ue-design-system.md](docs/ui-ue-design-system.md)
- Multi-platform clients: [docs/multi-platform-clients.md](docs/multi-platform-clients.md)
- Release notes: [docs/release-v0.7.md](docs/release-v0.7.md)

### ASR Integration

After selecting `command` on the Web admin provider page, SoloRecord can call any local ASR script or binary as long as it prints standard JSON to stdout:

```text
python /opt/solorecord-asr/run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
```

If your self-hosted ASR is exposed through an OpenAI-compatible HTTP service,
select `openai-compatible` or `funasr` and configure endpoint, API key, and
model on the server. The server first calls `/audio/transcriptions`, then
falls back to `/asr` when needed. Empty-speech results are kept as traceable
placeholder transcript rows so the meeting remains usable, but placeholder
rows do not count as effective source-segment coverage.

When ASR returns native speaker fields, the server uses them directly. If ASR
returns only plain text, a single speaker, long native-speaker chunks, or
contextual call-outs such as “Alice, please cover tests” followed by a
topic-continuation reply, the configured LLM performs semantic re-segmentation
and speaker inference. If the LLM is unavailable, a rule fallback still splits
clear markers such as “Alice said” or “Bob:” and conservatively handles named
call-outs followed by first-person or same-topic replies, including ASR output
that does not insert punctuation between the call-out and the reply. When the
LLM only splits a long native ASR-speaker row and keeps the same `speaker_id`
with `scenario=native_speaker`, derived rows keep `asr_speaker` as native ASR
evidence. Contextual attribution, task ownership, or topic continuation keeps
`speaker_review`, `scenario:*`, and `reason:*`, but does not pretend to be
`asr_speaker`; these inferences are review hints, not voiceprint confirmation.
The Web timeline surfaces “needs review”, “LLM segmented”, and “rule
segmented” review hints.
The quality panel also shows speaker-evidence risk, same-name speaker-label
conflicts, action evidence coverage, and a lightweight people-topic-action-time
graph, so weakly supported names or action items can be reviewed before they
are shared or indexed by downstream knowledge agents. Majority-source evidence
only strengthens the task text; if the owner is still unknown, a pronoun, or a
generic role, the action stays `weak_owner` with `knowledgeSafe=false` and may
carry a `suggestedOwner` for human review.
Summary evidence also flags `contradiction` when a summary or role-note claim
matches transcript text on the same topic but reverses completion or negation,
for example writing "sent" when the transcript says "do not send yet". This is
a hard knowledge-ingestion blocker and causes generated summaries to fall back
to the conservative transcript-grounded version. If that fallback cites
multi-source conflict rows, it keeps explicit "multi-source conflict pending
confirmation" wording in the summary and role notes so downstream knowledge
agents do not store the conflict as a confirmed fact.
Action evidence can also be `contradiction` when an action item turns
transcript blockers such as "do not send yet", "pause", or "cannot publish"
into an executable task. These action items are not knowledge-safe, block
automatic ingestion, and must be rewritten or removed from the transcript
evidence before downstream reminder agents use them. Review tasks such as
"confirm whether to send" are treated as review work, not as contradictory send
commands.
The summary prompt asks the LLM to preserve pause/review semantics, and the
server also removes contradictory executable action items before saving
generated summaries. Short condition phrases such as "wait for legal approval"
are treated as prerequisites, not owner assignments; organizational owners such
as legal, sales, frontend, and QA are used only when the same short phrase
contains an explicit action or responsibility.
Newly generated LLM action items that have no transcript evidence are also
removed before saving. If every generated action is unsupported, the server
keeps one transcript-referenced review action so users know to inspect the
source text, while downstream reminder agents still see it as non-actionable.
If the LLM is unavailable but ASR has produced real transcript text, the server
keeps the conservative summary and saves no synthetic review action. The
"check transcript result" review action is reserved for placeholder rows such
as `mock_asr`, `empty_asr`, or `missing_audio`.
Fallback review entries are exposed as `evidenceStatus=system_review`,
`actionKind=system_review`, `autoActionable=false`, and `reminderSafe=false`.
The Web copy action skips them, and downstream reminder agents must not send
them as meeting action items.
User-edited or historical unsupported actions are reported as `unsupported`
only, not double-counted as weak-owner evidence. Named call-outs can still
produce `suggestedOwner` before the transcript is fully split, even when the
current row speaker is a host or generic “Speaker 1”; topic nouns such as stage
audio, automated testing, or data source are filtered so they do not become
owners.

For multi-source recording, final processing merges near-overlapping text from
different sources only when the key facts agree. If one device starts tens of
seconds late, the server can also align evidence by the source-local segment
number, start-time delta, and text similarity; these rows are marked with
`multi_source_time_aligned` in addition to `multi_source_merged`. If at least
two sources agree and nearby conflicts do not outnumber them, the merged row is
also marked `multi_source_majority`. Legacy rows with `multi_source_merged` and
`multi_source_count:*` but no majority flag are treated as majority-supported in
API and quality-report responses without rewriting audited transcript rows. If sources
capture complementary non-conflicting phrases, the server can add those phrases
from the original transcripts into one evidence row and mark
`multi_source_complemented`; this is source-evidence fusion, not new LLM-written
content. If sources disagree on dates, amounts, or owners, SoloRecord keeps both
rows and marks `multi_source_conflict` plus `speaker_review` so a human can
replay the evidence.

See `docs/deployment.md` for the Local ASR Command Adapter details.

### Public Repository Boundary

The source code and documentation can be shared in a public repository, but real company secrets, LDAP details, SSO client secrets, model keys, Hermes tokens, ES credentials, `server/.env`, runtime data, databases, caches, APK build outputs, and customer meeting audio must never be committed. Production deployments remain internal systems protected by HTTPS, LDAP/SSO, server-side authorization, and internal network policy.

### Production Notes

Before production, change `SOLO_SECRET_KEY`, disable demo login, configure HTTPS and Synology LDAP, connect the local ASR/LLM providers, configure backups, publish the APK through the server, and verify that no secrets or runtime data are present in the public repository.
