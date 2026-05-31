import json
import re
from pathlib import Path

from .db import get_db
from .llm_adapters import mentioned_people_candidates
from .owner_terms import ORG_OWNER_TERMS
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
    audio_segments = []
    for row in audio_rows:
        item = row_to_dict(row)
        item["download_url"] = (
            f"/api/mobile/meetings/{meeting_id}/segments/{item['segment_no']}/audio"
        )
        audio_segments.append(item)
    quality_report = build_quality_report(
        transcript_segments,
        action_items,
        audio_rows,
        meeting_dict.get("summary", ""),
        meeting_dict.get("role_notes", ""),
    )
    action_items_with_evidence = _action_items_with_evidence(action_items, quality_report)
    return {
        "meeting": meeting_dict,
        "owner": {
            "id": meeting_dict["owner_id"],
            "display_name": meeting_dict.get("owner_name", ""),
            "email": meeting_dict.get("owner_email", ""),
        },
        "members": [row_to_dict(row) for row in members],
        "recordingSources": [row_to_dict(row) for row in recording_sources],
        "audioSegments": audio_segments,
        "transcriptSegments": [row_to_dict(row) for row in transcript_segments],
        "speakers": [row_to_dict(row) for row in speakers],
        "actionItems": action_items_with_evidence,
        "exports": [_export_item(row) for row in exports],
        "qualityReport": quality_report,
        "knowledgeReadiness": build_knowledge_readiness(quality_report),
        "knowledgeGraph": build_meeting_graph(meeting_dict, speakers, action_items, transcript_segments),
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
        "knowledgeGraph": document["knowledgeGraph"],
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


def build_quality_report(
    transcript_segments,
    action_items,
    audio_rows,
    summary: str = "",
    role_notes: str = "",
) -> dict:
    segments = [row_to_dict(row) for row in transcript_segments]
    actions = [row_to_dict(row) for row in action_items]
    audio_segments = [row_to_dict(row) for row in audio_rows]
    flags_by_segment = [_flags(item.get("flags")) for item in segments]
    speaker_names = [
        str(item.get("display_name") or item.get("speaker_id") or "").strip()
        for item in segments
        if str(item.get("display_name") or item.get("speaker_id") or "").strip()
    ]
    unique_speakers = sorted(set(speaker_names))
    speaker_alias_conflicts = _speaker_alias_conflicts(segments)
    candidate_people = mentioned_people_candidates(segments, limit=24)
    generic_actions = [
        item for item in actions if _is_generic_owner(str(item.get("owner") or ""))
    ]
    duplicate_actions = _duplicate_action_items(actions)
    owner_distribution = _owner_distribution(actions)
    unsupported_actions = _unsupported_action_evidence(actions, segments)
    weak_action_owners = _weak_action_owner_evidence(actions, segments, candidate_people)
    action_evidence = _action_evidence_items(
        actions,
        segments,
        unsupported_actions,
        weak_action_owners,
    )
    summary_evidence = _summary_evidence_report(summary, role_notes, segments)
    source_coverage = _source_coverage_report(segments, audio_segments)
    recording_source_ids = sorted(
        {
            str(item.get("source_id") or "primary")
            for item in audio_segments
            if str(item.get("source_id") or "primary")
        }
    )
    evidence_coverage = (
        1 - len(unsupported_actions) / len(actions)
        if actions
        else 1
    )
    review_segments = [
        item for item, flags in zip(segments, flags_by_segment, strict=False)
        if "speaker_review" in flags
    ]
    weak_speaker_evidence_segments = [
        item for item, flags in zip(segments, flags_by_segment, strict=False)
        if "speaker_evidence_weak" in flags
    ]
    speaker_evidence = _speaker_evidence_items(segments, flags_by_segment)
    long_segments = [
        item for item in segments
        if _segment_duration_ms(item) >= 180_000 or len(str(item.get("text") or "")) >= 900
    ]
    possible_mixed_segments = [
        item for item in segments
        if _speaker_marker_count(str(item.get("text") or "")) >= 2
    ]
    llm_segments = sum(
        1
        for flags in flags_by_segment
        if "llm_refined" in flags or "semantic_llm" in flags
    )
    rule_segments = sum(1 for flags in flags_by_segment if "semantic_rule" in flags)
    timeline_repaired = sum(1 for flags in flags_by_segment if "timeline_repaired" in flags)
    multi_source_merged = sum(1 for flags in flags_by_segment if "multi_source_merged" in flags)
    multi_source_complemented = sum(
        1 for flags in flags_by_segment if "multi_source_complemented" in flags
    )
    multi_source_conflicts = sum(1 for flags in flags_by_segment if "multi_source_conflict" in flags)
    scenario_counts: dict[str, int] = {}
    for flags in flags_by_segment:
        for flag in flags:
            if str(flag).startswith("scenario:"):
                scenario = str(flag).split(":", 1)[1] or "unknown"
                scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1

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
    if len(unique_speakers) <= 1 and len(segments) >= 2:
        issues.append(
            _quality_issue(
                "medium",
                "single_speaker",
                "整场只有一个发言人标签",
                "如果这是多人会议，建议先检查时间线中较长段落并拆分发言人。",
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
            "generic_owner_count": len(generic_actions),
            "duplicate_action_count": len(duplicate_actions),
            "unsupported_action_count": len(unsupported_actions),
            "weak_action_owner_count": len(weak_action_owners),
            "action_evidence_coverage": round(evidence_coverage, 4),
            "summary_evidence_coverage": summary_evidence["coverage"],
            "summary_unsupported_count": summary_evidence["unsupported_count"],
            "source_segment_coverage": source_coverage["coverage"],
            "source_segment_weak_count": source_coverage["weak_count"],
            "owner_distribution": owner_distribution,
            "top_owner_ratio": concentration[2] if concentration else 0,
            "speaker_review_count": len(review_segments),
            "speaker_evidence_weak_count": len(weak_speaker_evidence_segments),
            "speaker_alias_conflict_count": len(speaker_alias_conflicts),
            "long_segment_count": len(long_segments),
            "mixed_marker_segment_count": len(possible_mixed_segments),
            "llm_segment_count": llm_segments,
            "rule_segment_count": rule_segments,
            "timeline_repaired_count": timeline_repaired,
            "multi_source_merged_count": multi_source_merged,
            "multi_source_complemented_count": multi_source_complemented,
            "multi_source_conflict_count": multi_source_conflicts,
            "scenario_counts": scenario_counts,
        },
        "candidatePeople": list(candidate_people.keys()),
        "speakerEvidence": speaker_evidence[:12],
        "speakerAliasConflicts": speaker_alias_conflicts[:12],
        "actionEvidence": action_evidence,
        "duplicateActions": duplicate_actions[:8],
        "unsupportedActions": unsupported_actions[:8],
        "weakActionOwners": weak_action_owners[:8],
        "summaryEvidence": summary_evidence,
        "sourceCoverage": source_coverage,
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
        "single_speaker": "优先检查最长的转写段，使用“按人名拆分”和“设为新发言人”。",
        "speaker_review": "在人人物校对区把模型推断的人名统一成真实姓名。",
        "speaker_evidence_weak": "优先播放对应音频，确认模型没有把角色、议题或误听词当成人名。",
        "speaker_alias_conflict": "同名多标签通常来自模型保留 ASR 原始 speaker_id，确认后用人物校对统一。",
        "long_segment": "把超过 3 分钟或内容很长的段落继续按议题拆分。",
        "mixed_speaker_markers": "对出现“某某说/某某：”的段落执行按人名拆分。",
        "generic_owner": "复制待办前先把“待确认/负责人”改成真实人名或具体团队。",
        "duplicate_action": "复制待办前先合并重复项，避免同一件事多次发给负责人。",
        "unsupported_action_evidence": "对缺少证据的待办回看转写或录音，确认不是模型补写。",
        "weak_action_owner_evidence": "优先核对负责人和任务是否在同一议题上下文中被明确关联。",
        "summary_evidence_weak": "逐条核对纪要要点，删除或改写转写原文无法支撑的内容。",
        "source_segment_coverage_weak": "优先检查对应音频分段，必要时重新转写或回退到 ASR 原始结果。",
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
        or value in {"待确认", "未知", "不确定", "unknown"}
    )


def _speaker_evidence_items(segments: list[dict], flags_by_segment: list[list[str]]) -> list[dict]:
    items: list[dict] = []
    for index, (segment, flags) in enumerate(zip(segments, flags_by_segment, strict=False)):
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
        "generic_owner",
        "unsupported_action_evidence",
        "summary_evidence_weak",
        "source_segment_coverage_weak",
    }
    review_types = {
        "speaker_review",
        "speaker_evidence_weak",
        "speaker_alias_conflict",
        "weak_action_owner_evidence",
        "multi_source_conflict",
        "owner_over_concentrated",
        "candidate_people_not_speakers",
        "long_segment",
        "mixed_speaker_markers",
        "single_speaker",
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
            "unsupportedActionCount": int(metrics.get("unsupported_action_count") or 0),
            "weakActionOwnerCount": int(metrics.get("weak_action_owner_count") or 0),
            "summaryUnsupportedCount": int(metrics.get("summary_unsupported_count") or 0),
            "sourceSegmentWeakCount": int(metrics.get("source_segment_weak_count") or 0),
            "multiSourceMergedCount": int(metrics.get("multi_source_merged_count") or 0),
            "multiSourceComplementedCount": int(metrics.get("multi_source_complemented_count") or 0),
            "multiSourceConflictCount": int(metrics.get("multi_source_conflict_count") or 0),
            "actionEvidenceCoverage": float(metrics.get("action_evidence_coverage") or 0),
            "summaryEvidenceCoverage": float(metrics.get("summary_evidence_coverage") or 0),
            "sourceSegmentCoverage": float(metrics.get("source_segment_coverage") or 0),
        },
        "evidenceApi": {
            "transcript": "/api/external/meetings/{meetingId}/transcript?include_history=true",
            "meeting": "/api/external/meetings/{meetingId}",
        },
        "notes": _knowledge_readiness_notes(blockers, review_warnings),
    }


