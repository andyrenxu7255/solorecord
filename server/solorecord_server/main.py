from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import secrets
import sqlite3
import string

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
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
from .processing import enqueue_transcription, process_uploaded_segment
from .repository import list_documents_for_external, list_documents_for_user, meeting_document, transcript_document
from .schemas import (
    ActionItemsUpdate,
    LdapLoginRequest,
    LoginRequest,
    MeetingCreate,
    MeetingUpdate,
    MultiSourceJoinRequest,
    ProviderConfig,
    RecordingSourceCreate,
    SegmentJsonUpload,
    SpeakerRename,
    TranscriptUpdate,
)
from .search_index import index_meeting
from .transcripts import archive_transcript_rows
from .utils import new_id, now_iso, row_to_dict, sha256_file

app = FastAPI(title="SoloRecord Internal API", version="0.7.0")
settings = get_settings()

SUPPORTED_RELEASE_PLATFORMS = {"android", "windows", "macos", "ios", "harmony"}
PLATFORM_FILE_NAMES = {
    "android": "solorecord.apk",
    "windows": "SoloRecord-Setup.exe",
    "macos": "SoloRecord.dmg",
    "ios": "SoloRecord.ipa",
    "harmony": "SoloRecord.hap",
}

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
    values = _config_values()
    return {
        "appName": settings.app_name,
        "serverTime": now_iso(),
        "segmentMinutes": int(values.get("audio_segment_minutes", settings.audio_segment_minutes)),
        "features": {
            "speakerRename": True,
            "exports": ["markdown", "json", "srt", "docx", "pdf"],
            "apkDownload": True,
            "multiSourceRecording": True,
            "maxRecordingSources": 8,
        },
    }


@app.post("/api/mobile/meetings")
@app.post("/api/web/meetings")
def create_meeting(request: MeetingCreate, user: CurrentUser) -> dict:
    meeting_id = new_id("mtg")
    title = request.title.strip() or "未命名会议"
    recording_mode = "multi_source" if request.recording_mode == "multi_source" else "single"
    max_sources = _clamp_source_count(request.max_sources, default=1 if recording_mode == "single" else 3)
    join_code = _normalize_join_code(request.join_code) or _new_join_code()
    with get_db() as db:
        db.execute(
            """
            INSERT INTO meetings
            (id, title, owner_id, status, join_code, recording_mode, max_sources, created_at, updated_at, started_at)
            VALUES (?, ?, ?, 'local_recorded', ?, ?, ?, ?, ?, ?)
            """,
            (
                meeting_id,
                title,
                user["id"],
                join_code,
                recording_mode,
                max_sources,
                now_iso(),
                now_iso(),
                request.started_at,
            ),
        )
        db.execute(
            "INSERT INTO meeting_members (meeting_id, user_id, role) VALUES (?, ?, 'owner')",
            (meeting_id, user["id"]),
        )
        _ensure_recording_source(
            db,
            meeting_id,
            user,
            source_id="primary",
            label=request.source_label or user.get("display_name") or "主录音源",
            device_name=request.source_label or "",
        )
    audit(user["id"], "meeting.create", "meeting", meeting_id)
    return get_meeting(meeting_id, user)


