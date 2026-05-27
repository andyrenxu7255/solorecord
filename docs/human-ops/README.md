# SoloRecord 运维手册

## 适用读者

本手册给负责部署、维护、备份、权限和故障处理的人看。你不需要读 Android 或前端代码，也能完成服务器上线和日常运维。

## 系统组成

SoloRecord 由三部分组成：

- Android APK：员工录音、查看记录、同步到服务器。
- 服务端 API：登录、会议、音频、转写、纪要、待办、导出、APK 发布。
- Web 管理端：会议管理、模型配置、任务队列、APK 下载/发布、外部接口配置。

服务端是权威数据源。APK 本地只保存录音和缓存；重装 APK 后，用户重新登录即可通过服务器同步记录。

## 部署路径

推荐先用单机部署跑通：

```text
Nginx/Caddy HTTPS
        |
SoloRecord FastAPI :8000
        |
SQLite + var/storage + var/apk
```

生产稳定后再扩展：

```text
Nginx/Caddy HTTPS
        |
SoloRecord API + Worker
        |
PostgreSQL + NAS/S3/Object Storage + ES/OpenSearch
        |
Local ASR/LLM + Hermes/Sales Workspace
```

## 服务器准备

最低建议：

- Linux 服务器或 Windows 服务器均可，优先 Linux。
- CPU 4 核以上，内存 8 GB 以上。
- 磁盘按会议音频量预估，建议从 500 GB 起。
- 如果本地 ASR 需要 GPU，ASR 服务单独部署到 GPU 主机。
- HTTPS 域名，用于 Web、APK 下载和 SSO 回调。

必须准备：

- 群晖 SSO/OIDC 应用信息。
- SoloRecord 服务域名。
- 本地 ASR 命令或服务地址。
- LLM 模型接口，可是 Ollama、OpenAI 兼容接口或公司内网模型。
- Hermes/销售工作区 Webhook 或外部拉取 token。

## 首次启动

Windows 本地：

```powershell
scripts\run-server.ps1
```

Linux：

```bash
cp server/.env.example server/.env
python3 -m venv .venv
. .venv/bin/activate
pip install -r server/requirements.txt
PYTHONPATH=server uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000
```

Docker：

```bash
cp server/.env.example server/.env
docker compose up -d --build solorecord
```

如果 Windows 本地 Docker 构建卡住，可先用挂载源码方式验证：

```powershell
docker run --rm --name solorecord-smoke -d -p 8000:8000 `
  -w /app -v "${PWD}:/app" --env-file server/.env `
  -e PYTHONPATH=/app/server `
  python:3.12.13-slim `
  sh -c "pip install --disable-pip-version-check --timeout 120 --retries 5 --no-cache-dir -r /app/server/requirements.txt && uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000"
```

启动后跑完整链路验收：

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

## 必改配置

`server/.env` 至少修改：

```text
SOLO_BASE_URL=https://record.example.com
SOLO_SECRET_KEY=换成足够长的随机字符串
SOLO_ALLOW_DEMO_LOGIN=false
SOLO_DATABASE_PATH=var/solorecord.db
SOLO_STORAGE_DIR=var/storage
SOLO_APK_DIR=var/apk
SOLO_STATIC_DIR=server/static
```

内网演示阶段可以临时保留：

```text
SOLO_ALLOW_DEMO_LOGIN=true
```

演示完成后关闭。

如果启用 Docker Compose 的 `full` profile，还要把 `server/.env.example`
里的 `POSTGRES_PASSWORD` 和 `MINIO_ROOT_PASSWORD` 换成长随机值。

## 群晖 SSO 配置

推荐使用 OIDC。

需要在群晖 SSO 里注册：

- Client ID
- Client Secret
- Redirect URI：`https://record.example.com/api/auth/sso/callback`
- Scope：通常是 `openid email`

Android App 不保存群晖密钥。App 点击“登录”后会打开系统浏览器访问服务端 SSO 起始地址，并带上：

```text
redirect_after=solorecord://auth/callback
```

服务端完成群晖登录后会把短期 SoloRecord 会话 token 回跳给 App。正式环境关闭 `SOLO_ALLOW_DEMO_LOGIN` 后，手机端仍然可以通过这条统一登录链路登录。

服务端配置：

```text
SOLO_SSO_VERIFY_MODE=oidc
SOLO_SSO_ISSUER=https://sso.example.com
SOLO_SSO_CLIENT_ID=你的ClientID
SOLO_SSO_CLIENT_SECRET=你的ClientSecret
SOLO_SSO_REDIRECT_URI=https://record.example.com/api/auth/sso/callback
SOLO_SSO_SCOPE=openid email
SOLO_SSO_AUTHORIZE_URL=
SOLO_SSO_TOKEN_URL=
SOLO_SSO_USERINFO_URL=
SOLO_SSO_JWKS_URL=
```

如果群晖页面能给出完整 OIDC discovery 或 endpoint URL，优先填显式 URL。否则系统会按 Synology 风格从 `SOLO_SSO_ISSUER` 推导：

```text
/webman/sso/SSOOauth.cgi
/webman/sso/SSOAccessToken.cgi
```

## ASR 配置

默认 `mock` 模式用于跑通闭环：

```text
SOLO_ASR_PROVIDER=mock
```

接入本地 ASR 时，推荐使用命令适配器：

