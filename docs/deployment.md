# SoloRecord 部署参考

## Windows 开发机快速启动

```powershell
scripts\run-server.ps1
```

打开：

```text
http://127.0.0.1:8000
```

演示管理员账号：

```text
admin@example.com
```

## Linux 服务器快速启动

```bash
cp server/.env.example server/.env
python3 -m venv .venv
. .venv/bin/activate
pip install -r server/requirements.txt
PYTHONPATH=server uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
cp server/.env.example server/.env
docker compose up -d --build solorecord
```

首次部署默认使用 SQLite 和 `var/` 下的本地文件存储。

默认 Docker 镜像会跳过较大的可选系统包，方便本地 smoke 更快完成。如果生产 ASR 需要 `ffmpeg`，或 PDF 导出需要 CJK 字体，使用：

```bash
docker compose build --build-arg INSTALL_MEDIA_TOOLS=true solorecord
docker compose up -d solorecord
```

如果 Windows 本地 Docker BuildKit 构建卡住，可用挂载源码方式验证服务：

```powershell
docker run --rm --name solorecord-smoke -d -p 8000:8000 `
  -w /app -v "${PWD}:/app" --env-file server/.env `
  -e PYTHONPATH=/app/server `
  python:3.12.13-slim `
  sh -c "pip install --disable-pip-version-check --timeout 120 --retries 5 --no-cache-dir -r /app/server/requirements.txt && uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000"
```

服务健康后运行端到端 smoke：

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

## 生产检查清单

- 修改 `SOLO_SECRET_KEY`。
- SSO 接通后关闭 `SOLO_ALLOW_DEMO_LOGIN`。
- 在 `server/.env` 中配置群晖 SSO。优先复制群晖 discovery 页面里的 authorize/token/userinfo/JWKS URL；否则服务端会按 Synology 风格推导 `/webman/sso/SSOOauth.cgi` 和 `/webman/sso/SSOAccessToken.cgi`。
- 注册 Web 回调 `https://record.example.com/api/auth/sso/callback`。Android 登录使用同一回调，再跳回 `solorecord://auth/callback`。
- 在 `8000` 端口前放 Nginx/Caddy HTTPS。
- 将 `/downloads/android/*` 限制为登录用户或内网访问。
- 将 `var/` 挂载到持久磁盘。
- 如果使用 GPU ASR，安装 NVIDIA driver 和 container runtime。
- 在 Web 管理页配置 ASR Provider。
- 通过 Web 管理页上传第一个 APK。

如果启用可选 `full` Compose profile，`server/.env` 还必须包含真实 `POSTGRES_PASSWORD` 和 `MINIO_ROOT_PASSWORD`，生产环境不能使用占位密码。

## ASR Provider 模式

- `mock`：默认模式，生成占位转写，用于测试完整闭环。
- `sherpa-onnx`：推荐优先评估的本地 ASR runtime。
- `whisper.cpp`：推荐作为 ASR 质量基准或备选 runtime。
- `command`：自定义本地 ASR 脚本/二进制命令适配器。
- `remote-qwen`：可选远程兜底。

## 本地 ASR 命令适配器

服务端可以调用任何向 stdout 输出 JSON 的本地 ASR 脚本或二进制。Web 管理页配置示例：

```text
ASR 提供方: command
ASR 命令: python /opt/solorecord-asr/run_asr.py --audio {audio} --audios-json {audio_json} --sample-rate {sample_rate}
```

支持占位符：

- `{audio}`：第一段上传音频路径。
- `{audio_json}`：全部上传音频路径 JSON 数组。
- `{audios}`：全部上传音频路径，用空格拼接。
- `{meeting_id}`：SoloRecord 会议 ID。
- `{sample_rate}`：配置的目标采样率。
- `{diarization}` / `{denoise}`：`true` 或 `false`。

期望 stdout：

```json
{
  "segments": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "发言人 1",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "我们今天确认一下报价方案。",
      "confidence": 0.91
    }
  ]
}
```

## Web 体验说明

模型配置页有意减少必填项。内部用户可以先保存最小 Provider 名称，等 ASR runtime 准备好后再补 endpoint、model、command 等细节。

## 服务端数据和 ES/OpenSearch

服务端保存转写、纪要、待办、音频元数据、会议归属、成员、任务和审计日志的权威副本。Android 可安全重装：登录后调用 `GET /api/mobile/sync` 即可从服务器重建本地记录。

服务器音频播放使用受权限保护的分段下载接口：

```text
GET /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
```

Hermes 或其他内部系统可配置：

```text
SOLO_EXTERNAL_API_TOKENS=hermes:replace-with-long-random-token
```

然后调用：

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

如需全文检索或跨应用索引，启用 ES/OpenSearch：

```text
SOLO_ES_ENABLED=true
SOLO_ES_URL=http://127.0.0.1:9200
SOLO_ES_INDEX=solorecord_meetings
```