@app.post("/api/mobile/meetings/join")
@app.post("/api/web/meetings/join")
def join_multisource_meeting(request: MultiSourceJoinRequest, user: CurrentUser) -> dict:
    title = request.title.strip()
    join_code = _normalize_join_code(request.join_code)
    if not title and not join_code:
        raise HTTPException(status_code=400, detail="title or join_code is required")
    with get_db() as db:
        meeting = None
        if join_code:
            meeting = db.execute(
                """
                SELECT * FROM meetings
                WHERE join_code = ? AND deleted_at IS NULL
                """,
                (join_code,),
            ).fetchone()
        if not meeting and title:
            meeting = db.execute(
                """
                SELECT * FROM meetings
                WHERE title = ? AND recording_mode = 'multi_source' AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (title,),
            ).fetchone()
        if not meeting:
            temp_request = MeetingCreate(
                title=title or join_code,
                join_code=join_code,
                recording_mode="multi_source",
                max_sources=8,
                source_label=request.source_label,
            )
            return create_meeting(temp_request, user)
        _ensure_member(db, meeting["id"], user["id"], role="editor")
        source = _register_recording_source(
            db,
            meeting,
            user,
            request.source_label,
            request.device_name,
        )
    audit(user["id"], "meeting.join_multisource", "meeting", meeting["id"], {"source_id": source["source_id"]})
    result = get_meeting(meeting["id"], user)
    result["joinedSource"] = source
    return result


@app.get("/api/mobile/meetings/{meeting_id}/sources")
@app.get("/api/web/meetings/{meeting_id}/sources")
def list_recording_sources(meeting_id: str, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user)
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM recording_sources WHERE meeting_id = ? ORDER BY created_at",
            (meeting_id,),
        ).fetchall()
    return {"items": [row_to_dict(row) for row in rows], "maxSources": _meeting_max_sources(meeting_id)}


@app.post("/api/mobile/meetings/{meeting_id}/sources")
@app.post("/api/web/meetings/{meeting_id}/sources")
def create_recording_source(meeting_id: str, request: RecordingSourceCreate, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user, write=True)
    with get_db() as db:
        meeting = db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        source = _register_recording_source(db, meeting, user, request.label, request.device_name, request.source_id)
    audit(user["id"], "meeting.source.create", "meeting", meeting_id, {"source_id": source["source_id"]})
    return {"source": source}


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


@app.get("/api/mobile/meetings/discover")
@app.get("/api/web/meetings/discover")
def discover_joinable_meetings(
    user: CurrentUser,
    q: str = "",
    limit: int = Query(12, ge=1, le=50),
    recent_hours: int = Query(12, ge=1, le=168),
) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=recent_hours)).isoformat()
    keyword = f"%{_normalize_join_code(q) or q.strip()}%"
    params: list[object] = [cutoff]
    filter_sql = ""
    if q.strip():
        filter_sql = "AND (meetings.join_code LIKE ? OR meetings.title LIKE ?)"
        params.extend([keyword, f"%{q.strip()}%"])
    params.append(limit)
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT meetings.id, meetings.title, meetings.join_code, meetings.status,
                   meetings.max_sources, meetings.created_at, meetings.updated_at,
                   users.display_name AS owner_name,
                   COUNT(recording_sources.id) AS source_count
            FROM meetings
            JOIN users ON users.id = meetings.owner_id
            LEFT JOIN recording_sources ON recording_sources.meeting_id = meetings.id
            WHERE meetings.deleted_at IS NULL
              AND meetings.recording_mode = 'multi_source'
              AND meetings.ended_at IS NULL
              AND meetings.status NOT IN ('ready', 'failed')
              AND meetings.updated_at >= ?
              {filter_sql}
            GROUP BY meetings.id
            HAVING COUNT(recording_sources.id) < CASE
                WHEN meetings.max_sources < 1 THEN 1
                WHEN meetings.max_sources > 8 THEN 8
                ELSE meetings.max_sources
            END
            ORDER BY meetings.updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    items = []
    for row in rows:
        max_sources = _clamp_source_count(row["max_sources"], default=8)
        source_count = int(row["source_count"] or 0)
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "join_code": row["join_code"] or "",
                "status": row["status"],
                "owner_name": row["owner_name"] or "",
                "source_count": source_count,
                "max_sources": max_sources,
                "remaining_sources": max(0, max_sources - source_count),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return {"items": items, "limit": limit, "recentHours": recent_hours}


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
        "recordingSources": document.get("recordingSources", []),
        "audioSegments": document["audioSegments"],
        "speakers": document["speakers"],
        "actionItems": document["actionItems"],
        "exports": document["exports"],
        "qualityReport": document["qualityReport"],
        "knowledgeGraph": document["knowledgeGraph"],
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
    source_id: str = Form("primary"),
    source_label: str = Form(""),
    source_segment_no: int | None = Form(None),
    start_ms: int = Form(0),
    end_ms: int = Form(0),
    duration_ms: int = Form(0),
    file: UploadFile = File(...),
) -> dict:
    _assert_access(meeting_id, user, write=True)
    source_id = _normalize_source_id(source_id) or "primary"
    source_segment_no = _normalize_source_segment_no(source_segment_no, segment_no)
    with get_db() as db:
        meeting = db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        source = _ensure_upload_recording_source(
            db,
            meeting,
            user,
            source_id=source_id,
            label=source_label or user.get("display_name") or source_id,
            device_name="",
        )
        global_segment_no = _segment_no_for_source_upload(
            db,
            meeting_id,
            source["source_id"],
            source_segment_no,
            segment_no,
        )
    meeting_dir = settings.storage_dir / "meetings" / meeting_id / "audio" / source_id
    meeting_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or f"part_{source_segment_no:04d}.m4a").name
    path = meeting_dir / f"{source_id}_{source_segment_no:04d}_{safe_name}"
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)
    digest = sha256_file(path)
    segment_id = new_id("aud")
    with get_db() as db:
        db.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no,
             file_name, storage_path, mime_type, size_bytes, sha256,
             duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)
            ON CONFLICT(meeting_id, segment_no)
            DO UPDATE SET source_id=excluded.source_id, source_segment_no=excluded.source_segment_no,
                file_name=excluded.file_name, storage_path=excluded.storage_path,
                mime_type=excluded.mime_type, size_bytes=excluded.size_bytes,
                sha256=excluded.sha256, duration_ms=excluded.duration_ms,
                start_ms=excluded.start_ms, end_ms=excluded.end_ms,
                upload_status='uploaded'
            """,
            (
                segment_id,
                meeting_id,
                source_id,
                source_segment_no,
                global_segment_no,
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
    audit(
        user["id"],
        "audio.upload",
        "meeting",
        meeting_id,
        {
            "segment_no": global_segment_no,
            "source_id": source_id,
            "source_segment_no": source_segment_no,
        },
    )
    partial = process_uploaded_segment(meeting_id, global_segment_no)
    return {
        "segmentNo": global_segment_no,
        "sourceId": source_id,
        "sourceSegmentNo": source_segment_no,
        "sha256": digest,
        "sizeBytes": path.stat().st_size,
        "partial": partial,
    }


@app.post("/api/mobile/meetings/{meeting_id}/segments-json")
def upload_segment_json(meeting_id: str, request: SegmentJsonUpload, user: CurrentUser) -> dict:
    import base64

    _assert_access(meeting_id, user, write=True)
    source_id = _normalize_source_id(request.source_id) or "primary"
    source_segment_no = _normalize_source_segment_no(request.source_segment_no, request.segment_no)
    with get_db() as db:
        meeting = db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        source = _ensure_upload_recording_source(
            db,
            meeting,
            user,
            source_id=source_id,
            label=request.source_label or user.get("display_name") or source_id,
            device_name="",
        )
        global_segment_no = _segment_no_for_source_upload(
            db,
            meeting_id,
            source["source_id"],
            source_segment_no,
            request.segment_no,
        )
    meeting_dir = settings.storage_dir / "meetings" / meeting_id / "audio" / source_id
    meeting_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(request.file_name or f"part_{source_segment_no:04d}.m4a").name
    path = meeting_dir / f"{source_id}_{source_segment_no:04d}_{safe_name}"
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
            (id, meeting_id, source_id, source_segment_no, segment_no,
             file_name, storage_path, mime_type, size_bytes, sha256,
             duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'audio/mp4', ?, ?, ?, ?, ?, 'uploaded', ?)
            ON CONFLICT(meeting_id, segment_no)
            DO UPDATE SET source_id=excluded.source_id, source_segment_no=excluded.source_segment_no,
                file_name=excluded.file_name, storage_path=excluded.storage_path,
                mime_type=excluded.mime_type, size_bytes=excluded.size_bytes,
                sha256=excluded.sha256, duration_ms=excluded.duration_ms,
                start_ms=excluded.start_ms, end_ms=excluded.end_ms,
                upload_status='uploaded'
            """,
            (
                segment_id,
                meeting_id,
                source_id,
                source_segment_no,
                global_segment_no,
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
    audit(
        user["id"],
        "audio.upload_json",
        "meeting",
        meeting_id,
        {
            "segment_no": global_segment_no,
            "source_id": source_id,
            "source_segment_no": source_segment_no,
        },
    )
    partial = process_uploaded_segment(meeting_id, global_segment_no)
    return {
        "segmentNo": global_segment_no,
        "sourceId": source_id,
        "sourceSegmentNo": source_segment_no,
        "sha256": digest,
        "sizeBytes": path.stat().st_size,
        "partial": partial,
    }


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
        current_count = db.execute(
            "SELECT COUNT(*) AS count FROM transcript_segments WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()["count"]
        if user.get("role") != "admin" and len(request.segments) < current_count:
            raise HTTPException(
                status_code=403,
                detail="Only admin can remove transcript segments; edit text or speaker names instead",
            )
        next_version = request.version + 1
        archive_transcript_rows(db, meeting_id, None, user["id"], "user_update")
        db.execute("DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,))
        seen_speakers: dict[str, str] = {}
        for item in request.segments:
            speaker_id = item.speaker_id.strip() or "SPEAKER_01"
            display_name = item.display_name.strip() or speaker_id
            seen_speakers[speaker_id] = display_name
            db.execute(
                """
                INSERT INTO transcript_segments
                (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
                 start_ms, end_ms, text, confidence, flags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id or new_id("seg"),
                    meeting_id,
                    next_version,
                    item.source_id.strip(),
                    item.source_segment_no,
                    speaker_id,
                    display_name,
                    item.start_ms,
                    item.end_ms,
                    item.text,
                    item.confidence,
                    json.dumps(item.flags, ensure_ascii=False),
                    now_iso(),
                ),
            )
        for speaker_id, display_name in seen_speakers.items():
            db.execute(
                """
                INSERT INTO speakers (id, meeting_id, speaker_id, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(meeting_id, speaker_id)
                DO UPDATE SET display_name=excluded.display_name, updated_at=excluded.updated_at
                """,
                (new_id("spk"), meeting_id, speaker_id, display_name, now_iso(), now_iso()),
            )
        db.execute("UPDATE meetings SET version=?, updated_at=? WHERE id=?", (next_version, now_iso(), meeting_id))
    audit(user["id"], "transcript.update", "meeting", meeting_id)
    _try_index(meeting_id)
    return get_transcript(meeting_id, user)


@app.post("/api/web/meetings/{meeting_id}/speakers/rename")
@app.post("/api/mobile/meetings/{meeting_id}/speakers/rename")
def rename_speaker(meeting_id: str, request: SpeakerRename, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user, write=True)
    display_name = request.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="display_name is required")
    with get_db() as db:
        old_names = [
            str(row["display_name"] or "").strip()
            for row in db.execute(
                """
                SELECT display_name FROM speakers
                WHERE meeting_id = ? AND speaker_id = ?
                UNION
                SELECT display_name FROM transcript_segments
                WHERE meeting_id = ? AND speaker_id = ?
                """,
                (meeting_id, request.speaker_id, meeting_id, request.speaker_id),
            ).fetchall()
        ]
        aliases = _speaker_rename_aliases(
            request.aliases,
            old_names,
            request.speaker_id,
            display_name,
        )
        db.execute(
            """
            INSERT INTO speakers (id, meeting_id, speaker_id, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(meeting_id, speaker_id)
            DO UPDATE SET display_name=excluded.display_name, updated_at=excluded.updated_at
            """,
            (new_id("spk"), meeting_id, request.speaker_id, display_name, now_iso(), now_iso()),
        )
        db.execute(
            "UPDATE transcript_segments SET display_name=? WHERE meeting_id=? AND speaker_id=?",
            (display_name, meeting_id, request.speaker_id),
        )
        if request.replace_text:
            for alias in aliases:
                db.execute(
                    """
                    UPDATE transcript_segments
                    SET text = replace(text, ?, ?)
                    WHERE meeting_id = ?
                    """,
                    (alias, display_name, meeting_id),
                )
                db.execute(
                    """
                    UPDATE action_items
                    SET owner = CASE WHEN owner = ? THEN ? ELSE owner END,
                        task = replace(task, ?, ?)
                    WHERE meeting_id = ?
                    """,
                    (alias, display_name, alias, display_name, meeting_id),
                )
                db.execute(
                    """
                    UPDATE meetings
                    SET summary = replace(summary, ?, ?),
                        role_notes = replace(role_notes, ?, ?)
                    WHERE id = ?
                    """,
                    (alias, display_name, alias, display_name, meeting_id),
                )
            db.execute(
                "UPDATE meetings SET summary=replace(summary, ?, ?), role_notes=replace(role_notes, ?, ?) WHERE id=?",
                (request.speaker_id, display_name, request.speaker_id, display_name, meeting_id),
            )
        db.execute("UPDATE meetings SET version=version+1, updated_at=? WHERE id=?", (now_iso(), meeting_id))
    audit(
        user["id"],
        "speaker.rename",
        "meeting",
        meeting_id,
        {"speaker_id": request.speaker_id, "aliases": aliases, "replace_text": request.replace_text},
    )
    _try_index(meeting_id)
    return get_meeting(meeting_id, user)


