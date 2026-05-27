# 会议记录 App PRD

> 面向公司内部使用，覆盖 Android APK、服务端、本地 ASR、Web/PC 端、统一登录、APK 内部分发与运维部署。

## 1. 一句话目标

建设一套公司内部私有化会议记录系统：员工通过群晖统一登录后，可以用 Android App 可靠录音，服务端在网络恢复后自动完成上传、VAD、说话人分离、ASR、纪要与待办整理，并在 Web 端进行查看、编辑、搜索、导出、管理和 APK 下载。

## 2. 背景与关键判断

会议记录真正影响用户体验的不是“有没有 ASR”，而是整条链路是否稳：

- 录音不能丢，尤其是 App 关闭、锁屏、网络差、电量变化时。
- 转写不必实时完成，但状态必须清楚，失败必须可重试。
- 会议结果必须可编辑、可搜索、可导出。
- “谁说的”必须允许修正，不能假设说话人分离 100% 正确。
- 公司内部使用仍要保护密钥、录音、纪要和员工身份。
- 单卡 16GB 显存环境必须异步处理、限制并发、分段运行。

本产品采用“移动端轻处理 + 服务端重处理 + Web 管理编辑”的架构。

## 3. 产品范围

### 3.1 本次完整交付范围

- Android App
  - 群晖统一登录
  - 录音页、记录页、登录状态页
  - 前台录音服务
  - 3-5 分钟滚动保存音频
  - 网络恢复后自动上传
  - 本地播放未上传/已上传音频
  - 查看转写、纪要、待办
- 服务端
  - 群晖 SSO 对接
  - 会议、音频分段、任务、转写结果、导出文件管理
  - 本地 ASR 处理流水线
  - 异步队列、重试、失败状态、管理员可见日志
  - APK 下载与版本管理
- Web 应用
  - 登录
  - 会议列表、详情、播放器
  - 转写编辑、说话人改名
  - 会议纪要、待办编辑
  - 搜索、导出、APK 下载
- 导出
  - Markdown、Word、PDF、JSON、SRT

### 3.2 本次不作为上线阻塞项

以下能力保留接口或架构位置，但不阻塞明天内网部署：

- 真正多人同时协作编辑
- 实时字幕作为主流程
- 手机端本地 ASR 推理
- 自动静默升级 APK
- 完全自动识别真实姓名
- 外部公开 SaaS 分发

### 3.3 后续增强清单

- PC 桌面客户端，捕获麦克风和系统声音
- 近实时字幕
- 会议问答和全文语义检索
- 术语自动学习
- 与企业日历、飞书/企微文档、CRM/Hermes 深度联动

## 4. 用户角色

| 角色 | 需求 |
| --- | --- |
| 普通员工 | 录音、查看转写、整理纪要、导出 |
| 销售/项目经理 | 待办到人、客户会议记录可追溯、转发到销售工作区 |
| 管理者 | 查看团队会议产出、搜索关键内容 |
| IT 管理员 | SSO、权限、模型、队列、APK 版本、日志与告警 |
| 系统维护者 | 调整 ASR/LLM/降噪/说话人分离参数 |

## 5. 端侧体验设计

### 5.1 Android App 信息架构

App 固定三个页签：

- 录音
- 记录
- 登录状态

未登录时，录音与记录页显示登录引导，不允许创建会议或查看数据。

### 5.2 录音页

核心目标：一个按钮完成可靠录音。

页面元素：

- 当前登录用户
- 会议标题，默认“会议 yyyy-MM-dd HH:mm”
- 开始/结束录音主按钮
- 录音时长
- 当前分段保存状态
- 网络状态与上传状态
- 最近一次保存时间

交互：

- 点击“开始录音”后立即创建本地会议记录并启动前台录音服务。
- 录音服务每 3-5 分钟生成一个音频分段。
- 点击“结束录音”后关闭当前分段，会议进入“待上传/处理中”状态。
- App 被关闭时，录音服务收到关闭事件后停止并安全落盘当前分段。
- 系统异常或崩溃后，下次打开 App 要能识别未完成分段并提示恢复。

体验要求：

- 录音过程中保持通知栏常驻，提示正在录音。
- 录音中禁止误触退出；结束前二次确认。
- 录音过程中网络差不影响本地保存。
- 本地音频在上传成功和服务器确认前不得删除。

### 5.3 记录页

