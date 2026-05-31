import argparse
import json
from collections import Counter

from .db import get_db, init_db
from .llm_adapters import (
    llm_options_from_settings_and_db,
    mentioned_people_candidates,
    refine_segments_with_llm,
    summarize_with_llm,
)
from .processing import (
    _grounded_summary_result,
    _meeting_duration_ms,
    _merge_multisource_segments,
    _normalize_action_owners,
    _normalize_semantic_segments,
    _preserve_source_segments,
    _refined_segments_cover_source,
    _repair_refined_timeline,
    _rule_refine_residual_mixed_segments,
    _rule_refine_segments,
    _transcript_row_to_segment,
)
from .repository import build_quality_report, meeting_document
from .repository import build_knowledge_readiness
from .utils import row_to_dict


def probe_meeting(
    meeting_id: str,
    run_llm: bool = False,
    run_postprocess: bool = False,
) -> dict:
    """Return a read-only LLM quality probe for one meeting."""
    init_db()
    with get_db() as db:
        meeting = db.execute(
            "SELECT * FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
        transcript_rows = db.execute(
            """
            SELECT * FROM transcript_segments
            WHERE meeting_id = ?
            ORDER BY start_ms, id
            """,
            (meeting_id,),
        ).fetchall()
        action_rows = db.execute(
            "SELECT * FROM action_items WHERE meeting_id = ? ORDER BY created_at",
            (meeting_id,),
        ).fetchall()
        audio_rows = db.execute(
            "SELECT * FROM audio_segments WHERE meeting_id = ? ORDER BY segment_no",
            (meeting_id,),
        ).fetchall()
        values = {
            row["key"]: row["value"]
            for row in db.execute("SELECT key, value FROM app_config").fetchall()
        }
    if not meeting:
        return {"ok": False, "error": "meeting_not_found", "meeting_id": meeting_id}
    segments = [_transcript_row_to_segment(row) for row in transcript_rows]
    current_report = build_quality_report(
        transcript_rows,
        action_rows,
        audio_rows,
        meeting["summary"] if meeting else "",
        meeting["role_notes"] if meeting else "",
    )
    result = {
        "ok": True,
        "mode": "llm" if run_llm else "postprocess" if run_postprocess else "current",
        "meeting": {
            "id": meeting["id"],
            "title": meeting["title"],
            "status": meeting["status"],
            "duration_ms": meeting["duration_ms"],
            "version": meeting["version"],
        },
        "source": {
            "segment_count": len(segments),
            "speaker_counts": Counter(
                item.get("display_name") or item.get("speaker_id") or "待确认"
                for item in segments
            ).most_common(),
            "char_count": sum(len(str(item.get("text") or "")) for item in segments),
            "candidate_people": list(mentioned_people_candidates(segments, limit=24).keys()),
            "quality_report": current_report,
            "knowledge_readiness": build_knowledge_readiness(current_report),
        },
    }
    if run_postprocess:
        post_segments = _postprocess_segments_without_llm(segments)
        post_actions = _normalize_action_owners(
            [_action_row_like(item) for item in action_rows],
            post_segments,
        )
        post_summary, post_role_notes = _ground_summary_only(
            meeting["summary"] if meeting else "",
            meeting["role_notes"] if meeting else "",
            post_segments,
        )
        result["postprocess"] = _quality_snapshot(
            post_segments,
            post_actions,
            audio_rows,
            post_summary,
            post_role_notes,
        )
        result["postprocess"]["delta"] = _quality_delta(
            result["source"],
            result["postprocess"],
        )
    if not run_llm:
        return result
    options = llm_options_from_settings_and_db(values)
    refined = refine_segments_with_llm(segments, options)
    coverage_ok = _refined_segments_cover_source(refined, segments)
    llm_result = {
        "raw_refined_count": len(refined),
        "raw_speaker_counts": Counter(
            item.get("display_name") or item.get("speaker") or "待确认"
            for item in refined
        ).most_common(),
        "coverage_ok": coverage_ok,
    }
    if coverage_ok:
        refined = _repair_refined_timeline(
            refined,
            segments,
            _meeting_duration_ms(meeting_id),
        )
        refined = _rule_refine_residual_mixed_segments(refined)
        refined = _normalize_semantic_segments(
            _preserve_source_segments(refined, segments),
            "llm",
        )
        summary, role_notes, actions = summarize_with_llm(refined, options)
        summary, role_notes, actions = _grounded_summary_result(
            summary,
            role_notes,
            actions,
            refined,
        )
        llm_result.update(
            {
                "final_refined_count": len(refined),
                "final_start_end": _start_end(refined),
                "final_speaker_counts": Counter(
                    item.get("display_name") or item.get("speaker_id") or "待确认"
                    for item in refined
                ).most_common(),
                "timeline_repaired_count": sum(
                    1
                    for item in refined
                    if "timeline_repaired" in (item.get("flags") or [])
                ),
                "speaker_review_count": sum(
                    1
                    for item in refined
                    if "speaker_review" in (item.get("flags") or [])
                ),
                "action_count": len(actions),
                "actions": actions[:20],
                "generic_owner_count": sum(
                    1
                    for item in actions
                    if str(item.get("owner") or "") in _GENERIC_OWNERS
                ),
                "summary_preview": summary[:500],
                "role_notes_preview": role_notes[:500],
                "candidate_people": list(
                    mentioned_people_candidates(refined, limit=24).keys()
                ),
                "quality_report": build_quality_report(
                    [_segment_row_like(item) for item in refined],
                    [_action_row_like(item) for item in actions],
                    audio_rows,
                    summary,
                    role_notes,
                ),
            }
        )
        llm_result["knowledge_readiness"] = build_knowledge_readiness(
            llm_result["quality_report"]
        )
        llm_result["delta"] = _quality_delta(
            result["source"],
            _llm_delta_snapshot(llm_result),
        )
    result["llm"] = llm_result
    return result


def _postprocess_segments_without_llm(segments: list[dict]) -> list[dict]:
    refined = _merge_multisource_segments(segments)
    refined = _rule_refine_residual_mixed_segments(refined)
    refined = _rule_refine_segments(refined)
    return _normalize_semantic_segments(refined, "probe")


def _ground_summary_only(
    summary: str,
    role_notes: str,
    segments: list[dict],
) -> tuple[str, str]:
    grounded_summary, grounded_role_notes, _ = _grounded_summary_result(
        summary,
        role_notes,
        [],
        segments,
    )
    return grounded_summary, grounded_role_notes


def _quality_snapshot(
    segments: list[dict],
    actions,
    audio_rows,
    summary: str,
    role_notes: str,
) -> dict:
    report = build_quality_report(
        [_segment_row_like(item) for item in segments],
        [_action_row_like(item) for item in actions],
        audio_rows,
        summary,
        role_notes,
    )
    return {
        "segment_count": len(segments),
        "speaker_counts": Counter(
            item.get("display_name") or item.get("speaker_id") or "待确认"
            for item in segments
        ).most_common(),
        "char_count": sum(len(str(item.get("text") or "")) for item in segments),
        "candidate_people": list(mentioned_people_candidates(segments, limit=24).keys()),
        "summary_preview": summary[:500],
        "role_notes_preview": role_notes[:500],
        "quality_report": report,
        "knowledge_readiness": build_knowledge_readiness(report),
    }


def _llm_delta_snapshot(llm_result: dict) -> dict:
    return {
        "segment_count": llm_result.get("final_refined_count", 0),
        "speaker_counts": llm_result.get("final_speaker_counts", []),
        "candidate_people": llm_result.get("candidate_people", []),
        "quality_report": llm_result.get("quality_report") or {},
        "knowledge_readiness": llm_result.get("knowledge_readiness") or {},
    }


def _quality_delta(source: dict, target: dict) -> dict:
    source_report = source.get("quality_report") or {}
    target_report = target.get("quality_report") or {}
    source_metrics = source_report.get("metrics") or {}
    target_metrics = target_report.get("metrics") or {}
    source_speakers = _speaker_names(source)
    target_speakers = _speaker_names(target)
    source_candidates = set(source.get("candidate_people") or [])
    target_candidates = set(target.get("candidate_people") or [])
    metric_deltas = {
        key: _metric_delta(source_metrics, target_metrics, key)
        for key in _DELTA_METRICS
    }
    return {
        "score": {
            "from": int(source_report.get("score") or 0),
            "to": int(target_report.get("score") or 0),
            "delta": int(target_report.get("score") or 0)
            - int(source_report.get("score") or 0),
        },
        "status": {
            "from": source_report.get("status") or "",
            "to": target_report.get("status") or "",
        },
        "knowledge_readiness": {
            "from": (source.get("knowledge_readiness") or {}).get("status") or "",
            "to": (target.get("knowledge_readiness") or {}).get("status") or "",
        },
        "segment_count_delta": int(target.get("segment_count") or 0)
        - int(source.get("segment_count") or 0),
        "speaker_count_delta": len(target_speakers) - len(source_speakers),
        "speaker_names_added": sorted(target_speakers - source_speakers),
        "speaker_names_removed": sorted(source_speakers - target_speakers),
        "candidate_people_added": sorted(target_candidates - source_candidates),
        "metrics": metric_deltas,
        "improved_metrics": [
            key
            for key in _LOWER_IS_BETTER_METRICS
            if metric_deltas[key]["delta"] < 0
        ]
        + [
            key
            for key in _HIGHER_IS_BETTER_METRICS
            if metric_deltas[key]["delta"] > 0
        ],
        "regressed_metrics": [
            key
            for key in _LOWER_IS_BETTER_METRICS
            if metric_deltas[key]["delta"] > 0
        ]
        + [
            key
            for key in _HIGHER_IS_BETTER_METRICS
            if metric_deltas[key]["delta"] < 0
        ],
        "suggested_owner_count": {
            "from": _suggested_owner_count(source_report),
            "to": _suggested_owner_count(target_report),
            "delta": _suggested_owner_count(target_report)
            - _suggested_owner_count(source_report),
        },
        "suggested_owner_changed_count": len(
            _suggested_owner_changes(source_report, target_report)
        ),
        "suggested_owner_changes": _suggested_owner_changes(
            source_report,
            target_report,
        ),
        "suggested_owner_examples": _suggested_owner_examples(target_report),
        "action_owner_changed_count": len(
            _action_owner_changes(source_report, target_report)
        ),
        "action_owner_changes": _action_owner_changes(source_report, target_report),
        "issue_types_removed": sorted(
            _issue_types(source_report) - _issue_types(target_report)
        ),
        "issue_types_added": sorted(
            _issue_types(target_report) - _issue_types(source_report)
        ),
    }


def _metric_delta(source_metrics: dict, target_metrics: dict, key: str) -> dict:
    before = _metric_number(source_metrics.get(key))
    after = _metric_number(target_metrics.get(key))
    return {"from": before, "to": after, "delta": after - before}


def _metric_number(value) -> float | int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 4)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    if parsed.is_integer():
        return int(parsed)
    return round(parsed, 4)