def _speaker_rename_aliases(
    requested_aliases: list[str],
    old_names: list[str],
    speaker_id: str,
    display_name: str,
) -> list[str]:
    aliases: list[str] = []
    for alias in [*requested_aliases, *old_names, speaker_id]:
        value = str(alias or "").strip()
        if not value or value == display_name or value in aliases:
            continue
        aliases.append(value)
    return aliases


@app.put("/api/web/meetings/{meeting_id}/actions")
@app.put("/api/mobile/meetings/{meeting_id}/actions")
def update_action_items(meeting_id: str, request: ActionItemsUpdate, user: CurrentUser) -> dict:
    _assert_access(meeting_id, user, write=True)
    with get_db() as db:
        db.execute("DELETE FROM action_items WHERE meeting_id = ?", (meeting_id,))
        for item in request.items:
            task = item.task.strip()
            if not task:
                continue
            db.execute(
                """
                INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("act"),
                    meeting_id,
                    item.owner.strip() or "待确认",
                    task,
                    item.due.strip(),
                    item.status.strip() or "open",
                    now_iso(),
                    now_iso(),
                ),
            )
        db.execute("UPDATE meetings SET updated_at=?, version=version+1 WHERE id=?", (now_iso(), meeting_id))
    audit(user["id"], "action_items.update", "meeting", meeting_id, {"count": len(request.items)})
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


@app.get("/api/external/meetings/{meeting_id}/transcript")
def external_meeting_transcript(
    meeting_id: str,
    client: ExternalClient,
    include_history: bool = False,
) -> dict:
    document = transcript_document(meeting_id, include_history=include_history)
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
    result["download_url"] = f"/api/web/exports/{result['id']}/download"
    return result


@app.get("/api/web/exports/{export_id}/download")
def download_export(export_id: str, user: CurrentUser) -> FileResponse:
    with get_db() as db:
        row = db.execute("SELECT * FROM exports WHERE id = ?", (export_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Export not found")
    _assert_access(row["meeting_id"], user)
    path = Path(row["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")
    return FileResponse(
        str(path),
        filename=path.name,
        media_type="application/octet-stream",
    )


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
def latest_release(user: CurrentUser, platform: str = Query("android")) -> dict:
    platform = _normalize_release_platform(platform)
    with get_db() as db:
        row = db.execute(
            """
            SELECT * FROM apk_releases
            WHERE platform = ?
            ORDER BY version_code DESC, created_at DESC
            LIMIT 1
            """,
            (platform,),
        ).fetchone()
    if not row:
        return {"release": None}
    release = row_to_dict(row)
    release["downloadUrl"] = _release_download_url(release)
    return {"release": release}


@app.post("/api/admin/releases")
async def upload_release(
    user: CurrentUser,
    platform: str = Form("android"),
    version_name: str = Form(...),
    version_code: int = Form(...),
    release_notes: str = Form(""),
    force_update: bool = Form(False),
    file: UploadFile = File(...),
) -> dict:
    require_admin(user)
    platform = _normalize_release_platform(platform)
    release_dir = settings.apk_dir / platform / version_name
    release_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or PLATFORM_FILE_NAMES[platform]).name
    path = release_dir / safe_name
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)
    digest = sha256_file(path)
    release_id = new_id("rel")
    with get_db() as db:
        db.execute(
            """
            INSERT INTO apk_releases
            (id, platform, version_name, version_code, file_name, storage_path, content_type,
             sha256, release_notes, force_update, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                release_id,
                platform,
                version_name,
                version_code,
                safe_name,
                str(path),
                file.content_type or _release_media_type(platform),
                digest,
                release_notes,
                1 if force_update else 0,
                now_iso(),
            ),
        )
    audit(user["id"], "release.upload", "release", release_id, {"platform": platform})
    return {
        "id": release_id,
        "platform": platform,
        "sha256": digest,
        "downloadUrl": f"/downloads/{platform}/{version_name}/{safe_name}",
    }


