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

默认 Docker Compose 构建使用轻量镜像，不安装系统媒体包。人物校对会优先请求服务器裁剪样本；如果服务器没有 `ffmpeg`，Web 会尝试在浏览器端裁剪 5-20 秒样本并播放。

如果服务器包源和磁盘空间稳定，希望由服务端统一转码试听样本，可启用 `ffmpeg`：

```bash
INSTALL_MEDIA_TOOLS=true docker compose up -d --build solorecord
```

中文 PDF 如果需要系统级 CJK 字体，可额外启用字体包：

```bash
INSTALL_CJK_FONTS=true docker compose up -d --build solorecord
```

常规轻量构建：

```bash
docker compose up -d --build solorecord
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
- LDAP 接通后关闭 `SOLO_ALLOW_DEMO_LOGIN`。
- 在 `server/.env` 中配置群晖 LDAP：`SOLO_LDAP_ENABLED=true`、`SOLO_LDAP_SERVER=ldaps://...`、`SOLO_LDAP_BIND_DN_TEMPLATE=uid=XXX,...`、`SOLO_LDAP_SEARCH_DN=...`、`SOLO_LDAP_SEARCH_FILTER=cn` 或完整过滤器、`SOLO_LDAP_EMAIL_POSTFIX=`。
- 如果拿到的是 `ldapLogin` JSON，`baseDn` 写入 `SOLO_LDAP_BIND_DN_TEMPLATE`，`searchStandard` 写入 `SOLO_LDAP_SEARCH_FILTER`；不要保存 `bindPassword`，登录时使用用户输入的密码。
- 若目录要求服务账号先搜索真实用户 DN，再用用户密码校验，才配置 `SOLO_LDAP_LOOKUP_BIND_DN` 和 `SOLO_LDAP_LOOKUP_BIND_PASSWORD`。
- 如果后续改走浏览器统一登录，再配置群晖 SSO/OIDC、注册 Web 回调 `https://record.example.com/api/auth/sso/callback`，Android 回跳 `solorecord://auth/callback`。
- 在 `8000` 端口前放 Nginx/Caddy HTTPS。
- 将 `/downloads/android/*` 限制为登录用户或内网访问。
- 将 `var/` 挂载到持久磁盘。
- 如果使用 GPU ASR，安装 NVIDIA driver 和 container runtime。
- 在 Web 管理页配置 ASR Provider。
- 通过 Web 管理页上传第一个 APK。
- 公开 GitHub Release 附件 APK 不包含真实服务器地址或密钥；内部分发时用 `-PSOLO_SERVER_ENDPOINT=https://record.example.com` 重新构建，再上传到 Web 管理端发布中心。

如果启用可选 `full` Compose profile，`server/.env` 还必须包含真实 `POSTGRES_PASSWORD` 和 `MINIO_ROOT_PASSWORD`，生产环境不能使用占位密码。

## ASR Provider 模式

- `mock`：默认模式，生成占位转写，用于测试完整闭环。
- `sherpa-onnx`：推荐优先评估的本地 ASR runtime。
- `whisper.cpp`：推荐作为 ASR 质量基准或备选 runtime。
- `command`：自定义本地 ASR 脚本/二进制命令适配器。
- `openai-compatible`：OpenAI 兼容远程 STT 服务，调用 `/audio/transcriptions`。
- `funasr`：FunASR 兼容服务，优先调用 `/audio/transcriptions`，404 时回退 `/asr`。
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

## 远程 STT / FunASR 兼容服务

如果 ASR 已经由独立服务提供，推荐使用服务器端远程 STT 适配器，而不是把模型 key 写进 APK。

```text
SOLO_ASR_PROVIDER=funasr
SOLO_ASR_ENDPOINT=http://asr.example.com/v1
SOLO_ASR_API_KEY=
SOLO_ASR_MODEL=funasr-paraformer-zh
```

说明：

- `SOLO_ASR_PROVIDER` 可填 `openai-compatible`、`remote-stt` 或 `funasr`。
- Endpoint、API Key 和 Model 只写在服务器本地 `server/.env` 或 Web 管理端，不写入源码、文档、APK 或 Docker 镜像。
- 服务端会用 multipart 上传音频文件，字段名优先为 `file`；如果 `/audio/transcriptions` 返回 404，会尝试 `/asr`，字段名为 `audio`。
- 支持返回 `{ "text": "..." }`、`transcript`、`result`、`data` 或 `segments` 数组。
- 如果远程 STT 返回空文本，服务端会生成带 `empty_asr` 标记的占位转写，保留会议记录可用性，方便人工复核。

## ASR 后语义重分段

如果 ASR 服务返回原生说话人字段，SoloRecord 会直接使用。如果只返回单段文本或单一发言人，服务端会调用已配置的 LLM 进行语义重分段和发言人推断；LLM 不可用时，会用规则兜底拆分“张三说”“李四：”这类明确标记。

```text
SOLO_ENABLE_SEMANTIC_SEGMENTATION=true
```

