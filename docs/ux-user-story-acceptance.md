# SoloRecord 用户故事线与体验验收

## 中文

本文把 SoloRecord 按“真实使用者的一天”重新梳理，目标是达到主流会议记录系统的基础体验水位：录音可信、弱网可恢复、转写可校对、说话人可修正、纪要和待办可落地、数据能被企业知识平台读取。

## 体验基准

调研参考包括 Otter、Fireflies、Microsoft Teams Intelligent Recap、Zoom AI Companion、Notta、Fathom、Granola、Plaud 等。它们的共同体验不是单纯“把录音变成文字”，而是完整闭环：

| 能力 | 主流产品做法 | SoloRecord 落地要求 |
| --- | --- | --- |
| 会议中信任感 | 明确录音状态、时长、同步进度 | 录音页必须显示录音中、本地已保存、分段上传状态 |
| 时间线回看 | 按时间、说话人、章节回查 | 详情页必须保留转写时间线、音频分段和来源分段 |
| 多源证据 | 重复来源去重但保留分歧 | 使用 `(source_id, source_segment_no)`，支持保守错峰对齐，关键事实冲突保留复核 |
| 说话人修正 | 识别错了可手动改名并批量应用 | 同一 speaker id 改名后全场同步 |
| 行动项 | 会议后抽取 owner、task、due、status | Web 可编辑待办，服务端持久化并可同步 |
| 原文证据 | 摘要能追到转写和时间点 | 导出和外部 API 必须包含转写段和时间戳 |
| 弱网恢复 | 不要求重传整场会议 | 分段级断点续传，待上传分段清晰可见 |
| 企业治理 | 权限、审计、可外部读取 | 服务端为权威源，外部系统走 API，ES 仅作索引 |

参考资料：

- Otter: https://help.otter.ai/hc/en-us/articles/360047872833-Otter-ai-features
- Fireflies: https://fireflies.ai/
- Microsoft Teams Intelligent Recap: https://learn.microsoft.com/microsoftteams/intelligent-recap-calls-meetings
- Zoom AI Companion: https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0058013

## 用户故事线

### 1. 首次打开与登录

用户期望：

- 能确认自己连到正确服务器。
- 只输入公司账号密码，不接触模型 key、token 或 LDAP 技术细节。

系统要求：

- App 和 Web 未登录时阻止录音、记录、下载等敏感入口。
- 登录成功后显示用户名称、角色和服务器地址。
- APK/终端包不内置 ASR、LLM、LDAP、Hermes、ES 密钥。

验收：

- 未登录访问会议接口返回 401。
- LDAP 登录后可拉取本人会议。
- 公共源码和文档不包含真实密钥。

### 2. 开始录音

用户期望：

- 点“开始录音”后马上确认录音已经在本地保存。
- 授权麦克风后不需要再配置技术项。

系统要求：

- Android 使用前台录音服务和滚动 WAV 分段。
- 默认按服务器配置时长分段，当前推荐 5 分钟。
- 相邻分段保留约 2 秒重叠，降低边界丢词。
- 当前写入段定期保存本地索引，异常关闭后变成待上传段。

验收：

- App 录音页显示分段数、已上传、待上传、正在写入和转写段落数。
- 关闭 App 会停止录音，并尽量保留当前分段。
- 异常遗留的开放分段下次启动后不继续保持“正在写入”。

### 3. 会议中弱网

用户期望：

- 网络差也不要丢录音。
- 知道哪些分段已到服务器，哪些还在本机。

系统要求：

- 每段音频先落盘，再上传。
- 已上传分段本地标记为 uploaded。
- 重试时跳过已上传分段，只补传未完成分段。
- Web 录音中上传失败的分段在当前页面保留，并给重试入口。

验收：

- 两段音频上传时，第一段成功后第二段失败不会要求重传第一段。
- 上传状态可在 App 或 Web 记录详情中看到。
- 同步失败提示明确建议保持 App 数据，不要卸载或清理。

### 4. 在线分段转写

用户期望：

- 长会议不必等结束才知道识别有没有成功。
- 转写不断补充到同一条会议记录。

系统要求：

- 每个完成分段上传后立即触发 `segment_transcribe`。
- `transcript_segments.source_segment_no` 记录来源分段。
- 重传某个分段时只替换该来源分段的转写，不能误删重叠分段。

验收：

- 上传第 1 段后会议进入 `partial_ready`。
- 上传第 2 段后转写时间线包含两个来源分段。
- 结束会议后 `/finish` 可复用已有阶段转写生成纪要和待办。

### 4.1 多源同录校对

用户期望：

- 多台手机或电脑一起录同一场会议，不会把同一段话重复塞进转写。
- 如果有人晚一点才开始录音，系统仍能尽量对齐同一段内容。
- 如果不同设备听到的日期、数量或负责人不一样，系统不要擅自选一个。

