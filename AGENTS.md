# SoloRecord Agent Guide

## Critical Rules

- Do not put real ASR, LLM, SSO, Hermes, ES, or external API secrets in source, docs, APK, Docker image, or final answers.
- Server is the authoritative data source. Android local data is cache/offline recording protection.
- ES/OpenSearch is an optional index only. Always persist business data to DB first.
- Every meeting read/write endpoint must enforce access control.
- Web dynamic text must be escaped before rendering.
- Android recording reliability has priority over on-device audio processing.
- Do not remove user changes or generated data unless explicitly requested.

## Build And Test

Server tests:

```powershell
scripts\run-tests.ps1
```

Server dev run:

```powershell
scripts\run-server.ps1
```

Android debug APK:

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug
```

APK output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

Docker smoke fallback:

```powershell
docker run --rm --name solorecord-smoke -d -p 8000:8000 `
  -w /app -v "${PWD}:/app" --env-file server/.env `
  -e PYTHONPATH=/app/server `
  python:3.12.13-slim `
  sh -c "pip install --disable-pip-version-check --timeout 120 --retries 5 --no-cache-dir -r /app/server/requirements.txt && uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000"
```

Stop smoke container:

```powershell
docker stop solorecord-smoke
```

HTTP smoke:

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

## Architecture

Components:

- Android app: `app/src/main/java/com/solorecord/`
- FastAPI server: `server/solorecord_server/`
- Static Web app: `server/static/`
- Docs: `docs/`
- Tests: `server/tests/`

Core server files:

- `main.py`: API routes.
- `db.py`: SQLite schema and migrations.
- `auth.py`: user sessions, SSO, external token auth.
- `processing.py`: ASR, summary, forwarding, indexing workflow.
- `repository.py`: full meeting document aggregation.
- `search_index.py`: ES/OpenSearch indexing.
- `asr_adapters.py`: local command ASR.
- `llm_adapters.py`: LLM summary adapters.
- `publisher.py`: Hermes/Webhook push.
- `exports.py`: export formats.

Android files:

- `MainActivity.java`: hand-built three-tab UI.
- `RollingAudioRecorder.java`: rolling local recording.
- `RecordingService.java`: foreground recording notification.
- `SoloServerClient.java`: server API calls, mobile sync, server audio download.
- `MeetingStore.java`: local cache.
- `SessionStore.java`: login/server settings.

## Data Model

Important tables:

- `users`
- `sessions`
- `meetings`
- `meeting_members`
- `audio_segments`
- `transcript_segments`
- `speakers`
- `action_items`
- `processing_jobs`
- `apk_releases`
- `app_config`
- `audit_logs`

Meeting ownership:

- `meetings.owner_id` records creator.
- `meeting_members` records readable/writable users.
- `audit_logs.actor_user_id` records who performed actions.

## API Index

Mobile sync after APK reinstall:

```text
GET /api/mobile/sync
```

Meeting:

```text
POST /api/mobile/meetings
GET  /api/mobile/meetings
GET  /api/mobile/meetings/{meetingId}
POST /api/mobile/meetings/{meetingId}/segments
POST /api/mobile/meetings/{meetingId}/segments-json
GET  /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
POST /api/mobile/meetings/{meetingId}/finish
GET  /api/mobile/meetings/{meetingId}/transcript
POST /api/mobile/meetings/{meetingId}/speakers/rename
```

External integration:

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

Admin:

```text
GET  /api/admin/providers
PUT  /api/admin/providers
GET  /api/admin/jobs
POST /api/admin/jobs/{jobId}/retry
POST /api/admin/releases
POST /api/admin/search/reindex
```

## Common Tasks

### Add A Server Field

1. Update `server/solorecord_server/db.py`.
2. Add backward-compatible migration in `init_db`.
3. Update `repository.py` if the field appears in full meeting documents.
4. Update Web/Android clients if visible.
5. Extend `server/tests/test_api.py`.

### Add A Provider Config Field

1. Update `schemas.ProviderConfig`.
2. Update `main.get_providers` and `main.update_providers` if needed.
3. Update `server/static/index.html`.
4. Update `server/static/app.js`.
5. Do not echo secrets back to browser.

### Add ASR Runtime

Prefer a sidecar command that prints standard JSON. Avoid coupling model code to the business API.

### Add Export Format

1. Update `exports.py`.
2. Add Web button in `app.js`.
3. Add test assertion.

### Add External System

Use one of:

- `publisher.py` for push.
- `/api/external/*` for pull.
- ES/OpenSearch for full-text search.

Do not let external systems read SQLite directly.

## Documentation Map

Human operations:

- `docs/human-ops/README.md`

Human development:

- `docs/human-dev/README.md`

End users:

- `docs/user/README.md`

Agent maintenance:

- `docs/agents/README.md`
- `llms.txt`

Reference:

- `docs/meeting-app-prd-v2.md`
- `docs/deployment.md`
- `docs/data-storage-and-es.md`
- `docs/local-asr-pipeline.md`
- `docs/synology-bailian-architecture.md`
- `docs/open-source-research.md`
- `docs/security-audit.md`
