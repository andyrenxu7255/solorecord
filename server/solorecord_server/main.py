from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .audit import audit
from .auth import (
    CurrentUser,
    ExternalClient,
    build_sso_authorize_url,
    create_or_get_user,
    create_session,
    exchange_sso_code,
    ldap_login as authenticate_ldap,
    require_admin,
)
from .config import get_settings
from .db import get_db, init_db
from .exports import create_export
from .processing import enqueue_transcription
from .repository import list_documents_for_external, list_documents_for_user, meeting_document
from .schemas import (
    LdapLoginRequest,
    LoginRequest,
    MeetingCreate,
    MeetingUpdate,
    ProviderConfig,
    SegmentJsonUpload,
    SpeakerRename,
    TranscriptUpdate,
)
from .search_index import index_meeting
from .utils import new_id, now_iso, row_to_dict, sha256_file

app = FastAPI(title="SoloRecord Internal API", version="0.7.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.post("/api/auth/demo-login")
def demo_login(request: LoginRequest) -> dict:
    if not settings.allow_demo_login:
        raise HTTPException(status_code=403, detail="Demo login disabled")
    role = "admin" if request.email.endswith("@admin.local") or request.email == "admin@example.com" else "user"
    user = create_or_get_user(request.display_name, request.email, role=role)
    session = create_session(user["id"])
    return {"user": user, **session}


@app.post("/api/auth/ldap-login")
def ldap_login(request: LdapLoginRequest) -> dict:
    return authenticate_ldap(request.username, request.password)


@app.get("/api/auth/sso/start")
def sso_start(redirect_after: str = "/") -> RedirectResponse:
    return RedirectResponse(build_sso_authorize_url(redirect_after))


@app.get("/api/auth/sso/callback")
def sso_callback(code: str, state: str) -> HTMLResponse:
    data = exchange_sso_code(code, state)
    redirect_after = data.pop("redirect_after", "/")
    payload = {
        "access_token": data["access_token"],
        "user": data["user"],
        "redirect_after": redirect_after,
    }
    is_app_redirect = str(redirect_after).startswith("solorecord://")
    if is_app_redirect:
        script = """
const url = new URL(payload.redirect_after || "solorecord://auth/callback");
url.searchParams.set("access_token", payload.access_token);
url.searchParams.set("display_name", payload.user.display_name || "");
url.searchParams.set("email", payload.user.email || "");
location.replace(url.toString());
"""
    else:
        script = """
localStorage.setItem("solo_token", payload.access_token);
localStorage.setItem("solo_user", JSON.stringify(payload.user));
location.replace(payload.redirect_after || "/");
"""
    return HTMLResponse(
        """
<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>SoloRecord 登录完成</title>
<body>登录完成，正在返回 SoloRecord...</body>
<script>
const payload = __PAYLOAD__;
__SCRIPT__
</script>
</html>
        """
        .replace("__PAYLOAD__", __import__("json").dumps(payload, ensure_ascii=False))
        .replace("__SCRIPT__", script)
    )


@app.get("/api/web/me")
def me(user: CurrentUser) -> dict:
    return {"user": user}


@app.get("/api/mobile/config")
def mobile_config() -> dict:
    return {
        "appName": settings.app_name,
        "serverTime": now_iso(),
        "segmentMinutes": settings.audio_segment_minutes,
        "features": {
            "speakerRename": True,
            "exports": ["markdown", "json", "srt", "docx", "pdf"],
            "apkDownload": True,
        },
    }


@app.post("/api/mobile/meetings")
@app.post("/api/web/meetings")
def create_meeting(request: MeetingCreate, user: CurrentUser) -> dict:
    meeting_id = new_id("mtg")
    title = request.title.strip() or "未命名会议"
    with get_db() as db:
        db.execute(
            """
            INSERT INTO meetings (id, title, owner_id, status, created_at, updated_at, started_at)
            VALUES (?, ?, ?, 'local_recorded', ?, ?, ?)
            """,
            (meeting_id, title, user["id"], now_iso(), now_iso(), request.started_at),
        )
        db.execute(
            "INSERT INTO meeting_members (meeting_id, user_id, role) VALUES (?, ?, 'owner')",
            (meeting_id, user["id"]),
        )
    audit(user["id"], "meeting.create", "meeting", meeting_id)
    return get_meeting(meeting_id, user)


@app.get("/api/mobile/meetings")
@app.get("/api/web/meetings")
def list_meetings(user: CurrentUser) -> dict:
    with get_db() as db:
        rows = db.execute(
            """
            SELECT meetings.*
            FROM meetings
            JOIN meeting_members ON meeting_members.meeting_id = meetings.id
            WHERE meeting_members.user_id = ? AND meetings.deleted_at IS NULL
            ORDER BY meetings.created_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return {"items": [row_to_dict(row) for row in rows]}


@app.get("/api/mobile/meetings/{meeting_id}")
@app.get("/api/web/meetings/{meeting_id}")
def get_meeting(meeting_id: str, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user)
    document = meeting_document(meeting_id)
    if not document:
        raise HTTPException(status_code=404, detail="Meeting not found")
    with get_db() as db:
        jobs = db.execute(
            "SELECT * FROM processing_jobs WHERE meeting_id = ? ORDER BY created_at DESC",
            (meeting_id,),
        ).fetchall()
    return {
        "meeting": document["meeting"],
        "owner": document["owner"],
        "members": document["members"],
        "audioSegments": document["audioSegments"],
        "speakers": document["speakers"],
        "actionItems": document["actionItems"],
        "jobs": [row_to_dict(row) for row in jobs],
    }


@app.get("/api/mobile/meetings/{meeting_id}/segments/{segment_no}/audio")
@app.get("/api/web/meetings/{meeting_id}/segments/{segment_no}/audio")
def download_audio_segment(meeting_id: str, segment_no: int, user: CurrentUser) -> FileResponse:
    _assert_access(meeting_id, user)
    with get_db() as db:
        row = db.execute(
            """
            SELECT * FROM audio_segments
            WHERE meeting_id = ? AND segment_no = ?
            """,
            (meeting_id, segment_no),
        ).fetchone()
    if not row or not Path(row["storage_path"]).exists():
        raise HTTPException(status_code=404, detail="Audio segment not found")
    return FileResponse(
        row["storage_path"],
        filename=row["file_name"] or f"part_{segment_no:04d}.m4a",
        media_type=row["mime_type"] or "application/octet-stream",
    )


@app.patch("/api/web/meetings/{meeting_id}")
def update_meeting(meeting_id: str, request: MeetingUpdate, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user, write=True)
    fields = []
    values = []
    for key in ("title", "summary", "role_notes"):
        value = getattr(request, key)
        if value is not None:
            fields.append(f"{key} = ?")
            values.append(value)
    if fields:
        fields.append("updated_at = ?")
        values.append(now_iso())
        values.append(meeting_id)
        with get_db() as db:
            db.execute(f"UPDATE meetings SET {', '.join(fields)} WHERE id = ?", values)
    audit(user["id"], "meeting.update", "meeting", meeting_id)
    _try_index(meeting_id)
    return get_meeting(meeting_id, user)


@app.post("/api/mobile/meetings/{meeting_id}/segments")
async def upload_segment(
    meeting_id: str,
    user: CurrentUser,
    segment_no: int = Form(...),
    start_ms: int = Form(0),
    end_ms: int = Form(0),
    duration_ms: int = Form(0),
    file: UploadFile = File(...),
) -> dict:
    _assert_access(meeting_id, user, write=True)
    meeting_dir = settings.storage_dir / "meetings" / meeting_id / "audio"
    meeting_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or f"part_{segment_no:04d}.m4a").name
    path = meeting_dir / f"part_{segment_no:04d}_{safe_name}"
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)
    digest = sha256_file(path)
    segment_id = new_id("aud")
    with get_db() as db:
        db.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, segment_no, file_name, storage_path, mime_type, size_bytes, sha256,
             duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)
            ON CONFLICT(meeting_id, segment_no)
            DO UPDATE SET storage_path=excluded.storage_path, size_bytes=excluded.size_bytes,
                sha256=excluded.sha256, duration_ms=excluded.duration_ms, end_ms=excluded.end_ms,
                upload_status='uploaded'
            """,
            (
                segment_id,
                meeting_id,
                segment_no,
                safe_name,
                str(path),
                file.content_type or "application/octet-stream",
                path.stat().st_size,
                digest,
                duration_ms,
                start_ms,
                end_ms,
                now_iso(),
            ),
        )
        db.execute(
            "UPDATE meetings SET status='uploaded', updated_at=?, duration_ms=max(duration_ms, ?) WHERE id=?",
            (now_iso(), end_ms, meeting_id),
        )
    audit(user["id"], "audio.upload", "meeting", meeting_id, {"segment_no": segment_no})
    return {"segmentNo": segment_no, "sha256": digest, "sizeBytes": path.stat().st_size}


@app.post("/api/mobile/meetings/{meeting_id}/segments-json")
def upload_segment_json(meeting_id: str, request: SegmentJsonUpload, user: CurrentUser) -> dict:
    import base64

    _assert_access(meeting_id, user, write=True)
    meeting_dir = settings.storage_dir / "meetings" / meeting_id / "audio"
    meeting_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(request.file_name or f"part_{request.segment_no:04d}.m4a").name
    path = meeting_dir / f"part_{request.segment_no:04d}_{safe_name}"
    try:
        path.write_bytes(base64.b64decode(request.audio_base64))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid audio_base64") from exc
    digest = sha256_file(path)
    segment_id = new_id("aud")
    with get_db() as db:
        db.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, segment_no, file_name, storage_path, mime_type, size_bytes, sha256,
             duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES (?, ?, ?, ?, ?, 'audio/mp4', ?, ?, ?, ?, ?, 'uploaded', ?)
            ON CONFLICT(meeting_id, segment_no)
            DO UPDATE SET storage_path=excluded.storage_path, size_bytes=excluded.size_bytes,
                sha256=excluded.sha256, duration_ms=excluded.duration_ms, end_ms=excluded.end_ms,
                upload_status='uploaded'
            """,
            (
                segment_id,
                meeting_id,
                request.segment_no,
                safe_name,
                str(path),
                path.stat().st_size,
                digest,
                request.duration_ms,
                request.start_ms,
                request.end_ms,
                now_iso(),
            ),
        )
        db.execute(
            "UPDATE meetings SET status='uploaded', updated_at=?, duration_ms=max(duration_ms, ?) WHERE id=?",
            (now_iso(), request.end_ms, meeting_id),
        )
    audit(user["id"], "audio.upload_json", "meeting", meeting_id, {"segment_no": request.segment_no})
    return {"segmentNo": request.segment_no, "sha256": digest, "sizeBytes": path.stat().st_size}


@app.post("/api/mobile/meetings/{meeting_id}/finish")
def finish_meeting(meeting_id: str, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user, write=True)
    with get_db() as db:
        existing_job = db.execute(
            """
            SELECT * FROM processing_jobs
            WHERE meeting_id = ?
              AND type = 'transcribe'
              AND status IN ('queued', 'running', 'succeeded', 'succeeded_with_publish_warning')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (meeting_id,),
        ).fetchone()
        if not existing_job:
            db.execute(
                "UPDATE meetings SET status='uploaded', ended_at=?, updated_at=? WHERE id=?",
                (now_iso(), now_iso(), meeting_id),
            )
    if existing_job:
        audit(user["id"], "meeting.finish.retry", "meeting", meeting_id, {"job_id": existing_job["id"]})
        return {"meetingId": meeting_id, "jobId": existing_job["id"], "reused": True}
    job_id = enqueue_transcription(meeting_id)
    audit(user["id"], "meeting.finish", "meeting", meeting_id, {"job_id": job_id})
    return {"meetingId": meeting_id, "jobId": job_id, "reused": False}