@app.get("/downloads/android/{version}/app.apk")
def download_apk(version: str) -> FileResponse:
    return _download_release("android", version, "app.apk")


@app.get("/downloads/{platform}/{version}/{file_name}")
def download_release(platform: str, version: str, file_name: str) -> FileResponse:
    return _download_release(platform, version, file_name)


def _download_release(platform: str, version: str, file_name: str) -> FileResponse:
    # Internal deployments may also restrict this path at Nginx/VPN level.
    platform = _normalize_release_platform(platform)
    with get_db() as db:
        row = db.execute(
            """
            SELECT * FROM apk_releases
            WHERE platform = ? AND version_name = ?
            ORDER BY version_code DESC, created_at DESC
            LIMIT 1
            """,
            (platform, version),
        ).fetchone()
    if not row or not Path(row["storage_path"]).exists():
        raise HTTPException(status_code=404, detail="Release artifact not found")
    stored_name = row["file_name"] or PLATFORM_FILE_NAMES[platform]
    if file_name not in {stored_name, "app.apk"}:
        raise HTTPException(status_code=404, detail="Release artifact not found")
    return FileResponse(
        row["storage_path"],
        filename=stored_name,
        media_type=row["content_type"] or _release_media_type(platform),
    )


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
            "enable_semantic_segmentation": values.get("enable_semantic_segmentation", "true") == "true",
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


