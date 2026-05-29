# SoloRecord V0.7 用户体验审计

## 中文

本审计从真实使用者视角重走 SoloRecord 的完整体验：安装、登录、录音、弱网、阶段转写、会后整理、说话人修正、重装恢复、Web 回看、管理员配置和外部系统调用。结论是：V0.7 的底层闭环已经成立，当前最值得优化的是“让用户确信录音没有丢、结果正在补充、失败可恢复”。

## 参考产品观察

调研对象包括 Otter、Fireflies、Microsoft Teams 智能回顾、Zoom AI Companion、Granola、Fathom、Notta、Plaud 等会议记录产品。可取之处：

- 实时反馈：录音中要有明确状态、时长、同步进度和部分结果。
- 时间线优先：会议不是一篇静态文档，用户需要按时间、说话人、音频段回查。
- 结构化会后结果：纪要、待办、负责人、时间点、原文证据要相互可追。
- 低打扰：会议中不要求用户配置模型或理解技术状态。
- 可修正：说话人名称和转写文本必须可改，且修改要批量生效。

需要避免的坑：

- 自动摘要看起来漂亮，但找不到原文依据。
- 说话人识别错了以后修改成本太高。
- 录音或上传失败只给一个泛化错误，用户不知道是否丢失。
- 配置页必填项太多，导致运维在模型未就绪时无法先跑通闭环。
- 强依赖网络，弱网环境下让用户重传整场会议。

参考来源：

- Otter 官方功能说明：https://help.otter.ai/hc/en-us/articles/360047872833-Otter-ai-features
- Fireflies 官方功能说明：https://firefliesai.ai/
- Microsoft Teams Intelligent Recap 官方说明：https://learn.microsoft.com/MicrosoftTeams/intelligent-recap-calls-meetings
- Zoom AI Companion Meeting Summary 官方说明：https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0058013

## 用户故事线审视

### 1. 安装 APK

用户目标：拿到公司内部分发的 APK，安装后能直接看到服务器地址或知道该填什么。

当前状态：

- 支持服务器端发布 APK。
- 公开 APK 不包含真实服务器地址和密钥。
- 内部分发 APK 可只预置服务器地址。

优化建议：

- Web 下载页展示版本、发布时间、SHA-256、是否强制更新。
- App 首次打开时，如果没有服务器地址，应突出“请向运维获取服务器地址”，而不是让用户猜。

### 2. 登录

用户目标：输入 LDAP 用户名密码后进入系统，不理解 token、LDAP、SSO 也能用。

当前状态：

- App 和 Web 支持 LDAP 登录。
- 密码只提交到服务端校验，不写入 APK。

优化建议：

- 登录失败时区分服务器不可达、账号密码错误、LDAP 配置错误、证书错误。
- 登录成功后自动拉取服务器配置和最近会议，让用户确认自己进入了正确工作区。

### 3. 开始录音

用户目标：点一下就开始，马上相信“已经在保存”。

当前状态：

- 未登录不能录音。
- 使用前台录音服务。
- 录音已改为连续 `AudioRecord` 采集，WAV 分段落盘。
- 当前写入中的分段会定期保存到本地索引，WAV 文件头会边录边刷新，异常关闭后下次启动会转为待上传分段。
- 默认约 5 分钟分段，可由服务端配置。
- 相邻分段约 2 秒重叠，减少边界丢词。

已落地优化：

- App 提示当前分段分钟数、2 秒重叠和在线分段转写。
- App 记录卡显示音频分段、已上传、待上传、正在写入、转写段落数量。

下一步建议：

- 录音中可以继续强化麦克风权限状态、最近一次分段保存时间。
- 若磁盘空间不足或麦克风被占用，应在开始前阻断并给明确提示。

### 4. 会议中在线分段转写

用户目标：长会不想等结束才知道有没有识别成功。

当前状态：

- 每个完成分段上传后，服务端立即执行 `segment_transcribe`。
- 阶段转写写入同一条会议记录。
- `transcript_segments.source_segment_no` 记录来源分段，重传某段时只替换该段结果。
- 结束会议时，如果所有分段已有阶段转写，服务端复用这些转写生成完整纪要和待办，避免重复 ASR。

已落地优化：

- Web 详情页显示录音分段时间线。
- Web 转写行显示来源分段。

下一步建议：

- App 录音页可以增加“已生成阶段转写 N 段”的轻量状态。
- Web 可以按分段过滤转写，便于排查某个音频段 ASR 异常。

### 5. 弱网与失败

用户目标：网络差也不怕，知道“哪些已经安全到服务器，哪些还在手机上”。

当前状态：

- 分段级断点续传。
- 已上传分段本地标记为 `uploaded`。
- 重试只补传未完成分段。
- 如果上传中断，最多重传当前未确认分段。

优化建议：

- App 记录详情中突出待上传分段数。
- 上传失败提示中给出下一步：检查网络后点击同步，不要卸载或清理数据。
- 服务端对反向代理 body size、存储权限等常见上传问题提供运维检查项。

### 6. 结束会议

用户目标：点结束后，最后一段安全保存，会议进入“处理中”，最终可看纪要和待办。

当前状态：

- 结束录音会停止分段计时器、保存最后一段、触发同步和 `/finish`。
- 关闭 App 会停止录音并尽量保存当前段。
- `/finish` 可重试，避免重复任务。

优化建议：

- 结束后不要只跳到记录页，还应显示“最后一段已保存、正在上传、可稍后回来查看”。
- 如果未登录或 token 过期，保留本地录音并引导重新登录后同步。

### 7. 查看记录

用户目标：快速确认这场会有没有完整、谁说了什么、下一步做什么。

当前状态：

