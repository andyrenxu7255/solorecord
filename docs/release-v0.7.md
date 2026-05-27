# SoloRecord V0.7 发布说明

## 中文

SoloRecord V0.7 是公司内部会议记录系统的首个可部署交付版，包含 Android APK、服务端 API、Web 管理/PC 端、文档和自动化验收脚本。

### 主要能力

- Android App 三页签：录音、记录、登录状态。
- 群晖/公司统一登录链路：Web 回调后可回跳 Android `solorecord://auth/callback`。
- 滚动分段录音：点击开始后本地即时保存，结束或关闭 App 时停止并尽量保存最后一段。
- 服务器权威存储：保存登录用户名、会议、音频分段、转写、纪要、待办、角色名和审计日志。
- 重装 APK 后恢复：登录后可从 `/api/mobile/sync` 恢复服务器记录，并按权限下载服务器音频播放。
- Web 管理端：会议查看/编辑、转写编辑、角色改名、导出、模型配置、任务查看、APK 发布。
- 模型密钥服务端保存：APK 不包含 ASR/LLM/SSO/Hermes/ES 密钥。
- 本地 ASR 命令适配器：可接入自建 ASR，标准 JSON 输出即可。
- LLM 纪要适配器：支持 mock、Ollama、OpenAI 兼容接口和内部模型。
- 外部系统接口：Hermes/CRM 等可通过服务端 token 拉取会议数据。
- 可选 ES/OpenSearch 索引。

### 验收状态

- 服务端主流程测试通过。
- HTTP 端到端 smoke 通过，覆盖登录、上传、受权限保护的音频下载、处理、转写、角色改名、同步、外部 API、导出和 APK 发布下载。
- Android `assembleDebug` 通过。
- `pip check` 通过。
- `pip-audit -r server/requirements.txt --timeout 60` 无已知漏洞。
- Web 页面打开验证通过。
- Git 提交边界检查通过，未提交 `server/.env`、`var/`、`.venv`、APK、数据库或缓存文件。

### 部署提醒

- 正式部署前必须修改 `SOLO_SECRET_KEY`。
- 正式环境关闭 `SOLO_ALLOW_DEMO_LOGIN`。
- 配置 HTTPS、群晖 SSO 回调、本地 ASR、LLM、备份和外部 API token。
- 代码仓库可以公开，但必须确认没有提交真实密钥、`server/.env`、运行数据、数据库、缓存、APK 构建产物或客户会议音频；生产部署仍按公司内部系统管控。

## English

SoloRecord V0.7 is the first deployable internal release of the company meeting recorder. It includes the Android APK source, server API, Web admin/PC UI, documentation, and automated verification scripts.

### Highlights

- Android app with three tabs: recording, records, and login status.
- Synology/company SSO flow: Web callback can return to Android through `solorecord://auth/callback`.
- Rolling segmented recording: local audio is saved immediately after start; ending or closing the app stops recording and preserves the last segment as far as possible.
- Server-authoritative storage: user identity, meetings, audio segments, transcripts, summaries, action items, speaker names, and audit logs are stored server-side.
- APK reinstall recovery: after login, the app can restore records through `/api/mobile/sync` and download protected server audio segments for playback.
- Web admin: meeting review/editing, transcript editing, speaker rename, exports, model configuration, job view, and APK publishing.
- Server-side secrets: the APK does not contain ASR, LLM, SSO, Hermes, or ES credentials.
- Local ASR command adapter: any local ASR runtime can be integrated by printing standard JSON.
- LLM summary adapter: mock, Ollama, OpenAI-compatible, and internal providers are supported.
- External integration API: Hermes/CRM systems can pull meeting data with server-side bearer tokens.
- Optional ES/OpenSearch indexing.

### Verification

- Server regression test passed.
- HTTP end-to-end smoke passed, covering login, upload, protected audio download, processing, transcript fetch, speaker rename, sync, external API, export, and APK release download.
- Android `assembleDebug` passed.
- `pip check` passed.
- `pip-audit -r server/requirements.txt --timeout 60` found no known vulnerabilities.
- Web page rendering check passed.
- Git boundary checks passed; `server/.env`, `var/`, `.venv`, APKs, databases, and cache files are not committed.

### Deployment Notes

- Change `SOLO_SECRET_KEY` before production deployment.
- Disable `SOLO_ALLOW_DEMO_LOGIN` in production.
- Configure HTTPS, Synology SSO callback, local ASR, LLM, backups, and external API tokens.
- The source repository can be public, but verify that real secrets, `server/.env`, runtime data, databases, caches, APK build outputs, and customer meeting audio are not committed. Production deployments remain internal systems.