核心目标：每次开始到结束是一条会议记录，即使内部有多个音频分段。

列表字段：

- 标题
- 创建时间
- 时长
- 状态：录音中、待上传、上传中、排队中、转写中、整理中、已完成、失败
- 上传进度
- 处理进度

详情页：

- 音频播放器，按分段连续播放
- 时间线转写：时间、说话人、正文
- 说话人改名，例如 `SPEAKER_01` 改为“张三”
- 会议纪要
- 待办列表：负责人、事项、截止时间、状态
- 操作：重新整理、重新转写、导出、删除本地音频、从服务器重新同步

编辑策略：

- App 支持基础编辑：改文字、改说话人、改待办状态。
- 复杂编辑建议在 Web 完成。
- 编辑保存采用版本号，避免覆盖服务端新版本。

### 5.4 登录状态页

页面元素：

- 登录状态
- 用户姓名、账号、部门或邮箱
- Token 到期时间
- 服务器地址
- App 版本
- 检查更新
- 退出登录

登录方式：

- 优先使用系统浏览器或 Custom Tabs 打开群晖 SSO。
- 登录成功后回跳 App，App 只保存服务端签发的短期会话 token。
- 群晖 SSO client secret 只保存在服务端。

### 5.5 Android 更新与 APK 下载

由于公司内部使用，采用服务端托管 APK：

- Web 登录后可访问“下载 Android App”页面。
- App 登录状态页可以检查新版本。
- 新版本提示用户下载 APK。
- Android 侧安装仍需用户确认，除非公司设备是 MDM/设备所有者模式。
- 服务端保存版本号、更新说明、APK 文件、SHA-256、发布时间、强制更新标记。

## 6. Web/PC 端设计

### 6.1 为什么需要 Web

Web 是本次交付的必要组成，因为它解决移动端不适合做的事情：

- 长文本编辑
- 说话人批量改名
- 导出 Word/PDF
- 搜索历史会议
- 管理词表、成员、权限、模型参数
- 下载 APK
- 查看任务失败原因

### 6.2 Web 功能

普通用户：

- 登录/退出
- 会议列表
- 会议详情
- 播放音频
- 查看和编辑转写
- 批量替换说话人名称
- 编辑纪要和待办
- 搜索会议标题、正文、说话人、待办
- 导出 Markdown、Word、PDF、JSON、SRT
- 下载 Android APK

管理员：

- 用户与权限管理
- ASR/LLM Provider 配置
- 音频处理参数配置
- 词表管理
- APK 版本管理
- 队列与任务监控
- 失败任务重试
- 数据保留策略
- 系统日志与审计

### 6.3 PC 桌面客户端判断

本次先做响应式 Web，不把完整桌面客户端作为上线阻塞项。

原因：

- 当前主要采集端是手机 APK。
- Web 已能覆盖查看、编辑、导出和管理。
- 桌面端最大的价值是捕获 PC 麦克风和系统声音，这涉及 Windows/macOS 权限、驱动、回声消除和会议软件兼容，复杂度明显高。

如后续需要 PC 端，推荐 Tauri 桌面客户端：

- 前端复用 Web 页面。
- Rust/Tauri 负责本机录音、系统音频捕获、上传和托盘状态。
- 可参考 MIT 许可的 Meetily 架构。

## 7. 服务端总体设计

### 7.1 服务组件

建议用 Docker Compose 起步，后续可迁移 Kubernetes。

必需组件：

- Nginx/Caddy：HTTPS、反向代理、静态文件、APK 下载
- Web 前端：React/Vue/Svelte 均可
- API 服务：认证、会议、上传、任务、导出、管理
- Worker 服务：音频处理、ASR、说话人分离、纪要整理
- PostgreSQL：业务数据
- Redis：队列、缓存、锁
- MinIO 或本地对象存储：音频、导出文件、APK
- ASR Runtime：sherpa-onnx/whisper.cpp/自研模型服务
- LLM Runtime：本地 Ollama/vLLM/兼容 OpenAI API 的服务，或公司内网模型 API
- 监控：Prometheus + Grafana，可后置
- 日志：Loki 或文件日志，可后置

### 7.2 推荐技术栈

移动端：

- Android Kotlin/Java
- Foreground Service
- WorkManager
- Room 或 SQLite
- MediaRecorder M4A/AAC

后端：