- App 和 Web 都可看记录。
- Web 可编辑标题、纪要、转写、说话人名称。
- 支持导出 Markdown、Word、PDF、JSON、SRT。

已落地优化：

- Web 顶部增加录音分段、已上传、转写段落、总时长。
- Web 详情增加音频分段列表。

下一步建议：

- 详情页默认顺序建议为：状态概览、纪要、待办、转写时间线、音频分段、任务日志。
- 待办应能编辑负责人、截止时间和状态，而不仅仅展示。
- 摘要中的关键结论最好能跳转到原文时间点。

### 8. 修改说话人

用户目标：把“发言人 1”改成真实姓名，后面自动全部替换。

当前状态：

- App 和 Web 支持按 `speaker_id` 批量重命名。
- 修改后同步到服务端。

优化建议：

- 改名入口文字可以更口语化，例如“把这个角色改成某人”。
- Web 上可以显示“将替换 X 条段落”，降低误操作焦虑。
- 未来可结合参会人名单、LDAP 用户和销售工作区用户做候选名称。

### 9. 重装 App 和跨端访问

用户目标：手机坏了或重装后，服务器记录还能找回来。

当前状态：

- 服务端是权威数据源。
- App 可通过 `/api/mobile/sync` 恢复会议。
- 恢复后可按权限下载服务器音频播放。

优化建议：

- 登录后首次进入记录页，如果本地为空，应自动提示“从服务器恢复记录”。
- 同步结果应说明恢复了多少条、是否有音频可下载。

### 10. 管理员配置模型

用户目标：先跑通，再逐步接 ASR、LLM、Hermes、ES。

当前状态：

- 配置页保留少量必填项。
- 密钥不回显。
- mock 模式能先跑通闭环。
- 手机分段分钟数可配置，App 会从服务端读取。

优化建议：

- Provider 保存后自动跑一次连接检查，而不是等真实会议失败。
- 对 ASR endpoint/model/key 的错误做分层提示。
- 增加“测试一小段音频”的管理入口。

## 已在本轮落地的体验改进

- Android 连续 WAV 录音，约 2 秒分段重叠。
- 录音中定期检查点保存当前段索引，并刷新 WAV 头部；异常关闭后下次启动会把开放分段转为待上传。
- App 按服务器配置读取分段分钟数。
- 在线每段上传后返回阶段转写。
- `source_segment_no` 保护重叠分段重传，不误删相邻段转写。
- 最终 `/finish` 复用已完成阶段转写，减少重复 ASR。
- App 列表和详情显示已上传、待上传、转写段落数量。
- Web 详情显示音频分段时间线、总时长、转写来源分段。
- 测试和 smoke 覆盖两段重叠上传、阶段转写、最终同一会议记录。

## 发布前不建议再硬塞的改动

- 真正实时流式转写：需要服务端任务队列和移动端长连接，风险高。
- 端侧 VAD/降噪：可能影响录音可靠性，应等真实会议 A/B 测试。
- 自动识别真实姓名：需要参会人名单和权限边界，先保留人工修正。
- 大幅重做移动端 UI：当前原生 Java 手写 UI 足够跑通，部署前应保持变更克制。

## English

# SoloRecord V0.7 UX Review

This review walks through SoloRecord from a real user perspective: install, sign-in, recording, weak network, partial transcripts, final notes, speaker correction, reinstall recovery, Web review, admin configuration, and external access. The core loop is now in place. The most important UX goal is to help users trust that recording is safe, partial results are progressing, and failures can be recovered.

## Product Patterns Reviewed

Products reviewed include Otter, Fireflies, Microsoft Teams Intelligent Recap, Zoom AI Companion, Granola, Fathom, Notta, and Plaud.

Useful patterns:

- Clear live recording feedback.
- Timeline-first review by time, speaker, and source audio.
- Structured post-meeting outputs: summary, action items, owners, timestamps, and supporting transcript.
- Low interruption during the meeting.
- Editable speaker names and transcript text.

Pitfalls to avoid:

- Pretty summaries without supporting transcript.
- Expensive speaker-name correction.
- Generic failure messages that do not say whether audio is safe.
- Too many required admin fields before the basic loop works.
- Requiring whole-meeting retransmission on weak networks.

References:

- Otter official feature guide: https://help.otter.ai/hc/en-us/articles/360047872833-Otter-ai-features
- Fireflies official feature guide: https://firefliesai.ai/
- Microsoft Teams Intelligent Recap official guide: https://learn.microsoft.com/MicrosoftTeams/intelligent-recap-calls-meetings
- Zoom AI Companion Meeting Summary official guide: https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0058013

## Improvements Landed In This Round

- Continuous Android WAV recording with about two seconds of overlap between adjacent segments.
- During recording, the app checkpoints the open segment into the local index and refreshes the WAV header; after an unexpected shutdown, next launch converts the open segment into a pending upload segment.
- Segment duration is read from the server configuration.
- Each accepted segment triggers partial ASR and writes transcript rows into the same meeting.
- `source_segment_no` prevents overlapped retries from deleting neighboring transcript rows.
- Final `/finish` reuses completed partial transcripts to reduce duplicate ASR work.
- Android shows uploaded, pending, and transcript counts.
- Web details show audio segment timeline, duration, and transcript source segment.
- Tests and smoke now cover two overlapped uploaded segments, partial transcript return, and final processing into one meeting.

## Recommended Later Work

- More visible recording timer and last-save status on Android.
- Clearer error categories for login, upload, and ASR failures.
- Editable action items on Web.
- Source-backed summary links from conclusions to transcript timestamps.
- Admin “test provider” buttons for ASR and LLM configuration.
- Speaker-name suggestions from participants, LDAP, or sales workspace users.