@app.post("/api/mobile/meetings/{meeting_id}/process")
@app.post("/api/web/meetings/{meeting_id}/process")
def process_meeting(meeting_id: str, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user, write=True)
    job_id = enqueue_transcription(meeting_id)
    audit(user["id"], "meeting.process", "meeting", meeting_id, {"job_id": job_id})
    return {"jobId": job_id}


@app.get("/api/mobile/meetings/{meeting_id}/status")
@app.get("/api/web/meetings/{meeting_id}/status")
def meeting_status(meeting_id: str, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user)
    with get_db() as db:
        meeting = db.execute("SELECT id, status, updated_at FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        job = db.execute(
            "SELECT * FROM processing_jobs WHERE meeting_id = ? ORDER BY created_at DESC LIMIT 1",
            (meeting_id,),
        ).fetchone()
    return {"meeting": row_to_dict(meeting), "job": row_to_dict(job) if job else None}


@app.get("/api/mobile/meetings/{meeting_id}/transcript")
@app.get("/api/web/meetings/{meeting_id}/transcript")
def get_transcript(meeting_id: str, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user)
    with get_db() as db:
        meeting = db.execute("SELECT version FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        rows = db.execute(
            "SELECT * FROM transcript_segments WHERE meeting_id = ? ORDER BY start_ms",
            (meeting_id,),
        ).fetchall()
    return {"version": meeting["version"], "segments": [row_to_dict(row) for row in rows]}


