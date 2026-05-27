from .db import get_db
from .utils import json_dumps, new_id, now_iso


def audit(actor_user_id: str, action: str, resource_type: str, resource_id: str, metadata: dict | None = None) -> None:
    with get_db() as db:
        db.execute(
            """
            INSERT INTO audit_logs (id, actor_user_id, action, resource_type, resource_id, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("aud"),
                actor_user_id,
                action,
                resource_type,
                resource_id,
                json_dumps(metadata or {}),
                now_iso(),
            ),
        )
