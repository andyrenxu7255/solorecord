import hashlib
import json
import re
from pathlib import Path

from .db import get_db
from .llm_adapters import mentioned_people_candidates
from .owner_terms import ORG_OWNER_TERMS
from .utils import row_to_dict

PLACEHOLDER_ASR_FLAGS = {"mock_asr", "empty_asr", "missing_audio"}
NON_SUBSTANTIVE_TRANSCRIPT_FLAGS = {*PLACEHOLDER_ASR_FLAGS, "source_coverage_gap"}
SYSTEM_REVIEW_TASK_PREFIXES = (
    "检查转写结果并补充真实会议纪要",
    "按转写原文复核待办",
)


def meeting_overview_document(meeting_id: str) -> dict:
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
            """
            SELECT audio_segments.*, recording_sources.label AS source_label,
                   recording_sources.device_name AS source_device_name
            FROM audio_segments
            LEFT JOIN recording_sources
              ON recording_sources.meeting_id = audio_segments.meeting_id
             AND recording_sources.source_id = audio_segments.source_id
            WHERE audio_segments.meeting_id = ?
            ORDER BY audio_segments.segment_no
            """,
            (meeting_id,),
        ).fetchall()
        recording_sources = db.execute(
            """
            SELECT * FROM recording_sources
            WHERE meeting_id = ?
            ORDER BY created_at, source_id
            """,
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
        exports = db.execute(
            "SELECT * FROM exports WHERE meeting_id = ? ORDER BY created_at DESC",
            (meeting_id,),
        ).fetchall()
    meeting_dict = row_to_dict(meeting)
    return {
        "meeting": meeting_dict,
        "owner": {
            "id": meeting_dict["owner_id"],
            "display_name": meeting_dict.get("owner_name", ""),
            "email": meeting_dict.get("owner_email", ""),
        },
        "members": [row_to_dict(row) for row in members],
        "recordingSources": [row_to_dict(row) for row in recording_sources],
        "audioSegments": _audio_segment_items(meeting_id, audio_rows),
        "speakers": [row_to_dict(row) for row in speakers],
        "actionItems": [row_to_dict(row) for row in action_items],
        "exports": [_export_item(row) for row in exports],
    }


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
            """
            SELECT audio_segments.*, recording_sources.label AS source_label,
                   recording_sources.device_name AS source_device_name
            FROM audio_segments
            LEFT JOIN recording_sources
              ON recording_sources.meeting_id = audio_segments.meeting_id
             AND recording_sources.source_id = audio_segments.source_id
            WHERE audio_segments.meeting_id = ?
            ORDER BY audio_segments.segment_no
            """,
            (meeting_id,),
        ).fetchall()
        recording_sources = db.execute(
            """
            SELECT * FROM recording_sources
            WHERE meeting_id = ?
            ORDER BY created_at, source_id
            """,
            (meeting_id,),
        ).fetchall()
        transcript_segments = db.execute(
            "SELECT * FROM transcript_segments WHERE meeting_id = ? ORDER BY start_ms, id",
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
        exports = db.execute(
            "SELECT * FROM exports WHERE meeting_id = ? ORDER BY created_at DESC",
            (meeting_id,),
        ).fetchall()
    meeting_dict = row_to_dict(meeting)
    transcript_text = "\n".join(
        f"[{_time(row['start_ms'])}] {row['display_name']}: {row['text']}" for row in transcript_segments
    )
    action_text = "\n".join(f"{row['owner']}: {row['task']} {row['due']}" for row in action_items)
    normalized_transcript_segments = with_derived_quality_flags(transcript_segments)
    audio_segments = _audio_segment_items(meeting_id, audio_rows)
    quality_report = build_quality_report(
        normalized_transcript_segments,
        action_items,
        audio_rows,
        meeting_dict.get("summary", ""),
        meeting_dict.get("role_notes", ""),
    )
    action_items_with_evidence = _action_items_with_evidence(action_items, quality_report)
    document = {
        "meeting": meeting_dict,
        "owner": {
            "id": meeting_dict["owner_id"],
            "display_name": meeting_dict.get("owner_name", ""),
            "email": meeting_dict.get("owner_email", ""),
        },
        "members": [row_to_dict(row) for row in members],
        "recordingSources": [row_to_dict(row) for row in recording_sources],
        "audioSegments": audio_segments,
        "transcriptSegments": normalized_transcript_segments,
        "speakers": [row_to_dict(row) for row in speakers],
        "actionItems": action_items_with_evidence,
        "exports": [_export_item(row) for row in exports],
        "qualityReport": quality_report,
        "knowledgeReadiness": build_knowledge_readiness(quality_report),
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
    return document


def transcript_document(meeting_id: str, include_history: bool = False) -> dict:
    document = meeting_document(meeting_id)
    if not document:
        return {}
    current_segments = document["transcriptSegments"]
    current_text = "\n".join(
        f"[{_time(row['start_ms'])}] {row['display_name']}: {row['text']}" for row in current_segments
    )
    result = {
        "meeting": document["meeting"],
        "owner": document["owner"],
        "members": document["members"],
        "recordingSources": document["recordingSources"],
        "speakers": document["speakers"],
        "qualityReport": document["qualityReport"],
        "knowledgeReadiness": document["knowledgeReadiness"],
        "transcript": {
            "version": document["meeting"]["version"],
            "segments": current_segments,
            "plain_text": current_text,
            "segment_count": len(current_segments),
            "immutable_notice": (
                "Current transcript rows are persisted server-side. Replacements archive prior rows "
                "into transcript_segment_history for audit and knowledge-agent traceability."
            ),
        },
        "audioSegments": document["audioSegments"],
        "actionItems": document["actionItems"],
        "exports": document["exports"],
        "searchText": document["searchText"],
    }
    if include_history:
        with get_db() as db:
            rows = db.execute(
                """
                SELECT * FROM transcript_segment_history
                WHERE meeting_id = ?
                ORDER BY archived_at, start_ms, original_segment_id
                """,
                (meeting_id,),
            ).fetchall()
        result["transcript"]["history"] = [row_to_dict(row) for row in rows]
    return result


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


def _export_item(row) -> dict:
    item = row_to_dict(row)
    path = Path(item.get("storage_path") or "")
    item["file_name"] = path.name
    item["size_bytes"] = path.stat().st_size if path.exists() else 0
    item["download_url"] = f"/api/web/exports/{item['id']}/download"
    return item


def _audio_segment_items(meeting_id: str, rows) -> list[dict]:
    audio_segments = []
    for row in rows:
        item = row_to_dict(row)
        item["download_url"] = (
            f"/api/mobile/meetings/{meeting_id}/segments/{item['segment_no']}/audio"
        )
        audio_segments.append(item)
    return audio_segments


def with_derived_quality_flags(rows) -> list[dict]:
    return [_with_derived_quality_flags_for_row(row_to_dict(row)) for row in rows]


def _with_derived_quality_flags_for_row(row: dict) -> dict:
    item = dict(row)
    flags = _flags(item.get("flags"))
    if (
        "multi_source_merged" in flags
        and "multi_source_conflict" not in flags
        and "multi_source_majority" not in flags
        and _multi_source_count_from_flags(flags) >= 2
    ):
        flags.append("multi_source_majority")
        item["flags"] = json.dumps(flags, ensure_ascii=False)
    return item


def _multi_source_count_from_flags(flags: list[str]) -> int:
    for flag in flags:
        if not str(flag).startswith("multi_source_count:"):
            continue
        try:
            return int(str(flag).split(":", 1)[1])
        except (TypeError, ValueError):
            return 0
    for flag in flags:
        if not str(flag).startswith("multi_source_refs:"):
            continue
        refs = [item for item in str(flag).split(":", 1)[1].split(",") if item]
        return len(refs)
    return 0


def build_quality_report(
    transcript_segments,
    action_items,
    audio_rows,
    summary: str = "",
    role_notes: str = "",
) -> dict:
    segments = _segments_with_stable_ids(with_derived_quality_flags(transcript_segments))
    actions = [row_to_dict(row) for row in action_items]
    audio_segments = [row_to_dict(row) for row in audio_rows]
    flags_by_segment = [_flags(item.get("flags")) for item in segments]
    placeholder_segments = _placeholder_transcript_segments(segments, flags_by_segment)
    system_review_actions = [
        item for item in actions if _is_system_review_action(item)
    ]
    actionable_actions = [
        item for item in actions if not _is_system_review_action(item)
    ]
    substantive_segments = [
        item
        for item, flags in zip(segments, flags_by_segment, strict=False)
        if not _is_non_substantive_transcript_flags(flags)
    ]
    speaker_names = [
        str(item.get("display_name") or item.get("speaker_id") or "").strip()
        for item in substantive_segments
        if str(item.get("display_name") or item.get("speaker_id") or "").strip()
    ]
    unique_speakers = sorted(set(speaker_names))
    speaker_alias_conflicts = _speaker_alias_conflicts(substantive_segments)
    candidate_people = mentioned_people_candidates(substantive_segments, limit=24)
    generic_actions = [
        item
        for item in actionable_actions
        if _is_generic_owner(str(item.get("owner") or ""))
    ]
    duplicate_actions = _duplicate_action_items(actionable_actions)
    owner_distribution = _owner_distribution(actionable_actions)
    unsupported_actions = _unsupported_action_evidence(actionable_actions, substantive_segments)
    unsupported_action_keys = {
        _action_quality_key(item) for item in unsupported_actions
    }
    weak_action_owners = _weak_action_owner_evidence(
        actionable_actions,
        substantive_segments,
        candidate_people,
        unsupported_action_keys,
    )
    action_evidence = _action_evidence_items(
        actions,
        substantive_segments,
        unsupported_actions,
        weak_action_owners,
    )
    contradictory_actions = [
        item for item in action_evidence if item.get("status") == "contradiction"
    ]
    summary_evidence = _summary_evidence_report(summary, role_notes, substantive_segments)
    source_coverage = _source_coverage_report(segments, audio_segments)
    recording_source_ids = sorted(
        {
            str(item.get("source_id") or "primary")
            for item in audio_segments
            if str(item.get("source_id") or "primary")
        }
    )
    evidence_coverage = (
        1 - len(unsupported_actions) / len(actionable_actions)
        if actionable_actions
        else 1
    )
    review_segments = [
        item for item, flags in zip(segments, flags_by_segment, strict=False)
        if "speaker_review" in flags
        and not _is_non_substantive_transcript_flags(flags)
    ]
    weak_speaker_evidence_segments = [
        item for item, flags in zip(segments, flags_by_segment, strict=False)
        if "speaker_evidence_weak" in flags
        and not _is_non_substantive_transcript_flags(flags)
    ]
    speaker_evidence = _speaker_evidence_items(segments, flags_by_segment)
    long_segments = [
        item for item in segments
        if not _is_non_substantive_transcript_flags(_flags(item.get("flags")))
        and (_segment_duration_ms(item) >= 180_000 or len(str(item.get("text") or "")) >= 900)
    ]
    possible_mixed_segments = [
        item for item in segments
        if not _is_non_substantive_transcript_flags(_flags(item.get("flags")))
        and _looks_like_unresolved_mixed_segment(str(item.get("text") or ""))
    ]
    substantive_flags = [
        flags
        for flags in flags_by_segment
        if not _is_non_substantive_transcript_flags(flags)
    ]
    llm_segments = sum(
        1
        for flags in substantive_flags
        if "llm_refined" in flags or "semantic_llm" in flags
    )
    rule_segments = sum(1 for flags in substantive_flags if "semantic_rule" in flags)
    timeline_repaired = sum(1 for flags in substantive_flags if "timeline_repaired" in flags)
    multi_source_merged = sum(1 for flags in substantive_flags if "multi_source_merged" in flags)
    multi_source_majority = sum(
        1 for flags in substantive_flags if "multi_source_majority" in flags
    )
    multi_source_complemented = sum(
        1 for flags in substantive_flags if "multi_source_complemented" in flags
    )
    multi_source_conflicts = sum(
        1 for flags in substantive_flags if "multi_source_conflict" in flags
    )
    multi_source_conflict_items = _multi_source_conflict_items(segments, flags_by_segment)
    scenario_counts: dict[str, int] = {}
    for flags in substantive_flags:
        for flag in flags:
            if str(flag).startswith("scenario:"):
                scenario = str(flag).split(":", 1)[1] or "unknown"
                scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
    expected_speaker_ceiling = max(8, len(candidate_people) + 4)
    too_many_speakers = (
        len(unique_speakers) >= 16
        or (
            len(unique_speakers) >= 10
            and len(unique_speakers) > expected_speaker_ceiling
        )
    )

    issues: list[dict] = []
    if not segments:
        issues.append(
            _quality_issue(
                "high",
                "empty_transcript",
                "暂无转写",
                "会议还没有可检查的转写文本，无法判断分段和负责人质量。",
            )
        )
    if placeholder_segments:
        issues.append(
            _quality_issue(
                "high",
                "placeholder_transcript",
                "存在占位转写",
                (
                    f"{len(placeholder_segments)} 个转写段来自占位、空语音或缺音频兜底，"
                    "需要重新转写或人工复核后再入库。"
                ),
            )
        )
    if len(unique_speakers) <= 1 and len(segments) >= 2:
        issues.append(
            _quality_issue(
                "medium",
                "single_speaker",
                "整场只有一个发言人标签",
                "如果这是多人会议，建议先检查时间线中较长段落并拆分发言人。",
            )
        )
    if too_many_speakers:
        severity = "high" if len(unique_speakers) >= 24 else "medium"
        issues.append(
            _quality_issue(
                severity,
                "too_many_speakers",
                "发言人标签异常偏多",
                (
                    f"当前识别出 {len(unique_speakers)} 个发言人标签，"
                    "明显偏多时通常是同一人被拆成多个 speaker。"
                ),
            )
        )
    if review_segments:
        issues.append(
            _quality_issue(
                "medium",
                "speaker_review",
                "存在需要校对的发言人",
                f"{len(review_segments)} 个段落由模型推断或置信度偏低，建议抽查人物名称。",
            )
        )
    if weak_speaker_evidence_segments:
        issues.append(
            _quality_issue(
                "medium",
                "speaker_evidence_weak",
                "发言人缺少原文证据",
                f"{len(weak_speaker_evidence_segments)} 个发言人名称没有在原始转写或原始说话人标签中找到充分依据。",
            )
        )
    if speaker_alias_conflicts:
        sample = "；".join(
            f"{item['display_name']}：{len(item['speaker_ids'])} 个标签"
            for item in speaker_alias_conflicts[:3]
        )
        issues.append(
            _quality_issue(
                "low",
                "speaker_alias_conflict",
                "同一发言人存在多个标签",
                f"{len(speaker_alias_conflicts)} 个姓名对应多个 speaker_id，建议确认是否为同一人：{sample}",
            )
        )
    if long_segments:
        issues.append(
            _quality_issue(
                "medium",
                "long_segment",
                "存在过长转写段",
                f"{len(long_segments)} 个段落较长，可能包含多人轮次或多个议题。",
            )
        )
    if possible_mixed_segments:
        issues.append(
            _quality_issue(
                "medium",
                "mixed_speaker_markers",
                "段落里出现多个人名/说话标记",
                f"{len(possible_mixed_segments)} 个段落可能还可以继续按人拆分。",
            )
        )
    if multi_source_conflicts:
        issues.append(
            _quality_issue(
                "medium",
                "multi_source_conflict",
                "多源同录存在不一致片段",
                f"{multi_source_conflicts} 个时间段的多录音源内容差异较大，建议回听确认。",
            )
        )
    if source_coverage["weak_count"]:
        issues.append(
            _quality_issue(
                "high",
                "source_segment_coverage_weak",
                "原始音频分段覆盖不足",
                f"{source_coverage['weak_count']} 个音频分段在当前转写中覆盖不足，可能存在大模型后处理漏段。",
            )
        )
    if generic_actions:
        issues.append(
            _quality_issue(
                "high",
                "generic_owner",
                "待办负责人仍需确认",
                f"{len(generic_actions)} 个待办的负责人仍是泛化角色或待确认。",
            )
        )
    if system_review_actions:
        sample = "；".join(
            str(item.get("task") or "")[:80] for item in system_review_actions[:3]
        )
        issues.append(
            _quality_issue(
                "medium",
                "system_review_action",
                "存在系统复核提醒",
                (
                    f"{len(system_review_actions)} 条记录只是系统复核入口，不是可自动督办的会议待办"
                    f"{'：' + sample if sample else '。'}"
                ),
            )
        )
    if duplicate_actions:
        sample = "；".join(
            f"{item['owner']}：{item['task']}" for item in duplicate_actions[:3]
        )
        issues.append(
            _quality_issue(
                "medium",
                "duplicate_action",
                "存在疑似重复待办",
                f"{len(duplicate_actions)} 个待办和其他项高度相似，建议合并后再督办：{sample}",
            )
        )
    if unsupported_actions:
        ratio = len(unsupported_actions) / max(1, len(actions))
        severity = "high" if len(unsupported_actions) >= 2 and ratio >= 0.5 else "medium"
        sample = "；".join(
            f"{item['owner']}：{item['task']}" for item in unsupported_actions[:3]
        )
        issues.append(
            _quality_issue(
                severity,
                "unsupported_action_evidence",
                "待办缺少转写证据",
                f"{len(unsupported_actions)} 个待办与转写文本关联较弱，建议复核：{sample}",
            )
        )
    if contradictory_actions:
        sample = "；".join(
            f"{item['owner']}：{item['task']}" for item in contradictory_actions[:3]
        )
        issues.append(
            _quality_issue(
                "high",
                "action_evidence_contradiction",
                "待办与转写证据相反",
                f"{len(contradictory_actions)} 个待办与匹配转写片段的执行状态相反，建议按原文改写或删除：{sample}",
            )
        )
    if weak_action_owners:
        sample = "；".join(
            f"{item['owner']}：{item['task']}" for item in weak_action_owners[:3]
        )
        issues.append(
            _quality_issue(
                "medium",
                "weak_action_owner_evidence",
                "待办负责人缺少上下文证据",
                f"{len(weak_action_owners)} 个待办的负责人能在文本中出现，但缺少明确任务归属证据，建议复核：{sample}",
            )
        )
    concentration = _owner_concentration(owner_distribution, actions)
    if concentration and len(candidate_people) >= 3:
        owner, count, ratio = concentration
        issues.append(
            _quality_issue(
                "medium",
                "owner_over_concentrated",
                "待办负责人过度集中",
                f"{count} 个待办中约 {round(ratio * 100)}% 都归给“{owner}”，但文本中出现多个候选人员，建议复核任务归属。",
            )
        )
    if candidate_people and len(candidate_people) > len(unique_speakers) + 2:
        issues.append(
            _quality_issue(
                "low",
                "candidate_people_not_speakers",
                "文本中还有未统一的人名线索",
                "候选人名多于当前发言人标签，建议在人物校对中统一音译名或补充分段。",
            )
        )
    if summary_evidence["unsupported_count"]:
        severity = "high" if summary_evidence["coverage"] < 0.45 else "medium"
        issues.append(
            _quality_issue(
                severity,
                "summary_evidence_weak",
                "纪要缺少转写证据",
                f"{summary_evidence['unsupported_count']} 个纪要要点与转写文本关联较弱，建议复核纪要是否由模型补写。",
            )
        )
    if summary_evidence.get("contradiction_count"):
        issues.append(
            _quality_issue(
                "high",
                "summary_evidence_contradiction",
                "纪要与转写证据相反",
                f"{summary_evidence['contradiction_count']} 个纪要要点与可匹配转写片段存在否定或完成状态冲突，建议改写或删除。",
            )
        )
    if summary_evidence.get("conflict_count"):
        severity = "medium" if summary_evidence.get("unqualified_conflict_count") else "low"
        issues.append(
            _quality_issue(
                severity,
                "summary_multisource_conflict",
                "纪要引用了多源冲突证据",
                (
                    f"{summary_evidence['conflict_count']} 个纪要要点只由冲突录音源片段支撑，"
                    "请确认纪要是否已经保留复核语气。"
                ),
            )
        )
    score = _quality_score(issues, segments, actions)
    return {
        "score": score,
        "status": _quality_status(score, issues),
        "metrics": {
            "segment_count": len(segments),
            "audio_segment_count": len(audio_segments),
            "recording_source_count": len(recording_source_ids),
            "speaker_count": len(unique_speakers),
            "candidate_people_count": len(candidate_people),
            "action_count": len(actions),
            "actionable_action_count": len(actionable_actions),
            "system_review_action_count": len(system_review_actions),
            "generic_owner_count": len(generic_actions),
            "duplicate_action_count": len(duplicate_actions),
            "unsupported_action_count": len(unsupported_actions),
            "weak_action_owner_count": len(weak_action_owners),
            "action_contradiction_count": len(contradictory_actions),
            "action_evidence_coverage": round(evidence_coverage, 4),
            "summary_evidence_coverage": summary_evidence["coverage"],
            "summary_unsupported_count": summary_evidence["unsupported_count"],
            "summary_contradiction_count": summary_evidence.get("contradiction_count", 0),
            "summary_majority_count": summary_evidence.get("majority_count", 0),
            "summary_conflict_count": summary_evidence.get("conflict_count", 0),
            "summary_unqualified_conflict_count": summary_evidence.get(
                "unqualified_conflict_count",
                0,
            ),
            "source_segment_coverage": source_coverage["coverage"],
            "source_segment_weak_count": source_coverage["weak_count"],
            "placeholder_transcript_count": len(placeholder_segments),
            "owner_distribution": owner_distribution,
            "top_owner_ratio": concentration[2] if concentration else 0,
            "speaker_review_count": len(review_segments),
            "speaker_evidence_weak_count": len(weak_speaker_evidence_segments),
            "speaker_alias_conflict_count": len(speaker_alias_conflicts),
            "speaker_over_split_count": (
                max(0, len(unique_speakers) - expected_speaker_ceiling)
                if too_many_speakers
                else 0
            ),
            "long_segment_count": len(long_segments),
            "mixed_marker_segment_count": len(possible_mixed_segments),
            "llm_segment_count": llm_segments,
            "rule_segment_count": rule_segments,
            "timeline_repaired_count": timeline_repaired,
            "multi_source_merged_count": multi_source_merged,
            "multi_source_majority_count": multi_source_majority,
            "multi_source_complemented_count": multi_source_complemented,
            "multi_source_conflict_count": multi_source_conflicts,
            "scenario_counts": scenario_counts,
        },
        "candidatePeople": list(candidate_people.keys()),
        "speakerEvidence": speaker_evidence[:12],
        "speakerAliasConflicts": speaker_alias_conflicts[:12],
        "actionEvidence": action_evidence,
        "contradictoryActions": contradictory_actions[:8],
        "duplicateActions": duplicate_actions[:8],
        "unsupportedActions": unsupported_actions[:8],
        "weakActionOwners": weak_action_owners[:8],
        "summaryEvidence": summary_evidence,
        "sourceCoverage": source_coverage,
        "multiSourceConflicts": multi_source_conflict_items,
        "issues": issues,
        "recommendations": _quality_recommendations(issues),
    }


def _quality_score(issues: list[dict], segments: list[dict], actions: list[dict]) -> int:
    if not segments:
        return 0
    score = 92
    for issue in issues:
        severity = issue.get("severity")
        if severity == "high":
            score -= 22
        elif severity == "medium":
            score -= 12
        else:
            score -= 6
    if actions and not any(_is_generic_owner(str(item.get("owner") or "")) for item in actions):
        score += 4
    return max(0, min(100, score))


def _quality_status(score: int, issues: list[dict]) -> str:
    if any(item.get("severity") == "high" for item in issues):
        return "needs_review"
    if score < 70:
        return "needs_review"
    if score < 86:
        return "review_recommended"
    return "good"


def _quality_issue(severity: str, issue_type: str, title: str, detail: str) -> dict:
    return {
        "severity": severity,
        "type": issue_type,
        "title": title,
        "detail": detail,
    }


def _quality_recommendations(issues: list[dict]) -> list[str]:
    mapping = {
        "empty_transcript": "先完成转写，再生成纪要和待办。",
        "placeholder_transcript": "占位转写不能作为会议证据，先重新转写或回听校正。",
        "single_speaker": "优先检查最长的转写段，使用“按人名拆分”和“设为新发言人”。",
        "too_many_speakers": "优先播放人物校对区的声音样本，把同一人的多个 speaker_id 统一为真实姓名。",
        "speaker_review": "在人人物校对区把模型推断的人名统一成真实姓名。",
        "speaker_evidence_weak": "优先播放对应音频，确认模型没有把角色、议题或误听词当成人名。",
        "speaker_alias_conflict": "同名多标签通常来自模型保留 ASR 原始 speaker_id，确认后用人物校对统一。",
        "long_segment": "把超过 3 分钟或内容很长的段落继续按议题拆分。",
        "mixed_speaker_markers": "对出现“某某说/某某：”的段落执行按人名拆分。",
        "system_review_action": "系统复核提醒只用于提醒人工补齐记录，不要复制给 IM 或同步为督办。",
        "generic_owner": "复制待办前先把“待确认/负责人”改成真实人名或具体团队。",
        "duplicate_action": "复制待办前先合并重复项，避免同一件事多次发给负责人。",
        "unsupported_action_evidence": "对缺少证据的待办回看转写或录音，确认不是模型补写。",
        "action_evidence_contradiction": "待办与原文表达相反，先按转写原文改写或删除后再督办。",
        "weak_action_owner_evidence": "优先核对负责人和任务是否在同一议题上下文中被明确关联。",
        "summary_evidence_weak": "逐条核对纪要要点，删除或改写转写原文无法支撑的内容。",
        "summary_evidence_contradiction": "纪要要点与原文表达相反，先按转写原文改写后再入库。",
        "summary_multisource_conflict": "多源冲突支撑的纪要要保留待确认语气，必要时回听对应来源。",
        "source_segment_coverage_weak": "优先检查对应音频分段，必要时重新转写或回退到 ASR 原始结果。",
        "multi_source_conflict": "打开多源冲突清单，逐条定位转写并回听对应录音源。",
        "owner_over_concentrated": "如果待办高度集中到主持人或单一人员，请按候选人名逐条复核负责人。",
        "candidate_people_not_speakers": "候选人名可以作为检查清单，逐个确认是否需要成为发言人或负责人。",
    }
    recommendations = []
    for issue in issues:
        item = mapping.get(issue.get("type"))
        if item and item not in recommendations:
            recommendations.append(item)
    return recommendations


def _speaker_alias_conflicts(segments: list[dict]) -> list[dict]:
    by_name: dict[str, dict[str, dict]] = {}
    for segment in segments:
        display_name = str(segment.get("display_name") or "").strip()
        speaker_id = str(segment.get("speaker_id") or "").strip()
        if not display_name or not speaker_id:
            continue
        if _is_generic_speaker_label(display_name):
            continue
        item = by_name.setdefault(display_name, {})
        stats = item.setdefault(
            speaker_id,
            {
                "speaker_id": speaker_id,
                "count": 0,
                "start_ms": int(segment.get("start_ms") or 0),
                "end_ms": int(segment.get("end_ms") or 0),
                "sample": "",
            },
        )
        stats["count"] += 1
        stats["start_ms"] = min(stats["start_ms"], int(segment.get("start_ms") or 0))
        stats["end_ms"] = max(stats["end_ms"], int(segment.get("end_ms") or 0))
        if not stats["sample"]:
            stats["sample"] = _compact_snippet(str(segment.get("text") or ""), 90)

    conflicts: list[dict] = []
    for display_name, speaker_items in by_name.items():
        if len(speaker_items) < 2:
            continue
        aliases = sorted(
            speaker_items.values(),
            key=lambda item: (item["start_ms"], item["speaker_id"]),
        )
        conflicts.append(
            {
                "display_name": display_name,
                "speaker_ids": [item["speaker_id"] for item in aliases],
                "segment_count": sum(int(item["count"]) for item in aliases),
                "aliases": aliases,
            }
        )
    return sorted(conflicts, key=lambda item: (-item["segment_count"], item["display_name"]))


def _is_generic_speaker_label(name: str) -> bool:
    value = str(name or "").strip()
    if not value:
        return True
    return (
        value.startswith("发言人")
        or value.lower().startswith("speaker")
        or value in {"待确认", "未知", "不确定", "系统复核", "unknown"}
    )


def _speaker_evidence_items(segments: list[dict], flags_by_segment: list[list[str]]) -> list[dict]:
    items: list[dict] = []
    for index, (segment, flags) in enumerate(zip(segments, flags_by_segment, strict=False)):
        if _is_non_substantive_transcript_flags(flags):
            continue
        if "speaker_review" not in flags and "speaker_evidence_weak" not in flags:
            continue
        speaker = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
        scenario = _flag_value(flags, "scenario:") or "unknown"
        reason = _flag_value(flags, "reason:")
        item = {
            "segment_id": segment.get("id", ""),
            "source_id": segment.get("source_id") or "",
            "source_segment_no": segment.get("source_segment_no"),
            "speaker": speaker or "待确认",
            "speaker_id": segment.get("speaker_id", ""),
            "start_ms": int(segment.get("start_ms") or 0),
            "end_ms": int(segment.get("end_ms") or 0),
            "scenario": scenario,
            "scenario_label": _speaker_scenario_label(scenario),
            "reason": reason or _speaker_evidence_reason(flags, scenario),
            "risk": _speaker_evidence_risk(flags),
            "flags": flags,
            "text": _compact_snippet(str(segment.get("text") or ""), 160),
            "context": _speaker_context_snippets(segments, index),
        }
        items.append(item)
    return items


def _multi_source_conflict_items(
    segments: list[dict],
    flags_by_segment: list[list[str]],
) -> list[dict]:
    conflict_segments = [
        (index, segment, flags)
        for index, (segment, flags) in enumerate(zip(segments, flags_by_segment, strict=False))
        if "multi_source_conflict" in flags
    ]
    items: list[dict] = []
    for index, segment, flags in conflict_segments:
        item = _quality_segment_reference(segment, flags)
        item["nearby"] = _nearby_conflict_references(segment, index, conflict_segments)
        items.append(item)
    return sorted(
        items,
        key=lambda item: (
            int(item.get("start_ms") or 0),
            str(item.get("source_id") or ""),
            int(item.get("source_segment_no") or 0),
            str(item.get("segment_id") or ""),
        ),
    )[:12]


def _nearby_conflict_references(
    target: dict,
    target_index: int,
    conflict_segments: list[tuple[int, dict, list[str]]],
    limit: int = 3,
) -> list[dict]:
    target_source = str(target.get("source_id") or "")
    target_start = int(target.get("start_ms") or 0)
    target_end = int(target.get("end_ms") or target_start)
    related: list[tuple[int, dict, list[str]]] = []
    for index, segment, flags in conflict_segments:
        if index == target_index:
            continue
        if target_source and str(segment.get("source_id") or "") == target_source:
            continue
        start_ms = int(segment.get("start_ms") or 0)
        end_ms = int(segment.get("end_ms") or start_ms)
        overlap = min(target_end, end_ms) - max(target_start, start_ms)
        distance = min(abs(start_ms - target_start), abs(end_ms - target_end))
        if overlap < 0 and distance > 90_000:
            continue
        related.append((max(0, distance - max(0, overlap)), segment, flags))
    related.sort(
        key=lambda item: (
            item[0],
            int(item[1].get("start_ms") or 0),
            str(item[1].get("source_id") or ""),
        )
    )
    return [
        _quality_segment_reference(segment, flags, text_limit=110)
        for _, segment, flags in related[:limit]
    ]


def _quality_segment_reference(
    segment: dict,
    flags: list[str] | None = None,
    text_limit: int = 180,
) -> dict:
    return {
        "segment_id": segment.get("id", ""),
        "source_id": segment.get("source_id") or "",
        "source_segment_no": segment.get("source_segment_no"),
        "speaker": str(segment.get("display_name") or segment.get("speaker_id") or ""),
        "speaker_id": segment.get("speaker_id", ""),
        "start_ms": int(segment.get("start_ms") or 0),
        "end_ms": int(segment.get("end_ms") or 0),
        "text": _compact_snippet(str(segment.get("text") or ""), text_limit),
        "flags": flags if flags is not None else _flags(segment.get("flags")),
    }


def _flag_value(flags: list[str], prefix: str) -> str:
    for flag in flags:
        value = str(flag)
        if value.startswith(prefix):
            return value[len(prefix) :].strip()
    return ""


def _speaker_scenario_label(scenario: str) -> str:
    return {
        "explicit_name": "明确人名",
        "context_bridge": "上下文衔接",
        "dialogue_logic": "对话逻辑",
        "task_ownership": "任务归属",
        "native_speaker": "ASR说话人",
        "unknown": "推断未知",
    }.get(str(scenario or ""), "推断未知")


def _speaker_evidence_reason(flags: list[str], scenario: str) -> str:
    if "speaker_evidence_weak" in flags:
        return "该发言人名称缺少原始转写或 ASR 说话人标签支撑，建议回听确认。"
    if "contextual_speaker_inference" in flags:
        return "系统根据前文点名和后续第一人称回应做了保守归属。"
    if scenario == "task_ownership":
        return "系统根据任务归属、被点名事项或职责上下文推断发言人。"
    if scenario == "context_bridge":
        return "系统根据相邻段落承接关系推断发言人。"
    if scenario == "explicit_name":
        return "系统根据文本中的姓名前缀或明确人名推断发言人。"
    return "该发言人由模型或规则推断，建议人工抽查。"


def _speaker_evidence_risk(flags: list[str]) -> str:
    if "speaker_evidence_weak" in flags:
        return "weak_evidence"
    if "contextual_speaker_inference" in flags:
        return "context_inferred"
    if "speaker_review" in flags:
        return "review"
    return "ok"


def _speaker_context_snippets(
    segments: list[dict],
    index: int,
    radius: int = 1,
) -> list[dict]:
    start = max(0, index - radius)
    end = min(len(segments), index + radius + 1)
    snippets = []
    for position in range(start, end):
        segment = segments[position]
        snippets.append(
            {
                "segment_id": segment.get("id", ""),
                "source_id": segment.get("source_id") or "",
                "source_segment_no": segment.get("source_segment_no"),
                "speaker": str(segment.get("display_name") or segment.get("speaker_id") or ""),
                "start_ms": int(segment.get("start_ms") or 0),
                "end_ms": int(segment.get("end_ms") or 0),
                "text": _compact_snippet(str(segment.get("text") or ""), 120),
                "current": position == index,
            }
        )
    return snippets


def build_knowledge_readiness(quality_report: dict) -> dict:
    metrics = quality_report.get("metrics") or {}
    issues = quality_report.get("issues") or []
    issue_types = {str(item.get("type") or "") for item in issues}
    blocking_types = {
        "empty_transcript",
        "placeholder_transcript",
        "generic_owner",
        "unsupported_action_evidence",
        "action_evidence_contradiction",
        "summary_evidence_weak",
        "summary_evidence_contradiction",
        "source_segment_coverage_weak",
    }
    review_types = {
        "speaker_review",
        "speaker_evidence_weak",
        "speaker_alias_conflict",
        "weak_action_owner_evidence",
        "multi_source_conflict",
        "summary_multisource_conflict",
        "owner_over_concentrated",
        "candidate_people_not_speakers",
        "long_segment",
        "mixed_speaker_markers",
        "single_speaker",
        "system_review_action",
    }
    blockers = sorted(issue_types & blocking_types)
    review_warnings = sorted(issue_types & review_types)
    can_index = not blockers
    return {
        "status": "ready" if can_index and not review_warnings else "review_first" if can_index else "hold",
        "canIndex": can_index,
        "blockers": blockers,
        "reviewWarnings": review_warnings,
        "metrics": {
            "score": quality_report.get("score", 0),
            "speakerReviewCount": int(metrics.get("speaker_review_count") or 0),
            "speakerEvidenceWeakCount": int(metrics.get("speaker_evidence_weak_count") or 0),
            "speakerAliasConflictCount": int(metrics.get("speaker_alias_conflict_count") or 0),
            "placeholderTranscriptCount": int(metrics.get("placeholder_transcript_count") or 0),
            "unsupportedActionCount": int(metrics.get("unsupported_action_count") or 0),
            "weakActionOwnerCount": int(metrics.get("weak_action_owner_count") or 0),
            "systemReviewActionCount": int(metrics.get("system_review_action_count") or 0),
            "actionableActionCount": int(metrics.get("actionable_action_count") or 0),
            "actionContradictionCount": int(metrics.get("action_contradiction_count") or 0),
            "summaryUnsupportedCount": int(metrics.get("summary_unsupported_count") or 0),
            "summaryContradictionCount": int(
                metrics.get("summary_contradiction_count") or 0
            ),
            "sourceSegmentWeakCount": int(metrics.get("source_segment_weak_count") or 0),
            "multiSourceMergedCount": int(metrics.get("multi_source_merged_count") or 0),
            "multiSourceMajorityCount": int(metrics.get("multi_source_majority_count") or 0),
            "multiSourceComplementedCount": int(metrics.get("multi_source_complemented_count") or 0),
            "multiSourceConflictCount": int(metrics.get("multi_source_conflict_count") or 0),
            "summaryMajorityCount": int(metrics.get("summary_majority_count") or 0),
            "summaryConflictCount": int(metrics.get("summary_conflict_count") or 0),
            "summaryUnqualifiedConflictCount": int(
                metrics.get("summary_unqualified_conflict_count") or 0
            ),
            "actionEvidenceCoverage": float(metrics.get("action_evidence_coverage") or 0),
            "summaryEvidenceCoverage": float(metrics.get("summary_evidence_coverage") or 0),
            "sourceSegmentCoverage": float(metrics.get("source_segment_coverage") or 0),
        },
        "evidenceApi": {
            "transcript": "/api/external/meetings/{meetingId}/transcript?include_history=true",
            "meeting": "/api/external/meetings/{meetingId}",
        },
        "reviewEvidence": _knowledge_review_evidence(quality_report),
        "notes": _knowledge_readiness_notes(blockers, review_warnings),
    }


def _knowledge_readiness_notes(blockers: list[str], review_warnings: list[str]) -> list[str]:
    notes = []
    if blockers:
        notes.append("存在阻塞风险，建议暂缓自动入库，先由人工复核。")
    if "placeholder_transcript" in blockers:
        notes.append("存在占位转写，知识平台不得把占位文本当作会议原始证据。")
    if "unsupported_action_evidence" in blockers:
        notes.append("待办缺少转写证据，知识平台不要直接生成督办记录。")
    if "action_evidence_contradiction" in blockers:
        notes.append("待办与转写原文存在反向证据，知识平台不得自动督办，应按原文改写或删除该待办。")
    if "summary_evidence_weak" in blockers:
        notes.append("纪要存在缺证据要点，知识平台应以转写为准重建摘要。")
    if "summary_evidence_contradiction" in blockers:
        notes.append("纪要与转写原文存在反向证据，知识平台必须以转写原文为准，暂缓自动入库。")
    if "summary_multisource_conflict" in review_warnings:
        notes.append("纪要包含多源冲突证据，知识平台应保留待确认语气或等待人工回听。")
    if "source_segment_coverage_weak" in blockers:
        notes.append("当前转写没有覆盖全部音频分段，知识平台不要把该会议视为完整证据。")
    if "speaker_evidence_weak" in review_warnings or "speaker_review" in review_warnings:
        notes.append("发言人包含模型推断，知识平台应保留置信风险或等待人工校正。")
    if "speaker_alias_conflict" in review_warnings:
        notes.append("同一显示名对应多个说话人标签，知识平台应按显示名合并展示并保留原始 speaker_id。")
    if "weak_action_owner_evidence" in review_warnings:
        notes.append("待办负责人证据弱，知识平台应保留待确认状态。")
    if "system_review_action" in review_warnings:
        notes.append("系统复核提醒不是会议待办，外部督办 Agent 应忽略自动提醒。")
    return notes


def _knowledge_review_evidence(quality_report: dict) -> dict:
    source_coverage = quality_report.get("sourceCoverage") or {}
    summary_evidence = quality_report.get("summaryEvidence") or {}
    summary_claims = []
    for item in summary_evidence.get("supportedClaims") or []:
        if item.get("status") in {"majority", "conflict", "contradiction"}:
            summary_claims.append(item)
    for item in summary_evidence.get("contradictedClaims") or []:
        if item not in summary_claims:
            summary_claims.append(item)
    for item in summary_evidence.get("unsupportedClaims") or []:
        copy = dict(item)
        copy.setdefault("status", "unsupported")
        summary_claims.append(copy)
    action_evidence = [
        item
        for item in quality_report.get("actionEvidence") or []
        if item.get("status") in {
            "system_review",
            "majority",
            "conflict",
            "contradiction",
            "weak_owner",
            "unsupported",
        }
    ]
    return {
        "multiSourceConflicts": (quality_report.get("multiSourceConflicts") or [])[:6],
        "sourceCoverageWeakSegments": (source_coverage.get("weakSegments") or [])[:6],
        "speakerEvidence": (quality_report.get("speakerEvidence") or [])[:6],
        "speakerAliasConflicts": (quality_report.get("speakerAliasConflicts") or [])[:6],
        "summaryClaims": summary_claims[:6],
        "actionEvidence": action_evidence[:8],
    }


def _flags(value) -> list[str]:
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
    return [str(value)] if value else []


def _placeholder_transcript_segments(
    segments: list[dict],
    flags_by_segment: list[list[str]] | None = None,
) -> list[dict]:
    if flags_by_segment is None:
        flags_by_segment = [_flags(item.get("flags")) for item in segments]
    return [
        item
        for item, flags in zip(segments, flags_by_segment, strict=False)
        if NON_SUBSTANTIVE_TRANSCRIPT_FLAGS & set(flags)
    ]


def _is_non_substantive_transcript_flags(flags: list[str]) -> bool:
    return bool(NON_SUBSTANTIVE_TRANSCRIPT_FLAGS & set(flags))


def _is_system_review_action(action: dict) -> bool:
    task = str(action.get("task") or "").strip()
    return any(task.startswith(prefix) for prefix in SYSTEM_REVIEW_TASK_PREFIXES)


def _system_review_action_reason(task: str) -> str:
    if task.startswith("检查转写结果并补充真实会议纪要"):
        return "这是占位转写、空语音或缺音频触发的系统复核提醒，不是会议中产生的可督办待办。"
    return "这是模型待办被证据检查拦截后保留的人工复核入口，不应自动同步为督办事项。"


def _segment_duration_ms(item: dict) -> int:
    return max(0, int(item.get("end_ms") or 0) - int(item.get("start_ms") or 0))


def _speaker_marker_count(text: str) -> int:
    pattern = re.compile(
        r"(^|[\n\r。！？!?；;])\s*"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,12})"
        r"\s*(?:[:：]|说[，,、]?)"
    )
    addressed = re.compile(
        r"(?:^|[\s，,。！？!?；;、])"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
        r"(?:你|您)(?:先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调|那|这)"
    )
    ownership = re.compile(
        r"(?:^|[\s，,。！？!?；;、])"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
        r"(?:(?:你|您)(?:那个部分|这个部分|那块|这块|那边|这边|部分)|(?:的)?(?:部分|那块|这块|那边|这边|那个部分|这个部分))"
    )
    return max(
        len(pattern.findall(text)),
        len(addressed.findall(text)) + len(ownership.findall(text)),
    )