@app.put("/api/mobile/meetings/{meeting_id}/transcript")
@app.put("/api/web/meetings/{meeting_id}/transcript")
def update_transcript(meeting_id: str, request: TranscriptUpdate, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user, write=True)
    with get_db() as db:
        meeting = db.execute("SELECT version FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if request.version != meeting["version"]:
            raise HTTPException(status_code=409, detail="Transcript version changed, please reload")
        next_version = request.version + 1
        db.execute("DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,))
        for item in request.segments:
            db.execute(
                """
                INSERT INTO transcript_segments
                (id, meeting_id, version, speaker_id, display_name, start_ms, end_ms, text, confidence, flags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id or new_id("seg"),
                    meeting_id,
                    next_version,
                    item.speaker_id,
                    item.display_name,
                    item.start_ms,
                    item.end_ms,
                    item.text,
                    item.confidence,
                    "[]",
                    now_iso(),
                ),
            )
        db.execute("UPDATE meetings SET version=?, updated_at=? WHERE id=?", (next_version, now_iso(), meeting_id))
    audit(user["id"], "transcript.update", "meeting", meeting_id)
    _try_index(meeting_id)
    return get_transcript(meeting_id, user)


@app.post("/api/web/meetings/{meeting_id}/speakers/rename")
@app.post("/api/mobile/meetings/{meeting_id}/speakers/rename")
def rename_speaker(meeting_id: str, request: SpeakerRename, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user, write=True)
    with get_db() as db:
        db.execute(
            """
            INSERT INTO speakers (id, meeting_id, speaker_id, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(meeting_id, speaker_id)
            DO UPDATE SET display_name=excluded.display_name, updated_at=excluded.updated_at
            """,
            (new_id("spk"), meeting_id, request.speaker_id, request.display_name, now_iso(), now_iso()),
        )
        db.execute(
            "UPDATE transcript_segments SET display_name=? WHERE meeting_id=? AND speaker_id=?",
            (request.display_name, meeting_id, request.speaker_id),
        )
        db.execute("UPDATE meetings SET version=version+1, updated_at=? WHERE id=?", (now_iso(), meeting_id))
    audit(user["id"], "speaker.rename", "meeting", meeting_id, {"speaker_id": request.speaker_id})
    _try_index(meeting_id)
    return get_meeting(meeting_id, user)


@app.get("/api/mobile/sync")
@app.get("/api/web/sync")
def sync_records(user: CurrentUser, limit: int = 100, offset: int = 0) -> dict:
    documents = list_documents_for_user(user["id"], limit=limit, offset=offset)
    return {
        "user": {
            "id": user["id"],
            "display_name": user.get("display_name", ""),
            "email": user.get("email", ""),
        },
        "items": documents,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/external/meetings")
def external_meetings(client: ExternalClient, limit: int = 100, offset: int = 0) -> dict:
    return {"client": client["client"], "items": list_documents_for_external(limit=limit, offset=offset)}


@app.get("/api/external/meetings/{meeting_id}")
def external_meeting(meeting_id: str, client: ExternalClient) -> dict:
    document = meeting_document(meeting_id)
    if not document:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"client": client["client"], **document}


@app.post("/api/admin/search/reindex")
def reindex_all(user: CurrentUser) -> dict:
    require_admin(user)
    documents = list_documents_for_external(limit=500, offset=0)
    indexed = 0
    for document in documents:
        try:
            index_meeting(document["meeting"]["id"])
            indexed += 1
        except Exception:
            audit(user["id"], "index.failed", "meeting", document["meeting"]["id"])
    return {"indexed": indexed}


@app.post("/api/web/meetings/{meeting_id}/exports")
def export_meeting(meeting_id: str, export_format: str, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user)
    try:
        result = create_export(meeting_id, export_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(user["id"], "meeting.export", "meeting", meeting_id, {"format": export_format})
    return result


@app.get("/api/web/search")
def search(q: str, user: CurrentUser) -> dict:
    like = f"%{q}%"
    with get_db() as db:
        rows = db.execute(
            """
            SELECT DISTINCT meetings.*
            FROM meetings
            JOIN meeting_members ON meeting_members.meeting_id = meetings.id
            LEFT JOIN transcript_segments ON transcript_segments.meeting_id = meetings.id
            WHERE meeting_members.user_id = ?
              AND meetings.deleted_at IS NULL
              AND (meetings.title LIKE ? OR meetings.summary LIKE ? OR transcript_segments.text LIKE ?)
            ORDER BY meetings.updated_at DESC
            """,
            (user["id"], like, like, like),
        ).fetchall()
    return {"items": [row_to_dict(row) for row in rows]}


@app.get("/api/mobile/releases/latest")
@app.get("/api/web/releases/latest")
def latest_release(user: CurrentUser) -> dict:
    with get_db() as db:
        row = db.execute("SELECT * FROM apk_releases ORDER BY version_code DESC LIMIT 1").fetchone()
    if not row:
        return {"release": None}
    release = row_to_dict(row)
    release["downloadUrl"] = f"/downloads/android/{release['version_name']}/app.apk"
    return {"release": release}


@app.post("/api/admin/releases")
async def upload_release(
    user: CurrentUser,
    version_name: str = Form(...),
    version_code: int = Form(...),
    release_notes: str = Form(""),
    force_update: bool = Form(False),
    file: UploadFile = File(...),
) -> dict:
    require_admin(user)
    release_dir = settings.apk_dir / version_name
    release_dir.mkdir(parents=True, exist_ok=True)
    path = release_dir / "app.apk"
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)
    digest = sha256_file(path)
    release_id = new_id("rel")
    with get_db() as db:
        db.execute(
            """
            INSERT INTO apk_releases
            (id, version_name, version_code, file_name, storage_path, sha256, release_notes, force_update, created_at)
            VALUES (?, ?, ?, 'app.apk', ?, ?, ?, ?, ?)
            """,
            (release_id, version_name, version_code, str(path), digest, release_notes, 1 if force_update else 0, now_iso()),
        )
    audit(user["id"], "release.upload", "release", release_id)
    return {"id": release_id, "sha256": digest}


@app.get("/downloads/android/{version}/app.apk")
def download_apk(version: str) -> FileResponse:
    # Internal deployments may also restrict this path at Nginx/VPN level.
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM apk_releases WHERE version_name = ? ORDER BY version_code DESC LIMIT 1",
            (version,),
        ).fetchone()
    if not row or not Path(row["storage_path"]).exists():
        raise HTTPException(status_code=404, detail="APK not found")
    return FileResponse(row["storage_path"], filename="solorecord.apk", media_type="application/vnd.android.package-archive")


@app.get("/api/admin/providers")
def get_providers(user: CurrentUser) -> dict:
    require_admin(user)
    with get_db() as db:
        rows = db.execute("SELECT key, value, secret FROM app_config").fetchall()
    values = {row["key"]: row["value"] for row in rows}
    return {
        "config": {
            "asr_provider": values.get("asr_provider", settings.asr_provider),
            "asr_command": values.get("asr_command", settings.asr_command),
            "asr_endpoint": values.get("asr_endpoint", settings.asr_endpoint),
            "asr_api_key_set": bool(values.get("asr_api_key") or settings.asr_api_key),
            "asr_model": values.get("asr_model", settings.asr_model),
            "llm_provider": values.get("llm_provider", settings.llm_provider),
            "llm_endpoint": values.get("llm_endpoint", settings.llm_endpoint),
            "llm_api_key_set": bool(values.get("llm_api_key") or settings.llm_api_key),
            "llm_model": values.get("llm_model", settings.llm_model),
            "hermes_webhook_url": values.get("hermes_webhook_url", settings.hermes_webhook_url),
            "hermes_webhook_token_set": bool(values.get("hermes_webhook_token") or settings.hermes_webhook_token),
            "es_enabled": values.get("es_enabled", str(settings.es_enabled)).lower() == "true",
            "es_url": values.get("es_url", settings.es_url),
            "es_index": values.get("es_index", settings.es_index),
            "external_api_tokens_set": bool(values.get("external_api_tokens") or settings.external_api_tokens),
            "audio_segment_minutes": int(values.get("audio_segment_minutes", settings.audio_segment_minutes)),
            "enable_diarization": values.get("enable_diarization", "true") == "true",
            "enable_denoise": values.get("enable_denoise", "false") == "true",
            "target_sample_rate": int(values.get("target_sample_rate", "16000")),
        }
    }


@app.put("/api/admin/providers")
def update_providers(request: ProviderConfig, user: CurrentUser) -> dict:
    require_admin(user)
    values = request.model_dump()
    existing = _config_values()
    with get_db() as db:
        for key, value in values.items():
            is_secret = key in {"asr_api_key", "llm_api_key", "hermes_webhook_token", "external_api_tokens"}
            if is_secret and not str(value).strip():
                continue
            stored_value = str(value).lower() if isinstance(value, bool) else str(value)
            if is_secret and stored_value == "__KEEP__":
                stored_value = existing.get(key, "")
            db.execute(
                """
                INSERT INTO app_config (key, value, secret, updated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, secret=excluded.secret,
                    updated_at=excluded.updated_at
                """,
                (key, stored_value, 1 if is_secret else 0, now_iso()),
            )
    audit(user["id"], "providers.update", "config", "providers")
    return {"ok": True}


@app.get("/api/admin/jobs")
def admin_jobs(user: CurrentUser) -> dict:
    require_admin(user)
    with get_db() as db:
        rows = db.execute("SELECT * FROM processing_jobs ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"items": [row_to_dict(row) for row in rows]}


@app.post("/api/admin/jobs/{job_id}/retry")
def retry_job(job_id: str, user: CurrentUser) -> dict:
    require_admin(user)
    with get_db() as db:
        job = db.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    new_job = enqueue_transcription(job["meeting_id"], job["asr_provider"])
    audit(user["id"], "job.retry", "job", job_id, {"new_job": new_job})
    return {"jobId": new_job}


def _assert_access(meeting_id: str, user: dict, write: bool = False) -> None:
    with get_db() as db:
        row = db.execute(
            """
            SELECT role FROM meeting_members
            WHERE meeting_id = ? AND user_id = ?
            """,
            (meeting_id, user["id"]),
        ).fetchone()
    if not row and user.get("role") != "admin":
        raise HTTPException(status_code=404, detail="Meeting not found")
    if write and row and row["role"] not in {"owner", "editor"} and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Write access denied")


def _config_values() -> dict[str, str]:
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
    return {row["key"]: row["value"] for row in rows}


def _try_index(meeting_id: str) -> None:
    try:
        index_meeting(meeting_id)
    except Exception:
        pass


static_path = settings.static_dir
if static_path.exists():
    app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