系统要求：

- 多源证据必须按 `(source_id, source_segment_no)` 追溯。
- 同一时间窗或保守错峰窗口内，文本高度相近且关键事实一致时才合并。
- 多源互补只能使用原始转写中的非冲突短语，不得新增原文里没有的事实。
- 错峰对齐合并必须保留 `multi_source_time_aligned` 和 `multi_source_refs:*`。
- 关键事实冲突必须保留多条 `multi_source_conflict`，并提示人工回听。

验收：

- 两个来源错开 45 秒录到同一句话时，最终转写只保留一条合并证据，并保留两个原始来源引用。
- 两个来源各自漏掉不同短语且没有关键事实冲突时，最终转写保留互补后的完整文本，并标记 `multi_source_complemented`。
- 两个来源错开 45 秒但日期或数量不同，最终转写保留两条冲突证据。
- Web 质量区能显示多源合并、多源冲突和来源分段覆盖情况。

### 5. 结束会议

用户期望：

- 最后一段先保存，再处理。
- 处理过程可以稍后回来查看，不必守在页面上。

系统要求：

- 结束录音时停止计时、关闭当前分段、保存到本机、上传、调用 `/finish`。
- `/finish` 可重试，重复调用复用已有 job。
- 如果还有待上传分段，系统不应假装完成。

验收：

- 重复调用 `/finish` 返回同一个 job id。
- 有待上传分段时，Web 录音页保留重试按钮。
- 记录详情状态说明用户下一步应做什么。

### 6. 会后查看与校对

用户期望：

- 先看到会议是否完整，然后看纪要、待办、转写和录音证据。
- 能按说话人或音频分段排查错误。

系统要求：

- Web 详情顺序为：标题/操作、状态说明、进度概览、说话人统计、纪要、待办、录音分段、转写时间线、任务日志。
- Web 音频分段支持授权加载播放。
- Web 转写可按全部、来源音频分段、说话人筛选。
- 筛选后保存转写不能删除隐藏段落。
- Android 详情页优先展示纪要、待办、说话人统计，再展示转写时间线。

验收：

- Web 详情页可编辑标题、纪要、待办、转写和说话人。
- Web 详情页导出 Markdown、Word、PDF、JSON、SRT。
- Android 详情页可播放本地音频或下载服务器音频后播放。

### 7. 修改说话人

用户期望：

- 把“发言人 1”改成真实姓名后，同一个角色全部替换。

系统要求：

- 使用 `speaker_id` 作为批量改名主键。
- 改名后更新 `speakers` 和当前 `transcript_segments.display_name`。
- 同步到移动端和外部 API。

验收：

- Web 或 App 改名后，同 speaker id 的段落全部更新。
- `/api/mobile/sync` 返回改名后的显示名。

### 8. 待办落地

用户期望：

- 自动提取的行动项能人工校正，尤其是负责人、截止时间和状态。

系统要求：

- 服务端提供待办更新接口。
- Web 支持新增、编辑、删除待办行。
- 待办写入数据库并出现在同步、导出、外部 API 和 ES 索引内容中。

验收：

- owner/editor/admin 可更新待办。
- 无写权限用户不能更新待办。
- `/api/mobile/sync` 和 `/api/external/meetings` 能读取更新后的待办。

### 9. 重装恢复和跨端访问

用户期望：

- 手机重装后，服务器上的记录还能恢复。
- PC、Web、桌面端看到同一份数据。

系统要求：

- 服务端是权威数据源。
- App 通过 `/api/mobile/sync` 恢复自己有权限的会议。
- 服务器音频可按权限下载播放。

验收：

- 重装后登录同一账号可恢复会议、转写、纪要、待办和服务器音频下载地址。
- 非会议成员访问会议详情和音频返回 404 或 403。

### 10. 企业知识平台接入

用户期望：

- 会议结果能被 Hermes 或企业知识平台 agent 稳定读取。
- 转写作为证据层不可随意丢失。

系统要求：

- 当前转写和历史归档都服务端持久化。
- 非 admin 不能删除转写段。
- 外部系统走 `/api/external/*`，不能直接读 SQLite。
- ES/OpenSearch 只作可选索引，业务数据先写 SQLite。

验收：

- `/api/external/meetings/{meetingId}/transcript?include_history=true` 返回当前转写和历史。
- 错误 token 访问外部接口返回 401。
- 人工替换转写前会归档旧行。

## 本轮体验改造落地