def _clamp_source_count(value: int | None, default: int = 1) -> int:
    try:
        count = int(value if value is not None else default)
    except (TypeError, ValueError):
        count = default
    return max(1, min(8, count))


def _normalize_join_code(value: str | None) -> str:
    code = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    return code[:16]


def _new_join_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    with get_db() as db:
        for _ in range(32):
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            row = db.execute("SELECT 1 FROM meetings WHERE join_code = ?", (code,)).fetchone()
            if not row:
                return code
    return "".join(secrets.choice(alphabet) for _ in range(10))


def _normalize_source_id(value: str | None) -> str:
    source = re.sub(r"[^A-Za-z0-9_-]", "_", str(value or "").strip())
    source = re.sub(r"_+", "_", source).strip("_-")
    return source[:48]


def _normalize_source_segment_no(value: int | None, fallback: int) -> int:
    try:
        segment_no = int(value if value is not None else fallback)
    except (TypeError, ValueError):
        segment_no = int(fallback or 1)
    return max(1, segment_no)


def _ensure_member(db, meeting_id: str, user_id: str, role: str = "editor") -> None:
    existing = db.execute(
        "SELECT role FROM meeting_members WHERE meeting_id = ? AND user_id = ?",
        (meeting_id, user_id),
    ).fetchone()
    if existing:
        if existing["role"] == "owner" or existing["role"] == role:
            return
        db.execute(
            "UPDATE meeting_members SET role = ? WHERE meeting_id = ? AND user_id = ?",
            (role, meeting_id, user_id),
        )
        return
    db.execute(
        "INSERT INTO meeting_members (meeting_id, user_id, role) VALUES (?, ?, ?)",
        (meeting_id, user_id, role),
    )