- FastAPI 或 NestJS
- PostgreSQL
- Redis + RQ/Celery/BullMQ
- ffmpeg
- sherpa-onnx 作为优先 ASR/VAD/diarization 评估对象
- whisper.cpp 作为 ASR 基准或备选
- python-docx / LibreOffice headless 生成 Word/PDF

Web：

- React + TanStack Query
- 组件库可用 Ant Design 或 shadcn/ui
- 文本编辑可先用普通 textarea/段落编辑，后续再换富文本

### 7.3 服务边界

API 服务负责：

- SSO 登录回调与会话签发
- 权限校验
- 会议 CRUD
- 音频分段上传
- 任务创建和状态查询
- 结果读取和保存
- 导出任务
- APK 版本管理

Worker 负责：

- 音频转码
- VAD
- 质量检测
- 可选降噪/去混响
- 可选说话人分离
- ASR
- 时间线合并
- 标点、数字、术语后处理
- LLM 纪要与待办
- 导出文件生成
- Hermes/销售工作区转发

## 8. 音频与 ASR 流水线

### 8.1 输入策略

APK 保存：

- 每个会议一个 `meeting_id`
- 多个音频分段 `part_0001.m4a`
- 每个分段记录开始时间、结束时间、大小、上传状态

服务端处理：

1. 接收分段。
2. 转码为模型要求格式。
3. 计算质量指标。
4. VAD 切出有效人声片段。
5. 可选降噪/去混响。
6. 可选说话人分离。
7. ASR。
8. 合并到全局时间线。
9. 后处理。
10. 纪要和待办整理。

### 8.2 默认参数

| 参数 | 默认值 |
| --- | --- |
| APK 滚动分段 | 3-5 分钟 |
| 服务端 VAD chunk | 10-30 秒 |
| chunk overlap | 300-800 ms |
| ASR 输入 | mono，16k 或模型要求 |
| GPU ASR 并发 | 1 |
| Diarization | 可开关，默认启用但可降级 |
| 降噪/去混响 | 默认关闭，通过真实录音 A/B 后开启 |

### 8.3 开源组件复用策略

优先复用：

- sherpa-onnx：ASR、VAD、Diarization、标点、语音增强评估。
- whisper.cpp：ASR 备选和质量基准。
- Vosk：低资源备用。
- android-vad：App 端可选实时人声提示。
- Android-Wave-Recorder：如未来改录 WAV/PCM 可参考。

只参考架构：

- Listen：Android 前台录音、分段、WorkManager、播放，但 GPL-3.0 不直接复制。
- Whishper：Web 转写系统架构，但 AGPL-3.0 不直接复制。
- Millet/Meetscribe：会议转写和导出思路，但 GPL-3.0 不直接复制。
- HushNote、ownscribe、Meetily：说话人标注、桌面端和纪要体验参考。

### 8.4 本地模型与远程模型

本次以本地 ASR 为主：

- 模型服务部署在公司服务器或 NAS 旁边的 GPU 主机。
- API/Worker 通过内部地址调用。
- 模型密钥或配置不进入 APK。

远程 Qwen ASR 保留为可选 Provider：

- 用于兜底或对比质量。
- 由 Worker 调用，不由 APK 调用。
- 具备超时、重试、熔断和脱敏日志。

## 9. 统一登录与权限

### 9.1 登录

支持群晖统一登录插件，具体协议以公司插件文档为准。

服务端支持三种验证模式：

- OIDC/JWT：JWKS 验签
- introspection：调用统一登录接口验 token
- ticket_verify：调用公司插件验票接口

配置项：

```text
SSO_VERIFY_MODE=oidc|introspection|ticket_verify
SSO_ISSUER=
SSO_CLIENT_ID=
SSO_CLIENT_SECRET=
SSO_REDIRECT_URI=
SSO_JWKS_URL=
SSO_INTROSPECTION_URL=
SSO_TICKET_VERIFY_URL=
```

### 9.2 权限模型

会议角色：

- owner：创建者，全部权限
- editor：可编辑转写、纪要、待办
- viewer：只读和导出
- admin：系统管理员

会议可见性：

- 默认仅 owner 可见。
- 可添加成员。
- 可配置“同部门可见”作为后续增强。

### 9.3 审计

记录以下行为：

- 登录成功/失败
- 创建会议
- 上传/删除音频
- 查看会议
- 编辑转写/纪要/待办
- 导出
- 重新转写/重新整理
- 管理员修改配置或 APK 版本