```text
SOLO_ASR_PROVIDER=command
SOLO_ASR_COMMAND=python /opt/solorecord-asr/run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
```

命令必须向 stdout 输出 JSON：

```json
{
  "segments": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "发言人 1",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "我们今天确认报价方案。",
      "confidence": 0.91
    }
  ]
}
```

可用占位符：

- `{audio}`：第一段音频路径。
- `{audio_json}`：全部音频路径 JSON 数组。
- `{audios}`：全部音频路径用空格拼接。
- `{meeting_id}`：会议 ID。
- `{sample_rate}`：目标采样率。
- `{diarization}`：是否启用说话人分离。
- `{denoise}`：是否启用降噪。

## LLM 配置

默认 `mock` 生成占位纪要：

```text
SOLO_LLM_PROVIDER=mock
```

Ollama：

```text
SOLO_LLM_PROVIDER=ollama
SOLO_LLM_ENDPOINT=http://127.0.0.1:11434
SOLO_LLM_MODEL=qwen3
```

OpenAI 兼容接口：

```text
SOLO_LLM_PROVIDER=openai-compatible
SOLO_LLM_ENDPOINT=https://model.example.com/v1
SOLO_LLM_API_KEY=
SOLO_LLM_MODEL=qwen3
```

真实 API Key 只填在服务端 `server/.env` 或密钥管理系统里，不要写进 APK。

## 外部系统调用

Hermes 或其他内部系统可以通过外部 API 拉取记录：

```text
SOLO_EXTERNAL_API_TOKENS=hermes:换成长随机token,crm:另一个token
```

接口：

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

请求头：

```text
Authorization: Bearer 换成长随机token
```

## ES/OpenSearch

ES/OpenSearch 是可选检索层，不是唯一数据源。

配置：

```text
SOLO_ES_ENABLED=true
SOLO_ES_URL=http://127.0.0.1:9200
SOLO_ES_INDEX=solorecord_meetings
SOLO_ES_API_KEY=
SOLO_ES_USERNAME=
SOLO_ES_PASSWORD=
```

重建索引：

```text
POST /api/admin/search/reindex
```

需要管理员登录。

## APK 发布

管理员登录 Web 后进入“管理”页上传 APK：

- 版本名：例如 `1.0.0`
- 版本号：整数，递增
- 更新说明
- 是否强制更新
- APK 文件

用户在 Web 的“App 下载”页下载。App 的登录状态页也会提示从 Web 下载最新 APK。

App 重装后，本机缓存会清空，但服务器记录不丢失。用户重新登录后可在“录音”或“记录”页点击“从服务器恢复记录”。恢复后的记录带服务器音频下载地址；播放时会按用户权限下载音频分段再播放。

## 数据目录

默认目录：

```text
var/solorecord.db
var/storage/
var/apk/
```

必须备份：

- `var/solorecord.db`
- `var/storage/`
- `var/apk/`
- `server/.env`

不要把 `server/.env` 发给外部人员或放进镜像。

## 备份建议

每日备份：

- SQLite 数据库文件。
- 音频和导出文件。
- APK 发布文件。

备份前建议暂停写入或使用数据库一致性备份。生产长期运行建议迁移 PostgreSQL。

## 健康检查

服务健康：

```text
GET /api/health
```

返回：

```json
{"status":"ok","app":"SoloRecord"}
```

Web 首页：

```text
GET /
GET /styles.css
GET /app.js
```

## 常见故障

### 登录跳转失败

检查：

- `SOLO_BASE_URL`
- `SOLO_SSO_REDIRECT_URI`
- 群晖 SSO 应用里的回调地址
- Nginx/Caddy 是否正确转发 HTTPS Host

### App 无法同步

检查：

- App 登录状态页里的服务器地址。
- 服务器是否能访问。
- Token 是否过期。
- `GET /api/mobile/sync` 是否返回数据。

### 转写一直失败

检查：

- `SOLO_ASR_PROVIDER`
- `SOLO_ASR_COMMAND`
- ASR 命令在服务器上是否可执行。
- ASR stdout 是否是合法 JSON。
- `processing_jobs.error_message`

### 纪要为空或占位

检查：

- `SOLO_LLM_PROVIDER`
- `SOLO_LLM_ENDPOINT`
- `SOLO_LLM_MODEL`
- `SOLO_LLM_API_KEY`

如果 LLM 未配置，系统会回退 mock 纪要。

### PDF 中文显示异常

生产镜像构建时安装 CJK 字体：

```bash
docker compose build --build-arg INSTALL_MEDIA_TOOLS=true solorecord
```

### Docker 构建卡住

本地 Windows 可先用挂载源码方式 smoke。生产服务器建议使用 Linux Docker 构建。

## 上线前检查清单

- `SOLO_SECRET_KEY` 已更换。
- `SOLO_ALLOW_DEMO_LOGIN=false`。
- HTTPS 已启用。
- SSO 回调已验证。
- ASR 命令或服务已验证。
- LLM 配置已验证。
- `var/` 已挂到持久磁盘。
- 备份任务已配置。
- 外部 API token 已换成长随机值。
- APK 已上传并可下载。
- 测试用户完成统一登录、录音、上传、转写、改名、导出、从服务器恢复记录、下载播放服务器音频。
- `scripts\smoke-e2e.ps1` 已通过。
- `pip-audit -r server/requirements.txt` 无已知漏洞。
