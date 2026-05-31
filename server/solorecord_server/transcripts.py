from .utils import new_id, now_iso


def archive_transcript_rows(
    db,
    meeting_id: str,
    source_segment_no: int | None,
    actor_user_id: str,
    reason: str,
    source_id: str | None = None,
) -> None:
    if source_segment_no is None:
        rows = db.execute("SELECT * FROM transcript_segments WHERE meeting_id = ?", (meeting_id,)).fetchall()
    elif source_id is not None:
        if source_id == "primary":
            rows = db.execute(
                """
                SELECT * FROM transcript_segments
                WHERE meeting_id = ?
                  AND COALESCE(NULLIF(source_id, ''), 'primary') = 'primary'
                  AND source_segment_no = ?
                """,
                (meeting_id, source_segment_no),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT * FROM transcript_segments
                WHERE meeting_id = ? AND source_id = ? AND source_segment_no = ?
                """,
                (meeting_id, source_id, source_segment_no),
            ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT * FROM transcript_segments
            WHERE meeting_id = ? AND source_segment_no = ?
            """,
            (meeting_id, source_segment_no),
        ).fetchall()
    archived_at = now_iso()
    for row in rows:
        db.execute(
            """
            INSERT INTO transcript_segment_history
            (id, original_segment_id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at,
             archived_at, archived_by_user_id, archive_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("seghist"),
                row["id"],
                row["meeting_id"],
                row["version"],
                row["source_id"],
                row["source_segment_no"],
                row["speaker_id"],
                row["display_name"],
                row["start_ms"],
                row["end_ms"],
                row["text"],
                row["confidence"],
                row["flags"],
                row["created_at"],
                archived_at,
                actor_user_id,
                reason,
            ),
        )