不记录敏感 token，不在日志中输出原始 API Key。

## 10. API 设计

### 10.1 移动端 API

```text
GET  /api/mobile/config
POST /api/mobile/auth/start
POST /api/mobile/auth/callback
POST /api/mobile/sessions/refresh
POST /api/mobile/meetings
GET  /api/mobile/meetings
GET  /api/mobile/meetings/{meetingId}
POST /api/mobile/meetings/{meetingId}/segments
PUT  /api/mobile/meetings/{meetingId}/segments/{segmentNo}/complete
POST /api/mobile/meetings/{meetingId}/finish
POST /api/mobile/meetings/{meetingId}/process
GET  /api/mobile/meetings/{meetingId}/status
GET  /api/mobile/meetings/{meetingId}/transcript
PUT  /api/mobile/meetings/{meetingId}/transcript
GET  /api/mobile/releases/latest
GET  /downloads/android/{version}/app.apk
```

### 10.2 Web API

```text
GET    /api/web/me
GET    /api/web/meetings
POST   /api/web/meetings
GET    /api/web/meetings/{meetingId}
PATCH  /api/web/meetings/{meetingId}
DELETE /api/web/meetings/{meetingId}
GET    /api/web/meetings/{meetingId}/audio
GET    /api/web/meetings/{meetingId}/transcript
PUT    /api/web/meetings/{meetingId}/transcript
POST   /api/web/meetings/{meetingId}/summaries/regenerate
GET    /api/web/meetings/{meetingId}/exports
POST   /api/web/meetings/{meetingId}/exports
GET    /api/web/search
```

### 10.3 管理 API

```text
GET  /api/admin/jobs
POST /api/admin/jobs/{jobId}/retry
GET  /api/admin/providers
PUT  /api/admin/providers/{providerId}
GET  /api/admin/terms
POST /api/admin/terms
GET  /api/admin/releases
POST /api/admin/releases
GET  /api/admin/audit-logs
GET  /api/admin/metrics/summary
```

## 11. 数据模型

### 11.1 核心表

- `users`
- `sessions`
- `meetings`
- `meeting_members`
- `audio_segments`
- `processing_jobs`
- `transcript_versions`
- `transcript_segments`
- `speakers`
- `summaries`
- `action_items`
- `exports`
- `apk_releases`
- `term_dictionary`
- `audit_logs`

### 11.2 关键字段

`audio_segments`：

```json
{
  "meeting_id": "uuid",
  "segment_no": 1,
  "local_id": "phone-generated-id",
  "storage_key": "meetings/{id}/audio/part_0001.m4a",
  "start_ms": 0,
  "end_ms": 300000,
  "duration_ms": 300000,
  "size_bytes": 4812345,
  "sha256": "...",
  "upload_status": "uploaded"
}
```

`transcript_segments`：

```json
{
  "meeting_id": "uuid",
  "version": 3,
  "speaker_id": "SPEAKER_01",
  "display_name": "张三",
  "start_ms": 10200,
  "end_ms": 18400,
  "text": "我们下周一前把报价方案发出来。",
  "confidence": 0.88,
  "flags": ["low_confidence"]
}
```

`processing_jobs`：

```json
{
  "job_id": "uuid",
  "meeting_id": "uuid",
  "type": "transcribe",
  "status": "transcribing",
  "progress": 42,
  "current_stage": "asr",
  "asr_provider": "local-sherpa-onnx",
  "gpu_slot": "gpu0",
  "retry_count": 0,
  "error_code": null
}
```

## 12. 任务状态机

会议状态：

```text
local_recording
local_recorded
uploading
uploaded
queued
preprocessing
diarizing
transcribing
postprocessing
summarizing
ready
failed
```

失败策略：

- 每个阶段可重试。
- ASR 单 chunk 失败不应导致整场会议立即失败，先标记片段失败并继续。
- 可选步骤失败可降级，例如降噪失败则跳过，Diarization 失败则使用未知说话人。
- 严重失败进入 `failed`，用户和管理员可查看原因并重试。

## 13. 用户体验细节

### 13.1 状态提示

用户看不到“技术步骤堆砌”，看到的是可理解状态：

- 正在保存录音
- 等待网络上传
- 已上传，等待处理
- 正在识别人声
- 正在转写
- 正在整理纪要
- 已完成
- 处理失败，可重试

### 13.2 低置信度处理

当音频质量差或 ASR 置信度低：

