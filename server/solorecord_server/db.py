import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import get_settings


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    sso_subject TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sso_states (
    state TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    redirect_after TEXT NOT NULL DEFAULT '/',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL,
    join_code TEXT,
    recording_mode TEXT NOT NULL DEFAULT 'single',
    max_sources INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    role_notes TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    deleted_at TEXT,
    FOREIGN KEY(owner_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS recording_sources (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    label TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    user_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(meeting_id, source_id),
    FOREIGN KEY(meeting_id) REFERENCES meetings(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS meeting_members (
    meeting_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY(meeting_id, user_id),
    FOREIGN KEY(meeting_id) REFERENCES meetings(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audio_segments (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT 'primary',
    source_segment_no INTEGER,
    segment_no INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    start_ms INTEGER NOT NULL DEFAULT 0,
    end_ms INTEGER NOT NULL DEFAULT 0,
    upload_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(meeting_id, segment_no),
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    asr_provider TEXT NOT NULL DEFAULT 'mock',
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    source_id TEXT NOT NULL DEFAULT '',
    source_segment_no INTEGER,
    speaker_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    confidence REAL,
    flags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS transcript_segment_history (
    id TEXT PRIMARY KEY,
    original_segment_id TEXT NOT NULL,
    meeting_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    source_id TEXT NOT NULL DEFAULT '',
    source_segment_no INTEGER,
    speaker_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    confidence REAL,
    flags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    archived_by_user_id TEXT NOT NULL DEFAULT 'system',
    archive_reason TEXT NOT NULL,
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS speakers (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(meeting_id, speaker_id),
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS action_items (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    task TEXT NOT NULL,
    due TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    source_segment_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS ontology_entities (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    label TEXT NOT NULL,
    normalized_label TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    confidence REAL,
    evidence TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'rule',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(meeting_id, entity_type, normalized_label),
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS ontology_relations (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    label TEXT NOT NULL,
    confidence REAL,
    evidence TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'rule',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(meeting_id, source_entity_id, target_entity_id, relation_type),
    FOREIGN KEY(meeting_id) REFERENCES meetings(id),
    FOREIGN KEY(source_entity_id) REFERENCES ontology_entities(id),
    FOREIGN KEY(target_entity_id) REFERENCES ontology_entities(id)
);

CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    format TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS apk_releases (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT 'android',
    version_name TEXT NOT NULL,
    version_code INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    sha256 TEXT NOT NULL,
    release_notes TEXT NOT NULL DEFAULT '',
    force_update INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    secret INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ontology_entities_meeting
    ON ontology_entities(meeting_id, entity_type);

CREATE INDEX IF NOT EXISTS idx_ontology_relations_meeting
    ON ontology_relations(meeting_id);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    settings = get_settings()
    db_path = path or settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        columns = [row["name"] for row in connection.execute("PRAGMA table_info(app_config)").fetchall()]
        if "secret" not in columns:
            connection.execute("ALTER TABLE app_config ADD COLUMN secret INTEGER NOT NULL DEFAULT 0")
        transcript_columns = [
            row["name"] for row in connection.execute("PRAGMA table_info(transcript_segments)").fetchall()
        ]
        if "source_segment_no" not in transcript_columns:
            connection.execute("ALTER TABLE transcript_segments ADD COLUMN source_segment_no INTEGER")
        if "source_id" not in transcript_columns:
            connection.execute("ALTER TABLE transcript_segments ADD COLUMN source_id TEXT NOT NULL DEFAULT ''")
        history_columns = [
            row["name"] for row in connection.execute("PRAGMA table_info(transcript_segment_history)").fetchall()
        ]
        if "source_id" not in history_columns:
            connection.execute("ALTER TABLE transcript_segment_history ADD COLUMN source_id TEXT NOT NULL DEFAULT ''")
        meeting_columns = [row["name"] for row in connection.execute("PRAGMA table_info(meetings)").fetchall()]
        if "join_code" not in meeting_columns:
            connection.execute("ALTER TABLE meetings ADD COLUMN join_code TEXT")
        if "recording_mode" not in meeting_columns:
            connection.execute("ALTER TABLE meetings ADD COLUMN recording_mode TEXT NOT NULL DEFAULT 'single'")
        if "max_sources" not in meeting_columns:
            connection.execute("ALTER TABLE meetings ADD COLUMN max_sources INTEGER NOT NULL DEFAULT 1")
        audio_columns = [row["name"] for row in connection.execute("PRAGMA table_info(audio_segments)").fetchall()]
        if "source_id" not in audio_columns:
            connection.execute("ALTER TABLE audio_segments ADD COLUMN source_id TEXT NOT NULL DEFAULT 'primary'")
        if "source_segment_no" not in audio_columns:
            connection.execute("ALTER TABLE audio_segments ADD COLUMN source_segment_no INTEGER")
            connection.execute("UPDATE audio_segments SET source_segment_no=segment_no WHERE source_segment_no IS NULL")
        release_columns = [row["name"] for row in connection.execute("PRAGMA table_info(apk_releases)").fetchall()]
        if "platform" not in release_columns:
            connection.execute("ALTER TABLE apk_releases ADD COLUMN platform TEXT NOT NULL DEFAULT 'android'")
        if "content_type" not in release_columns:
            connection.execute(
                "ALTER TABLE apk_releases ADD COLUMN content_type TEXT NOT NULL DEFAULT 'application/octet-stream'"
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_apk_releases_platform_version
            ON apk_releases(platform, version_code DESC, created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_meetings_join_code
            ON meetings(join_code)
            WHERE join_code IS NOT NULL AND join_code != ''
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audio_segments_source
            ON audio_segments(meeting_id, source_id, source_segment_no)
            """
        )


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