每个上传分段会先生成阶段转写；点击结束会议后，服务端会基于整场上下文再整理一次最终时间线并写回数据库。

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

By default, Docker Compose uses a lightweight image and does not install OS
media packages. The people calibration UI first requests a server-side clipped
sample; when `ffmpeg` is not installed, the Web UI tries to clip the 5-20 second
sample in the browser before playback.

If the server package mirror and disk capacity are ready, enable `ffmpeg` for
server-side sample transcoding:

```bash
INSTALL_MEDIA_TOOLS=true docker compose up -d --build solorecord
```

If Chinese PDF export needs system CJK fonts, enable the font package
explicitly:

```bash
INSTALL_CJK_FONTS=true docker compose up -d --build solorecord
```

Regular lightweight build:

```bash
docker compose up -d --build solorecord
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
- Disable `SOLO_ALLOW_DEMO_LOGIN` after LDAP is connected.
- Configure Synology LDAP in `server/.env`: `SOLO_LDAP_ENABLED=true`,
  `SOLO_LDAP_SERVER=ldaps://...`, `SOLO_LDAP_BIND_DN_TEMPLATE=uid=XXX,...`,
  `SOLO_LDAP_SEARCH_DN=...`, `SOLO_LDAP_SEARCH_FILTER=cn` or a full filter,
  and `SOLO_LDAP_EMAIL_POSTFIX=`.
- If you receive a `ldapLogin` JSON object, map `baseDn` to
  `SOLO_LDAP_BIND_DN_TEMPLATE` and `searchStandard` to
  `SOLO_LDAP_SEARCH_FILTER`. Do not store `bindPassword`; user-entered login
  passwords are used for LDAP bind.
- Configure `SOLO_LDAP_LOOKUP_BIND_DN` and `SOLO_LDAP_LOOKUP_BIND_PASSWORD`
  only if the directory requires a service account lookup before validating the
  user's password.
- If browser unified login is enabled later, configure Synology SSO/OIDC,
  register `https://record.example.com/api/auth/sso/callback`, and keep the
  Android return URI `solorecord://auth/callback`.
- Put Nginx/Caddy with HTTPS in front of port `8000`.
- Restrict `/downloads/android/*` to logged-in users or internal network.
- Mount `var/` to persistent disk.
- Install NVIDIA driver and container runtime if using GPU ASR.
- Configure ASR provider from the Web admin page.
- Upload first APK from Web admin page.

If the optional `full` Compose profile is enabled, `server/.env` must also
contain real `POSTGRES_PASSWORD` and `MINIO_ROOT_PASSWORD` values. Do not use
placeholder passwords in production.

For the public GitHub Release APK, no real server URL or secret is embedded. For internal distribution, rebuild with:

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug -PSOLO_SERVER_ENDPOINT=https://record.example.com
```

Then upload `app/build/outputs/apk/debug/app-debug.apk` from the Web admin release page.

## ASR Provider Modes

- `mock`: default. Generates placeholder transcript so the whole system can be tested.
- `sherpa-onnx`: recommended first real local ASR runtime.
- `whisper.cpp`: recommended ASR benchmark or alternative runtime.
- `command`: command adapter for a custom local ASR script.
- `openai-compatible`: OpenAI-compatible remote STT service using `/audio/transcriptions`.
- `funasr`: FunASR-compatible service; tries `/audio/transcriptions` first and falls back to `/asr` on 404.
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

## Remote STT / FunASR-Compatible Service

If ASR is already exposed as a separate service, use the server-side remote STT
adapter instead of putting model keys in the APK.

```text
SOLO_ASR_PROVIDER=funasr
SOLO_ASR_ENDPOINT=http://asr.example.com/v1
SOLO_ASR_API_KEY=
SOLO_ASR_MODEL=funasr-paraformer-zh
```

Notes:

- `SOLO_ASR_PROVIDER` can be `openai-compatible`, `remote-stt`, or `funasr`.
- Endpoint, API key, and model belong only in server-local `server/.env` or the Web admin configuration, never in source, docs, APKs, or Docker images.
- The server uploads audio as multipart with field `file`; if `/audio/transcriptions` returns 404, it tries `/asr` with field `audio`.
- Responses can use `text`, `transcript`, `result`, `data`, or a `segments` array.
- Empty STT text is saved as a traceable `empty_asr` placeholder transcript so the meeting remains usable for review.

## Semantic Re-Segmentation After ASR

If ASR returns native speaker fields, SoloRecord uses them directly. If ASR
returns only one text block or a single speaker, the server calls the configured
LLM for semantic re-segmentation and speaker inference. If the LLM is
unavailable, a rule fallback splits clear markers such as “Alice said” or
“Bob:”.

```text
SOLO_ENABLE_SEMANTIC_SEGMENTATION=true
```

Each uploaded segment receives partial transcript post-processing first. When
the meeting is finished, the server refines the final timeline with full-meeting
context and writes it back to the database.

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
