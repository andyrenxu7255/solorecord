from pathlib import Path

from .asr_adapters import transcribe_with_command, transcribe_with_openai_compatible
from .config import get_settings
from .db import get_db
from .llm_adapters import LlmAdapterError, llm_options_from_settings_and_db, summarize_with_llm
from .publisher import publish_meeting
from .search_index import index_meeting
from .utils import new_id, now_iso


def enqueue_transcription(meeting_id: str, asr_provider: str | None = None) -> str:
    settings = get_settings()
    job_id = new_id("job")
    provider = asr_provider or _current_asr_provider(settings.asr_provider)
    with get_db() as db:
        db.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES (?, ?, 'transcribe', 'queued', 'queued', 0, ?, ?, ?)
            """,
            (job_id, meeting_id, provider, now_iso(), now_iso()),
        )
        db.execute(
            "UPDATE meetings SET status = 'queued', updated_at = ? WHERE id = ?",
            (now_iso(), meeting_id),
        )
    process_transcription_job(job_id)
    return job_id


def _current_asr_provider(default: str) -> str:
    with get_db() as db:
        row = db.execute("SELECT value FROM app_config WHERE key='asr_provider'").fetchone()
    return row["value"] if row else default


def process_transcription_job(job_id: str) -> None:
    with get_db() as db:
        job = db.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return
        meeting_id = job["meeting_id"]
        db.execute(
            """
            UPDATE processing_jobs
            SET status='running', current_stage='preprocessing', progress=10, started_at=?, updated_at=?
            WHERE id=?
            """,
            (now_iso(), now_iso(), job_id),
        )
        db.execute(
            "UPDATE meetings SET status='preprocessing', updated_at=? WHERE id=?",
            (now_iso(), meeting_id),
        )

    try:
        segments = _transcribe(meeting_id)
        _replace_transcript(meeting_id, segments)
        summary, role_notes, actions = _summarize(segments)
        with get_db() as db:
            db.execute(
                """
                UPDATE meetings
                SET status='ready', summary=?, role_notes=?, updated_at=?, version=version+1
                WHERE id=?
                """,
                (summary, role_notes, now_iso(), meeting_id),
            )
            db.execute("DELETE FROM action_items WHERE meeting_id = ?", (meeting_id,))
            for item in actions:
                db.execute(
                    """
                    INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("act"),
                        meeting_id,
                        item["owner"],
                        item["task"],
                        item.get("due", ""),
                        item.get("status", "open"),
                        now_iso(),
                        now_iso(),
                    ),
                )
            db.execute(
                """
                UPDATE processing_jobs
                SET current_stage='forwarding', progress=95, updated_at=?
                WHERE id=?
                """,
                (now_iso(), job_id),
            )
        publish_failed = False
        try:
            publish_meeting(meeting_id)
        except Exception:
            publish_failed = True
        with get_db() as db:
            job_status = "succeeded_with_publish_warning" if publish_failed else "succeeded"
            db.execute(
                """
                UPDATE processing_jobs
                SET status=?, current_stage='ready', progress=100, finished_at=?, updated_at=?
                WHERE id=?
                """,
                (job_status, now_iso(), now_iso(), job_id),
            )
            if publish_failed:
                db.execute(
                    """
                    INSERT INTO audit_logs (id, actor_user_id, action, resource_type, resource_id, metadata, created_at)
                    VALUES (?, 'system', 'publish.failed', 'meeting', ?, '{}', ?)
                    """,
                    (new_id("audlog"), meeting_id, now_iso()),
                )
        try:
            index_meeting(meeting_id)
        except Exception:
            with get_db() as db:
                db.execute(
                    """
                    INSERT INTO audit_logs (id, actor_user_id, action, resource_type, resource_id, metadata, created_at)
                    VALUES (?, 'system', 'index.failed', 'meeting', ?, '{}', ?)
                    """,
                    (new_id("audlog"), meeting_id, now_iso()),
                )
    except Exception as exc:
        with get_db() as db:
            db.execute(
                """
                UPDATE processing_jobs
                SET status='failed', current_stage='failed', error_code='PROCESSING_FAILED',
                    error_message=?, updated_at=?, finished_at=?
                WHERE id=?
                """,
                (str(exc), now_iso(), now_iso(), job_id),
            )
            db.execute(
                "UPDATE meetings SET status='failed', updated_at=? WHERE id=?",
                (now_iso(), meeting_id),
            )