def _ensure_recording_source(
    db,
    meeting_id: str,
    user: dict,
    source_id: str,
    label: str = "",
    device_name: str = "",
) -> dict:
    normalized_source_id = _normalize_source_id(source_id) or "primary"
    display_label = (label or "").strip() or normalized_source_id
    now = now_iso()
    db.execute(
        """
        INSERT INTO recording_sources
        (id, meeting_id, source_id, label, device_name, user_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
        ON CONFLICT(meeting_id, source_id)
        DO UPDATE SET label=CASE
                WHEN excluded.label != '' AND recording_sources.label = recording_sources.source_id
                THEN excluded.label
                ELSE recording_sources.label
            END,
            device_name=CASE
                WHEN excluded.device_name != '' THEN excluded.device_name
                ELSE recording_sources.device_name
            END,
            user_id=COALESCE(recording_sources.user_id, excluded.user_id),
            status='active',
            updated_at=excluded.updated_at
        """,
        (
            new_id("src"),
            meeting_id,
            normalized_source_id,
            display_label,
            (device_name or "").strip(),
            user.get("id"),
            now,
            now,
        ),
    )
    row = db.execute(
        "SELECT * FROM recording_sources WHERE meeting_id = ? AND source_id = ?",
        (meeting_id, normalized_source_id),
    ).fetchone()
    return row_to_dict(row)


