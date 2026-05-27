from .db import get_db
from .utils import row_to_dict


def meeting_document(meeting_id: str) -> dict:
    with get_db() as db:
        meeting = db.execute(
            """
            SELECT meetings.*, users.display_name AS owner_name, users.email AS owner_email
            FROM meetings
            JOIN users ON users.id = meetings.owner_id
            WHERE meetings.id = ?
            """,
            (meeting_id,),
        ).fetchone()
        if not meeting:
            return {}
        members = db.execute(
            """
            SELECT meeting_members.role, users.id, users.display_name, users.email
            FROM meeting_members
            JOIN users ON users.id = meeting_members.user_id
            WHERE meeting_members.meeting_id = ?
            ORDER BY meeting_members.role, users.display_name
            """,
            (meeting_id,),
        ).fetchall()
        audio_rows = db.execute(
            "SELECT * FROM audio_segments WHERE meeting_id = ? ORDER BY segment_no",
            (meeting_id,),
        ).fetchall()
        transcript_segments = db.execute(
            "SELECT * FROM transcript_segments WHERE meeting_id = ? ORDER BY start_ms",
            (meeting_id,),
        ).fetchall()
        speakers = db.execute(
            "SELECT * FROM speakers WHERE meeting_id = ? ORDER BY speaker_id",
            (meeting_id,),
        ).fetchall()
        action_items = db.execute(
            "SELECT * FROM action_items WHERE meeting_id = ? ORDER BY created_at",
            (meeting_id,),
        ).fetchall()
    meeting_dict = row_to_dict(meeting)
    transcript_text = "\n".join(
        f"[{_time(row['start_ms'])}] {row['display_name']}: {row['text']}" for row in transcript_segments
    )
    action_text = "\n".join(f"{row['owner']}: {row['task']} {row['due']}" for row in action_items)
    audio_segments = []
    for row in audio_rows:
        item = row_to_dict(row)
        item["download_url"] = (
            f"/api/mobile/meetings/{meeting_id}/segments/{item['segment_no']}/audio"
        )
        audio_segments.append(item)
    return {
        "meeting": meeting_dict,
        "owner": {
            "id": meeting_dict["owner_id"],
            "display_name": meeting_dict.get("owner_name", ""),
            "email": meeting_dict.get("owner_email", ""),
        },
        "members": [row_to_dict(row) for row in members],
        "audioSegments": audio_segments,
        "transcriptSegments": [row_to_dict(row) for row in transcript_segments],
        "speakers": [row_to_dict(row) for row in speakers],
        "actionItems": [row_to_dict(row) for row in action_items],
        "searchText": "\n".join(
            part
            for part in [
                meeting_dict.get("title", ""),
                meeting_dict.get("summary", ""),
                meeting_dict.get("role_notes", ""),
                transcript_text,
                action_text,
            ]
            if part
        ),
    }


def list_documents_for_user(user_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            """
            SELECT meetings.id
            FROM meetings
            JOIN meeting_members ON meeting_members.meeting_id = meetings.id
            WHERE meeting_members.user_id = ? AND meetings.deleted_at IS NULL
            ORDER BY meetings.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
    return [meeting_document(row["id"]) for row in rows]


def list_documents_for_external(limit: int = 100, offset: int = 0) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id FROM meetings
            WHERE deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
    return [meeting_document(row["id"]) for row in rows]


def _time(ms: int) -> str:
    seconds = max(0, int(ms / 1000))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
