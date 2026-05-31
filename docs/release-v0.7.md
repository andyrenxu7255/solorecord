# SoloRecord V0.7 发布说明

## 中文

SoloRecord V0.7 是公司内部会议记录系统的首个可部署交付版，包含 Android APK、服务端 API、Web 管理/PC 端、文档和自动化验收脚本。

### 主要能力

- Android App 三页签：录音、记录、登录状态。
- 群晖/公司登录链路：默认 LDAP 用户名密码登录；可选 Web SSO 回调后回跳 Android `solorecord://auth/callback`。
- 连续滚动分段录音：点击开始后以 WAV 分段本地即时保存，默认约 5 分钟一段，可由服务器配置；相邻分段约 2 秒重叠，结束或关闭 App 时停止并尽量保存最后一段。
- 在线分段转写：每个分段上传成功后立即触发该段 ASR，阶段转写持续写回同一个会议记录；结束时优先复用这些分段转写生成完整纪要和待办，避免重复跑整场 ASR。
- 弱网分段续传：音频分段本地落盘，multipart 文件流上传，已确认分段重试时跳过，重复 finish 会复用已有处理任务。
- 多源同录校对：1-8 个录音源可用同一会议编号加入；服务端按 `(source_id, source_segment_no)` 保留证据，合并关键事实一致的重复片段，设备错峰起录时可保守对齐并标记 `multi_source_time_aligned`；当至少两个来源一致且多于附近冲突来源时，主结果标记 `multi_source_majority`，少数冲突源仍保留为 `multi_source_conflict`。
- 服务器权威存储：保存登录用户名、会议、音频分段、转写、纪要、待办、角色名和审计日志。
- 重装 APK 后恢复：登录后可从 `/api/mobile/sync` 恢复服务器记录，并按权限下载服务器音频播放。
- Web 管理端：会议查看/编辑、Web 实时录音、转写编辑、角色改名、可编辑待办、按说话人/分段筛选转写、授权播放服务器音频、导出、模型配置、任务查看、多平台终端发布。
- 多平台客户端：Windows Electron 可运行包已生成并启动验证；macOS、iOS、HarmonyOS 提供 WebView 外壳工程，签名安装包需在对应官方构建机生成。
- APK Release 附件：公开附件不包含真实服务器地址和任何 token/key；内部分发时只预置服务器地址，再由 Web 管理端发布下载。
- 模型密钥服务端保存：APK 不包含 ASR/LLM/LDAP/SSO/Hermes/ES 密钥。
- ASR 适配器：支持本地命令适配器，也支持 OpenAI 兼容/FunASR 远程 STT 服务；模型密钥仅保存在服务器端。
- 空语音/空转写保护：远程 STT 返回空文本时保留可追踪占位转写，会议记录仍可查看和人工复核。
- LLM 纪要适配器：支持 mock、Ollama、OpenAI 兼容接口和内部模型。
- 外部系统接口：Hermes/CRM 等可通过服务端 token 拉取会议数据。
- 可选 ES/OpenSearch 索引。

### 验收状态

- 服务端主流程测试通过。
- HTTP 端到端 smoke 通过，覆盖登录、重叠分段上传、阶段转写、受权限保护的音频下载、处理、转写、角色改名、待办编辑、同步、外部 API、导出和多平台发布下载。
- Windows `clients/desktop/dist/win-unpacked/SoloRecord.exe` 启动 smoke 通过，`clients/desktop/release/SoloRecord-0.7.0-windows-x64.zip` 已生成。
- Android `assembleDebug` 通过。
- APK 当前约 60KB 属于预期：不内置 ASR/LLM 模型和三方重 SDK，只包含登录、录音、分段账本、同步、播放和展示逻辑。
- `pip check` 通过。
- `pip-audit -r server/requirements.txt --timeout 60` 无已知漏洞。
- Web 页面打开验证通过。
- Git 提交边界检查通过，未提交 `server/.env`、`var/`、`.venv`、APK、数据库或缓存文件。

### 部署提醒

- 正式部署前必须修改 `SOLO_SECRET_KEY`。
- 正式环境关闭 `SOLO_ALLOW_DEMO_LOGIN`。
- 配置 HTTPS、群晖 LDAP、本地 ASR、LLM、备份和外部 API token；如果启用浏览器统一登录，再配置 SSO 回调。
- 如果要让员工免填服务器地址，请用 `-PSOLO_SERVER_ENDPOINT=https://record.example.com` 重新构建 APK，再上传到服务器 Web 管理端；不要把任何 token/key 打进 APK。
- 代码仓库可以公开，但必须确认没有提交真实密钥、`server/.env`、运行数据、数据库、缓存、APK 构建产物或客户会议音频；生产部署仍按公司内部系统管控。

