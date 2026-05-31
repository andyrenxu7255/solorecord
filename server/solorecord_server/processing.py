import json
import re
from pathlib import Path

from .asr_adapters import transcribe_with_command, transcribe_with_openai_compatible
from .config import get_settings
from .db import get_db
from .llm_adapters import (
    LlmAdapterError,
    llm_options_from_settings_and_db,
    mentioned_people_candidates,
    refine_segments_with_llm,
    summarize_with_llm,
)
from .publisher import publish_meeting
from .repository import build_quality_report
from .search_index import index_meeting
from .transcripts import archive_transcript_rows
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


def process_uploaded_segment(meeting_id: str, segment_no: int) -> dict:
    settings = get_settings()
    provider = _current_asr_provider(settings.asr_provider)
    job_id = new_id("job")
    with get_db() as db:
        db.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES (?, ?, 'segment_transcribe', 'running', 'transcribing', 20, ?, ?, ?)
            """,
            (job_id, meeting_id, provider, now_iso(), now_iso()),
        )
        audio_row = db.execute(
            "SELECT * FROM audio_segments WHERE meeting_id = ? AND segment_no = ?",
            (meeting_id, segment_no),
        ).fetchone()
    if not audio_row:
        return {"jobId": job_id, "status": "failed", "segments": []}
    try:
        segments = _transcribe_rows(meeting_id, [audio_row], offset_single=True)
        segments = _refine_segments(
            meeting_id,
            segments,
            force_semantic=False,
            scope="partial",
        )
        _replace_transcript_for_segment(meeting_id, segment_no, segments)
        with get_db() as db:
            db.execute(
                """
                UPDATE meetings
                SET status='partial_ready', updated_at=?, version=version+1
                WHERE id=? AND status NOT IN ('ready', 'failed')
                """,
                (now_iso(), meeting_id),
            )
            db.execute(
                """
                UPDATE processing_jobs
                SET status='succeeded', current_stage='partial_ready', progress=100, finished_at=?, updated_at=?
                WHERE id=?
                """,
                (now_iso(), now_iso(), job_id),
            )
        try:
            index_meeting(meeting_id)
        except Exception:
            pass
        return {"jobId": job_id, "status": "succeeded", "segments": segments}
    except Exception as exc:
        with get_db() as db:
            db.execute(
                """
                UPDATE processing_jobs
                SET status='failed', current_stage='failed', error_code='SEGMENT_PROCESSING_FAILED',
                    error_message=?, finished_at=?, updated_at=?
                WHERE id=?
                """,
                (str(exc), now_iso(), now_iso(), job_id),
            )
        return {"jobId": job_id, "status": "failed", "segments": [], "error": str(exc)}


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
        segments, reused_partial = _transcribe_or_reuse_partial(meeting_id)
        segments = _merge_multisource_segments(segments)
        segments = _refine_segments(
            meeting_id,
            segments,
            force_semantic=True,
            scope="final",
        )
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
    return _transcribe_rows(meeting_id, audio_rows, offset_single=False)


def _transcribe_or_reuse_partial(meeting_id: str) -> tuple[list[dict], bool]:
    with get_db() as db:
        audio_count = db.execute(
            "SELECT COUNT(*) AS count FROM audio_segments WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()["count"]
        covered_segments = db.execute(
            """
            SELECT COUNT(DISTINCT COALESCE(NULLIF(source_id, ''), 'primary') || ':' || source_segment_no) AS count
            FROM transcript_segments
            WHERE meeting_id = ? AND source_segment_no IS NOT NULL
            """,
            (meeting_id,),
        ).fetchone()["count"]
        rows = db.execute(
            """
            SELECT * FROM transcript_segments
            WHERE meeting_id = ? AND source_segment_no IS NOT NULL
            ORDER BY start_ms, source_segment_no
            """,
            (meeting_id,),
        ).fetchall()
    if audio_count and covered_segments >= audio_count:
        return [_transcript_row_to_segment(row) for row in rows], True
    return _transcribe(meeting_id), False


def _transcribe_rows(meeting_id: str, audio_rows: list, offset_single: bool) -> list[dict]:
    settings = get_settings()
    runtime = _runtime_options()
    asr_provider = runtime.get("asr_provider", settings.asr_provider)
    asr_command = runtime.get("asr_command", settings.asr_command)
    if asr_provider == "command" and asr_command:
        segments: list[dict] = []
        if offset_single or len(audio_rows) == 1:
            for row in audio_rows:
                row_segments = transcribe_with_command(
                    asr_command,
                    [row["storage_path"]],
                    meeting_id,
                    runtime,
                )
                row_segments = _offset_segments(row_segments, int(row["start_ms"] or 0))
                segments.extend(_tag_segments_with_audio_source(row_segments, row))
            return segments
        command_segments = transcribe_with_command(
            asr_command,
            [row["storage_path"] for row in audio_rows],
            meeting_id,
            runtime,
        )
        return _tag_batched_segments_with_audio_sources(command_segments, audio_rows)
    if asr_provider in {"openai-compatible", "remote-stt", "funasr"}:
        segments: list[dict] = []
        for row in audio_rows:
            row_segments = transcribe_with_openai_compatible(
                runtime.get("asr_endpoint", settings.asr_endpoint),
                runtime.get("asr_api_key", settings.asr_api_key),
                runtime.get("asr_model", settings.asr_model),
                [row["storage_path"]],
            )
            row_segments = _offset_segments(row_segments, int(row["start_ms"] or 0))
            segments.extend(_tag_segments_with_audio_source(row_segments, row))
        return segments

    result: list[dict] = []
    speakers = [("SPEAKER_01", "发言人 1"), ("SPEAKER_02", "发言人 2")]
    for index, row in enumerate(audio_rows):
        duration = int(row["duration_ms"] or 180000)
        speaker_id, display_name = speakers[index % len(speakers)]
        file_name = Path(row["file_name"]).name
        start_ms = int(row["start_ms"] or 0)
        result.append(
            {
                "source_id": row["source_id"],
                "source_segment_no": row["source_segment_no"] or row["segment_no"],
                "speaker_id": speaker_id,
                "display_name": display_name,
                "start_ms": start_ms,
                "end_ms": start_ms + duration,
                "text": f"已接收音频分段 {row['segment_no']}（{file_name}）。本地 ASR 未配置时先生成占位转写，部署模型后可重新转写。",
                "confidence": 0.55,
                "flags": ["mock_asr"],
            }
        )
    return result


def _transcript_row_to_segment(row) -> dict:
    return {
        "source_id": row["source_id"],
        "speaker_id": row["speaker_id"],
        "display_name": row["display_name"],
        "source_segment_no": row["source_segment_no"],
        "start_ms": int(row["start_ms"]),
        "end_ms": int(row["end_ms"]),
        "text": row["text"],
        "confidence": row["confidence"],
        "flags": _normalize_flags_value(row["flags"]),
    }


def _offset_segments(segments: list[dict], offset_ms: int) -> list[dict]:
    if offset_ms <= 0:
        return segments
    shifted: list[dict] = []
    for segment in segments:
        item = dict(segment)
        original_start = int(segment.get("start_ms", 0))
        original_end = int(segment.get("end_ms", original_start))
        item["start_ms"] = original_start + offset_ms
        item["end_ms"] = original_end + offset_ms
        shifted.append(item)
    return shifted


def _tag_segments_with_audio_source(segments: list[dict], audio_row) -> list[dict]:
    tagged: list[dict] = []
    source_id = str(audio_row["source_id"] or "primary")
    source_segment_no = int(audio_row["source_segment_no"] or audio_row["segment_no"])
    for segment in segments:
        item = dict(segment)
        item["source_id"] = item.get("source_id") or source_id
        item["source_segment_no"] = item.get("source_segment_no") or source_segment_no
        tagged.append(item)
    return tagged


def _tag_batched_segments_with_audio_sources(segments: list[dict], audio_rows: list) -> list[dict]:
    if not audio_rows:
        return segments
    tagged: list[dict] = []
    for segment in segments:
        start_ms = int(segment.get("start_ms") or 0)
        match = next(
            (
                row
                for row in audio_rows
                if int(row["start_ms"] or 0) <= start_ms <= int(row["end_ms"] or row["start_ms"] or 0)
            ),
            audio_rows[0],
        )
        tagged.extend(_tag_segments_with_audio_source([segment], match))
    return tagged


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


def _refine_segments(
    meeting_id: str,
    segments: list[dict],
    force_semantic: bool = False,
    scope: str = "",
) -> list[dict]:
    if not segments:
        return segments
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
    values = {row["key"]: row["value"] for row in rows}
    if values.get("enable_semantic_segmentation", str(get_settings().enable_semantic_segmentation)).lower() != "true":
        return _mark_semantic_scope(_normalize_semantic_segments(segments, "asr"), scope)
    if not force_semantic and not _needs_semantic_segmentation(segments):
        return _mark_semantic_scope(_normalize_semantic_segments(segments, "asr"), scope)
    try:
        refined = refine_segments_with_llm(segments, llm_options_from_settings_and_db(values))
        if not _refined_segments_cover_source(refined, segments):
            raise LlmAdapterError("LLM refined transcript dropped too much source text")
        refined = _repair_refined_timeline(refined, segments, _meeting_duration_ms(meeting_id))
        refined = _rule_refine_residual_mixed_segments(refined)
        return _mark_semantic_scope(
            _apply_contextual_speaker_inference(
                _normalize_semantic_segments(
                    _preserve_source_segments(refined, segments),
                    "llm",
                )
            ),
            scope,
        )
    except Exception as exc:
        with get_db() as db:
            db.execute(
                """
                INSERT INTO audit_logs (id, actor_user_id, action, resource_type, resource_id, metadata, created_at)
                VALUES (?, 'system', 'semantic_refine.fallback', 'meeting', ?, ?, ?)
                """,
                (
                    new_id("audlog"),
                    meeting_id,
                    json.dumps({"error": str(exc)[:180]}, ensure_ascii=False),
                    now_iso(),
                ),
            )
        return _mark_semantic_scope(
            _apply_contextual_speaker_inference(
                _normalize_semantic_segments(_rule_refine_segments(segments), "rule")
            ),
            scope,
        )


def _mark_semantic_scope(segments: list[dict], scope: str) -> list[dict]:
    if scope not in {"partial", "final"}:
        return segments
    marker = f"semantic_{scope}"
    marked: list[dict] = []
    for segment in segments:
        item = dict(segment)
        flags = _flags(item)
        if marker not in flags:
            flags.append(marker)
        item["flags"] = flags
        marked.append(item)
    return marked


def _merge_multisource_segments(segments: list[dict]) -> list[dict]:
    source_ids = {
        str(item.get("source_id") or "primary")
        for item in segments
        if str(item.get("source_id") or "primary")
    }
    if len(source_ids) <= 1 or len(segments) < 2:
        return segments
    ordered = sorted(
        (dict(item) for item in segments),
        key=lambda item: (
            int(item.get("start_ms") or 0),
            int(item.get("end_ms") or 0),
            str(item.get("source_id") or ""),
        ),
    )
    consumed: set[int] = set()
    merged: list[dict] = []
    for index, segment in enumerate(ordered):
        if index in consumed:
            continue
        group = [segment]
        consumed.add(index)
        for other_index in range(index + 1, len(ordered)):
            if other_index in consumed:
                continue
            other = ordered[other_index]
            if _segments_are_multisource_duplicates(segment, other):
                group.append(other)
                consumed.add(other_index)
        if len(group) == 1:
            item = dict(segment)
            if _has_nearby_multisource_conflict(item, ordered):
                flags = _flags(item)
                for flag in ("multi_source_conflict", "speaker_review"):
                    if flag not in flags:
                        flags.append(flag)
                item["flags"] = flags
            merged.append(item)
            continue
        merged.append(_merge_duplicate_source_group(group))
    return sorted(
        merged,
        key=lambda item: (
            int(item.get("start_ms") or 0),
            int(item.get("end_ms") or 0),
            str(item.get("source_id") or ""),
        ),
    )


def _segments_are_multisource_duplicates(left: dict, right: dict) -> bool:
    left_source = str(left.get("source_id") or "primary")
    right_source = str(right.get("source_id") or "primary")
    if left_source == right_source:
        return False
    left_text = str(left.get("text") or "")
    right_text = str(right.get("text") or "")
    if not left_text or not right_text:
        return False
    similarity = _text_similarity(left_text, right_text)
    if _segments_overlap_enough(left, right):
        if _segments_have_critical_fact_conflict(left, right):
            return False
        return similarity >= 0.58
    if not _segments_are_offset_aligned_duplicate(left, right, similarity):
        return False
    return not _segments_have_critical_fact_conflict(left, right)


def _segments_overlap_enough(left: dict, right: dict) -> bool:
    left_start = int(left.get("start_ms") or 0)
    left_end = int(left.get("end_ms") or left_start)
    right_start = int(right.get("start_ms") or 0)
    right_end = int(right.get("end_ms") or right_start)
    overlap = max(0, min(left_end, right_end) - max(left_start, right_start))
    shortest = max(1, min(max(1, left_end - left_start), max(1, right_end - right_start)))
    if overlap / shortest >= 0.45:
        return True
    return abs(left_start - right_start) <= 2500


def _text_similarity(left: str, right: str) -> float:
    left_tokens = set(_merge_text_tokens(left))
    right_tokens = set(_merge_text_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _merge_text_tokens(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(text or "").lower())
    tokens: list[str] = []
    tokens.extend(re.findall(r"[a-z0-9_+-]{2,24}", compact))
    for length in (3, 2):
        for index in range(0, max(0, len(compact) - length + 1)):
            token = compact[index : index + length]
            if re.fullmatch(r"[\u4e00-\u9fa5]{%d}" % length, token):
                tokens.append(token)
    return list(dict.fromkeys(tokens))[:180]


def _merge_duplicate_source_group(group: list[dict]) -> dict:
    best = max(
        group,
        key=lambda item: (
            len(_merge_text_tokens(str(item.get("text") or ""))),
            float(item.get("confidence") or 0),
            len(str(item.get("text") or "")),
        ),
    )
    merged = dict(best)
    source_ids = sorted({str(item.get("source_id") or "primary") for item in group})
    source_numbers = sorted(
        {
            f"{item.get('source_id') or 'primary'}:{item.get('source_segment_no') or ''}"
            for item in group
        }
    )
    time_aligned = _group_has_offset_aligned_sources(group)
    if time_aligned:
        merged["start_ms"] = int(best.get("start_ms") or 0)
        merged["end_ms"] = int(best.get("end_ms") or merged["start_ms"])
    else:
        merged["start_ms"] = min(int(item.get("start_ms") or 0) for item in group)
        merged["end_ms"] = max(int(item.get("end_ms") or merged["start_ms"]) for item in group)
    merged["source_id"] = "+".join(source_ids)
    flags = _flags(merged)
    for flag in (
        "multi_source_merged",
        f"multi_source_count:{len(source_ids)}",
        f"multi_source_refs:{','.join(source_numbers)[:120]}",
    ):
        if flag not in flags:
            flags.append(flag)
    if time_aligned and "multi_source_time_aligned" not in flags:
        flags.append("multi_source_time_aligned")
    merged["flags"] = flags
    try:
        confidences = [float(item.get("confidence") or 0) for item in group if item.get("confidence") is not None]
        if confidences:
            merged["confidence"] = min(0.98, max(confidences) + 0.04)
    except (TypeError, ValueError):
        pass
    return merged


def _has_nearby_multisource_conflict(segment: dict, segments: list[dict]) -> bool:
    source_id = str(segment.get("source_id") or "primary")
    for other in segments:
        if other is segment:
            continue
        if str(other.get("source_id") or "primary") == source_id:
            continue
        if not _segments_overlap_enough(segment, other):
            similarity = _text_similarity(
                str(segment.get("text") or ""),
                str(other.get("text") or ""),
            )
            if not _segments_are_offset_aligned_conflict_candidate(
                segment,
                other,
                similarity,
            ):
                continue
        if _segments_have_critical_fact_conflict(segment, other):
            return True
        if _text_similarity(str(segment.get("text") or ""), str(other.get("text") or "")) < 0.28:
            return True
    return False


def _group_has_offset_aligned_sources(group: list[dict]) -> bool:
    for index, left in enumerate(group):
        for right in group[index + 1 :]:
            if str(left.get("source_id") or "primary") == str(right.get("source_id") or "primary"):
                continue
            if _segments_overlap_enough(left, right):
                continue
            similarity = _text_similarity(
                str(left.get("text") or ""),
                str(right.get("text") or ""),
            )
            if _segments_are_offset_aligned_duplicate(left, right, similarity):
                return True
    return False


def _segments_are_offset_aligned_duplicate(
    left: dict,
    right: dict,
    similarity: float,
) -> bool:
    if not _has_substantive_offset_alignment_text(left, right):
        return False
    return (
        similarity >= 0.72
        and _source_segments_are_near(left, right)
        and _segment_start_delta_ms(left, right) <= 180_000
    )


def _segments_are_offset_aligned_conflict_candidate(
    left: dict,
    right: dict,
    similarity: float,
) -> bool:
    return (
        similarity >= 0.36
        and _source_segments_are_near(left, right)
        and _segment_start_delta_ms(left, right) <= 180_000
    )


def _source_segments_are_near(left: dict, right: dict) -> bool:
    left_no = _source_segment_no(left)
    right_no = _source_segment_no(right)
    if left_no is None or right_no is None:
        return False
    return abs(left_no - right_no) <= 1


def _has_substantive_offset_alignment_text(left: dict, right: dict) -> bool:
    left_text = _compact_alignment_text(str(left.get("text") or ""))
    right_text = _compact_alignment_text(str(right.get("text") or ""))
    if min(len(left_text), len(right_text)) >= 12:
        return True
    shared_tokens = set(_merge_text_tokens(left_text)) & set(_merge_text_tokens(right_text))
    return len(shared_tokens) >= 8


def _compact_alignment_text(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]+", "", str(text or "").lower())


def _source_segment_no(segment: dict) -> int | None:
    try:
        value = segment.get("source_segment_no")
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _segment_start_delta_ms(left: dict, right: dict) -> int:
    return abs(int(left.get("start_ms") or 0) - int(right.get("start_ms") or 0))


def _segments_have_critical_fact_conflict(left: dict, right: dict) -> bool:
    left_facts = _critical_fact_sets(str(left.get("text") or ""))
    right_facts = _critical_fact_sets(str(right.get("text") or ""))
    for key in ("time", "amount", "owner"):
        left_values = left_facts.get(key, set())
        right_values = right_facts.get(key, set())
        if left_values and right_values and not left_values & right_values:
            return True
    return False


def _critical_fact_sets(text: str) -> dict[str, set[str]]:
    value = re.sub(r"\s+", "", str(text or ""))
    time_values = set(
        re.findall(
            r"(今天|明天|后天|下周[一二三四五六日天]?|本周[一二三四五六日天]?|"
            r"周[一二三四五六日天]|月底|月初|上午|下午|晚上|"
            r"\d{1,2}月\d{1,2}[日号]?|\d{1,2}[日号])",
            value,
        )
    )
    amount_values = set(
        re.findall(
            r"([一二三四五六七八九十两\d]+(?:个|类|份|版|轮|次|条|项|点|页|张|人))",
            value,
        )
    )
    owner_values = set()
    for match in re.finditer(
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
        r"(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)",
        value,
    ):
        owner = _clean_addressed_speaker(match.group(1))
        if owner and not _is_rule_speaker_stopword(owner):
            owner_values.add(owner)
    return {
        "time": time_values,
        "amount": amount_values,
        "owner": owner_values,
    }


def _needs_semantic_segmentation(segments: list[dict]) -> bool:
    speaker_ids = {str(item.get("speaker_id") or "") for item in segments}
    has_asr_speaker = any("asr_speaker" in _flags(item) for item in segments)
    if any(len(str(item.get("text") or "")) > 160 for item in segments):
        return True
    if _has_contextual_speaker_cues(segments):
        return True
    if _has_unresolved_named_turn_cues(segments):
        return True
    if any(_speaker_marker_count(str(item.get("text") or "")) >= 2 for item in segments):
        return True
    if has_asr_speaker and len(speaker_ids) > 1:
        return False
    return False


def _meeting_duration_ms(meeting_id: str) -> int:
    with get_db() as db:
        meeting = db.execute(
            "SELECT duration_ms FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
        audio = db.execute(
            "SELECT MAX(end_ms) AS end_ms FROM audio_segments WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()
    meeting_duration = int(meeting["duration_ms"] or 0) if meeting else 0
    audio_duration = int(audio["end_ms"] or 0) if audio else 0
    return max(meeting_duration, audio_duration)


def _repair_refined_timeline(
    refined: list[dict],
    original: list[dict],
    meeting_duration_ms: int,
) -> list[dict]:
    if len(refined) < 2:
        return refined
    original_start = min(int(item.get("start_ms") or 0) for item in original) if original else 0
    original_end = max(int(item.get("end_ms") or 0) for item in original) if original else 0
    target_start = max(0, original_start)
    target_end = max(original_end, meeting_duration_ms, target_start + len(refined) * 1000)
    refined_start = min(int(item.get("start_ms") or 0) for item in refined)
    refined_end = max(int(item.get("end_ms") or 0) for item in refined)
    refined_span = max(1, refined_end - refined_start)
    target_span = max(len(refined), target_end - target_start)
    needs_repair = target_span > refined_span * 5 or refined_span <= len(refined) * 250
    if not needs_repair:
        return refined
    repaired: list[dict] = []
    for index, item in enumerate(refined):
        next_item = refined[index + 1] if index + 1 < len(refined) else None
        start = target_start + round(target_span * index / len(refined))
        end = (
            target_end
            if next_item is None
            else target_start + round(target_span * (index + 1) / len(refined))
        )
        next_item = dict(item)
        next_item["start_ms"] = start
        next_item["end_ms"] = max(start + 1, end)
        flags = _flags(next_item)
        if "timeline_repaired" not in flags:
            flags.append("timeline_repaired")
        next_item["flags"] = flags
        repaired.append(next_item)
    return repaired


def _refined_segments_cover_source(refined: list[dict], original: list[dict]) -> bool:
    source_tokens = _coverage_tokens(" ".join(str(item.get("text") or "") for item in original))
    if len(source_tokens) < 24:
        return True
    refined_tokens = set(_coverage_tokens(" ".join(str(item.get("text") or "") for item in refined)))
    if not refined_tokens:
        return False
    covered = sum(1 for token in source_tokens if token in refined_tokens)
    if covered / len(source_tokens) < 0.42:
        return False
    return _refined_segments_cover_each_source(refined, original)


def _refined_segments_cover_each_source(
    refined: list[dict],
    original: list[dict],
) -> bool:
    for source in original:
        source_text = str(source.get("text") or "")
        source_tokens = _coverage_tokens(source_text)
        if len(source_tokens) < 8:
            continue
        related_text = _related_refined_text(refined, source)
        related_tokens = set(_coverage_tokens(related_text))
        if not related_tokens:
            return False
        covered = sum(1 for token in source_tokens if token in related_tokens)
        if covered / len(source_tokens) < 0.25:
            return False
    return True


def _related_refined_text(refined: list[dict], source: dict) -> str:
    source_no = source.get("source_segment_no")
    related: list[str] = []
    if source_no is not None:
        related = [
            str(item.get("text") or "")
            for item in refined
            if item.get("source_segment_no") == source_no
        ]
        if related:
            return " ".join(related)
    source_start = int(source.get("start_ms") or 0)
    source_end = int(source.get("end_ms") or source_start)
    for item in refined:
        item_start = int(item.get("start_ms") or 0)
        item_end = int(item.get("end_ms") or item_start)
        if item_start <= source_end and item_end >= source_start:
            related.append(str(item.get("text") or ""))
    return " ".join(related)


def _coverage_tokens(text: str) -> list[str]:
    text = re.sub(r"\s+", "", str(text or ""))
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_+-]{2,24}", text):
        tokens.append(match.group(0).lower())
    for length in (4, 3):
        for index in range(0, max(0, len(text) - length + 1), length):
            token = text[index : index + length]
            if re.fullmatch(r"[\u4e00-\u9fa5]{%d}" % length, token):
                tokens.append(token)
    return list(dict.fromkeys(tokens))[:260]


def _rule_refine_segments(segments: list[dict]) -> list[dict]:
    refined: list[dict] = []
    for segment in segments:
        blocks = _split_mixed_speaker_blocks(str(segment.get("text") or ""))
        if len(blocks) < 2:
            blocks = _split_speaker_markers(str(segment.get("text") or ""))
        if len(blocks) < 2:
            blocks = _split_addressed_speaker_blocks(str(segment.get("text") or ""))
        if len(blocks) < 2:
            blocks = _split_inline_addressed_response(segment)
        if len(blocks) < 2:
            block = _single_speaker_marker_block(str(segment.get("text") or ""))
            if block and _is_generic_speaker_name(
                str(segment.get("display_name") or segment.get("speaker_id") or "")
            ):
                refined.append(
                    {
                        **segment,
                        "speaker_id": _speaker_id(block["speaker"]),
                        "display_name": block["speaker"],
                        "text": block["text"],
                        "confidence": min(float(segment.get("confidence") or 0.72), 0.82),
                        "flags": [
                            *_flags(segment),
                            "semantic_rule",
                            "single_marker_speaker_inference",
                            "speaker_review",
                            "scenario:explicit_name",
                        ],
                    }
                )
                continue
        if len(blocks) < 2:
            refined.append(segment)
            continue
        start_ms = int(segment.get("start_ms") or 0)
        end_ms = int(segment.get("end_ms") or start_ms + len(blocks) * 1000)
        duration = max(len(blocks), end_ms - start_ms)
        for index, block in enumerate(blocks):
            block_start = start_ms + round(duration * index / len(blocks))
            block_end = end_ms if index == len(blocks) - 1 else start_ms + round(duration * (index + 1) / len(blocks))
            speaker = block["speaker"]
            scenario = block.get("scenario", "explicit_name")
            confidence_cap = _block_confidence_cap(block, 0.82)
            flags = [
                *_flags(segment),
                f"semantic_rule:{scenario}",
                "semantic_rule",
                "speaker_review",
                f"scenario:{scenario}",
            ]
            for flag in block.get("flags", []):
                if flag not in flags:
                    flags.append(flag)
            reason = str(block.get("reason") or "").strip()
            if reason:
                reason_flag = f"reason:{reason[:80]}"
                if reason_flag not in flags:
                    flags.append(reason_flag)
            refined.append(
                {
                    **segment,
                    "speaker_id": block.get("speaker_id") or _speaker_id(speaker),
                    "display_name": speaker,
                    "start_ms": block_start,
                    "end_ms": max(block_start + 1, block_end),
                    "text": block["text"],
                    "confidence": min(float(segment.get("confidence") or 0.72), confidence_cap),
                    "flags": flags,
                }
            )
    return refined


def _block_confidence_cap(block: dict, default: float) -> float:
    try:
        return float(block.get("confidence_cap", default))
    except (TypeError, ValueError):
        return default


def _rule_refine_residual_mixed_segments(segments: list[dict]) -> list[dict]:
    refined: list[dict] = []
    for segment in segments:
        text = str(segment.get("text") or "")
        if _speaker_marker_count(text) < 2:
            refined.append(segment)
            continue
        split = _rule_refine_segments([segment])
        if len(split) <= 1:
            refined.append(segment)
            continue
        for item in split:
            flags = _flags(item)
            for flag in ("llm_residual_rule_refined", "speaker_review"):
                if flag not in flags:
                    flags.append(flag)
            item["flags"] = flags
            try:
                item["confidence"] = min(float(item.get("confidence") or 0.72), 0.74)
            except (TypeError, ValueError):
                item["confidence"] = 0.68
            refined.append(item)
    return refined


def _apply_contextual_speaker_inference(segments: list[dict]) -> list[dict]:
    if len(segments) < 2:
        return segments
    source_ids = [str(item.get("speaker_id") or "") for item in segments]
    single_source_id = len({item for item in source_ids if item}) <= 1
    speaker_id_map: dict[str, str] = {}
    result: list[dict] = []
    pending: dict | None = None
    for segment in segments:
        item = dict(segment)
        speaker_id = str(item.get("speaker_id") or "")
        if speaker_id in speaker_id_map and _is_generic_speaker_name(
            str(item.get("display_name") or speaker_id)
        ):
            _apply_inferred_speaker(
                item,
                speaker_id_map[speaker_id],
                preserve_speaker_id=not single_source_id,
                scenario="context_bridge",
                reason="同一 ASR 说话人标签此前已由上下文归属。",
            )
        elif pending and _can_apply_pending_speaker(pending, item):
            preserve_speaker_id = not single_source_id and speaker_id != pending.get("source_speaker_id")
            _apply_inferred_speaker(
                item,
                str(pending["speaker"]),
                preserve_speaker_id=preserve_speaker_id,
                scenario=str(pending.get("scenario") or "context_bridge"),
                reason=str(pending.get("reason") or "前文点名后，当前段落承接该上下文。"),
            )
            if speaker_id and preserve_speaker_id:
                speaker_id_map[speaker_id] = str(pending["speaker"])
            pending = None

        result.append(item)
        addressed = _extract_addressed_speakers(str(item.get("text") or ""))
        if addressed:
            topic_text = _addressed_topic_text(str(item.get("text") or ""), addressed[-1])
            pending = {
                "speaker": addressed[-1]["speaker"],
                "scenario": addressed[-1].get("scenario", "context_bridge"),
                "source_speaker_id": str(item.get("speaker_id") or ""),
                "topic_tokens": _pending_topic_tokens(
                    topic_text,
                    addressed[-1]["speaker"],
                ),
                "topic_text": topic_text,
                "reason": _pending_speaker_reason(topic_text, addressed[-1]["speaker"]),
                "ttl": 2,
            }
            continue
        if pending:
            pending["ttl"] = int(pending.get("ttl") or 0) - 1
            if pending["ttl"] <= 0:
                pending = None
    return result


def _can_apply_pending_speaker(pending: dict, segment: dict) -> bool:
    speaker = str(pending.get("speaker") or "").strip()
    if not speaker or _is_rule_speaker_stopword(speaker):
        return False
    text = str(segment.get("text") or "").strip()
    if not text:
        return False
    display_name = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
    if not _is_generic_speaker_name(display_name) and display_name != speaker:
        return False
    explicit = _single_speaker_marker_block(text)
    if explicit and explicit.get("speaker") != speaker:
        return False
    if _looks_like_addressed_response(text):
        return True
    if _matches_pending_topic(pending, text):
        return True
    speaker_id = str(segment.get("speaker_id") or "")
    return bool(speaker_id and speaker_id != pending.get("source_speaker_id"))


def _apply_inferred_speaker(
    segment: dict,
    speaker: str,
    preserve_speaker_id: bool,
    scenario: str = "context_bridge",
    reason: str = "",
) -> None:
    segment["display_name"] = speaker
    if not preserve_speaker_id:
        segment["speaker_id"] = _speaker_id(speaker)
    confidence = segment.get("confidence")
    try:
        segment["confidence"] = min(float(confidence), 0.72)
    except (TypeError, ValueError):
        segment["confidence"] = 0.68
    flags = _flags(segment)
    for flag in (
        "semantic_rule",
        "contextual_speaker_inference",
        "speaker_review",
        f"scenario:{scenario or 'context_bridge'}",
    ):
        if flag not in flags:
            flags.append(flag)
    if reason:
        reason_flag = f"reason:{reason[:80]}"
        if reason_flag not in flags:
            flags.append(reason_flag)
    segment["flags"] = flags


def _normalize_semantic_segments(segments: list[dict], source: str) -> list[dict]:
    normalized: list[dict] = []
    last_end = 0
    for index, segment in enumerate(segments):
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        speaker = str(segment.get("display_name") or segment.get("speaker") or segment.get("speaker_id") or "待确认").strip()
        speaker_id = str(segment.get("speaker_id") or _speaker_id(speaker)).strip()
        start_ms = int(segment.get("start_ms") or last_end or index * 1000)
        end_ms = int(segment.get("end_ms") or start_ms + 1000)
        flags = _flags(segment)
        marker = f"semantic_{source}"
        if marker not in flags:
            flags.append(marker)
        normalized.append(
            {
                **segment,
                "speaker_id": speaker_id,
                "display_name": speaker or speaker_id,
                "start_ms": max(0, start_ms),
                "end_ms": max(max(0, start_ms) + 1, end_ms),
                "text": text,
                "confidence": segment.get("confidence"),
                "flags": flags,
            }
        )
        last_end = normalized[-1]["end_ms"]
    return normalized or segments


def _preserve_source_segments(refined: list[dict], original: list[dict]) -> list[dict]:
    if not original:
        return refined
    for item in refined:
        if item.get("source_id") and item.get("source_segment_no"):
            continue
        match = next(
            (
                segment
                for segment in original
                if int(segment.get("start_ms") or 0) <= int(item.get("start_ms") or 0) <= int(segment.get("end_ms") or 0)
            ),
            original[0],
        )
        if match.get("source_id") and not item.get("source_id"):
            item["source_id"] = match["source_id"]
        if match.get("source_segment_no"):
            item["source_segment_no"] = match["source_segment_no"]
    return refined


def _split_speaker_markers(text: str) -> list[dict]:
    pattern = re.compile(r"(^|[\n\r。！？!?；;])\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,12})\s*(?:[:：]|说[，,、]?)")
    matches = []
    for match in pattern.finditer(text):
        boundary_len = len(match.group(1) or "")
        matches.append(
            {
                "marker_start": match.start() + boundary_len,
                "content_start": match.end(),
                "speaker": match.group(2).strip(),
            }
        )
    if len(matches) < 2:
        return []
    prefix = text[: matches[0]["marker_start"]].strip()
    blocks = []
    for index, item in enumerate(matches):
        next_item = matches[index + 1] if index + 1 < len(matches) else None
        body = text[item["content_start"] : next_item["marker_start"] if next_item else len(text)].strip()
        if prefix and index == 0:
            body = f"{prefix}\n{body}".strip()
        if body:
            blocks.append(
                {
                    "speaker": item["speaker"],
                    "text": body,
                    "scenario": "explicit_name",
                }
            )
    return blocks


def _split_mixed_speaker_blocks(text: str) -> list[dict]:
    candidates: list[dict] = []
    candidates.extend(
        {
            **item,
            "kind": "addressed",
        }
        for item in _extract_addressed_speakers(text)
    )
    explicit_pattern = re.compile(
        r"(^|[\n\r。！？!?；;])\s*"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,12})\s*"
        r"(?:[:：]|说[，,、]?)"
    )
    for match in explicit_pattern.finditer(text):
        boundary_len = len(match.group(1) or "")
        raw_speaker = str(match.group(2) or "")
        if "你" in raw_speaker or "您" in raw_speaker:
            continue
        speaker = _clean_addressed_speaker(raw_speaker)
        if not speaker or _is_rule_speaker_stopword(speaker):
            continue
        candidates.append(
            {
                "start": match.start(2),
                "marker_start": match.start() + boundary_len,
                "content_start": match.end(),
                "speaker": speaker,
                "scenario": "explicit_name",
                "kind": "explicit",
            }
        )
    if len(candidates) < 2:
        return []
    candidates = sorted(candidates, key=lambda item: (item["marker_start"], item["start"]))
    deduped: list[dict] = []
    for item in candidates:
        if deduped and abs(int(item["marker_start"]) - int(deduped[-1]["marker_start"])) <= 2:
            if (
                deduped[-1].get("kind") != "explicit"
                and item.get("kind") == "explicit"
            ) or (
                deduped[-1].get("scenario") != "task_ownership"
                and item.get("scenario") == "task_ownership"
            ):
                deduped[-1] = item
            continue
        deduped.append(item)
    if len(deduped) < 2:
        return []
    prefix = text[: int(deduped[0]["marker_start"])].strip()
    blocks: list[dict] = []
    for index, item in enumerate(deduped):
        next_item = deduped[index + 1] if index + 1 < len(deduped) else None
        body_start = int(item.get("content_start") or item["marker_start"])
        if item.get("kind") == "addressed":
            body_start = int(item["marker_start"])
        body_end = int(next_item["marker_start"]) if next_item else len(text)
        body = text[body_start:body_end].strip()
        if item.get("kind") == "addressed":
            body = _remove_address_prefix(body, str(item["speaker"]))
        if prefix and index == 0:
            body = f"{prefix}\n{body}".strip()
        if body:
            blocks.append(
                {
                    "speaker": item["speaker"],
                    "text": body,
                    "scenario": item.get("scenario", "explicit_name"),
                }
            )
    return blocks


def _single_speaker_marker_block(text: str) -> dict | None:
    pattern = re.compile(
        r"^\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,8})"
        r"\s*(?:[:：]|说[，,、]?)\s*(.+)$",
        re.DOTALL,
    )
    match = pattern.match(text.strip())
    if not match:
        return None
    raw_speaker = str(match.group(1) or "")
    if "你" in raw_speaker or "您" in raw_speaker:
        return None
    speaker = _clean_addressed_speaker(raw_speaker)
    body = str(match.group(2) or "").strip()
    if not speaker or not body or _is_rule_speaker_stopword(speaker):
        return None
    return {
        "speaker": speaker,
        "text": body,
        "scenario": "explicit_name",
    }


def _split_addressed_speaker_blocks(text: str) -> list[dict]:
    candidates: list[dict] = []
    candidates.extend(_extract_addressed_speakers(text))
    if len(candidates) < 2:
        return []
    candidates = sorted(candidates, key=lambda item: item["start"])
    deduped: list[dict] = []
    last_start = -1
    for item in candidates:
        if item["start"] == last_start:
            if deduped and deduped[-1]["scenario"] != "task_ownership" and item["scenario"] == "task_ownership":
                deduped[-1] = item
            continue
        deduped.append(item)
        last_start = item["start"]
    if len(deduped) < 2:
        return []
    prefix = text[: deduped[0]["marker_start"]].strip()
    blocks: list[dict] = []
    for index, item in enumerate(deduped):
        next_item = deduped[index + 1] if index + 1 < len(deduped) else None
        body_start = item["marker_start"]
        body_end = next_item["marker_start"] if next_item else len(text)
        body = text[body_start:body_end].strip()
        body = _remove_address_prefix(body, item["speaker"])
        if prefix and index == 0:
            body = f"{prefix}\n{body}".strip()
        if body:
            blocks.append(
                {
                    "speaker": item["speaker"],
                    "text": body,
                    "scenario": item["scenario"],
                }
            )
    return blocks


def _split_inline_addressed_response(segment: dict) -> list[dict]:
    text = str(segment.get("text") or "").strip()
    addressed = _extract_addressed_speakers(text)
    if len(addressed) != 1:
        return []
    candidate = addressed[0]
    speaker = str(candidate.get("speaker") or "").strip()
    if not speaker or _is_rule_speaker_stopword(speaker):
        return []

    marker_start = int(candidate.get("marker_start") or 0)
    sentence_end = _inline_response_boundary(text, marker_start)
    if sentence_end <= marker_start or sentence_end >= len(text):
        return []
    prefix = text[:marker_start].strip()
    addressed_sentence = text[marker_start:sentence_end].strip()
    response = text[sentence_end:].strip()
    if not response or not _looks_like_inline_response(response):
        return []

    original_speaker = str(
        segment.get("display_name") or segment.get("speaker_id") or "发言人"
    ).strip()
    prompt_text = " ".join(part for part in [prefix, addressed_sentence] if part).strip()
    if not prompt_text:
        return []
    prompt_text = _remove_address_prefix(prompt_text, speaker)
    prompt_text = prompt_text or addressed_sentence
    response_text = _strip_leading_sentence_punctuation(response)
    if not response_text:
        return []
    source_speaker_id = str(segment.get("speaker_id") or "")
    return [
        {
            "speaker": original_speaker,
            "speaker_id": source_speaker_id or _speaker_id(original_speaker),
            "text": prompt_text,
            "scenario": "native_speaker",
            "flags": ["inline_address_prompt"],
            "confidence_cap": 0.82,
        },
        {
            "speaker": speaker,
            "speaker_id": _speaker_id(speaker),
            "text": response_text,
            "scenario": str(candidate.get("scenario") or "context_bridge"),
            "flags": ["inline_addressed_response"],
            "confidence_cap": 0.72,
            "reason": _pending_speaker_reason(addressed_sentence, speaker),
        },
    ]


def _sentence_end_after(text: str, start: int) -> int:
    match = re.search(r"[。！？!?；;\n\r]", text[max(0, start):])
    if not match:
        return -1
    return max(0, start) + match.end()


def _inline_response_boundary(text: str, start: int) -> int:
    sentence_end = _sentence_end_after(text, start)
    search_from = max(0, start)
    match = _INLINE_RESPONSE_CUE_PATTERN.search(text[search_from:])
    cue_boundary = search_from + match.start() if match else -1
    boundaries = [
        value
        for value in (sentence_end, cue_boundary)
        if value > start
    ]
    return min(boundaries) if boundaries else -1


_INLINE_RESPONSE_CUE_PATTERN = re.compile(
    r"(?:好的?|可以|行|没问题)?[\s，,、]*"
    r"(?:我这边|我们这边|我来|我负责|我们负责|我准备|我已经|我们已经|"
    r"我先|我们先|我会|我们会|这块我|这边我|这部分我|这部分我们)"
)


def _looks_like_inline_response(text: str) -> bool:
    text = _strip_leading_sentence_punctuation(text)
    if _looks_like_addressed_response(text):
        return True
    if re.match(
        r"^(这块|这边|这部分|我们|我)?"
        r"(已经|准备|负责|确认|补充|整理|输出|完成|推进|处理|测试|检查|会|能|可以)",
        text,
    ):
        return True
    return False


def _strip_leading_sentence_punctuation(text: str) -> str:
    return re.sub(r"^[\s。！？!?；;，,、]+", "", str(text or "")).strip()


def _extract_addressed_speakers(text: str) -> list[dict]:
    candidates: list[dict] = []
    for pattern, scenario in _ADDRESSED_SPEAKER_PATTERNS:
        for match in pattern.finditer(text):
            speaker = _clean_addressed_speaker(match.group(1))
            if not speaker or _is_rule_speaker_stopword(speaker):
                continue
            candidates.append(
                {
                    "start": match.start(1),
                    "marker_start": match.start(),
                    "content_start": match.end(1),
                    "speaker": speaker,
                    "scenario": scenario,
                }
            )
    return sorted(candidates, key=lambda item: item["start"])


def _addressed_topic_text(text: str, addressed: dict) -> str:
    marker_start = int(addressed.get("marker_start") or 0)
    next_boundary = re.search(r"[。！？!?；;\n\r]", text[marker_start:])
    if next_boundary:
        return text[marker_start : marker_start + next_boundary.start()]
    return text[marker_start : min(len(text), marker_start + 120)]


def _pending_topic_tokens(text: str, speaker: str) -> list[str]:
    cleaned = _remove_address_prefix(str(text or ""), speaker)
    cleaned = re.sub(
        r"(你|您|先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调|"
        r"一下|这个|那个|部分|那块|这块|那边|这边)",
        "",
        cleaned,
    )
    tokens = [
        token for token in _context_tokens(cleaned)
        if len(token) >= 2 and not _is_context_stopword(token)
    ]
    return list(dict.fromkeys(tokens))[:16]


def _matches_pending_topic(pending: dict, text: str) -> bool:
    tokens = set(pending.get("topic_tokens") or [])
    if not tokens:
        return False
    text_tokens = set(_context_tokens(text))
    overlap = tokens & text_tokens
    if len(overlap) >= 2:
        return True
    if len(overlap) == 1 and re.search(
        r"(明天|今天|周[一二三四五六日]|下周|月底|补完|完成|给结果|给大家|确认|处理|推进|"
        r"准备|输出|发|改|调|测试|覆盖|检查)",
        text,
    ):
        return True
    return False


def _pending_speaker_reason(topic_text: str, speaker: str) -> str:
    topic = _remove_address_prefix(str(topic_text or ""), speaker)
    topic = re.sub(r"\s+", "", topic)[:36]
    if topic:
        return f"前文点名“{speaker}”并提到“{topic}”，当前段落承接该议题。"
    return f"前文点名“{speaker}”，当前段落承接该上下文。"


def _has_contextual_speaker_cues(segments: list[dict]) -> bool:
    generic_seen = any(
        _is_generic_speaker_name(
            str(item.get("display_name") or item.get("speaker_id") or "")
        )
        for item in segments
    )
    for segment in segments:
        text = str(segment.get("text") or "")
        if _extract_addressed_speakers(text):
            return True
        if generic_seen and _single_speaker_marker_block(text):
            return True
    return False


def _has_unresolved_named_turn_cues(segments: list[dict]) -> bool:
    if len(segments) < 2:
        return False
    display_names = [
        str(item.get("display_name") or item.get("speaker_id") or "").strip()
        for item in segments
    ]
    generic_seen = any(_is_generic_speaker_name(name) for name in display_names)
    if not generic_seen:
        return False
    concrete_speakers = {
        name for name in display_names if name and not _is_generic_speaker_name(name)
    }
    candidates = set(mentioned_people_candidates(segments, limit=12))
    unresolved = candidates - concrete_speakers
    if len(unresolved) >= 2:
        return True
    text = "\n".join(str(item.get("text") or "") for item in segments)
    return bool(
        unresolved
        and re.search(
            r"(提到|补充|确认|负责|跟进|准备|处理|输出|给|发|看|改|调)",
            text,
        )
    )


def _looks_like_addressed_response(text: str) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    if re.search(
        r"(我这边|我们这边|我来|我负责|我们负责|我准备|我已经|我们已经|"
        r"我先|我们先|这块我|这边我|好的[，,、]?(我|我们)|可以[，,、]?(我|我们))",
        text,
    ):
        return True
    if re.match(r"^(好|好的|可以|行|没问题)[，,、。\s]*(这块|这边|我|我们)", text):
        return True
    return False


_ADDRESSED_SPEAKER_PATTERNS = [
    (
        re.compile(
            r"(?:^|[\s，,。！？!?；;、])"
            r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
            r"(?:你|您)(?:先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调|那|这)"
        ),
        "context_bridge",
    ),
    (
        re.compile(
            r"(?:^|[\s，,。！？!?；;、])"
            r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
            r"(?:你|您)(?:那个部分|这个部分|那块|这块|那边|这边|部分)"
        ),
        "task_ownership",
    ),
    (
        re.compile(
            r"(?:^|[\s，,。！？!?；;、])"
            r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
            r"(?:的)?(?:部分|那块|这块|那边|这边|那个部分|这个部分)"
        ),
        "task_ownership",
    ),
    (
        re.compile(
            r"(?:^|[\s，,。！？!?；;、])"
            r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
            r"(?:后面|后续|回头|稍后|之后)"
            r"(?:看|确认|负责|跟进|处理|补|改|调|发|做|给|整理|输出)"
        ),
        "task_ownership",
    ),
    (
        re.compile(
            r"(?:^|[\s，,。！？!?；;、])"
            r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
            r"(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)"
        ),
        "task_ownership",
    ),
]


def _remove_address_prefix(text: str, speaker: str) -> str:
    pattern = (
        r"^[\s，,。！？!?；;、]*"
        + re.escape(speaker)
        + r"(?:你|您)?(?:那个部分|这个部分|的部分|那块|这块|那边|这边|部分|"
        r"后面|后续|回头|稍后|之后|先|再|来|把|帮|看|说|讲|分享|确认|负责|"
        r"处理|弄|搞|发|补|改|调|那|这)?[，,、：:\s]*"
    )
    return re.sub(pattern, "", text, count=1).strip()


def _clean_addressed_speaker(name: str) -> str:
    value = re.sub(
        r"^[\s，,。！？!?；;、:：]+|[\s，,。！？!?；;、:：]+$",
        "",
        str(name or ""),
    )
    value = re.sub(r"^(?:然后|接下来|请)", "", value)
    if len(value) > 2 and value.startswith("那"):
        value = value[1:]
    if len(value) > 3 and value.startswith(("这个", "那个")):
        value = value[2:]
    return re.sub(
        r"(?:你|您|你那个|您那个|你这个|您这个|这个|那个|这边|那边|后面|先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调)+$",
        "",
        value,
    ).strip()


def _is_rule_speaker_stopword(name: str) -> bool:
    if name in {
        "这个",
        "那个",
        "我",
        "你",
        "您",
        "他",
        "她",
        "咱们",
        "大家",
        "我们",
        "你们",
        "他们",
        "会议",
        "客户",
        "问题",
        "功能",
        "系统",
        "模型",
        "数据",
        "前端",
        "后端",
        "团队",
        "负责人",
        "事项",
        "待办",
    }:
        return True
    if _looks_like_rule_topic_phrase(name):
        return True
    return False


def _looks_like_rule_topic_phrase(name: str) -> bool:
    value = str(name or "").strip()
    if not re.fullmatch(r"[\u4e00-\u9fa5]{3,8}", value):
        return False
    topic_words = {
        "错误",
        "样例",
        "自动",
        "测试",
        "外接",
        "数据源",
        "登录",
        "界面",
        "图标",
        "模型",
        "质量",
        "部署",
        "下载",
        "截图",
        "客户",
        "名单",
        "物料",
        "舞台",
        "音响",
        "报价",
    }
    return any(word in value for word in topic_words)


def _is_generic_speaker_name(name: str) -> bool:
    name = str(name or "").strip()
    if not name:
        return True
    lowered = name.lower()
    if lowered.startswith("speaker") or name.startswith("发言人"):
        return True
    return name in {"未知", "待确认", "不确定", "unknown"}


def _speaker_marker_count(text: str) -> int:
    return max(len(_split_speaker_markers(text)), len(_split_addressed_speaker_blocks(text)))


def _speaker_id(name: str) -> str:
    token = "".join(char for char in str(name or "") if char.isalnum())
    return f"MANUAL_{token[:24]}" if token else "SPEAKER_01"


def _flags(segment: dict) -> list[str]:
    value = segment.get("flags") or []
    return _normalize_flags_value(value)


def _normalize_flags_value(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]
    return [str(value)]


def _replace_transcript(meeting_id: str, segments: list[dict]) -> None:
    with get_db() as db:
        archive_transcript_rows(db, meeting_id, None, "system", "transcribe_replace")
        db.execute("DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,))
        _insert_transcript_segments(db, meeting_id, segments, 1, None)


def _replace_transcript_for_segment(meeting_id: str, segment_no: int, segments: list[dict]) -> None:
    with get_db() as db:
        meeting = db.execute("SELECT version FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        version = int(meeting["version"] if meeting else 1) + 1
        audio = db.execute(
            "SELECT * FROM audio_segments WHERE meeting_id = ? AND segment_no = ?",
            (meeting_id, segment_no),
        ).fetchone()
        source_id = str(audio["source_id"] or "primary") if audio else None
        source_segment_no = int(audio["source_segment_no"] or segment_no) if audio else segment_no
        archive_transcript_rows(
            db,
            meeting_id,
            source_segment_no,
            "system",
            "segment_retranscribe",
            source_id,
        )
        db.execute(
            _delete_transcript_for_source_sql(source_id),
            _delete_transcript_for_source_params(meeting_id, source_id, source_segment_no),
        )
        _insert_transcript_segments(db, meeting_id, segments, version, source_segment_no)


def _insert_transcript_segments(
    db,
    meeting_id: str,
    segments: list[dict],
    version: int,
    source_segment_no: int | None,
) -> None:
    saved_speakers = {
        row["speaker_id"]: row["display_name"]
        for row in db.execute(
            "SELECT speaker_id, display_name FROM speakers WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchall()
        if row["display_name"] and not _is_generic_speaker_name(row["display_name"])
    }
    seen_speakers: dict[str, str] = {}
    for segment in segments:
        speaker_id = segment["speaker_id"]
        display_name = saved_speakers.get(speaker_id) or segment.get("display_name") or speaker_id
        segment_source_no = segment.get("source_segment_no")
        if segment_source_no is None:
            segment_source_no = source_segment_no
        segment_source_id = str(segment.get("source_id") or "").strip()
        flags = segment.get("flags") or []
        if not isinstance(flags, list):
            flags = [str(flags)]
        seen_speakers[speaker_id] = display_name
        db.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("seg"),
                meeting_id,
                version,
                segment_source_id,
                segment_source_no,
                speaker_id,
                display_name,
                int(segment["start_ms"]),
                int(segment["end_ms"]),
                segment["text"],
                segment.get("confidence"),
                json.dumps(flags, ensure_ascii=False),
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


def _delete_transcript_for_source_sql(source_id: str | None) -> str:
    if source_id == "primary":
        return """
            DELETE FROM transcript_segments
            WHERE meeting_id = ?
              AND COALESCE(NULLIF(source_id, ''), 'primary') = 'primary'
              AND source_segment_no = ?
            """
    return """
        DELETE FROM transcript_segments
        WHERE meeting_id = ? AND source_id = ? AND source_segment_no = ?
    """


def _delete_transcript_for_source_params(
    meeting_id: str,
    source_id: str | None,
    source_segment_no: int,
) -> tuple:
    if source_id == "primary":
        return (meeting_id, source_segment_no)
    return (meeting_id, source_id or "", source_segment_no)


def _summarize(segments: list[dict]) -> tuple[str, str, list[dict]]:
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
    values = {row["key"]: row["value"] for row in rows}
    try:
        summary, role_notes, actions = summarize_with_llm(
            segments,
            llm_options_from_settings_and_db(values),
        )
        return _grounded_summary_result(summary, role_notes, actions, segments)
    except Exception:
        pass
    summary, role_notes = _grounded_summary_from_segments(segments)
    actions = [
        {
            "owner": "待确认",
            "task": "检查转写结果并补充真实会议纪要",
            "due": "",
            "status": "open",
        }
    ]
    return summary, role_notes, actions


def _grounded_summary_result(
    summary: str,
    role_notes: str,
    actions: list[dict],
    segments: list[dict],
) -> tuple[str, str, list[dict]]:
    normalized_actions = _normalize_action_owners(actions, segments)
    if _summary_is_grounded(summary, role_notes, normalized_actions, segments):
        return summary, role_notes, normalized_actions
    fallback_summary, fallback_role_notes = _grounded_summary_from_segments(segments)
    fallback_actions = _prefer_suggested_action_owners(normalized_actions, segments)
    return fallback_summary, fallback_role_notes, fallback_actions


def _summary_is_grounded(
    summary: str,
    role_notes: str,
    actions: list[dict],
    segments: list[dict],
) -> bool:
    if not segments:
        return True
    report = build_quality_report(
        [_segment_row_like(item) for item in segments],
        [_action_row_like(item) for item in actions],
        [],
        summary,
        role_notes,
    )
    metrics = report.get("metrics") or {}
    coverage = float(metrics.get("summary_evidence_coverage") or 0)
    unsupported = int(metrics.get("summary_unsupported_count") or 0)
    if unsupported == 0:
        return True
    return coverage >= 0.6 and unsupported <= 1


def _grounded_summary_from_segments(segments: list[dict]) -> tuple[str, str]:
    if not segments:
        return "", ""
    topic_lines = _grounded_topic_lines(segments)
    if topic_lines:
        summary = "基于转写原文的保守整理：\n" + "\n".join(
            f"- {line}" for line in topic_lines[:8]
        )
    else:
        summary = "基于转写原文的保守整理：\n" + "\n".join(
            f"- {item['speaker']}：{item['text']}" for item in _speaker_segments(segments)[:8]
        )
    role_notes = "\n".join(
        f"{speaker}：{'；'.join(texts[:4])}"
        for speaker, texts in _group_text_by_speaker(segments).items()
    )
    return summary, role_notes


def _grounded_topic_lines(segments: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in _speaker_segments(segments):
        text = item["text"]
        speaker = item["speaker"]
        if not text:
            continue
        if speaker and not _is_generic_speaker_name(speaker):
            line = f"{speaker}：{text}"
        else:
            line = text
        if line not in lines:
            lines.append(line)
    return lines


def _speaker_segments(segments: list[dict]) -> list[dict]:
    items = []
    for segment in segments:
        text = _clean_summary_text(str(segment.get("text") or ""))
        if not text:
            continue
        speaker = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
        items.append({"speaker": speaker, "text": text})
    return items


def _group_text_by_speaker(segments: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for item in _speaker_segments(segments):
        speaker = item["speaker"] or "待确认"
        grouped.setdefault(speaker, [])
        if item["text"] not in grouped[speaker]:
            grouped[speaker].append(item["text"])
    return grouped


def _clean_summary_text(text: str, limit: int = 120) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = re.sub(r"^[，,。！？!?；;、:：\s]+", "", value)
    return value[:limit]


def _prefer_suggested_action_owners(actions: list[dict], segments: list[dict]) -> list[dict]:
    if not actions:
        return actions
    report = build_quality_report(
        [_segment_row_like(item) for item in segments],
        [
            _action_row_like(
                item,
                fallback_id=f"act_probe_{index + 1}",
            )
            for index, item in enumerate(actions)
        ],
        [],
        "",
        "",
    )
    suggestions = {
        str(item.get("id") or ""): str(item.get("suggested_owner") or "").strip()
        for item in report.get("actionEvidence") or []
        if str(item.get("suggested_owner") or "").strip()
    }
    if not suggestions:
        return actions
    updated: list[dict] = []
    for index, action in enumerate(actions):
        item = dict(action)
        action_id = str(item.get("id") or f"act_probe_{index + 1}")
        suggestion = suggestions.get(action_id)
        if suggestion and (
            _is_generic_owner(str(item.get("owner") or ""))
            or _owner_overrides_context(
                str(item.get("owner") or ""),
                str(item.get("task") or ""),
                _owner_context_candidates(segments),
            )
        ):
            item["owner"] = suggestion
        updated.append(item)
    return updated


def _segment_row_like(segment: dict) -> dict:
    flags = segment.get("flags") or []
    if not isinstance(flags, list):
        flags = [str(flags)]
    return {
        "id": segment.get("id", ""),
        "meeting_id": segment.get("meeting_id", ""),
        "version": segment.get("version", 1),
        "source_id": segment.get("source_id", ""),
        "source_segment_no": segment.get("source_segment_no"),
        "speaker_id": segment.get("speaker_id") or "SPEAKER_01",
        "display_name": segment.get("display_name") or segment.get("speaker_id") or "发言人",
        "start_ms": int(segment.get("start_ms") or 0),
        "end_ms": int(segment.get("end_ms") or 0),
        "text": segment.get("text") or "",
        "confidence": segment.get("confidence"),
        "flags": json.dumps(flags, ensure_ascii=False),
        "created_at": segment.get("created_at", ""),
    }


def _action_row_like(action: dict, fallback_id: str = "") -> dict:
    return {
        "id": action.get("id") or fallback_id,
        "meeting_id": action.get("meeting_id", ""),
        "owner": action.get("owner") or "待确认",
        "task": action.get("task") or "",
        "due": action.get("due") or "",
        "status": action.get("status") or "open",
        "source_segment_id": action.get("source_segment_id"),
        "created_at": action.get("created_at", ""),
        "updated_at": action.get("updated_at", ""),
    }


def _normalize_action_owners(actions: list[dict], segments: list[dict]) -> list[dict]:
    if not actions:
        return actions
    speaker_names = [
        str(item.get("display_name") or "").strip()
        for item in segments
        if str(item.get("display_name") or "").strip()
    ]
    speaker_names = list(dict.fromkeys(speaker_names))
    owner_aliases = _owner_alias_candidates(segments, speaker_names)
    context_hints = _owner_context_candidates(segments)
    normalized: list[dict] = []
    for action in actions:
        item = dict(action)
        owner = str(item.get("owner") or "").strip()
        task = str(item.get("task") or "")
        replacement = ""
        if _is_pronoun_owner(owner):
            replacement = _infer_owner_from_pronoun(owner, task, segments)
        if not replacement and (
            _is_generic_owner(owner) or _owner_overrides_context(owner, task, context_hints)
        ):
            query = " ".join(part for part in [owner, task] if part)
            replacement = _infer_owner_from_context(query, context_hints, excluded_owner=owner)
            if not replacement:
                replacement = _infer_owner_from_task(query, owner_aliases)
        if replacement:
            item["owner"] = replacement
        elif _is_pronoun_owner(owner):
            item["owner"] = "待确认"
        item = _enrich_action_collaborators(item, segments)
        item["status"] = _normalize_action_status(item.get("status"))
        normalized.append(item)
    return _dedupe_actions(normalized)


def _enrich_action_collaborators(action: dict, segments: list[dict]) -> dict:
    owner = str(action.get("owner") or "").strip()
    task = str(action.get("task") or "").strip()
    if not task:
        return action
    collaborators = _infer_action_collaborators(owner, task, segments)
    if not collaborators:
        return action
    if any(name in task for name in collaborators):
        return action
    suffix = "；协同：" + "、".join(collaborators[:3])
    if len(task) + len(suffix) > 180:
        return action
    updated = dict(action)
    updated["task"] = task + suffix
    return updated


def _infer_action_collaborators(
    owner: str,
    task: str,
    segments: list[dict],
) -> list[str]:
    task_tokens = set(_context_tokens(task))
    if not task_tokens:
        return []
    collaborators: list[str] = []
    for segment in segments:
        speaker = str(segment.get("display_name") or "").strip()
        if not speaker or speaker == owner or _is_generic_owner(speaker):
            continue
        text = str(segment.get("text") or "")
        if not _has_collaboration_phrase(text, speaker):
            continue
        overlap = task_tokens & set(_context_tokens(text))
        if len(overlap) < 2 and not any(token in text for token in task_tokens):
            continue
        if speaker not in collaborators:
            collaborators.append(speaker)
    return collaborators


def _has_collaboration_phrase(text: str, speaker: str) -> bool:
    if not text or not speaker:
        return False
    escaped = re.escape(speaker)
    patterns = [
        rf"{escaped}(?:这边)?(?:配合|协同|协助|一起|同步|补充)",
        rf"(?:配合|协同|协助|拉上|叫上|和){escaped}",
        r"(我|我们|咱们)(这边)?(?:配合|协同|协助|一起|同步|补充)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _dedupe_actions(actions: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: dict[str, int] = {}
    for action in actions:
        key = _action_dedupe_key(action)
        if not key or key not in seen:
            seen[key] = len(deduped)
            deduped.append(action)
            continue
        existing = deduped[seen[key]]
        if not str(existing.get("due") or "").strip() and str(action.get("due") or "").strip():
            existing["due"] = action.get("due", "")
        if _action_status_rank(action.get("status")) > _action_status_rank(existing.get("status")):
            existing["status"] = _normalize_action_status(action.get("status"))
    return deduped


def _action_dedupe_key(action: dict) -> str:
    owner = str(action.get("owner") or "").strip()
    task = _compact_action_task(str(action.get("task") or ""))
    if not task:
        return ""
    return f"{owner}|{task}"


def _compact_action_task(task: str) -> str:
    text = re.sub(r"\s+", "", str(task or "").lower())
    text = re.sub(
        r"(请|需要|负责|跟进|处理|确认|补充|整理|输出|完成|推进|一下|这个|那个|相关|事项|工作)",
        "",
        text,
    )
    return text[:80]


def _normalize_action_status(value) -> str:
    status = str(value or "").strip().lower()
    mapping = {
        "": "open",
        "open": "open",
        "todo": "open",
        "to_do": "open",
        "pending": "open",
        "待处理": "open",
        "待办": "open",
        "未开始": "open",
        "doing": "doing",
        "in_progress": "doing",
        "progress": "doing",
        "ongoing": "doing",
        "进行中": "doing",
        "处理中": "doing",
        "done": "done",
        "complete": "done",
        "completed": "done",
        "closed": "done",
        "已完成": "done",
        "完成": "done",
        "blocked": "blocked",
        "block": "blocked",
        "stuck": "blocked",
        "受阻": "blocked",
        "阻塞": "blocked",
    }
    return mapping.get(status, "open")


def _action_status_rank(value) -> int:
    return {
        "open": 1,
        "doing": 2,
        "blocked": 3,
        "done": 4,
    }.get(_normalize_action_status(value), 1)


def _owner_alias_candidates(segments: list[dict], speaker_names: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for name in speaker_names:
        if not _is_generic_owner(name):
            aliases[name] = name
    keyword_map = {
        "前端": ("前端", "UI", "界面", "登录", "图标", "样式", "页面"),
        "UI": ("前端", "UI", "界面", "登录", "图标", "样式", "页面"),
        "一键部署": ("一键部署", "部署", "安装包"),
        "PPT": ("PPT", "串场", "主持"),
        "演示": ("演示", "demo", "Demo"),
        "模型": ("模型", "deep", "flash"),
        "数据": ("数据", "图谱", "MySQL", "PostgreSQL", "Oracle"),
    }
    for segment in segments:
        name = str(segment.get("display_name") or "").strip()
        if not name or _is_generic_owner(name):
            continue
        text = str(segment.get("text") or "")
        for alias, keywords in keyword_map.items():
            if alias not in aliases and any(keyword in text for keyword in keywords):
                aliases[alias] = name
    return aliases


def _owner_context_candidates(segments: list[dict]) -> dict[str, dict]:
    people = mentioned_people_candidates(segments, limit=24)
    speaker_names = [
        str(item.get("display_name") or "").strip()
        for item in segments
        if str(item.get("display_name") or "").strip()
    ]
    candidates = {
        name: {
            "score": 2 if name in speaker_names else 1,
            "keywords": set(),
            "mentions": list(snippets),
        }
        for name, snippets in people.items()
        if not _is_generic_owner(name)
    }
    for name in speaker_names:
        if not _is_generic_owner(name):
            candidates.setdefault(name, {"score": 1, "keywords": set(), "mentions": []})
    for index, segment in enumerate(segments):
        text = str(segment.get("text") or "")
        speaker = str(segment.get("display_name") or "").strip()
        if speaker and speaker in candidates:
            other_names = [
                name for name in candidates if name and name != speaker and name in text
            ]
            speaker_contexts = _speaker_context_windows(text, speaker, other_names)
            for speaker_text in speaker_contexts:
                _add_owner_context(candidates[speaker], speaker_text, speaker_boost=2)
        for name in candidates:
            if not name or name == speaker or name not in text:
                continue
            mention_windows = _mention_windows(text, name)
            for window_text in mention_windows:
                boost = 3 if _has_owner_assignment(window_text, name) else 1
                _add_owner_context(candidates[name], window_text, speaker_boost=boost)
    return candidates


def _speaker_context_windows(text: str, speaker: str, other_names: list[str]) -> list[str]:
    if not other_names:
        return [text]
    windows = _mention_windows(text, speaker)
    if windows:
        return windows
    chunks = [
        chunk.strip()
        for chunk in re.split(r"[。！？!?；;\n\r]+", text)
        if chunk.strip()
    ]
    safe_chunks = [
        chunk for chunk in chunks if not any(name and name in chunk for name in other_names)
    ]
    if safe_chunks:
        return safe_chunks[:2]
    return [] if len(text) > 180 else [text]


def _add_owner_context(item: dict, text: str, speaker_boost: int) -> None:
    tokens = _context_tokens(text)
    item["keywords"].update(tokens)
    item["score"] += speaker_boost
    snippet = str(text or "")[:120]
    if snippet and snippet not in item["mentions"]:
        item["mentions"].append(snippet)


def _mention_windows(text: str, name: str, radius: int = 70) -> list[str]:
    windows = []
    for match in re.finditer(re.escape(name), text):
        windows.append(text[max(0, match.start() - radius) : min(len(text), match.end() + radius)])
    return windows


def _has_owner_assignment(text: str, name: str) -> bool:
    if not text or not name:
        return False
    escaped = re.escape(name)
    patterns = [
        rf"{escaped}(?:你|您)?(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)",
        rf"(?:交给|让|找|通知|安排){escaped}(?:来|去)?(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)",
        rf"{escaped}(?:的)?(?:部分|那块|这块|那边|这边|那个部分|这个部分)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _infer_owner_from_context(
    task: str,
    context_hints: dict[str, dict],
    excluded_owner: str = "",
) -> str:
    task_tokens = set(_context_tokens(task))
    if not task_tokens:
        return ""
    best_name = ""
    best_score = 0
    for name, hint in context_hints.items():
        if name == excluded_owner or _is_generic_owner(name):
            continue
        keywords = set(hint.get("keywords") or [])
        overlap = task_tokens & keywords
        if not overlap:
            continue
        score = len(overlap) * 4 + int(hint.get("score") or 0)
        if _has_owner_assignment(" ".join(str(item) for item in hint.get("mentions") or []), name):
            score += 6
        if name in task:
            score += 8
        mention_text = " ".join(str(item) for item in hint.get("mentions") or [])
        if any(token in mention_text for token in task_tokens):
            score += 2
        if score > best_score:
            best_name = name
            best_score = score
    return best_name if best_score >= 6 else ""


def _owner_overrides_context(owner: str, task: str, context_hints: dict[str, dict]) -> bool:
    if _is_generic_owner(owner) or not owner or not task:
        return False
    alternate = _infer_owner_from_context(task, context_hints, excluded_owner=owner)
    if owner not in context_hints:
        return bool(alternate)
    task_tokens = set(_context_tokens(task))
    if not task_tokens:
        return False
    owner_tokens = set(context_hints.get(owner, {}).get("keywords") or [])
    if len(task_tokens & owner_tokens) >= 2:
        return False
    if not alternate:
        return False
    alternate_tokens = set(context_hints.get(alternate, {}).get("keywords") or [])
    return len(task_tokens & alternate_tokens) > len(task_tokens & owner_tokens) + 1


def _infer_owner_from_pronoun(owner: str, task: str, segments: list[dict]) -> str:
    task_tokens = set(_context_tokens(task))
    if not task_tokens:
        return ""
    best_name = ""
    best_score = 0
    for segment in segments:
        speaker = str(segment.get("display_name") or "").strip()
        if not speaker or _is_generic_owner(speaker) or _is_pronoun_owner(speaker):
            continue
        text = str(segment.get("text") or "")
        text_tokens = set(_context_tokens(text))
        overlap = task_tokens & text_tokens
        if not overlap:
            continue
        score = len(overlap) * 4
        if _has_first_person_assignment(text):
            score += 8
        if _looks_like_addressed_response(text):
            score += 3
        if any(token in text for token in task_tokens):
            score += 2
        if score > best_score:
            best_name = speaker
            best_score = score
    return best_name if best_score >= 8 else ""


def _has_first_person_assignment(text: str) -> bool:
    return bool(
        re.search(
            r"(我|我们|咱们)(这边)?(?:来|负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞|检查)",
            str(text or ""),
        )
    )


def _infer_owner_from_task(task: str, owner_aliases: dict[str, str]) -> str:
    for keyword, owner in owner_aliases.items():
        if keyword and keyword in task:
            return owner
    return ""


def _context_tokens(text: str) -> list[str]:
    text = str(text or "")
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_+-]{1,24}", text):
        token = match.group(0)
        if not _is_context_stopword(token):
            tokens.append(token)
    for length in (4, 3, 2):
        for index in range(0, max(0, len(text) - length + 1)):
            token = text[index : index + length]
            if not re.fullmatch(r"[\u4e00-\u9fa5]{%d}" % length, token):
                continue
            if _is_context_stopword(token):
                continue
            tokens.append(token)
    return list(dict.fromkeys(tokens))[:80]


def _is_context_stopword(token: str) -> bool:
    token = str(token or "").strip()
    if len(token) < 2:
        return True
    stopwords = {
        "这个",
        "那个",
        "就是",
        "然后",
        "但是",
        "所以",
        "因为",
        "如果",
        "可以",
        "不是",
        "没有",
        "还是",
        "一下",
        "一个",
        "我们",
        "你们",
        "他们",
        "大家",
        "这边",
        "那边",
        "今天",
        "明天",
        "昨天",
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周六",
        "周日",
        "会议",
        "问题",
        "事情",
        "东西",
        "任务",
        "部分",
        "待办",
        "负责人",
        "相关",
        "确认",
        "处理",
    }
    return token in stopwords


def _is_generic_owner(owner: str) -> bool:
    if not owner:
        return True
    generic_words = {
        "负责人",
        "相关负责人",
        "前端开发",
        "UI讨论者",
        "主持人",
        "全体",
        "团队",
        "待确认",
    }
    return owner in generic_words or owner.endswith("负责人")


def _is_pronoun_owner(owner: str) -> bool:
    value = re.sub(r"\s+", "", str(owner or "").strip())
    return value in {
        "我",
        "我们",
        "咱们",
        "他",
        "她",
        "他们",
        "她们",
        "这边",
        "那边",
        "我这边",
        "我们这边",
        "他这边",
        "她这边",
        "大家",
    }
