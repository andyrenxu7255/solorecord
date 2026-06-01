import base64

import httpx

from .config import get_settings
from .repository import meeting_document


def index_meeting(meeting_id: str) -> None:
    settings = get_settings()
    config = _config_values()
    enabled = str(config.get("es_enabled", settings.es_enabled)).lower() == "true"
    es_url = config.get("es_url", settings.es_url)
    es_index = config.get("es_index", settings.es_index)
    if not enabled or not es_url:
        return
    document = meeting_document(meeting_id, include_graphs=False)
    if not document:
        return
    url = f"{es_url.rstrip('/')}/{es_index}/_doc/{meeting_id}"
    with httpx.Client(timeout=20) as client:
        client.put(url, headers=_headers(), json=_es_document(document)).raise_for_status()


def delete_meeting(meeting_id: str) -> None:
    settings = get_settings()
    config = _config_values()
    enabled = str(config.get("es_enabled", settings.es_enabled)).lower() == "true"
    es_url = config.get("es_url", settings.es_url)
    es_index = config.get("es_index", settings.es_index)
    if not enabled or not es_url:
        return
    url = f"{es_url.rstrip('/')}/{es_index}/_doc/{meeting_id}"
    with httpx.Client(timeout=20) as client:
        response = client.delete(url, headers=_headers())
        if response.status_code not in {200, 202, 404}:
            response.raise_for_status()


def _es_document(document: dict) -> dict:
    meeting = document["meeting"]
    owner = document["owner"]
    return {
        "meeting_id": meeting["id"],
        "title": meeting["title"],
        "status": meeting["status"],
        "created_at": meeting["created_at"],
        "updated_at": meeting["updated_at"],
        "started_at": meeting.get("started_at"),
        "ended_at": meeting.get("ended_at"),
        "duration_ms": meeting.get("duration_ms", 0),
        "owner_id": owner["id"],
        "owner_name": owner["display_name"],
        "owner_email": owner["email"],
        "summary": meeting.get("summary", ""),
        "role_notes": meeting.get("role_notes", ""),
        "speakers": [
            {"speaker_id": item["speaker_id"], "display_name": item["display_name"]}
            for item in document["speakers"]
        ],
        "transcript": [
            {
                "speaker_id": item["speaker_id"],
                "display_name": item["display_name"],
                "start_ms": item["start_ms"],
                "end_ms": item["end_ms"],
                "text": item["text"],
            }
            for item in document["transcriptSegments"]
        ],
        "action_items": [
            {
                "owner": item["owner"],
                "task": item["task"],
                "due": item["due"],
                "status": item["status"],
            }
            for item in document["actionItems"]
        ],
        "search_text": document["searchText"],
    }


def _headers() -> dict[str, str]:
    settings = get_settings()
    headers = {"Content-Type": "application/json"}
    if settings.es_api_key:
        headers["Authorization"] = f"ApiKey {settings.es_api_key}"
    elif settings.es_username or settings.es_password:
        token = base64.b64encode(f"{settings.es_username}:{settings.es_password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return headers


def _config_values() -> dict[str, str]:
    from .db import get_db

    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
    return {row["key"]: row["value"] for row in rows}