def _speaker_names(snapshot: dict) -> set[str]:
    names = set()
    for item in snapshot.get("speaker_counts") or []:
        if not item:
            continue
        names.add(str(item[0]).strip())
    return {item for item in names if item}


def _suggested_owner_count(report: dict) -> int:
    return sum(
        1
        for item in report.get("actionEvidence") or []
        if str(item.get("suggested_owner") or "").strip()
    )


def _suggested_owner_changes(source_report: dict, target_report: dict) -> list[dict]:
    source_map = _suggested_owner_map(source_report)
    target_map = _suggested_owner_map(target_report)
    changes = []
    for key, target in target_map.items():
        source = source_map.get(key, {})
        before = str(source.get("suggested_owner") or "").strip()
        after = str(target.get("suggested_owner") or "").strip()
        if before == after or not after:
            continue
        changes.append(
            {
                "id": target.get("id") or source.get("id") or "",
                "task": target.get("task") or source.get("task") or "",
                "from": before,
                "to": after,
                "reason": target.get("suggested_owner_reason", ""),
            }
        )
        if len(changes) >= 8:
            break
    return changes


def _action_owner_changes(source_report: dict, target_report: dict) -> list[dict]:
    source_map = _action_evidence_map(source_report)
    target_map = _action_evidence_map(target_report)
    changes = []
    for key, target in target_map.items():
        source = source_map.get(key, {})
        before = str(source.get("owner") or "").strip()
        after = str(target.get("owner") or "").strip()
        if before == after or not after:
            continue
        changes.append(
            {
                "id": target.get("id") or source.get("id") or "",
                "task": target.get("task") or source.get("task") or "",
                "from": before,
                "to": after,
                "status": target.get("status") or "",
            }
        )
        if len(changes) >= 8:
            break
    return changes