def _register_recording_source(
    db,
    meeting,
    user: dict,
    label: str = "",
    device_name: str = "",
    source_id: str = "",
) -> dict:
    meeting_id = meeting["id"]
    requested_source_id = _normalize_source_id(source_id)
    if requested_source_id:
        existing = db.execute(
            """
            SELECT * FROM recording_sources
            WHERE meeting_id = ? AND source_id = ?
            """,
            (meeting_id, requested_source_id),
        ).fetchone()
        if existing:
            return _ensure_recording_source(
                db,
                meeting_id,
                user,
                requested_source_id,
                label or existing["label"],
                device_name or existing["device_name"],
            )
    if not requested_source_id:
        reusable = _reusable_recording_source(db, meeting_id, user, label, device_name)
        if reusable:
            return _ensure_recording_source(
                db,
                meeting_id,
                user,
                reusable["source_id"],
                label or reusable["label"],
                device_name or reusable["device_name"],
            )
    max_sources = _clamp_source_count(meeting["max_sources"], default=1)
    count = db.execute(
        "SELECT COUNT(*) AS count FROM recording_sources WHERE meeting_id = ?",
        (meeting_id,),
    ).fetchone()["count"]
    if not requested_source_id and count >= max_sources:
        raise HTTPException(status_code=409, detail="Recording source limit reached")
    if requested_source_id and count >= max_sources:
        raise HTTPException(status_code=409, detail="Recording source limit reached")
    if not requested_source_id:
        for index in range(1, max_sources + 1):
            candidate = "primary" if index == 1 else f"source_{index:02d}"
            row = db.execute(
                "SELECT 1 FROM recording_sources WHERE meeting_id = ? AND source_id = ?",
                (meeting_id, candidate),
            ).fetchone()
            if not row:
                requested_source_id = candidate
                break
    if not requested_source_id:
        raise HTTPException(status_code=409, detail="Recording source limit reached")
    return _ensure_recording_source(
        db,
        meeting_id,
        user,
        requested_source_id,
        label or user.get("display_name") or requested_source_id,
        device_name,
    )


def _reusable_recording_source(
    db,
    meeting_id: str,
    user: dict,
    label: str = "",
    device_name: str = "",
):
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        return None
    label = (label or "").strip()
    device_name = (device_name or "").strip()
    rows = db.execute(
        """
        SELECT * FROM recording_sources
        WHERE meeting_id = ? AND user_id = ?
        ORDER BY CASE WHEN source_id = 'primary' THEN 0 ELSE 1 END, created_at
        """,
        (meeting_id, user_id),
    ).fetchall()
    if not rows:
        return None
    if not label and not device_name:
        return rows[0]
    for row in rows:
        row_device = str(row["device_name"] or "").strip()
        row_label = str(row["label"] or "").strip()
        if device_name and row_device and row_device == device_name:
            if not label or not row_label or row_label == label:
                return row
            continue
        if device_name and row_device and row_device != device_name:
            continue
        if device_name and label and row_label and row_label == label:
            return row
        if device_name:
            continue
        if label and row_label and row_label == label:
            return row
    return None