- 时间线段落显示“可能不准确”标记。
- 支持点击播放该段音频。
- 支持快速修正。

### 13.3 说话人体验

- 默认显示 `发言人 1`、`发言人 2`。
- 用户可以把 `发言人 1` 改为“张三”。
- 改名后同一 speaker_id 全局更新。
- 重叠发言或低置信说话人显示“不确定”。

### 13.4 待办体验

待办字段：

- 负责人
- 事项
- 截止时间
- 来源段落
- 状态：待处理、进行中、完成、已取消

点击来源段落可跳转到对应转写和音频时间点。

## 14. 部署方案

### 14.1 单机 Docker Compose 起步

目标机器：

- Linux 服务器
- NVIDIA GPU 16GB 显存，或 CPU-only 降级
- 32GB 内存建议
- 500GB+ 存储，视音频留存周期扩展

服务：

```text
nginx
web
api
worker-cpu
worker-gpu
postgres
redis
minio
asr-runtime
llm-runtime
prometheus
grafana
```

### 14.2 GPU 资源策略

- GPU worker 并发默认 1。
- CPU worker 可并行处理转码、VAD、导出。
- 队列超过阈值时：
  - 暂停自动纪要重生成
  - 降低 diarization 优先级
  - 保留 ASR 主流程
  - 前端提示预计等待时间

### 14.3 数据保留

默认建议：

- 原始音频保留 180 天。
- 转写和纪要长期保留，除非用户删除。
- 用户删除会议时，音频、转写、导出文件进入软删除，管理员可配置 7-30 天后物理删除。

## 15. 安全与合规

- 全站 HTTPS。
- App/API 使用短期 token + refresh。
- 录音和导出文件访问必须鉴权。
- 对象存储不暴露公网匿名读。
- APK 下载需要登录，或者至少使用内部网络限制。
- 密钥只在服务端配置。
- 管理操作有审计日志。
- 导出文件可后续增加水印或导出人信息。

## 16. 测试与验收

### 16.1 录音可靠性

- 锁屏 2 小时录音不丢。
- App 切后台录音不丢。
- App 被用户关闭后当前分段可保存。
- 网络断开录音不受影响。
- 网络恢复后自动上传。

### 16.2 服务端处理

- 1 小时会议可完整处理。
- 单卡 16GB 不 OOM。
- 队列并发可控。
- Worker 重启后任务可恢复。
- 单分段失败可定位并重试。

### 16.3 登录权限

- 未登录不能访问 App 业务页。
- 未授权用户不能查看他人会议。
- Token 过期可刷新或重新登录。
- 管理员权限单独控制。

### 16.4 Web 体验

- 用户可在 Web 搜索历史会议。
- 转写可编辑保存。
- 说话人可批量改名。
- 可导出 Word、PDF、Markdown、JSON、SRT。
- 可下载最新版 APK。

## 17. 里程碑

### M1：可用闭环

- 服务端基础框架
- SSO 登录
- APK 下载页
- Android 三页签
- 前台录音与滚动分段
- 上传与状态同步
- 服务端转码、VAD、本地 ASR
- Web 会议列表与详情
- Markdown/JSON 导出

### M2：会议可用性

- 说话人分离
- 说话人改名
- 纪要与待办
- Word/PDF/SRT 导出
- 失败重试与管理员任务面板
- 词表和专名纠错

### M3：内部生产

- 队列监控与告警
- GPU 并发治理
- APK 版本管理与强制更新
- Hermes/销售工作区转发
- 数据保留策略
- 固定测试集回归

### M4：PC 增强

- 响应式 Web 优化
- 可选 Tauri 桌面端
- PC 麦克风/系统音频采集
- 近实时字幕

## 18. 推荐实施顺序

1. 先做服务端骨架、SSO、用户和会议模型。
2. 做 Android 前台录音服务和滚动分段。
3. 做上传队列和服务器音频分段接收。
4. 接入本地 ASR 的最小流水线：转码 + VAD + ASR。
5. 做 Web 会议详情、播放器、转写展示。
6. 增加编辑、导出、纪要和待办。
7. 增加说话人分离和改名体验。
8. 做管理员面板、APK 版本管理、监控告警。

## 19. 开源复用结论

可以充分复用开源组件，但不要直接克隆开源会议 App：