## English

SoloRecord V0.7 is the first deployable internal release of the company meeting recorder. It includes the Android APK source, server API, Web admin/PC UI, documentation, and automated verification scripts.

### Highlights

- Android app with three tabs: recording, records, and login status.
- Synology/company login flow: LDAP username/password login by default; optional Web SSO callback can return to Android through `solorecord://auth/callback`.
- Continuous rolling segmented recording: local WAV audio is saved immediately after start. Segments default to about five minutes, are configurable from the server, and adjacent segments keep about two seconds of overlap. Ending or closing the app stops recording and preserves the last segment as far as possible.
- Online segment transcription: each accepted segment triggers ASR immediately, and partial transcript rows are written into the same meeting record. Final stop reuses those rows when all segments are covered, then produces the full summary and action items.
- Weak-network segment resume: audio segments are stored locally, uploaded as multipart files, skipped after acknowledgement, and repeated finish calls reuse the existing processing job.
- Multi-source cross-check: 1-8 sources can join with the same meeting code. The server keeps evidence by `(source_id, source_segment_no)`, merges duplicate rows only when key facts agree, can conservatively align late-starting devices with `multi_source_time_aligned`, marks a primary row as `multi_source_majority` when at least two sources agree and outnumber nearby conflicting sources, and preserves minority disagreements as `multi_source_conflict`.
- Server-authoritative storage: user identity, meetings, audio segments, transcripts, summaries, action items, speaker names, and audit logs are stored server-side.
- APK reinstall recovery: after login, the app can restore records through `/api/mobile/sync` and download protected server audio segments for playback.
- Web admin: meeting review/editing, Web live recording, transcript editing, speaker rename, editable action items, transcript filters by speaker/source segment, authorized server-audio playback, exports, model configuration, job view, and multi-platform client publishing.
- Multi-platform clients: Windows Electron package generated and smoke-started. macOS, iOS, and HarmonyOS WebView shell projects are provided; signed packages require the matching official build machines.
- APK Release asset: the public attachment contains no real server URL or token/key. For internal distribution, embed only the server URL and publish the APK from the Web admin.
- Server-side secrets: the APK does not contain ASR, LLM, LDAP, SSO, Hermes, or ES credentials.
- ASR adapters: local command runtimes and OpenAI-compatible/FunASR remote STT services are supported; model secrets remain server-side.
- Empty-speech protection: when remote STT returns empty text, SoloRecord keeps a traceable placeholder transcript so the meeting remains reviewable.
- LLM summary adapter: mock, Ollama, OpenAI-compatible, and internal providers are supported.
- External integration API: Hermes/CRM systems can pull meeting data with server-side bearer tokens.
- Optional ES/OpenSearch indexing.

### Verification

- Server regression test passed.
- HTTP end-to-end smoke passed, covering login, overlapped segment upload, partial transcript return, protected audio download, processing, transcript fetch, speaker rename, action-item editing, sync, external API, export, and multi-platform release download.
- Windows `clients/desktop/dist/win-unpacked/SoloRecord.exe` smoke-started successfully, and `clients/desktop/release/SoloRecord-0.7.0-windows-x64.zip` was generated.
- Android `assembleDebug` passed.
- The APK is roughly 60KB by design because ASR/LLM models and heavy third-party SDKs are not embedded; it contains login, recording, upload ledger, sync, playback, and display logic.
- `pip check` passed.
- `pip-audit -r server/requirements.txt --timeout 60` found no known vulnerabilities.
- Web page rendering check passed.
- Git boundary checks passed; `server/.env`, `var/`, `.venv`, APKs, databases, and cache files are not committed.

### Deployment Notes

- Change `SOLO_SECRET_KEY` before production deployment.
- Disable `SOLO_ALLOW_DEMO_LOGIN` in production.
- Configure HTTPS, Synology LDAP, local ASR, LLM, backups, and external API tokens. Configure SSO callback only if browser unified login is enabled.
- To avoid asking employees to type the server URL, rebuild with `-PSOLO_SERVER_ENDPOINT=https://record.example.com`, then upload that APK from the server Web admin. Never put tokens or keys into the APK.
- The source repository can be public, but verify that real secrets, `server/.env`, runtime data, databases, caches, APK build outputs, and customer meeting audio are not committed. Production deployments remain internal systems.