def _suggested_owner_map(report: dict) -> dict[str, dict]:
    return {
        key: item
        for key, item in _action_evidence_map(report).items()
        if str(item.get("suggested_owner") or "").strip()
    }


def _action_evidence_map(report: dict) -> dict[str, dict]:
    mapped = {}
    for item in report.get("actionEvidence") or []:
        key = str(item.get("id") or "").strip()
        if not key:
            owner = str(item.get("owner") or "").strip()
            task = str(item.get("task") or "").strip()
            key = f"{owner}|{task}"
        if key:
            mapped[key] = item
    return mapped


def _suggested_owner_examples(report: dict) -> list[dict]:
    examples = []
    for item in report.get("actionEvidence") or []:
        suggested_owner = str(item.get("suggested_owner") or "").strip()
        if not suggested_owner:
            continue
        examples.append(
            {
                "id": item.get("id", ""),
                "owner": item.get("owner", ""),
                "suggested_owner": suggested_owner,
                "task": item.get("task", ""),
                "reason": item.get("suggested_owner_reason", ""),
            }
        )
        if len(examples) >= 5:
            break
    return examples


def _issue_types(report: dict) -> set[str]:
    return {
        str(item.get("type") or "")
        for item in report.get("issues") or []
        if str(item.get("type") or "")
    }


