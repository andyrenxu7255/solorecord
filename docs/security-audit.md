# 安全审计记录

日期：2026-05-27

## 当前内部构建状态

本项目当前是可运行的公司内部原型，包含：

- Android APK 源码和 debug APK 构建能力。
- FastAPI 服务端。
- 静态 Web 应用。
- SQLite 默认持久化。
- 本地文件存储。
- demo 登录。
- mock ASR 兜底。
- 已更新的 Python 安全依赖。

## 生产前必须修改

- 修改 `SOLO_SECRET_KEY`。
- 关闭 `SOLO_ALLOW_DEMO_LOGIN`。
- 配置群晖 LDAP；如果启用浏览器统一登录，再配置群晖 SSO 并在服务端验证 token。
- 在服务前启用 HTTPS。
- 将 APK 下载路径限制为登录用户或内网访问。
- ASR/LLM 凭证只放到服务端 `.env` 或密钥管理系统。
- 为 `var/` 配置备份。
- 审核音频和转写的数据保留策略。

## 已加入的代码级控制

- APK 不包含 ASR/LLM 密钥。
- 服务端持有 ASR/LLM/Hermes 配置。
- Web 管理端不把已保存 LLM/Hermes 密钥回显到浏览器。
- 会议读写检查成员权限。
- 服务器音频分段下载使用同一会议权限检查。
- LDAP 用户名在 DN 和搜索过滤器中使用标准转义；SSO 回跳目标限制为本地路径或 `solorecord://auth/callback`。
- 说话人改名按稳定 speaker id 更新全部匹配转写行。
- 上传 APK 保存 SHA-256。
- 审计日志记录登录相邻业务动作和管理变更。
- Web 渲染动态文本前转义。
- 默认 mock ASR 让模型凭证可选。
- 本地 ASR 命令适配器不走 shell 展开，并要求 JSON stdout。

## 已知原型风险

- demo 登录为首轮部署测试有意开启。
- SQLite 适合初期内网验证，多用户生产建议迁移 PostgreSQL。
- Android 原型保留 Base64 JSON 上传，长会议建议改 multipart 或断点续传。
- PDF 导出使用简单绘制，服务器字体未安装时中文渲染可能不完美。
- 原型处理任务在 API 进程同步执行，高并发前应改 Redis/Celery/RQ/BullMQ worker。
- Android 当前由 Activity 控制 MediaRecorder，并使用前台通知服务；满足“关闭 App 停止录音”。如果未来要求 UI 被杀后仍持续后台录音，需要把 recorder 所有权完全迁移到 Service。
- Android session token 当前保存在 SharedPreferences，广泛推广前建议迁移 EncryptedSharedPreferences/Android Keystore。

## 已执行验证

- `scripts\run-tests.ps1` 通过，包含 LDAP 登录、DN/过滤器转义和权限主流程。
- Gradle `assembleDebug` 通过。
- `pip check` 通过。
- `pip-audit -r server/requirements.txt --timeout 60` 无已知漏洞。
- HTTP smoke 通过，覆盖健康检查、Web 静态资源、匿名拒绝、demo 登录、会议创建、音频上传、受保护音频下载、处理、转写、说话人改名、移动端同步、外部 API、Markdown 导出、APK 发布和 APK 下载。
- Secret scan 未发现真实云厂商/模型 key，仅测试文件中有故意占位 token。
- APK 输出：`app/build/outputs/apk/debug/app-debug.apk`。
- Linux 容器 smoke 已用 `python:3.12.13-slim`、挂载源码和锁定 requirements 验证通过。

## Docker 构建说明

Windows 本地 Docker BuildKit/build 输出在 PyPI 下载较慢时可能超过本地超时。Dockerfile 已固定 Python base image，并设置 pip timeout/retry。生产 Linux 部署仍建议使用：

```bash
docker compose up -d --build solorecord
```

慢网络本地验证时，使用文档中的 `python:3.12.13-slim` 挂载源码 smoke 路径，再运行：

```powershell
scripts\smoke-e2e.ps1
```

## 公开仓库安全边界