详见 `docs/data-storage-and-es.md`。

## English

# SoloRecord Deployment

## Quick Start On Windows Dev Machine

```powershell
scripts\run-server.ps1
```

Open:

```text
http://127.0.0.1:8000
```

Demo admin login:

```text
admin@example.com
```

## Quick Start On Linux Server

```bash
cp server/.env.example server/.env
python3 -m venv .venv
. .venv/bin/activate
pip install -r server/requirements.txt
PYTHONPATH=server uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
cp server/.env.example server/.env
docker compose up -d --build solorecord
```

The first deploy uses SQLite and local file storage under `var/`.

By default, the Docker image skips large optional OS packages so local smoke
tests build quickly. If the production ASR pipeline needs `ffmpeg`, or PDF
export needs system CJK fonts, build with:

```bash
docker compose build --build-arg INSTALL_MEDIA_TOOLS=true solorecord
docker compose up -d solorecord
```

If Docker BuildKit hangs on Windows while building the image, use this smoke
test fallback to validate the service in Docker without building a custom image:

```powershell
docker run --rm --name solorecord-smoke -d -p 8000:8000 `
  -w /app -v "${PWD}:/app" --env-file server/.env `
  -e PYTHONPATH=/app/server `
  python:3.12.13-slim `
  sh -c "pip install --disable-pip-version-check --timeout 120 --retries 5 --no-cache-dir -r /app/server/requirements.txt && uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000"
```

After the service is healthy, run the end-to-end smoke:

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

## Production Checklist

- Change `SOLO_SECRET_KEY`.
- Disable `SOLO_ALLOW_DEMO_LOGIN` after SSO is connected.
- Configure Synology SSO values in `server/.env`. Prefer copying the OIDC
  authorize/token/userinfo/JWKS URLs from Synology's discovery page when
  available; otherwise the server can fall back to Synology-style
  `/webman/sso/SSOOauth.cgi` and `/webman/sso/SSOAccessToken.cgi` endpoints.
- Register the Web callback `https://record.example.com/api/auth/sso/callback`.
  Android login uses the same callback and then returns to the APK with
  `solorecord://auth/callback`.
- Put Nginx/Caddy with HTTPS in front of port `8000`.
- Restrict `/downloads/android/*` to logged-in users or internal network.
- Mount `var/` to persistent disk.
- Install NVIDIA driver and container runtime if using GPU ASR.
- Configure ASR provider from the Web admin page.
- Upload first APK from Web admin page.

If the optional `full` Compose profile is enabled, `server/.env` must also
contain real `POSTGRES_PASSWORD` and `MINIO_ROOT_PASSWORD` values. Do not use
placeholder passwords in production.

## ASR Provider Modes

- `mock`: default. Generates placeholder transcript so the whole system can be tested.
- `sherpa-onnx`: recommended first real local ASR runtime.
- `whisper.cpp`: recommended ASR benchmark or alternative runtime.
- `command`: command adapter for a custom local ASR script.
- `remote-qwen`: optional remote fallback.

## Local ASR Command Adapter

The server can call any local ASR script/binary that prints JSON to stdout.
Configure the Web admin page with:

```text
ASR 提供方: command
ASR 命令: python /opt/solorecord-asr/run_asr.py --audio {audio} --audios-json {audio_json} --sample-rate {sample_rate}
```

Supported placeholders:

- `{audio}`: first uploaded segment path.
- `{audio_json}`: JSON array of all uploaded segment paths.
- `{audios}`: all uploaded segment paths joined by spaces.
- `{meeting_id}`: SoloRecord meeting id.
- `{sample_rate}`: configured target sample rate.
- `{diarization}` / `{denoise}`: `true` or `false`.

Expected stdout:

```json
{
  "segments": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "发言人 1",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "我们今天确认一下报价方案。",
      "confidence": 0.91
    }
  ]
}
```

## Web UX Notes

The model configuration page intentionally has few required fields. Internal users can save a minimal provider name first, then progressively add endpoint/model/command details after the ASR runtime is ready.

## Server Data And ES/OpenSearch

The server stores the authoritative copy of transcript, summary, action items,
audio metadata, meeting owner, members, jobs, and audit logs. Android can be
reinstalled safely: after login it can call `GET /api/mobile/sync` to rebuild
local records from server data.

Server-side audio playback is available through the protected segment download
endpoint:

```text
GET /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
```

If Hermes or other internal systems need to pull data, configure:

```text
SOLO_EXTERNAL_API_TOKENS=hermes:replace-with-long-random-token
```

Then call:

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

If full-text search or cross-application indexing is needed, enable
ES/OpenSearch:

```text
SOLO_ES_ENABLED=true
SOLO_ES_URL=http://127.0.0.1:9200
SOLO_ES_INDEX=solorecord_meetings
```

Details are in `docs/data-storage-and-es.md`.
