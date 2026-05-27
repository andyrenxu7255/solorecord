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