源码和文档可以公开，但发布前必须确认未提交真实密钥、LDAP 凭据、`server/.env`、运行数据、数据库、缓存、APK 构建产物或客户会议音频。生产部署仍是公司内部系统，必须由 HTTPS、LDAP/SSO、服务端权限和内网策略保护。

## English

# Security Audit Notes

Date: 2026-05-27

## Current Internal Build Status

This project is now an internal runnable prototype with:

- Android APK source and debug APK build.
- FastAPI server.
- Static Web app.
- SQLite default persistence.
- Local file storage.
- Demo login.
- Mock ASR fallback.
- Security-updated Python dependencies.

## Must Change Before Production

- Change `SOLO_SECRET_KEY`.
- Disable `SOLO_ALLOW_DEMO_LOGIN`.
- Configure Synology LDAP. If browser unified login is enabled, configure Synology SSO and verify tokens server-side.
- Put HTTPS in front of the server.
- Restrict APK download path to logged-in users or internal network.
- Move ASR/LLM credentials to server `.env` or secret manager only.
- Configure backups for `var/`.
- Review data retention defaults for audio and transcript storage.

## Code-Level Controls Already Added

- APK does not contain ASR/LLM secret keys.
- Server owns ASR/LLM/Hermes configuration.
- Web admin does not echo saved LLM/Hermes secrets back to the browser.
- Meeting reads/writes check membership.
- Server-side audio segment download checks the same meeting membership.
- LDAP usernames are escaped for DN and search filters. SSO return targets are limited to local paths or `solorecord://auth/callback`.
- Speaker rename updates all matching transcript rows by stable speaker id.
- Uploaded APK stores SHA-256.
- Audit log records login-adjacent business actions and admin changes.
- Web escapes dynamic text before rendering.
- Service defaults to mock ASR so model credentials are optional.
- Local ASR command adapter runs without shell expansion and expects JSON stdout.

## Known Prototype Risks

- Demo login is intentionally enabled for first deployment testing.
- SQLite is fine for initial internal validation but should be migrated to
  PostgreSQL for multi-user production use.
- Base64 JSON upload is available for the Android prototype; large meetings
  should move to multipart or resumable upload.
- PDF export uses simple drawing and may not render Chinese perfectly on every
  host until server fonts are installed.
- Worker execution is synchronous in the API process for the prototype; use
  Redis/Celery/RQ/BullMQ workers before high concurrency.
- Android recording now starts a foreground notification service, while the
  MediaRecorder is still controlled by the Activity according to the current
  "close App stops recording" requirement. If future policy requires locked-
  screen/background recording after the UI is killed, move recorder ownership
  fully into the service.
- Session token is stored in Android SharedPreferences for the prototype; move
  to EncryptedSharedPreferences/Android Keystore before broad rollout.

## Verification Performed

- `scripts\run-tests.ps1`: passed on FastAPI `0.136.1`, Starlette `1.1.0`,
  `python-multipart` `0.0.29`, PyJWT `2.13.0`, pytest `9.0.3`.
- Gradle `assembleDebug`: passed.
- `pip check`: passed.
- `pip-audit -r server/requirements.txt --timeout 60`: no known vulnerabilities.
- HTTP smoke via `scripts/smoke_e2e.py`: health, Web static assets, anonymous
  auth rejection, demo login, meeting create, audio upload, protected audio
  download, processing,
  transcript fetch, speaker rename, mobile sync, external API token rejection
  and access, markdown export, APK release upload, and APK download all passed.
- Secret scan: no real cloud/model keys found; only intentional test token
  placeholders in tests/smoke scripts.
- Final APK path: `app/build/outputs/apk/debug/app-debug.apk`.
- Linux container smoke passed using `python:3.12.13-slim` with mounted source
  and offline wheelhouse install for the locked requirements.

## Docker Build Note

On the Windows local machine, Docker BuildKit/build output can exceed local
timeouts while downloading Python wheels from PyPI. The Dockerfile now uses a
pinned Python base image and explicit pip timeout/retry settings. Production
Linux deployment should still use `docker compose up -d --build solorecord`.

For local verification under slow network conditions, use the documented
`python:3.12.13-slim` mounted-source smoke path, then run
`scripts\smoke-e2e.ps1`.