def _transcribe(meeting_id: str) -> list[dict]:
    settings = get_settings()
    runtime = _runtime_options()
    asr_provider = runtime.get("asr_provider", settings.asr_provider)
    asr_command = runtime.get("asr_command", settings.asr_command)
    with get_db() as db:
        audio_rows = db.execute(
            "SELECT * FROM audio_segments WHERE meeting_id = ? ORDER BY segment_no",
            (meeting_id,),
        ).fetchall()
    if not audio_rows:
        return [
            {
                "speaker_id": "SPEAKER_01",
                "display_name": "发言人 1",
                "start_ms": 0,
                "end_ms": 5000,
                "text": "会议已创建，但尚未上传音频。请上传录音后重新转写。",
                "confidence": 0.1,
                "flags": ["missing_audio"],
            }
        ]

    if asr_provider == "command" and asr_command:
        return transcribe_with_command(
            asr_command,
            [row["storage_path"] for row in audio_rows],
            meeting_id,
            runtime,
        )
    if asr_provider in {"openai-compatible", "remote-stt", "funasr"}:
        return transcribe_with_openai_compatible(
            runtime.get("asr_endpoint", settings.asr_endpoint),
            runtime.get("asr_api_key", settings.asr_api_key),
            runtime.get("asr_model", settings.asr_model),
            [row["storage_path"] for row in audio_rows],
        )

    result: list[dict] = []
    cursor = 0
    speakers = [("SPEAKER_01", "发言人 1"), ("SPEAKER_02", "发言人 2")]
    for index, row in enumerate(audio_rows):
        duration = int(row["duration_ms"] or 180000)
        speaker_id, display_name = speakers[index % len(speakers)]
        file_name = Path(row["file_name"]).name
        result.append(
            {
                "speaker_id": speaker_id,
                "display_name": display_name,
                "start_ms": cursor,
                "end_ms": cursor + duration,
                "text": f"已接收音频分段 {row['segment_no']}（{file_name}）。本地 ASR 未配置时先生成占位转写，部署模型后可重新转写。",
                "confidence": 0.55,
                "flags": ["mock_asr"],
            }
        )
        cursor += duration
    return result


def _runtime_options() -> dict:
    settings = get_settings()
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
    values = {row["key"]: row["value"] for row in rows}
    return {
        "asr_provider": values.get("asr_provider", settings.asr_provider),
        "asr_command": values.get("asr_command", settings.asr_command),
        "asr_endpoint": values.get("asr_endpoint", settings.asr_endpoint),
        "asr_api_key": values.get("asr_api_key", settings.asr_api_key),
        "asr_model": values.get("asr_model", settings.asr_model),
        "target_sample_rate": int(values.get("target_sample_rate", settings.target_sample_rate)),
        "enable_diarization": values.get("enable_diarization", str(settings.enable_diarization)).lower() == "true",
        "enable_denoise": values.get("enable_denoise", str(settings.enable_denoise)).lower() == "true",
    }


def _replace_transcript(meeting_id: str, segments: list[dict]) -> None:
    with get_db() as db:
        db.execute("DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,))
        seen_speakers: dict[str, str] = {}
        for segment in segments:
            speaker_id = segment["speaker_id"]
            display_name = segment.get("display_name") or speaker_id
            seen_speakers[speaker_id] = display_name
            db.execute(
                """
                INSERT INTO transcript_segments
                (id, meeting_id, version, speaker_id, display_name, start_ms, end_ms, text, confidence, flags, created_at)
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("seg"),
                    meeting_id,
                    speaker_id,
                    display_name,
                    int(segment["start_ms"]),
                    int(segment["end_ms"]),
                    segment["text"],
                    segment.get("confidence"),
                    "[]",
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


def _summarize(segments: list[dict]) -> tuple[str, str, list[dict]]:
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
    values = {row["key"]: row["value"] for row in rows}
    try:
        return summarize_with_llm(segments, llm_options_from_settings_and_db(values))
    except LlmAdapterError:
        pass
    speaker_lines = [f"{item['display_name']}：{item['text']}" for item in segments]
    role_notes = "\n".join(speaker_lines)
    summary = "本次会议已完成基础整理。请在配置本地 ASR/LLM 后重新生成正式纪要。" if segments else ""
    actions = [
        {
            "owner": "待确认",
            "task": "检查转写结果并补充真实会议纪要",
            "due": "",
            "status": "open",
        }
    ]
    return summary, role_notes, actions