def _ensure_upload_recording_source(
    db,
    meeting,
    user: dict,
    source_id: str,
    label: str = "",
    device_name: str = "",
) -> dict:
    meeting_id = meeting["id"]
    normalized_source_id = _normalize_source_id(source_id) or "primary"
    existing = db.execute(
        """
        SELECT * FROM recording_sources
        WHERE meeting_id = ? AND source_id = ?
        """,
        (meeting_id, normalized_source_id),
    ).fetchone()
    if existing:
        return _ensure_recording_source(
            db,
            meeting_id,
            user,
            normalized_source_id,
            label or existing["label"],
            device_name or existing["device_name"],
        )
    max_sources = _clamp_source_count(meeting["max_sources"], default=1)
    count = db.execute(
        "SELECT COUNT(*) AS count FROM recording_sources WHERE meeting_id = ?",
        (meeting_id,),
    ).fetchone()["count"]
    if count >= max_sources:
        raise HTTPException(status_code=409, detail="Recording source limit reached")
    return _ensure_recording_source(
        db,
        meeting_id,
        user,
        normalized_source_id,
        label or user.get("display_name") or normalized_source_id,
        device_name,
    )


def _meeting_max_sources(meeting_id: str) -> int:
    with get_db() as db:
        row = db.execute("SELECT max_sources FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    return _clamp_source_count(row["max_sources"] if row else 1, default=1)


def _segment_no_for_source_upload(
    db,
    meeting_id: str,
    source_id: str,
    source_segment_no: int,
    requested_segment_no: int,
) -> int:
    existing = db.execute(
        """
        SELECT segment_no FROM audio_segments
        WHERE meeting_id = ? AND source_id = ? AND source_segment_no = ?
        """,
        (meeting_id, source_id, source_segment_no),
    ).fetchone()
    if existing:
        return int(existing["segment_no"])
    requested = max(1, int(requested_segment_no or source_segment_no or 1))
    conflict = db.execute(
        """
        SELECT 1 FROM audio_segments
        WHERE meeting_id = ? AND segment_no = ?
        """,
        (meeting_id, requested),
    ).fetchone()
    if not conflict:
        return requested
    row = db.execute(
        """
        SELECT COALESCE(MAX(segment_no), 0) + 1 AS next_no
        FROM audio_segments
        WHERE meeting_id = ?
        """,
        (meeting_id,),
    ).fetchone()
    return max(1, int(row["next_no"] if row else 1))


def _try_index(meeting_id: str) -> None:
    try:
        index_meeting(meeting_id)
    except Exception:
        pass


def _normalize_release_platform(platform: str) -> str:
    value = (platform or "android").strip().lower()
    aliases = {
        "apk": "android",
        "android-apk": "android",
        "win": "windows",
        "win32": "windows",
        "exe": "windows",
        "darwin": "macos",
        "mac": "macos",
        "osx": "macos",
        "ios-ipa": "ios",
        "openharmony": "harmony",
        "harmonyos": "harmony",
        "hap": "harmony",
    }
    value = aliases.get(value, value)
    if value not in SUPPORTED_RELEASE_PLATFORMS:
        raise HTTPException(status_code=400, detail="Unsupported release platform")
    return value


def _release_download_url(release: dict) -> str:
    platform = _normalize_release_platform(str(release.get("platform") or "android"))
    if platform == "android":
        return f"/downloads/android/{release['version_name']}/app.apk"
    return f"/downloads/{platform}/{release['version_name']}/{release['file_name']}"


def _release_media_type(platform: str) -> str:
    return {
        "android": "application/vnd.android.package-archive",
        "windows": "application/vnd.microsoft.portable-executable",
        "macos": "application/x-apple-diskimage",
        "ios": "application/octet-stream",
        "harmony": "application/octet-stream",
    }.get(platform, "application/octet-stream")

static_path = settings.static_dir
if static_path.exists():
    app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