_LOWER_IS_BETTER_METRICS = [
    "generic_owner_count",
    "unsupported_action_count",
    "action_contradiction_count",
    "weak_action_owner_count",
    "summary_unsupported_count",
    "source_segment_weak_count",
    "speaker_evidence_weak_count",
    "speaker_alias_conflict_count",
    "long_segment_count",
    "mixed_marker_segment_count",
    "multi_source_conflict_count",
]

_HIGHER_IS_BETTER_METRICS = [
    "speaker_count",
    "action_evidence_coverage",
    "summary_evidence_coverage",
    "source_segment_coverage",
    "multi_source_majority_count",
    "multi_source_complemented_count",
]

_DELTA_METRICS = _LOWER_IS_BETTER_METRICS + _HIGHER_IS_BETTER_METRICS


_GENERIC_OWNERS = {
    "",
    "待确认",
    "负责人",
    "相关负责人",
    "前端开发",
    "UI讨论者",
    "主持人",
}


def _start_end(segments: list[dict]) -> list[int]:
    if not segments:
        return [0, 0]
    return [
        min(int(item.get("start_ms") or 0) for item in segments),
        max(int(item.get("end_ms") or 0) for item in segments),
    ]


def _segment_row_like(segment: dict) -> dict:
    return {
        "id": segment.get("id", ""),
        "meeting_id": segment.get("meeting_id", ""),
        "version": segment.get("version", 1),
        "source_id": segment.get("source_id") or "",
        "source_segment_no": segment.get("source_segment_no"),
        "speaker_id": segment.get("speaker_id") or "SPEAKER_01",
        "display_name": segment.get("display_name") or segment.get("speaker_id") or "发言人",
        "start_ms": int(segment.get("start_ms") or 0),
        "end_ms": int(segment.get("end_ms") or 0),
        "text": segment.get("text") or "",
        "confidence": segment.get("confidence"),
        "flags": json.dumps(segment.get("flags") or [], ensure_ascii=False),
        "created_at": segment.get("created_at", ""),
    }


def _action_row_like(action: dict) -> dict:
    if not isinstance(action, dict):
        action = row_to_dict(action)
    return {
        "id": action.get("id", ""),
        "meeting_id": action.get("meeting_id", ""),
        "owner": action.get("owner") or "待确认",
        "task": action.get("task") or "",
        "due": action.get("due") or "",
        "status": action.get("status") or "open",
        "source_segment_id": action.get("source_segment_id"),
        "created_at": action.get("created_at", ""),
        "updated_at": action.get("updated_at", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only SoloRecord meeting quality probe."
    )
    parser.add_argument("--meeting-id", required=True)
    parser.add_argument(
        "--run-llm",
        action="store_true",
        help="Call configured LLM for semantic segmentation and summary probing.",
    )
    parser.add_argument(
        "--postprocess",
        action="store_true",
        help="Run local post-processing rules without calling the LLM.",
    )
    parser.add_argument(
        "--current-document",
        action="store_true",
        help="Include the current meeting document in the output.",
    )
    args = parser.parse_args()
    result = probe_meeting(
        args.meeting_id,
        run_llm=args.run_llm,
        run_postprocess=args.postprocess,
    )
    if args.current_document and result.get("ok"):
        result["currentDocument"] = meeting_document(args.meeting_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