- Web 会议详情新增状态说明，帮助用户判断“是否安全、是否还在处理、下一步做什么”。
- Web 会议详情新增说话人统计，按说话人显示段落数和时长。
- Web 音频分段新增授权加载播放入口。
- Web 转写时间线支持按来源音频分段和说话人筛选。
- Web 筛选后保存转写会合并隐藏段落，避免误删。
- Web 待办支持新增、编辑、删除和保存。
- 服务端新增 `/api/web/meetings/{meetingId}/actions` 与 `/api/mobile/meetings/{meetingId}/actions`。
- Web 录音上传失败时保留当前页面缓存并提供重试上传。
- Android 记录详情优先展示纪要、待办、说话人统计，再展示转写。
- Android 记录概览增强弱网和阶段转写提示。
- 多源最终处理支持保守错峰对齐，同时保留日期、数量和负责人冲突证据。

## 仍需真实会议验证的体验点

- 真实 ASR 的空语音、噪声、多人抢话和远场拾音效果。
- 5 分钟分段和 2 秒重叠是否适合公司常见会议环境。
- 说话人分离是否需要接入更强的 diarization sidecar。
- 纪要 prompt 是否稳定输出业务可用的负责人、待办和截止时间。
- iOS/macOS/HarmonyOS 签名后 WebView 麦克风权限体验。

## English

# SoloRecord User Stories And UX Acceptance

This document restates SoloRecord as a real user journey. The target baseline is a mainstream meeting recorder experience: trustworthy recording, weak-network recovery, editable transcripts, speaker correction, actionable summaries, and enterprise-readable data.

## UX Benchmark

Reviewed products include Otter, Fireflies, Microsoft Teams Intelligent Recap, Zoom AI Companion, Notta, Fathom, Granola, and Plaud. Their common pattern is a full meeting workflow, not only audio-to-text conversion.

| Capability | Mainstream Pattern | SoloRecord Requirement |
| --- | --- | --- |
| In-meeting trust | Clear recording state, duration, sync progress | Show recording, local-save, segment upload state |
| Timeline review | Review by time, speaker, chapter | Keep transcript timeline, audio segments, source segment number |
| Multi-source evidence | Deduplicate repeated sources while preserving disagreements | Use `(source_id, source_segment_no)`, support conservative late-start alignment, keep key-fact conflicts for review |
| Speaker correction | Rename speaker and apply globally | Batch rename by stable speaker id |
| Action items | Extract owner, task, due date, status | Editable action items persisted server-side |
| Evidence | Summary links back to transcript/time | Exports and external APIs include timestamped transcript |
| Weak network | Avoid whole-meeting retransmission | Segment-level retry with visible pending state |
| Enterprise governance | Permissions, audit, external access | Server is authoritative; external systems use APIs |

References:

- Otter: https://help.otter.ai/hc/en-us/articles/360047872833-Otter-ai-features
- Fireflies: https://fireflies.ai/
- Microsoft Teams Intelligent Recap: https://learn.microsoft.com/microsoftteams/intelligent-recap-calls-meetings
- Zoom AI Companion: https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0058013

## Acceptance Flow

1. Sign in: users enter company credentials only; secrets stay server-side.
2. Start recording: local audio is saved immediately and rolled into overlapping segments.
3. Weak network: completed segments are retried individually; uploaded segments are skipped.
4. Partial transcription: each uploaded segment creates partial transcript rows in the same meeting.
4.1. Multi-source review: duplicate evidence can be merged across sources, late-starting devices can be conservatively aligned, and fact conflicts stay visible for human review.
5. Finish meeting: the final segment is saved first, then `/finish` submits processing; retries reuse the same job.
6. Review: users see status, progress, speaker stats, summary, actions, audio, transcript, and jobs.
7. Speaker rename: changing one speaker id updates all matching rows.
8. Action items: users can edit owner, task, due date, and status.
9. Reinstall recovery: `/api/mobile/sync` restores server records and audio download URLs.
10. Knowledge integration: external agents read through `/api/external/*`; transcript history is preserved.

## Changes Landed In This Round

- Web meeting details now show an actionable status banner.
- Web meeting details show speaker statistics.
- Web audio segments can be loaded and played through authorized requests.
- Web transcript timeline can be filtered by source audio segment or speaker.
- Saving filtered transcript views preserves hidden rows.
- Web action items are editable.
- Server action-item update endpoints were added.
- Web recorder keeps failed upload blobs in the current page and provides retry.
- Android record details now prioritize summary, action items, speaker stats, then transcript.
- Android record overview gives clearer weak-network and partial-transcript guidance.
- Multi-source final processing supports conservative late-start alignment while preserving date, amount, and owner conflicts as separate evidence.

## Needs Real-Meeting Validation

- Real ASR behavior on silence, noise, cross-talk, and far-field audio.
- Whether five-minute segments and two-second overlap fit company meeting rooms.
- Whether stronger diarization is needed.
- Whether summary prompts reliably produce useful owners, action items, and due dates.
- Microphone-permission UX after signed iOS/macOS/HarmonyOS builds.
