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
- Configure Synology SSO and verify tokens server-side.
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
- SSO return targets are limited to local paths or `solorecord://auth/callback`.
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