def _knowledge_readiness_notes(blockers: list[str], review_warnings: list[str]) -> list[str]:
    notes = []
    if blockers:
        notes.append("存在阻塞风险，建议暂缓自动入库，先由人工复核。")
    if "unsupported_action_evidence" in blockers:
        notes.append("待办缺少转写证据，知识平台不要直接生成督办记录。")
    if "summary_evidence_weak" in blockers:
        notes.append("纪要存在缺证据要点，知识平台应以转写为准重建摘要。")
    if "source_segment_coverage_weak" in blockers:
        notes.append("当前转写没有覆盖全部音频分段，知识平台不要把该会议视为完整证据。")
    if "speaker_evidence_weak" in review_warnings or "speaker_review" in review_warnings:
        notes.append("发言人包含模型推断，知识平台应保留置信风险或等待人工校正。")
    if "speaker_alias_conflict" in review_warnings:
        notes.append("同一显示名对应多个说话人标签，知识平台应按显示名合并展示并保留原始 speaker_id。")
    if "weak_action_owner_evidence" in review_warnings:
        notes.append("待办负责人证据弱，知识平台应保留待确认状态。")
    return notes


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
) -> list[dict]:
    if not actions or not segments:
        return []
    weak: list[dict] = []
    speaker_names = {
        str(item.get("display_name") or item.get("speaker_id") or "").strip()
        for item in segments
        if str(item.get("display_name") or item.get("speaker_id") or "").strip()
    }
    known_people = set(candidate_people) | speaker_names | _org_owners_in_segments(segments)
    for item in actions:
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
        item["knowledgeSafe"] = status == "supported"
        item["requiresReview"] = status in {"unsupported", "weak_owner", "unknown"}
        items.append(item)
    return items


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
        status = "supported"
        reason = "该待办可在转写中找到相关任务或负责人线索。"
        if key in unsupported_keys:
            status = "unsupported"
            reason = "待办事项和转写原文关联较弱，请回看转写或录音。"
        elif _is_generic_owner(owner):
            status = "weak_owner"
            reason = "任务内容有转写依据，但负责人是泛化、代词或时间短语，建议人工确认。"
        elif key in weak_owner_keys:
            status = "weak_owner"
            reason = "任务内容有转写依据，但负责人和任务之间缺少明确上下文关联。"
        items.append(
            {
                "id": action.get("id", ""),
                "owner": owner,
                "task": task[:160],
                "due": action.get("due", ""),
                "status": status,
                "reason": reason,
                "evidence": evidence,
                "suggested_owner": suggestion.get("owner", ""),
                "suggested_owner_reason": suggestion.get("reason", ""),
                "suggested_owner_evidence": suggestion.get("evidence", []),
            }
        )
    return items


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
            "supportedClaims": [],
            "unsupportedClaims": [],
        }
    unsupported = []
    supported = []
    for claim in claims:
        evidence = _claim_reference_evidence(claim, segments)
        if evidence:
            supported.append({"claim": claim[:160], "evidence": evidence})
            continue
        unsupported.append({"claim": claim[:160], "evidence": []})
    coverage = 1 - len(unsupported) / max(1, len(claims))
    return {
        "coverage": round(coverage, 4),
        "claim_count": len(claims),
        "unsupported_count": len(unsupported),
        "supportedClaims": supported[:8],
        "unsupportedClaims": unsupported[:8],
    }


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
        text = " ".join(str(item.get("text") or "") for item in related)
        char_count = len(_compact_evidence_text(text))
        duration_ms = max(0, int(audio.get("duration_ms") or 0))
        status = str(audio.get("upload_status") or "")
        covered = bool(related and char_count >= _source_min_chars(duration_ms, status))
        item = {
            "segment_no": segment_no,
            "source_id": source_id,
            "source_label": audio.get("source_label") or "",
            "source_segment_no": source_segment_no,
            "status": "covered" if covered else "weak",
            "transcript_segment_count": len(related),
            "char_count": char_count,
            "duration_ms": duration_ms,
            "start_ms": int(audio.get("start_ms") or 0),
            "end_ms": int(audio.get("end_ms") or 0),
            "upload_status": status,
            "sample": _compact_snippet(text, 140),
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
        "请人工检查转写",
        "请在配置本地asrllm后重新生成正式纪要",
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
        window_texts: list[str] = []
        if speaker == owner:
            window_texts.append(text)
        if owner in text:
            window_texts.extend(_mention_windows(text, owner, radius=90))
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
        if not speaker or _is_generic_speaker_label(speaker):
            continue
        text = str(segment.get("text") or "")
        segment_tokens = set(_evidence_tokens(text))
        overlap = task_tokens & segment_tokens
        if not overlap:
            continue
        score = sum(_evidence_token_weight(token) for token in overlap)
        assignment = _owner_assignment_phrase(text, speaker)
        if assignment:
            score += 9
        if speaker == current_owner:
            score -= 2
        if not assignment and speaker != current_owner:
            score += 2
        if score < 6:
            continue
        item = candidates.setdefault(
            speaker,
            {
                "owner": speaker,
                "score": 0,
                "evidence": [],
                "assignment": False,
            },
        )
        item["score"] += score
        item["assignment"] = bool(item["assignment"] or assignment)
        item["evidence"].append(
            {
                "speaker": speaker,
                "segment_id": segment.get("id", ""),
                "source_id": segment.get("source_id") or "",
                "source_segment_no": segment.get("source_segment_no"),
                "start_ms": int(segment.get("start_ms") or 0),
                "end_ms": int(segment.get("end_ms") or 0),
                "text": _compact_snippet(text, 140),
                "matched_terms": sorted(overlap, key=lambda token: (-len(token), token))[:8],
            }
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
    escaped = re.escape(owner)
    return bool(
        re.search(rf"{escaped}(?:这边|那边|团队|部门|组)", value)
        or re.search(
            rf"{escaped}[^。！？!?；;\n\r]{{0,16}}"
            rf"(?:负责|跟进|处理|确认|补充|准备|整理|输出|完成|推进|看|改|发|做|搞)",
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


def build_meeting_graph(meeting: dict, speakers, action_items, transcript_segments) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()
    edge_keys: set[tuple[str, str, str]] = set()

    def add_node(node_id: str, label: str, node_type: str, **props) -> None:
        if not node_id or node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append({"id": node_id, "label": label, "type": node_type, **props})

    def add_edge(source: str, target: str, label: str) -> None:
        key = (source, target, label)
        if key in edge_keys:
            return
        if source in node_ids and target in node_ids:
            edge_keys.add(key)
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "source_label": _node_label(nodes, source),
                    "target_label": _node_label(nodes, target),
                    "label": label,
                }
            )

    meeting_id = str(meeting.get("id") or "")
    add_node(f"meeting:{meeting_id}", meeting.get("title") or "会议", "meeting")

    speaker_name_by_id = _canonical_speaker_map(speakers, transcript_segments)
    speaker_nodes: dict[str, dict] = {}
    for speaker_id, display_name in speaker_name_by_id.items():
        node_id = _speaker_node_id(speaker_id, display_name)
        item = speaker_nodes.setdefault(
            node_id,
            {
                "label": display_name or speaker_id,
                "speaker_ids": [],
                "inferred": False,
            },
        )
        if speaker_id and speaker_id not in item["speaker_ids"]:
            item["speaker_ids"].append(speaker_id)

    for node_id, item in speaker_nodes.items():
        add_node(
            node_id,
            item["label"],
            "speaker",
            speaker_id=item["speaker_ids"][0] if item["speaker_ids"] else "",
            speaker_ids=item["speaker_ids"],
            inferred=item["inferred"],
        )
        add_edge(f"meeting:{meeting_id}", node_id, "包含发言")

    topic_mentions = _graph_topic_mentions(transcript_segments, action_items)
    for topic, data in topic_mentions.items():
        topic_id = f"topic:{_stable_graph_token(topic)}"
        add_node(
            topic_id,
            topic,
            "topic",
            mention_count=int(data.get("mention_count") or 0),
            evidence=data.get("evidence", [])[:3],
        )
        add_edge(f"meeting:{meeting_id}", topic_id, "讨论主题")
        for speaker_id in data.get("speaker_ids", []):
            speaker_id = str(speaker_id or "").strip()
            if not speaker_id:
                continue
            add_edge(_speaker_node_for_owner(speaker_id, speaker_name_by_id), topic_id, "讨论")

    for index, row in enumerate(action_items, start=1):
        item = row_to_dict(row)
        task = item.get("task") or f"待办 {index}"
        action_id = f"action:{item.get('id') or index}"
        add_node(action_id, task, "action", status=item.get("status", "open"), due=item.get("due", ""))
        add_edge(f"meeting:{meeting_id}", action_id, "产生待办")
        for topic in _graph_topics_for_text(task):
            topic_id = f"topic:{_stable_graph_token(topic)}"
            if topic_id not in node_ids:
                add_node(topic_id, topic, "topic", mention_count=1, evidence=[])
                add_edge(f"meeting:{meeting_id}", topic_id, "讨论主题")
            add_edge(topic_id, action_id, "产生待办")
        owner = (item.get("owner") or "").strip()
        if owner:
            owner_id = _speaker_node_for_owner(owner, speaker_name_by_id)
            if owner_id not in node_ids:
                add_node(owner_id, owner, "speaker", inferred=True)
                add_edge(f"meeting:{meeting_id}", owner_id, "提及人员")
            add_edge(owner_id, action_id, "负责")
        due = (item.get("due") or "").strip()
        if due:
            time_id = f"time:{due}"
            add_node(time_id, due, "time")
            add_edge(action_id, time_id, "截止")

    return {"nodes": nodes, "edges": edges}


def _graph_topic_mentions(transcript_segments, action_items) -> dict[str, dict]:
    topics: dict[str, dict] = {}

    def add_topic(topic: str, speaker_id: str = "", evidence: dict | None = None) -> None:
        topic = str(topic or "").strip()
        if not topic:
            return
        item = topics.setdefault(
            topic,
            {"mention_count": 0, "speaker_ids": [], "evidence": []},
        )
        item["mention_count"] += 1
        if speaker_id and speaker_id not in item["speaker_ids"]:
            item["speaker_ids"].append(speaker_id)
        if evidence and len(item["evidence"]) < 5:
            item["evidence"].append(evidence)

    for row in transcript_segments:
        segment = row_to_dict(row)
        speaker_id = str(segment.get("speaker_id") or "")
        for topic in _graph_topics_for_text(str(segment.get("text") or "")):
            add_topic(
                topic,
                speaker_id,
                {
                    "segment_id": segment.get("id", ""),
                    "source_id": segment.get("source_id") or "",
                    "source_segment_no": segment.get("source_segment_no"),
                    "speaker": segment.get("display_name") or speaker_id,
                    "start_ms": int(segment.get("start_ms") or 0),
                    "end_ms": int(segment.get("end_ms") or 0),
                    "text": _compact_snippet(str(segment.get("text") or ""), 90),
                },
            )

    for row in action_items:
        action = row_to_dict(row)
        for topic in _graph_topics_for_text(str(action.get("task") or "")):
            add_topic(topic)

    return dict(
        sorted(
            topics.items(),
            key=lambda item: (-int(item[1].get("mention_count") or 0), item[0]),
        )[:12]
    )


def _graph_topics_for_text(text: str) -> list[str]:
    topics: list[str] = []
    for phrase in _GRAPH_TOPIC_PHRASES:
        if phrase in str(text or ""):
            topics.append(phrase)
    tokens = _evidence_tokens(text)
    for token in tokens:
        if _is_graph_topic_token(token):
            topics.append(token)
    return list(dict.fromkeys(topics))[:4]


_GRAPH_TOPIC_PHRASES = (
    "错误样例",
    "自动测试",
    "测试覆盖",
    "客户名单",
    "舞台音响",
    "合同条款",
    "登录界面",
    "外接数据源",
    "模型调优",
    "一键部署",
    "下载链接",
)


def _is_graph_topic_token(token: str) -> bool:
    value = str(token or "").strip()
    if not value or _is_evidence_stopword(value):
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_+-]{2,24}", value):
        return True
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", value):
        return False
    topic_markers = {
        "客户",
        "名单",
        "物料",
        "舞台",
        "音响",
        "报价",
        "合同",
        "条款",
        "错误",
        "样例",
        "自动",
        "测试",
        "覆盖",
        "登录",
        "界面",
        "图标",
        "数据源",
        "模型",
        "调优",
        "质量",
        "部署",
        "截图",
        "下载",
        "演示",
        "外接",
        "法务",
        "审批",
    }
    return any(marker in value for marker in topic_markers)


def _canonical_speaker_map(speakers, transcript_segments) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in speakers:
        item = row_to_dict(row)
        speaker_id = str(item.get("speaker_id") or item.get("id") or "").strip()
        display_name = str(item.get("display_name") or speaker_id).strip()
        if speaker_id:
            mapping[speaker_id] = display_name or speaker_id
    for row in transcript_segments:
        item = row_to_dict(row)
        speaker_id = str(item.get("speaker_id") or "").strip()
        display_name = str(item.get("display_name") or speaker_id).strip()
        if speaker_id:
            mapping.setdefault(speaker_id, display_name or speaker_id)
            if display_name and not _is_generic_speaker_label(display_name):
                mapping[speaker_id] = display_name
    return mapping


def _speaker_node_id(
    speaker_id: str,
    display_name: str,
) -> str:
    if display_name and not _is_generic_speaker_label(display_name):
        return f"speaker:name:{_stable_graph_token(display_name)}"
    return f"speaker:{speaker_id}"


def _speaker_node_for_owner(owner: str, speaker_name_by_id: dict[str, str]) -> str:
    if owner in speaker_name_by_id:
        display_name = speaker_name_by_id[owner]
        if display_name and not _is_generic_speaker_label(display_name):
            return f"speaker:name:{_stable_graph_token(display_name)}"
        return f"speaker:{owner}"
    for speaker_id, display_name in speaker_name_by_id.items():
        if owner == display_name or owner == speaker_id:
            if display_name and not _is_generic_speaker_label(display_name):
                return f"speaker:name:{_stable_graph_token(display_name)}"
            return f"speaker:{speaker_id}"
    return f"speaker:owner:{owner}"


def _stable_graph_token(value: str) -> str:
    token = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", str(value or "").strip())
    return token[:48] or "unknown"


def _node_label(nodes: list[dict], node_id: str) -> str:
    for node in nodes:
        if node["id"] == node_id:
            return node.get("label", node_id)
    return node_id