- 生产优先：Apache-2.0/MIT 组件。
- GPL/AGPL 项目只做架构参考，除非公司接受对应许可证义务。
- App 录音链路自研，参考 Listen 的思路。
- Web 转写后台参考 Whishper 的服务拆分，不复制代码。
- 本地 ASR 优先评估 sherpa-onnx 和 whisper.cpp。

## English

# Meeting Recorder App PRD

> Internal company system covering Android APK, server, local ASR, Web/PC UI, unified login, internal APK distribution, and operations deployment.

## 1. One-Sentence Goal

Build an internal meeting recorder: employees sign in through Synology/company SSO, record reliably on Android, and let the server complete upload, VAD, diarization, ASR, meeting summaries, and action items after network recovery. Users can review, edit, search, export, administer, and download the APK from the Web UI.

## 2. Background And Key Judgments

The user experience depends on the entire workflow, not ASR alone:

- Recordings must not be lost, especially during app close, lock screen, weak network, or power changes.
- Transcription does not need to be real-time, but status must be clear and failures must be retryable.
- Meeting results must be editable, searchable, and exportable.
- "Who said what" must be correctable; diarization is never assumed to be perfect.
- Internal use still requires protection for secrets, audio, summaries, and employee identity.
- A single 16 GB GPU environment needs asynchronous processing, concurrency limits, and segmented jobs.

The product uses a light mobile client, heavier server processing, and a Web admin/editor UI.

## 3. Product Scope

### Complete Delivery Scope

Android app:

- Synology/company unified login.
- Recording, Records, and Login Status tabs.
- Foreground recording service.
- Rolling audio files every 3 to 5 minutes.
- Upload after network recovery.
- Local and server audio playback.
- Transcript, summary, and action-item viewing.

Server:

- Synology SSO integration.
- Meeting, audio segment, job, transcript, export, and APK release management.
- Local ASR processing pipeline.
- Retryable processing state and admin-visible errors.

Web app:

- Login.
- Meeting list and details.
- Player.
- Transcript editing and speaker rename.
- Summary and action-item editing.
- Search, export, and APK download.
- Admin model/provider configuration and job retry.

Exports:

- Markdown, Word, PDF, JSON, and SRT.

### Not A Go-Live Blocker

- True multi-user collaborative editing.
- Real-time subtitles as the main workflow.
- Phone-side local ASR inference.
- Silent automatic APK upgrades.
- Fully automatic real-name speaker identification.
- Public SaaS distribution.

### Future Enhancements

- PC desktop client for microphone and system-audio capture.
- Near-real-time captions.
- Meeting Q&A and semantic search.
- Terminology learning.
- Calendar, Feishu/WeCom docs, CRM/Hermes integration.

## 4. User Roles

| Role | Need |
| --- | --- |
| Employee | Record, view transcripts, generate summaries, export |
| Sales / PM | Person-specific action items, traceable customer meetings, forwarding to sales workspace |
| Manager | Team meeting output and search |
| IT Admin | SSO, permissions, models, queues, APK versions, logs, alerts |
| Maintainer | ASR/LLM/denoise/diarization tuning |

## 5. Android UX

The app has three fixed tabs:

- Recording
- Records
- Login Status

Unauthenticated users cannot record or view records.

Recording tab:

- One primary button starts/stops recording.
- A local meeting record is created immediately after start.
- Audio rolls into segments every 3 to 5 minutes.
- Stop or app close finalizes the current segment.
- Bad network never blocks local recording.
- Local audio is not deleted before upload and server acknowledgement.

Records tab:

- One start/end cycle is one meeting record even with many audio segments.
- Detail view shows audio playback, transcript timeline, speaker rename, summary, action items, retry/export actions, and server recovery.
- Speaker rename updates all rows with the same stable speaker id.

Login Status tab:

- Shows current user, account/email, token expiry, server address, app version, update check, and logout.
- Login uses system browser/Custom Tabs and returns to `solorecord://auth/callback`.
- Synology client secret is server-only.

## 6. Web / PC

Web is required because mobile is not ideal for:

- Long-text editing.
- Batch speaker rename.
- Word/PDF export.
- Searching old meetings.
- Managing glossary, permissions, model settings, APK releases, and failed jobs.

The first delivery uses responsive Web rather than a full desktop client. A later Tauri desktop client can reuse Web UI and add PC microphone/system-audio capture.

## 7. Server Design

Recommended start is Docker Compose, with later migration to Kubernetes if needed.

Required or planned components:

