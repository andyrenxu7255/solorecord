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
    _meeting_duration_ms,
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
        result["postprocess"] = _quality_snapshot(
            post_segments,
            action_rows,
            audio_rows,
            meeting["summary"] if meeting else "",
            meeting["role_notes"] if meeting else "",
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
        actions = _normalize_action_owners(actions, refined)
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
    result["llm"] = llm_result
    return result


def _postprocess_segments_without_llm(segments: list[dict]) -> list[dict]:
    refined = _rule_refine_residual_mixed_segments(segments)
    refined = _rule_refine_segments(refined)
    return _normalize_semantic_segments(refined, "probe")


def _quality_snapshot(
    segments: list[dict],
    action_rows,
    audio_rows,
    summary: str,
    role_notes: str,
) -> dict:
    report = build_quality_report(
        [_segment_row_like(item) for item in segments],
        action_rows,
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
        "quality_report": report,
        "knowledge_readiness": build_knowledge_readiness(report),
    }


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
