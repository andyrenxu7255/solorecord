import httpx

from .config import get_settings
from .db import get_db


def publish_meeting(meeting_id: str) -> None:
    values = _config_values()
    url = values.get("hermes_webhook_url") or get_settings().hermes_webhook_url
    token = values.get("hermes_webhook_token") or get_settings().hermes_webhook_token
    if not url:
        return
    payload = _payload(meeting_id)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=30) as client:
        client.post(url, json=payload, headers=headers).raise_for_status()


def _payload(meeting_id: str) -> dict:
    with get_db() as db:
        meeting = db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        segments = db.execute(
            "SELECT * FROM transcript_segments WHERE meeting_id = ? ORDER BY start_ms",
            (meeting_id,),
        ).fetchall()
        actions = db.execute(
            "SELECT * FROM action_items WHERE meeting_id = ? ORDER BY created_at",
            (meeting_id,),
        ).fetchall()
    return {
        "type": "solorecord.meeting.ready",
        "meeting": dict(meeting) if meeting else {},
        "transcript": [dict(row) for row in segments],
        "actionItems": [dict(row) for row in actions],
    }


def _config_values() -> dict[str, str]:
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
    return {row["key"]: row["value"] for row in rows}