- Nginx/Caddy for HTTPS/reverse proxy.
- API service for auth, meetings, upload, jobs, exports, admin.
- Worker for audio processing, ASR, diarization, summaries, forwarding.
- PostgreSQL for production business data; SQLite is acceptable for initial validation.
- Redis for queue/cache/locks in production.
- MinIO/NAS/S3-compatible storage for audio, exports, APKs.
- ASR runtime such as sherpa-onnx, whisper.cpp, or custom local model service.
- LLM runtime such as Ollama, vLLM, OpenAI-compatible API, or internal model.
- Prometheus/Grafana and logs when production monitoring is required.

## 8. Audio And ASR Pipeline

APK saves:

- One `meeting_id`.
- Multiple `part_0001.m4a` style segments.
- Per-segment start, end, size, upload state.

Server steps:

1. Receive segments.
2. Transcode/normalize audio.
3. Compute quality metrics.
4. Run VAD.
5. Optionally denoise/dereverb.
6. Optionally diarize.
7. Run ASR.
8. Merge into a global timeline.
9. Post-process terms, punctuation, and numbers.
10. Generate summary and action items.

Recommended defaults:

| Parameter | Default |
| --- | --- |
| APK rolling segment | 3-5 minutes |
| Server VAD chunk | 10-30 seconds |
| Chunk overlap | 300-800 ms |
| ASR input | mono, 16 kHz or model-specific |
| GPU ASR concurrency | 1 |
| Diarization | Configurable, degraded safely |
| Denoise/dereverb | Off by default; enable after A/B tests |

## 9. Login, Authorization, And Audit

Supported SSO validation modes:

- OIDC/JWT with JWKS.
- Introspection.
- Ticket verification.

Meeting roles:

- owner
- editor
- viewer
- admin

Audit should record login-adjacent business events, meeting creation, upload/delete, read, edit, export, retry, and admin config changes. Logs must not contain raw API keys or sensitive tokens.

## 10. APIs

Mobile API includes meeting create/list/detail, segment upload, protected audio download, finish, process, status, transcript, speaker rename, latest release, and server sync.

Web API includes current user, meeting list/detail/edit, transcript edit, process, speaker rename, export, search, sync, and latest release.

Admin API includes providers, jobs, retry, releases, and search reindex.

External API includes:

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

## 11. Data Model

Core tables:

- `users`
- `sessions`
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

The server stores the authoritative copy. ES/OpenSearch is optional and rebuildable.

## 12. Status Machine

User-facing statuses should be understandable:

- Saving recording.
- Waiting for network upload.
- Uploaded, waiting for processing.
- Detecting speech.
- Transcribing.
- Summarizing.
- Ready.
- Failed, retry available.

Internal statuses include local recording, recorded, uploading, uploaded, queued, preprocessing, diarizing, transcribing, postprocessing, summarizing, ready, and failed.

## 13. Security And Compliance

- HTTPS everywhere.
- Short-lived app/API tokens.
- Authenticated access for audio and exports.
- No anonymous public object storage.
- APK download requires login or internal-network restriction.
- Secrets are server-only.
- Admin operations are audited.
- Export watermarking can be added later.

The source repository can be public if it contains no real secrets, runtime data, databases, caches, APK build artifacts, or customer meeting audio. Production deployment remains internal.

## 14. Testing And Acceptance

Recording reliability:

- Long recording does not lose data.
- Background/lock screen behavior follows policy.
- App close saves the current segment.
- Network loss does not affect local recording.
- Network recovery uploads pending segments.

Server processing:

- One-hour meeting can be processed.
- GPU concurrency is controlled.
- Jobs survive worker restart in production architecture.
- Failed segments are diagnosable and retryable.

Login and permissions:

- Unauthenticated users cannot access business pages.
- Unauthorized users cannot read others' meetings.
- Expired tokens require refresh or re-login.
- Admin privileges are separately controlled.

Web:

- Search, edit transcript, batch rename speakers, export Word/PDF/Markdown/JSON/SRT, and download latest APK.

## 15. Open-Source Reuse Conclusion

Reuse components, not whole meeting apps:

- Prefer Apache-2.0/MIT for production.
- Treat GPL/AGPL projects as architecture references unless the company accepts license obligations.
- Keep the recording path self-owned.
- Reference Whishper's service split, but do not copy AGPL code.
- Evaluate sherpa-onnx and whisper.cpp first for local ASR.