def _looks_like_unresolved_mixed_segment(text: str) -> bool:
    value = str(text or "")
    if _speaker_marker_count(value) >= 2:
        return True
    return _has_inline_addressed_response(value)


def _has_inline_addressed_response(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    addressed = re.compile(
        r"(?:^|[\s，,。！？!?；;、])"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
        r"(?:你|您)(?:先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调|那|这)"
    )
    response = re.compile(
        r"(?:好的?|可以|行|没问题)?[\s，,、。！？!?；;]*"
        r"(?:我这边|我们这边|我来|我负责|我们负责|我准备|我已经|我们已经|"
        r"我先|我们先|我会|我们会|这块我|这边我|这部分我|这部分我们)"
    )
    match = addressed.search(value)
    if not match:
        return False
    return bool(response.search(value[match.end() :]))


def _is_generic_owner(owner: str) -> bool:
    owner = str(owner or "").strip()
    if not owner:
        return True
    if owner in ORG_OWNER_TERMS:
        return False
    if _looks_like_due_time_phrase(owner):
        return True
    generic_words = {
        "负责人",
        "相关负责人",
        "前端开发",
        "UI讨论者",
        "主持人",
        "全体",
        "团队",
        "系统",
        "待确认",
    }
    return owner in generic_words or _is_pronoun_owner(owner) or owner.endswith("负责人")


def _looks_like_due_time_phrase(value: str) -> bool:
    text = re.sub(r"\s+", "", str(value or "").strip())
    if not text:
        return False
    if text in {
        "今天",
        "明天",
        "后天",
        "昨天",
        "今晚",
        "明晚",
        "上午",
        "下午",
        "晚上",
        "早上",
        "中午",
        "下班前",
        "会前",
        "会后",
        "会中",
        "本周",
        "下周",
        "月底",
        "月初",
        "年前",
        "年后",
    }:
        return True
    return bool(
        re.fullmatch(
            r"(?:(?:今天|明天|后天|昨天)?(?:上午|下午|晚上|早上|中午)|"
            r"(?:本周|下周)?周[一二三四五六日天](?:前|后|之前|以前|之后|左右)?|"
            r"(?:本周|下周|月底|月初|年前|年后)(?:前|后|之前|以前|之后|左右)?|"
            r"\d{1,2}月\d{1,2}[日号]?(?:前|后|之前|以前|之后|左右)?|"
            r"\d{1,2}[日号](?:前|后|之前|以前|之后|左右)?)",
            text,
        )
    )


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


def _owner_distribution(actions: list[dict]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for item in actions:
        owner = str(item.get("owner") or "").strip() or "待确认"
        distribution[owner] = distribution.get(owner, 0) + 1
    return distribution


def _duplicate_action_items(actions: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    duplicates: list[dict] = []
    for action in actions:
        task = str(action.get("task") or "").strip()
        if not task:
            continue
        owner = str(action.get("owner") or "").strip() or "待确认"
        key = f"{owner}|{_compact_action_task(task)}"
        if key in seen:
            duplicates.append(
                {
                    "id": action.get("id", ""),
                    "owner": owner,
                    "task": task[:160],
                    "duplicate_of": seen[key].get("id", ""),
                }
            )
            continue
        seen[key] = action
    return duplicates


def _compact_action_task(task: str) -> str:
    text = re.sub(r"\s+", "", str(task or "").lower())
    text = re.sub(
        r"(请|需要|负责|跟进|处理|确认|补充|整理|输出|完成|推进|一下|这个|那个|相关|事项|工作)",
        "",
        text,
    )
    return text[:80]


def _owner_concentration(
    distribution: dict[str, int],
    actions: list[dict],
) -> tuple[str, int, float] | None:
    concrete = {
        owner: count
        for owner, count in distribution.items()
        if not _is_generic_owner(owner)
    }
    if len(actions) < 4 or not concrete:
        return None
    owner, count = max(concrete.items(), key=lambda item: item[1])
    ratio = count / max(1, len(actions))
    if count >= 4 and ratio >= 0.7:
        return owner, count, ratio
    return None


def _unsupported_action_evidence(actions: list[dict], segments: list[dict]) -> list[dict]:
    corpus = "\n".join(
        f"{item.get('display_name') or item.get('speaker_id') or ''} "
        f"{item.get('text') or ''}"
        for item in segments
    )
    corpus_flat = _compact_evidence_text(corpus)
    corpus_tokens = set(_evidence_tokens(corpus))
    unsupported: list[dict] = []
    for item in actions:
        task = str(item.get("task") or "").strip()
        if not task:
            continue
        owner = str(item.get("owner") or "").strip() or "待确认"
        if _action_has_transcript_evidence(task, owner, corpus_flat, corpus_tokens):
            continue
        unsupported.append(
            {
                "id": item.get("id", ""),
                "owner": owner,
                "task": task[:120],
                "evidence": _action_reference_evidence(task, owner, segments),
            }
        )
    return unsupported


def _weak_action_owner_evidence(
    actions: list[dict],
    segments: list[dict],
    candidate_people: dict[str, list[str]],
    unsupported_action_keys: set[str] | None = None,
) -> list[dict]:
    if not actions or not segments:
        return []
    unsupported_action_keys = unsupported_action_keys or set()
    weak: list[dict] = []
    speaker_names = {
        str(item.get("display_name") or item.get("speaker_id") or "").strip()
        for item in segments
        if str(item.get("display_name") or item.get("speaker_id") or "").strip()
    }
    known_people = set(candidate_people) | speaker_names | _org_owners_in_segments(segments)
    for item in actions:
        if _action_quality_key(item) in unsupported_action_keys:
            continue
        owner = str(item.get("owner") or "").strip()
        task = str(item.get("task") or "").strip()
        if not owner or _is_generic_owner(owner) or not task:
            continue
        if owner not in known_people:
            weak.append(_weak_owner_item(item, owner, task, "owner_not_in_transcript", segments))
            continue
        if _action_owner_has_assignment_evidence(owner, task, segments):
            continue
        weak.append(_weak_owner_item(item, owner, task, "owner_task_link_weak", segments))
    return weak


def _weak_owner_item(item: dict, owner: str, task: str, reason: str, segments: list[dict]) -> dict:
    suggestion = _suggest_action_owner(task, owner, segments)
    return {
        "id": item.get("id", ""),
        "owner": owner,
        "task": task[:120],
        "reason": reason,
        "evidence": _action_reference_evidence(task, owner, segments),
        "suggested_owner": suggestion.get("owner", ""),
        "suggested_owner_reason": suggestion.get("reason", ""),
        "suggested_owner_evidence": suggestion.get("evidence", []),
    }


def _action_items_with_evidence(action_items, quality_report: dict) -> list[dict]:
    evidence_by_key = {
        _action_quality_key(item): item
        for item in quality_report.get("actionEvidence") or []
    }
    items: list[dict] = []
    for row in action_items:
        item = row_to_dict(row)
        evidence = evidence_by_key.get(_action_quality_key(item), {})
        status = str(evidence.get("status") or "unknown")
        item["evidenceStatus"] = status
        item["evidenceReason"] = str(evidence.get("reason") or "")
        item["evidence"] = evidence.get("evidence") or []
        item["suggestedOwner"] = str(evidence.get("suggested_owner") or "")
        item["suggestedOwnerReason"] = str(evidence.get("suggested_owner_reason") or "")
        item["suggestedOwnerEvidence"] = evidence.get("suggested_owner_evidence") or []
        item["actionKind"] = str(evidence.get("action_kind") or "meeting_action")
        item["reviewOnly"] = bool(evidence.get("review_only") or False)
        item["autoActionable"] = bool(evidence.get("auto_actionable", True))
        item["reminderSafe"] = bool(evidence.get("reminder_safe", False))
        item["knowledgeSafe"] = bool(evidence.get("knowledge_safe", status in {"supported", "majority"}))
        item["requiresReview"] = item["reviewOnly"] or status in {
            "unsupported",
            "weak_owner",
            "conflict",
            "contradiction",
            "majority",
            "system_review",
            "unknown",
        }
        items.append(item)
    return items


def action_items_with_evidence(action_items, quality_report: dict) -> list[dict]:
    """Return action items enriched with quality metadata for exports or APIs."""
    return _action_items_with_evidence(action_items, quality_report)


def _action_evidence_items(
    actions: list[dict],
    segments: list[dict],
    unsupported_actions: list[dict],
    weak_action_owners: list[dict],
) -> list[dict]:
    unsupported_keys = {_action_quality_key(item) for item in unsupported_actions}
    weak_owner_keys = {_action_quality_key(item) for item in weak_action_owners}
    items: list[dict] = []
    for action in actions:
        owner = str(action.get("owner") or "").strip() or "待确认"
        task = str(action.get("task") or "").strip()
        if not task:
            continue
        key = _action_quality_key(action)
        evidence = _action_reference_evidence(task, owner, segments)
        suggestion = _suggest_action_owner(task, owner, segments)
        contradiction = _action_claim_contradiction(task, evidence)
        status = "supported"
        reason = "该待办可在转写中找到相关任务或负责人线索。"
        action_kind = "meeting_action"
        review_only = False
        auto_actionable = True
        reminder_safe = False
        knowledge_safe = True
        if _is_system_review_action(action):
            status = "system_review"
            action_kind = "system_review"
            review_only = True
            auto_actionable = False
            knowledge_safe = False
            reason = _system_review_action_reason(task)
        elif contradiction:
            status = "contradiction"
            reason = contradiction
        elif key in unsupported_keys:
            status = "unsupported"
            reason = "待办事项和转写原文关联较弱，请回看转写或录音。"
        elif _is_generic_owner(owner):
            status = "weak_owner"
            reason = "任务内容有转写依据，但负责人是泛化、代词或时间短语，建议人工确认。"
        elif key in weak_owner_keys:
            status = "weak_owner"
            reason = "任务内容有转写依据，但负责人和任务之间缺少明确上下文关联。"
        elif evidence and _evidence_has_majority_with_conflict(evidence, segments):
            status = "majority"
            reason = "该待办由多数录音源一致片段支撑，但同时间仍有少数冲突来源，建议督办前抽查回听。"
        elif evidence and _evidence_has_multisource_conflict(evidence, segments):
            status = "conflict"
            reason = "该待办依据来自多源同录冲突片段，请回听确认日期、数量或负责人后再督办。"
        if status not in {"supported", "majority"}:
            knowledge_safe = False
            auto_actionable = False
        if status == "majority":
            reminder_safe = False
        elif status == "supported":
            reminder_safe = True
        items.append(
            {
                "id": action.get("id", ""),
                "owner": owner,
                "task": task[:160],
                "due": action.get("due", ""),
                "status": status,
                "reason": reason,
                "action_kind": action_kind,
                "review_only": review_only,
                "auto_actionable": auto_actionable,
                "reminder_safe": reminder_safe,
                "knowledge_safe": knowledge_safe,
                "evidence": evidence,
                "suggested_owner": suggestion.get("owner", ""),
                "suggested_owner_reason": suggestion.get("reason", ""),
                "suggested_owner_evidence": suggestion.get("evidence", []),
            }
        )
    return items


def _evidence_has_majority_with_conflict(
    evidence: list[dict],
    segments: list[dict],
) -> bool:
    if not _evidence_has_multisource_conflict(evidence, segments):
        return False
    majority_ids = _segment_ids_with_flag(segments, "multi_source_majority")
    majority_keys = _source_keys_with_flag(segments, "multi_source_majority")
    for item in evidence:
        if _evidence_item_matches_segments(item, majority_ids, majority_keys):
            return True
    return False


def _evidence_has_multisource_conflict(evidence: list[dict], segments: list[dict]) -> bool:
    conflict_segment_ids = _segment_ids_with_flag(segments, "multi_source_conflict")
    conflict_source_keys = _source_keys_with_flag(segments, "multi_source_conflict")
    if not conflict_segment_ids and not conflict_source_keys:
        return False
    return any(
        _evidence_item_matches_segments(item, conflict_segment_ids, conflict_source_keys)
        for item in evidence
    )


def _segment_ids_with_flag(segments: list[dict], flag: str) -> set[str]:
    return {
        str(item.get("id") or "")
        for item in segments
        if flag in _flags(item.get("flags"))
    }


def _source_keys_with_flag(segments: list[dict], flag: str) -> set[tuple[str, str]]:
    return {
        key
        for item in segments
        for key in [_source_segment_key(item)]
        if flag in _flags(item.get("flags"))
        if key is not None
    }


def _evidence_item_matches_segments(
    item: dict,
    segment_ids: set[str],
    source_keys: set[tuple[str, str]],
) -> bool:
    segment_id = str(item.get("segment_id") or "")
    if segment_id:
        return segment_id in segment_ids
    source_key = _source_segment_key(item)
    return source_key is not None and source_key in source_keys


def _segments_with_stable_ids(segments: list[dict]) -> list[dict]:
    return [_segment_with_stable_id(item, index) for index, item in enumerate(segments)]


def _segment_with_stable_id(segment: dict, index: int) -> dict:
    if str(segment.get("id") or "").strip():
        return segment
    item = dict(segment)
    item["id"] = _stable_segment_id(item, index)
    return item


def _stable_segment_id(segment: dict, index: int) -> str:
    parts = [
        str(segment.get("meeting_id") or ""),
        str(segment.get("source_id") or ""),
        str(segment.get("source_segment_no") or ""),
        str(segment.get("speaker_id") or ""),
        str(segment.get("display_name") or ""),
        str(int(segment.get("start_ms") or 0)),
        str(int(segment.get("end_ms") or 0)),
        str(segment.get("text") or ""),
        str(index),
    ]
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"probe_seg_{digest}"


def _source_segment_key(item: dict) -> tuple[str, str] | None:
    source_id = str(item.get("source_id") or "").strip()
    source_segment_no = item.get("source_segment_no")
    if not source_id or source_segment_no in (None, ""):
        return None
    return source_id, str(source_segment_no)


def _action_quality_key(item: dict) -> str:
    if item.get("id"):
        return f"id:{item.get('id')}"
    owner = str(item.get("owner") or "").strip()
    task = str(item.get("task") or "").strip()
    return f"text:{owner}|{task}"


def _summary_evidence_report(summary: str, role_notes: str, segments: list[dict]) -> dict:
    claims = _summary_claims(summary, role_notes)
    if not claims:
        return {
            "coverage": 1,
            "claim_count": 0,
            "unsupported_count": 0,
            "contradiction_count": 0,
            "majority_count": 0,
            "conflict_count": 0,
            "unqualified_conflict_count": 0,
            "supportedClaims": [],
            "contradictedClaims": [],
            "unsupportedClaims": [],
        }
    unsupported = []
    supported = []
    contradictions = []
    for claim in claims:
        evidence = _claim_reference_evidence(claim, segments)
        if evidence:
            contradiction = _summary_claim_contradiction(claim, evidence)
            if contradiction:
                contradictions.append(
                    {
                        "claim": claim[:160],
                        "status": "contradiction",
                        "reason": contradiction,
                        "evidence": evidence,
                    }
                )
                continue
            status, reason = _summary_claim_status(claim, evidence, segments)
            supported.append(
                {
                    "claim": claim[:160],
                    "status": status,
                    "reason": reason,
                    "evidence": evidence,
                }
            )
            continue
        unsupported.append({"claim": claim[:160], "evidence": []})
    coverage = 1 - len(unsupported) / max(1, len(claims))
    conflict_count = sum(1 for item in supported if item.get("status") == "conflict")
    return {
        "coverage": round(coverage, 4),
        "claim_count": len(claims),
        "unsupported_count": len(unsupported),
        "contradiction_count": len(contradictions),
        "majority_count": sum(1 for item in supported if item.get("status") == "majority"),
        "conflict_count": conflict_count,
        "unqualified_conflict_count": sum(
            1
            for item in supported
            if item.get("status") == "conflict"
            and not _claim_has_review_language(str(item.get("claim") or ""))
        ),
        "supportedClaims": [*contradictions, *supported][:8],
        "contradictedClaims": contradictions[:8],
        "unsupportedClaims": unsupported[:8],
    }


_SUMMARY_CONTRADICTION_EVENTS = (
    {
        "name": "定版/敲定",
        "action": (
            r"(?:定版|定稿|敲定|确认最终版)",
        ),
        "positive": (
            r"(?:已|已经|确认|明确|完成|正式|最终).{0,6}(?:定版|定稿|敲定)",
            r"(?:定版|定稿|敲定)(?:完成|了|好了|确认|明确)",
            r"(?:最终版|正式版)(?:已|已经)?(?:确认|完成)",
        ),
        "negative": (
            r"(?:还没|尚未|未|没有|没|暂未|待|不能|无法).{0,6}(?:定版|定稿|敲定|确认最终版)",
            r"(?:不|别|不要|先不|暂不).{0,6}(?:定版|定稿|敲定)",
        ),
    },
    {
        "name": "发送/通知",
        "action": (
            r"(?:发送|发出|发|推送|通知)",
        ),
        "positive": (
            r"(?:已|已经).{0,4}(?:发送|发出|发了|推送|通知)",
            r"(?:今天|明天|后天|上午|下午|晚上|本周|下周|周[一二三四五六日天]).{0,8}(?:发送|发出|发|推送|通知)",
            r"(?:决定|确认|安排|要求|负责|会|要|需要).{0,8}(?:发送|发出|发|推送|通知)",
            r"(?:客户|名单|消息|通知|邮件).{0,4}(?:已|已经|完成).{0,4}(?:发送|发出|推送|通知)",
        ),
        "negative": (
            r"(?:还没|尚未|未|没有|没|暂未|待).{0,6}(?:发送|发出|发|推送|通知)",
            r"(?:不|别|不要|先不|暂不|不能|无法).{0,6}(?:发送|发出|发|推送|通知)",
        ),
    },
    {
        "name": "完成/准备",
        "action": (
            r"(?:完成|做完|补完|准备好|解决|闭环)",
        ),
        "positive": (
            r"(?:已|已经).{0,4}(?:完成|做完|补完|准备好|解决|闭环)",
            r"(?:完成|做完|补完|准备好)(?:了|啦)?",
        ),
        "negative": (
            r"(?:还没|尚未|未|没有|没|暂未|待|不能|无法).{0,6}(?:完成|做完|补完|准备好|解决|闭环)",
            r"(?:不|别|不要|先不|暂不).{0,6}(?:完成|做完|补完|准备)",
        ),
    },
    {
        "name": "确认/确定",
        "action": (
            r"(?:确认|明确|确定|定下来)",
        ),
        "positive": (
            r"(?:已|已经).{0,4}(?:确认|明确|确定|定下来)",
            r"(?:确认|明确|确定|定下来)(?:完成|了)",
            r"(?:达成|形成).{0,4}(?:共识|结论)",
        ),
        "negative": (
            r"(?:还没|尚未|未|没有|没|暂未|待|不能|无法).{0,6}(?:确认|明确|确定|定下来)",
            r"(?:不确定|待确认|待明确)",
        ),
    },
    {
        "name": "审批/通过",
        "action": (
            r"(?:通过|批准|审批)",
        ),
        "positive": (
            r"(?:已|已经)?(?:通过|批准|审批通过)",
            r"(?:审批|评审).{0,4}(?:已|已经)?(?:通过|批准)",
        ),
        "negative": (
            r"(?:还没|尚未|未|没有|没|暂未|待|不能|无法).{0,6}(?:通过|批准|审批)",
            r"(?:不通过|未批准|驳回)",
        ),
    },
    {
        "name": "上线/发布",
        "action": (
            r"(?:上线|发布|投产)",
        ),
        "positive": (
            r"(?:已|已经)?(?:上线|发布|投产)",
            r"(?:上线|发布|投产).{0,4}(?:完成|了)",
        ),
        "negative": (
            r"(?:还没|尚未|未|没有|没|暂未|待|不能|无法).{0,6}(?:上线|发布|投产)",
            r"(?:不|别|不要|先不|暂不|暂缓|延期).{0,6}(?:上线|发布|投产)",
        ),
    },
    {
        "name": "启动/开始",
        "action": (
            r"(?:启动|开始|开展)",
        ),
        "positive": (
            r"(?:已|已经|决定|确认)?(?:启动|开始|开展)",
        ),
        "negative": (
            r"(?:还没|尚未|未|没有|没|暂未|待|不能|无法).{0,6}(?:启动|开始|开展)",
            r"(?:不|别|不要|先不|暂不|暂缓|延期|取消).{0,6}(?:启动|开始|开展)",
        ),
    },
    {
        "name": "同意/认可",
        "action": (
            r"(?:同意|认可)",
        ),
        "positive": (
            r"(?:已|已经)?(?:同意|认可)",
        ),
        "negative": (
            r"(?:不同意|不认可|反对)",
            r"(?:还没|尚未|未|没有|没|暂未|待).{0,6}(?:同意|认可)",
        ),
    },
)


def _summary_claim_contradiction(claim: str, evidence: list[dict]) -> str:
    claim_text = str(claim or "")
    if not claim_text:
        return ""
    return _claim_evidence_contradiction(
        claim_text,
        evidence,
        positive_reason="纪要写成已完成或已确认，但匹配转写片段包含未完成、暂缓或否定表达。",
        negative_reason="纪要写成未完成或未确认，但匹配转写片段表达为已完成或已确认。",
        require_claim_polarity=True,
    )


def _action_claim_contradiction(task: str, evidence: list[dict]) -> str:
    task_text = str(task or "")
    if not task_text or not evidence:
        return ""
    return _claim_evidence_contradiction(
        task_text,
        evidence,
        positive_reason="待办写成需要执行或推进，但匹配转写片段包含先不要、暂缓、不能执行或否定表达。",
        negative_reason="待办写成暂缓或不执行，但匹配转写片段表达为已确认、要执行或已完成。",
        require_claim_polarity=False,
    )


def _claim_evidence_contradiction(
    claim_text: str,
    evidence: list[dict],
    positive_reason: str,
    negative_reason: str,
    require_claim_polarity: bool,
) -> str:
    if not require_claim_polarity and _is_action_uncertain_or_question(claim_text):
        return ""
    for item in evidence:
        evidence_text = str(item.get("text") or "")
        if not evidence_text or not _summary_contradiction_same_topic(
            claim_text,
            evidence_text,
            item,
        ):
            continue
        for event in _SUMMARY_CONTRADICTION_EVENTS:
            if require_claim_polarity:
                claim_polarity = _summary_event_polarity(claim_text, event)
                evidence_polarity = _summary_event_polarity(evidence_text, event)
            else:
                claim_polarity = _action_implied_event_polarity(claim_text, event)
                evidence_polarity = _action_evidence_event_polarity(evidence_text, event)
            if not claim_polarity or not evidence_polarity:
                continue
            if claim_polarity == evidence_polarity:
                continue
            if claim_polarity == "positive":
                return positive_reason
            return negative_reason
    return ""


def _action_implied_event_polarity(text: str, event: dict) -> str:
    value = str(text or "")
    if _is_action_uncertain_or_question(value):
        return ""
    if _evidence_blocks_action_event(value, event):
        return "negative"
    action_patterns = event.get("action") or event.get("positive") or ()
    if any(re.search(pattern, value) for pattern in action_patterns):
        return "positive"
    return ""


def _action_evidence_event_polarity(text: str, event: dict) -> str:
    value = str(text or "")
    if _evidence_blocks_action_event(value, event):
        return "negative"
    polarity = _summary_event_polarity(value, event)
    if polarity == "positive":
        return "positive"
    return ""


def _evidence_blocks_action_event(text: str, event: dict) -> bool:
    value = str(text or "")
    action_patterns = event.get("action") or ()
    if not action_patterns:
        return False
    blockers = r"(?:不|别|不要|先不|暂不|暂缓|延期|取消|不能|无法|驳回)"
    for pattern in action_patterns:
        if re.search(rf"{blockers}[^。！？!?；;\n\r]{{0,12}}{pattern}", value):
            return True
        if re.search(rf"{pattern}[^。！？!?；;\n\r]{{0,12}}{blockers}", value):
            return True
    return False


def _summary_event_polarity(text: str, event: dict) -> str:
    value = str(text or "")
    if any(re.search(pattern, value) for pattern in event.get("negative") or ()):
        return "negative"
    if any(re.search(pattern, value) for pattern in event.get("positive") or ()):
        return "positive"
    return ""


def _is_action_uncertain_or_question(text: str) -> bool:
    return bool(
        re.search(
            r"(是否|能否|要不要|需不需要|讨论|评估|确认是否|看看是否|判断是否|方案|策略)",
            str(text or ""),
        )
    )


def _summary_contradiction_same_topic(claim: str, evidence_text: str, item: dict) -> bool:
    matched_terms = [
        str(token)
        for token in (item.get("matched_terms") or [])
        if _is_summary_contradiction_topic_token(str(token))
    ]
    if any(len(token) >= 3 for token in matched_terms):
        return True
    claim_tokens = set(_summary_contradiction_topic_tokens(claim))
    evidence_tokens = set(_summary_contradiction_topic_tokens(evidence_text))
    overlap = claim_tokens & evidence_tokens
    overlap_weight = sum(_evidence_token_weight(token) for token in overlap)
    if overlap_weight >= 6:
        return True
    return bool(overlap and any(len(token) >= 3 for token in overlap))


def _summary_contradiction_topic_tokens(text: str) -> list[str]:
    return [
        token
        for token in _evidence_tokens(text)
        if _is_summary_contradiction_topic_token(token)
    ]


def _is_summary_contradiction_topic_token(token: str) -> bool:
    value = str(token or "").strip().lower()
    if not value or _is_evidence_stopword(value):
        return False
    stop_tokens = {
        "已经",
        "还没",
        "尚未",
        "没有",
        "暂未",
        "不能",
        "无法",
        "不要",
        "先不",
        "暂不",
        "已完",
        "未完",
        "完成",
        "确认",
        "明确",
        "确定",
        "决定",
        "通过",
        "同意",
        "认可",
        "上午",
        "下午",
        "晚上",
        "今晚",
        "明早",
        "本周",
        "下周",
    }
    return value not in stop_tokens


def _summary_claim_status(
    claim: str,
    evidence: list[dict],
    segments: list[dict],
) -> tuple[str, str]:
    if _evidence_has_majority_with_conflict(evidence, segments):
        return "majority", "该纪要要点由多数录音源一致片段支撑，但附近仍有少数冲突来源。"
    if _evidence_has_multisource_conflict(evidence, segments):
        return "conflict", "该纪要要点只由多源冲突片段支撑，应保留不确定性或人工复核提示。"
    return "supported", "该纪要要点可在转写原文中找到依据。"


def _claim_has_review_language(claim: str) -> bool:
    return bool(
        re.search(
            r"(待核对|待确认|需确认|需复核|建议回听|回听确认|不确定|可能|少数冲突|冲突)",
            str(claim or ""),
        )
    )


def _source_coverage_report(segments: list[dict], audio_segments: list[dict]) -> dict:
    if not audio_segments:
        return {
            "coverage": 1,
            "expected_count": 0,
            "covered_count": 0,
            "weak_count": 0,
            "weakSegments": [],
            "segments": [],
        }
    transcript_by_source: dict[tuple[str, int], list[dict]] = {}
    for segment in segments:
        source_refs = _segment_source_refs(segment)
        for source_key in source_refs:
            transcript_by_source.setdefault(source_key, []).append(segment)
        source_no = segment.get("source_segment_no")
        if source_no is None:
            continue
        try:
            source_key = (
                str(segment.get("source_id") or "primary"),
                int(source_no),
            )
        except (TypeError, ValueError):
            continue
        transcript_by_source.setdefault(source_key, []).append(segment)
    items = []
    weak = []
    for audio in audio_segments:
        segment_no = int(audio.get("segment_no") or 0)
        if not segment_no:
            continue
        source_id = str(audio.get("source_id") or "primary")
        source_segment_no = int(audio.get("source_segment_no") or segment_no)
        related = transcript_by_source.get((source_id, source_segment_no), [])
        substantive = [
            item
            for item in related
            if not (NON_SUBSTANTIVE_TRANSCRIPT_FLAGS & set(_flags(item.get("flags"))))
        ]
        text = " ".join(str(item.get("text") or "") for item in substantive)
        review_text = " ".join(str(item.get("text") or "") for item in related)
        char_count = len(_compact_evidence_text(text))
        duration_ms = max(0, int(audio.get("duration_ms") or 0))
        status = str(audio.get("upload_status") or "")
        covered = bool(substantive and char_count >= _source_min_chars(duration_ms, status))
        item = {
            "segment_no": segment_no,
            "source_id": source_id,
            "source_label": audio.get("source_label") or "",
            "source_segment_no": source_segment_no,
            "status": "covered" if covered else "weak",
            "transcript_segment_count": len(related),
            "substantive_transcript_segment_count": len(substantive),
            "has_review_placeholder": len(related) > len(substantive),
            "char_count": char_count,
            "duration_ms": duration_ms,
            "start_ms": int(audio.get("start_ms") or 0),
            "end_ms": int(audio.get("end_ms") or 0),
            "upload_status": status,
            "sample": _compact_snippet(text or review_text, 140),
        }
        items.append(item)
        if not covered:
            weak.append(item)
    expected = len(items)
    coverage = 1 - len(weak) / expected if expected else 1
    return {
        "coverage": round(coverage, 4),
        "expected_count": expected,
        "covered_count": expected - len(weak),
        "weak_count": len(weak),
        "weakSegments": weak[:8],
        "segments": items[:24],
    }


def _segment_source_refs(segment: dict) -> list[tuple[str, int]]:
    refs = []
    for flag in _flags(segment.get("flags")):
        if not str(flag).startswith("multi_source_refs:"):
            continue
        raw_refs = str(flag).split(":", 1)[1]
        for raw_ref in raw_refs.split(","):
            if ":" not in raw_ref:
                continue
            source_id, source_no = raw_ref.rsplit(":", 1)
            try:
                refs.append((source_id or "primary", int(source_no)))
            except (TypeError, ValueError):
                continue
    return list(dict.fromkeys(refs))


def _source_min_chars(duration_ms: int, upload_status: str) -> int:
    if upload_status and upload_status != "uploaded":
        return 1
    if duration_ms <= 15_000:
        return 1
    if duration_ms <= 60_000:
        return 8
    if duration_ms <= 180_000:
        return 14
    return 20


def _summary_claims(summary: str, role_notes: str, limit: int = 18) -> list[str]:
    raw_text = "\n".join(part for part in [summary, role_notes] if part)
    claims = []
    seen = set()
    for item in re.split(r"[\n\r。！？!?；;]+", raw_text):
        claim = re.sub(r"^[\s\-*•·、0-9.）)]+", "", item).strip()
        claim = re.sub(r"[:：]\s*$", "", claim).strip()
        if len(_compact_evidence_text(claim)) < 8:
            continue
        if _is_summary_boilerplate(claim):
            continue
        compact = _compact_evidence_text(claim)
        if compact in seen:
            continue
        seen.add(compact)
        claims.append(claim)
        if len(claims) >= limit:
            break
    return claims


def _is_summary_boilerplate(text: str) -> bool:
    compact = _compact_evidence_text(text)
    boilerplates = {
        "暂无纪要",
        "暂无",
        "本次会议已完成基础整理",
        "基于转写原文的保守整理",
        "基于转写原文的会议要点",
        "请人工检查转写",
        "请在配置本地asrllm后重新生成正式纪要",
        "会议音频已保存但有效转写内容不足",
    }
    return any(item in compact for item in boilerplates)


def _claim_reference_evidence(claim: str, segments: list[dict], limit: int = 2) -> list[dict]:
    claim_tokens = set(_evidence_tokens(claim))
    if not claim_tokens:
        return []
    candidates: list[tuple[int, dict]] = []
    for segment in segments:
        text = str(segment.get("text") or "")
        overlap = claim_tokens & set(_evidence_tokens(text))
        if not overlap:
            continue
        overlap_weight = sum(_evidence_token_weight(token) for token in overlap)
        total_weight = sum(_evidence_token_weight(token) for token in claim_tokens)
        score = overlap_weight / max(1, total_weight)
        if overlap_weight < 8 and score < 0.24:
            continue
        candidates.append(
            (
                overlap_weight,
                {
                    "segment_id": segment.get("id", ""),
                    "source_id": segment.get("source_id") or "",
                    "source_segment_no": segment.get("source_segment_no"),
                    "speaker": str(segment.get("display_name") or segment.get("speaker_id") or ""),
                    "start_ms": int(segment.get("start_ms") or 0),
                    "end_ms": int(segment.get("end_ms") or 0),
                    "text": _compact_snippet(text, 140),
                    "matched_terms": sorted(overlap, key=lambda token: (-len(token), token))[:8],
                },
            )
        )
    candidates.sort(key=lambda item: (-item[0], item[1]["start_ms"]))
    return [item for _, item in candidates[:limit]]


def _action_reference_evidence(
    task: str,
    owner: str,
    segments: list[dict],
    limit: int = 3,
) -> list[dict]:
    task_tokens = set(_evidence_tokens(task))
    owner_flat = _compact_evidence_text(owner)
    candidates: list[tuple[int, dict]] = []
    for segment in segments:
        text = str(segment.get("text") or "")
        speaker = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
        segment_tokens = set(_evidence_tokens(text))
        overlap = task_tokens & segment_tokens
        owner_hit = bool(owner_flat and owner_flat in _compact_evidence_text(f"{speaker} {text}"))
        if not overlap and not owner_hit:
            continue
        score = sum(_evidence_token_weight(token) for token in overlap)
        if owner_hit:
            score += 5
        if speaker == owner:
            score += 3
        if _owner_assignment_phrase(text, owner):
            score += 6
        if score <= 0:
            continue
        candidates.append(
            (
                score,
                {
                    "segment_id": segment.get("id", ""),
                    "source_id": segment.get("source_id") or "",
                    "source_segment_no": segment.get("source_segment_no"),
                    "speaker": speaker,
                    "start_ms": int(segment.get("start_ms") or 0),
                    "end_ms": int(segment.get("end_ms") or 0),
                    "text": _compact_snippet(text, 140),
                    "matched_terms": sorted(overlap, key=lambda token: (-len(token), token))[:8],
                },
            )
        )
    candidates.sort(key=lambda item: (-item[0], item[1]["start_ms"]))
    return [item for _, item in candidates[:limit]]


def _action_owner_has_assignment_evidence(
    owner: str,
    task: str,
    segments: list[dict],
) -> bool:
    task_tokens = set(_evidence_tokens(task))
    if not task_tokens:
        return True
    for segment in segments:
        text = str(segment.get("text") or "")
        speaker = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
        addressed_candidates = _addressed_owner_task_candidates(task, segment)
        if any(item["owner"] == owner for item in addressed_candidates):
            return True
        competing_addressed_owner = any(
            item["owner"] != owner for item in addressed_candidates
        )
        window_texts: list[str] = []
        if speaker == owner and not competing_addressed_owner:
            window_texts.append(text)
        if owner in text:
            for window in _mention_windows(text, owner, radius=90):
                if _has_competing_addressed_owner(task, window, owner):
                    continue
                window_texts.append(window)
        for window_text in window_texts:
            window_tokens = set(_evidence_tokens(window_text))
            overlap = task_tokens & window_tokens
            if len(overlap) >= 2 and _has_long_evidence_phrase(list(overlap)):
                return True
            if len(overlap) >= 3 and (
                speaker == owner or owner in window_text or _owner_assignment_phrase(text, owner)
            ):
                return True
    return False


def _suggest_action_owner(
    task: str,
    current_owner: str,
    segments: list[dict],
) -> dict:
    task_tokens = set(_evidence_tokens(task))
    if not task_tokens:
        return {}
    current_owner = str(current_owner or "").strip()
    candidates: dict[str, dict] = {}
    for segment in segments:
        speaker = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
        text = str(segment.get("text") or "")
        segment_tokens = set(_evidence_tokens(text))
        overlap = task_tokens & segment_tokens
        can_use_segment_speaker = (
            bool(speaker)
            and not _is_generic_speaker_label(speaker)
            and not _is_generic_owner(speaker)
        )
        if overlap and can_use_segment_speaker:
            score = sum(_evidence_token_weight(token) for token in overlap)
            assignment = _owner_assignment_phrase(text, speaker)
            if assignment:
                score += 9
            if speaker == current_owner:
                score -= 2
            if not assignment and speaker != current_owner:
                score += 2
            if score >= 6:
                _add_owner_suggestion_candidate(
                    candidates,
                    speaker,
                    score,
                    assignment,
                    {
                        "speaker": speaker,
                        "segment_id": segment.get("id", ""),
                        "source_id": segment.get("source_id") or "",
                        "source_segment_no": segment.get("source_segment_no"),
                        "start_ms": int(segment.get("start_ms") or 0),
                        "end_ms": int(segment.get("end_ms") or 0),
                        "text": _compact_snippet(text, 140),
                        "matched_terms": sorted(
                            overlap,
                            key=lambda token: (-len(token), token),
                        )[:8],
                    },
                )
        for addressed in _addressed_owner_task_candidates(task, segment):
            _add_owner_suggestion_candidate(
                candidates,
                addressed["owner"],
                int(addressed["score"]),
                True,
                addressed["evidence"],
            )
    if not candidates:
        return {}
    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            -int(item.get("score") or 0),
            0 if item.get("assignment") else 1,
            str(item.get("owner") or ""),
        ),
    )
    best = ranked[0]
    if best["owner"] == current_owner or int(best["score"]) < 8:
        return {}
    return {
        "owner": best["owner"],
        "reason": (
            "转写中该发言人与任务关键词和责任表述更接近。"
            if best.get("assignment")
            else "转写中该发言人与任务关键词更接近，建议人工确认。"
        ),
        "evidence": best["evidence"][:3],
    }


def _add_owner_suggestion_candidate(
    candidates: dict[str, dict],
    owner: str,
    score: int,
    assignment: bool,
    evidence: dict,
) -> None:
    if not owner or _is_generic_speaker_label(owner):
        return
    item = candidates.setdefault(
        owner,
        {
            "owner": owner,
            "score": 0,
            "evidence": [],
            "assignment": False,
        },
    )
    item["score"] += score
    item["assignment"] = bool(item["assignment"] or assignment)
    item["evidence"].append(evidence)


def _has_competing_addressed_owner(task: str, text: str, owner: str) -> bool:
    segment = {"text": text, "display_name": ""}
    return any(
        item["owner"] != owner
        for item in _addressed_owner_task_candidates(task, segment)
    )


def _addressed_owner_task_candidates(task: str, segment: dict) -> list[dict]:
    task_tokens = set(_evidence_tokens(task))
    if not task_tokens:
        return []
    text = str(segment.get("text") or "")
    speaker = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
    candidates: list[dict] = []
    for addressed in _extract_addressed_owner_spans(text):
        owner = str(addressed.get("owner") or "").strip()
        if _is_invalid_addressed_owner(owner):
            continue
        window = _addressed_owner_topic_text(text, addressed)
        topic = _remove_address_prefix(window, owner) or window
        overlap = task_tokens & set(_evidence_tokens(topic))
        if not overlap:
            continue
        score = sum(_evidence_token_weight(token) for token in overlap) + 12
        if addressed.get("scenario") == "task_ownership":
            score += 4
        if _has_long_evidence_phrase(list(overlap)):
            score += 3
        if score < 8:
            continue
        candidates.append(
            {
                "owner": owner,
                "score": score,
                "evidence": {
                    "speaker": speaker,
                    "addressed_owner": owner,
                    "segment_id": segment.get("id", ""),
                    "source_id": segment.get("source_id") or "",
                    "source_segment_no": segment.get("source_segment_no"),
                    "start_ms": int(segment.get("start_ms") or 0),
                    "end_ms": int(segment.get("end_ms") or 0),
                    "text": _compact_snippet(window, 140),
                    "matched_terms": sorted(
                        overlap,
                        key=lambda token: (-len(token), token),
                    )[:8],
                },
            }
        )
    return candidates


def _extract_addressed_owner_spans(text: str) -> list[dict]:
    value = str(text or "")
    candidates: list[dict] = []
    patterns = [
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
                r"(?:你|您)(?:先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调|那|这)"
            ),
            "context_bridge",
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
    for pattern, scenario in patterns:
        for match in pattern.finditer(value):
            owner = _clean_addressed_owner(match.group(1))
            if not owner:
                continue
            candidates.append(
                {
                    "owner": owner,
                    "marker_start": match.start(),
                    "start": match.start(1),
                    "scenario": scenario,
                }
            )
    deduped: dict[tuple[str, int], dict] = {}
    for item in sorted(
        candidates,
        key=lambda value: (
            value["start"],
            0 if value["scenario"] == "task_ownership" else 1,
        ),
    ):
        key = (str(item.get("owner") or ""), int(item.get("start") or 0))
        deduped.setdefault(key, item)
    return list(deduped.values())


def _addressed_owner_topic_text(text: str, addressed: dict) -> str:
    value = str(text or "")
    marker_start = int(addressed.get("start") or addressed.get("marker_start") or 0)
    next_boundary = re.search(r"[。！？!?；;\n\r]", value[marker_start:])
    if next_boundary:
        return value[marker_start : marker_start + next_boundary.start()]
    return value[marker_start : min(len(value), marker_start + 120)]


def _remove_address_prefix(text: str, owner: str) -> str:
    address_words = (
        r"那个部分|这个部分|的部分|那块|这块|那边|这边|部分|那个|这个|"
        r"后面|后续|回头|稍后|之后|你|您|先|再|来|把|帮|看|说|讲|"
        r"分享|确认|负责|处理|弄|搞|发|补|改|调|一下|下|那|这"
    )
    pattern = (
        r"^[\s，,。！？!?；;、]*"
        + re.escape(owner)
        + rf"(?:(?:{address_words}))*[，,、：:\s]*"
    )
    return re.sub(pattern, "", str(text or ""), count=1).strip()


def _clean_addressed_owner(owner: str) -> str:
    value = re.sub(
        r"^[\s，,。！？!?；;、:：]+|[\s，,。！？!?；;、:：]+$",
        "",
        str(owner or ""),
    )
    value = re.sub(r"^(?:然后|接下来|请)", "", value)
    value = re.sub(
        r"(今天|明天|后天|昨天|本周|下周|月底|月初|周[一二三四五六日天]|\d{1,2}月|\d{1,2}[日号]).*$",
        "",
        value,
    )
    value = re.sub(
        r"(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞).*$",
        "",
        value,
    )
    return re.sub(
        r"(?:你|您|你那个|您那个|你这个|您这个|这个|那个|这边|那边|后面|先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调)+$",
        "",
        value,
    ).strip()


def _is_invalid_addressed_owner(owner: str) -> bool:
    value = str(owner or "").strip()
    if not value:
        return True
    if _is_generic_speaker_label(value) or _is_generic_owner(value):
        return True
    if value in {
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
    return _looks_like_due_time_phrase(value) or _looks_like_topic_owner_phrase(value)


def _looks_like_topic_owner_phrase(value: str) -> bool:
    text = str(value or "").strip()
    if not re.fullmatch(r"[\u4e00-\u9fa5]{3,8}", text):
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
        "合同",
        "审批",
    }
    return any(word in text for word in topic_words)


def _mention_windows(text: str, name: str, radius: int = 70) -> list[str]:
    windows = []
    for match in re.finditer(re.escape(name), text):
        windows.append(text[max(0, match.start() - radius) : min(len(text), match.end() + radius)])
    return windows


def _owner_assignment_phrase(text: str, owner: str) -> bool:
    if not text or not owner:
        return False
    escaped = re.escape(owner)
    patterns = [
        rf"{escaped}(?:你|您)?(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)",
        rf"{escaped}(?:这边|那边|团队|部门|组)[^。！？!?；;\n\r]{{0,16}}"
        rf"(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)",
        rf"(?:交给|让|找|通知|安排){escaped}(?:来|去)?(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)",
        rf"{escaped}(?:的)?(?:部分|那块|这块|那边|这边|那个部分|这个部分)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _org_owners_in_segments(segments: list[dict]) -> set[str]:
    owners: set[str] = set()
    for segment in segments:
        text = str(segment.get("text") or "")
        speaker = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
        for owner in ORG_OWNER_TERMS:
            if owner == speaker or _org_owner_mentioned_as_owner(text, owner):
                owners.add(owner)
    return owners


def _org_owner_mentioned_as_owner(text: str, owner: str) -> bool:
    value = str(text or "")
    chunks = [
        chunk.strip()
        for chunk in re.split(r"[，,、。！？!?；;\n\r]+", value)
        if chunk.strip()
    ]
    return any(
        not _org_owner_condition_phrase(chunk, owner)
        and _org_owner_assignment_phrase(chunk, owner)
        for chunk in chunks
    )


def _org_owner_assignment_phrase(text: str, owner: str) -> bool:
    if not text or not owner:
        return False
    escaped = re.escape(owner)
    return bool(
        re.search(rf"{escaped}(?:这边|那边|团队|部门|组)", text)
        or re.search(
            rf"{escaped}[^。！？!?；;\n\r]{{0,16}}"
            rf"(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)",
            text,
        )
    )


def _org_owner_condition_phrase(text: str, owner: str) -> bool:
    value = str(text or "")
    if not owner or not value:
        return False
    escaped = re.escape(owner)
    return bool(
        re.search(
            rf"(?:等|待|等待|等到|等着){escaped}"
            rf"[^。！？!?；;\n\r]{{0,10}}(?:确认|审批|批准|同意|回复|反馈|定版|定稿)",
            value,
        )
        or re.search(
            rf"{escaped}[^。！？!?；;\n\r]{{0,10}}(?:确认|审批|批准|同意|回复|反馈)"
            rf"[^。！？!?；;\n\r]{{0,10}}(?:后|之后|以后|再)",
            value,
        )
    )


def _action_has_transcript_evidence(
    task: str,
    owner: str,
    corpus_flat: str,
    corpus_tokens: set[str],
) -> bool:
    task_flat = _compact_evidence_text(task)
    if not task_flat:
        return True
    if len(task_flat) >= 6 and task_flat in corpus_flat:
        return True
    tokens = _evidence_tokens(task)
    if len(tokens) < 2:
        return True
    overlap = [token for token in tokens if token in corpus_tokens or token in corpus_flat]
    if _has_long_evidence_phrase(overlap):
        return True
    total_weight = sum(_evidence_token_weight(token) for token in tokens)
    overlap_weight = sum(_evidence_token_weight(token) for token in overlap)
    score = overlap_weight / max(1, total_weight)
    owner_flat = _compact_evidence_text(owner)
    if owner_flat and not _is_generic_owner(owner) and owner_flat in corpus_flat:
        score += 0.08
    return overlap_weight >= 6 or score >= 0.22


def _has_long_evidence_phrase(tokens: list[str]) -> bool:
    return any(
        len(token) >= 4
        for token in tokens
        if re.search(r"[\u4e00-\u9fa5A-Za-z]", token)
    )


def _evidence_tokens(text: str) -> list[str]:
    text = str(text or "")
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_+-]{1,24}", text):
        token = match.group(0).lower()
        if not _is_evidence_stopword(token):
            tokens.append(token)
    compact = _compact_evidence_text(text)
    for length in (4, 3, 2):
        for index in range(0, max(0, len(compact) - length + 1)):
            token = compact[index : index + length]
            if not re.fullmatch(r"[\u4e00-\u9fa5]{%d}" % length, token):
                continue
            if _is_evidence_stopword(token):
                continue
            tokens.append(token)
    return list(dict.fromkeys(tokens))[:120]


def _compact_evidence_text(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9_+-]+", "", str(text or "")).lower()


def _compact_snippet(text: str, limit: int = 140) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _evidence_token_weight(token: str) -> int:
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_+-]{1,24}", token):
        return min(6, max(2, len(token) // 3))
    return min(6, max(2, len(token)))


def _is_evidence_stopword(token: str) -> bool:
    token = str(token or "").strip().lower()
    if len(token) < 2:
        return True
    stopwords = {
        "这个",
        "那个",
        "这些",
        "那些",
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
        "负责",
        "负责人",
        "相关",
        "确认",
        "处理",
        "准备",
        "完成",
        "推进",
        "跟进",
    }
    return token in stopwords
