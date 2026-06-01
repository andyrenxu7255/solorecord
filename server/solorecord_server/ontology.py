import json
import re
from collections import Counter

from .db import get_db
from .llm_adapters import (
    LlmAdapterError,
    extract_ontology_with_llm,
    llm_options_from_settings_and_db,
    mentioned_people_candidates,
)
from .utils import new_id, now_iso, row_to_dict


ENTITY_TYPES = {"person", "place", "time", "matter", "action"}
RELATION_LABELS = {
    "mentioned": "提及",
    "discussed": "讨论",
    "related_to": "关联",
    "responsible_for": "负责",
    "due_at": "截止",
    "located_at": "地点",
    "scheduled_at": "发生时间",
    "depends_on": "依赖",
}
PLACE_WORDS = (
    "会议室",
    "展厅",
    "现场",
    "客户现场",
    "工作区",
    "办公室",
    "园区",
    "机房",
    "上海",
    "北京",
    "深圳",
    "广州",
    "杭州",
    "南京",
    "成都",
    "武汉",
)
TIME_PATTERN = re.compile(
    r"((?:今天|明天|后天|昨天)(?:上午|下午|晚上|中午|早上)?|"
    r"本周[一二三四五六日]?|下周[一二三四五六日]?|周[一二三四五六日]|"
    r"月底前?|月初|上午|下午|晚上|中午|早上|今晚|明晚|"
    r"\d{1,2}[月/-]\d{1,2}[日号]?|\d{1,2}点(?:半)?|\d{1,2}:\d{2})"
)
ACTION_VERBS = (
    "确认",
    "补充",
    "整理",
    "推进",
    "跟进",
    "处理",
    "准备",
    "发送",
    "同步",
    "完成",
    "修复",
    "测试",
    "部署",
    "联调",
    "复核",
    "负责",
    "更新",
    "提供",
    "输出",
)
MATTER_PHRASES = (
    "客户名单",
    "报价明细",
    "合同条款",
    "销售工作区",
    "错误样例",
    "自动测试覆盖",
    "测试覆盖",
    "外接数据源",
    "接口联调",
    "测试账号",
    "模型调优",
    "一键部署",
    "下载链接",
    "登录界面",
    "舞台音响",
)
ACTION_FRAME_PATTERNS = (
    re.compile(
        r"(?:要求|请|让|安排|通知|交给)"
        r"(?P<owner>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,7}?)"
        r"(?=(?:今天|明天|后天|昨天|本周|下周|周[一二三四五六日]|"
        r"上午|下午|晚上|中午|早上|到|去|在|于|把|将|先|"
        r"确认|补充|整理|推进|跟进|处理|准备|发送|同步|完成|"
        r"修复|测试|部署|联调|复核|更新|提供|输出|发|做))"
        r"(?P<body>[^，,。；;！？!?\n\r]{2,36})"
    ),
    re.compile(
        r"(?:^|[，,。；;！？!?\n\r])"
        r"(?P<owner>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,7}?)"
        r"(?:负责|来|去|把|帮|牵头|跟进|处理)"
        r"(?P<body>[^，,。；;！？!?\n\r]{2,36})"
    ),
    re.compile(
        r"(?:依赖|需要|等待|等)"
        r"(?P<owner>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,7}?)"
        r"(?:先|先行)?"
        r"(?P<body>(?:确认|补充|整理|推进|跟进|处理|准备|发送|同步|完成|"
        r"修复|测试|部署|联调|复核|更新|提供|输出|发|做)"
        r"[^，,。；;！？!?\n\r]{1,30})"
    ),
    re.compile(
        r"(?:^|[，,。；;！？!?\n\r])"
        r"(?P<owner>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,7}?)"
        r"(?=(?:今天|明天|后天|昨天|本周|下周|周[一二三四五六日]|"
        r"上午|下午|晚上|中午|早上))"
        r"(?P<body>[^，,。；;！？!?\n\r]*(?:确认|补充|整理|推进|跟进|处理|准备|发送|同步|完成|"
        r"修复|测试|部署|联调|复核|更新|提供|输出|发|做)[^，,。；;！？!?\n\r]{0,30})"
    ),
)
ACTION_BODY_PREFIX = re.compile(
    r"^(?:负责|来|去|把|帮|牵头|跟进|确认|处理|一下|相关|这个|那个|把|将)"
)
ACTION_TRAILING_NOISE = re.compile(
    r"(?:给大家看|发给大家|同步给大家|这块|这个部分|相关事项|相关工作).*"
)


def enqueue_ontology_extraction(meeting_id: str, *, run_inline: bool = True) -> str:
    job_id = new_id("job")
    with get_db() as db:
        db.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES (?, ?, 'knowledge_graph', 'queued', 'queued', 0, 'ontology', ?, ?)
            """,
            (job_id, meeting_id, now_iso(), now_iso()),
        )
    if run_inline:
        process_ontology_job(job_id)
    return job_id


def process_ontology_job(job_id: str) -> None:
    with get_db() as db:
        job = db.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return
        meeting_id = job["meeting_id"]
        db.execute(
            """
            UPDATE processing_jobs
            SET status='running', current_stage='extracting_ontology',
                progress=20, started_at=?, updated_at=?
            WHERE id=?
            """,
            (now_iso(), now_iso(), job_id),
        )
    try:
        graph = extract_and_store_ontology(meeting_id)
        with get_db() as db:
            db.execute(
                """
                UPDATE processing_jobs
                SET status='succeeded', current_stage='knowledge_graph_ready',
                    progress=100, finished_at=?, updated_at=?
                WHERE id=?
                """,
                (now_iso(), now_iso(), job_id),
            )
            db.execute(
                """
                INSERT INTO audit_logs
                (id, actor_user_id, action, resource_type, resource_id, metadata, created_at)
                VALUES (?, 'system', 'ontology.extract.succeeded', 'meeting', ?, ?, ?)
                """,
                (
                    new_id("audlog"),
                    meeting_id,
                    json.dumps(
                        {
                            "entity_count": len(graph["nodes"]),
                            "relation_count": len(graph["edges"]),
                        },
                        ensure_ascii=False,
                    ),
                    now_iso(),
                ),
            )
    except Exception as exc:
        with get_db() as db:
            db.execute(
                """
                UPDATE processing_jobs
                SET status='failed', current_stage='failed',
                    error_code='ONTOLOGY_EXTRACTION_FAILED',
                    error_message=?, finished_at=?, updated_at=?
                WHERE id=?
                """,
                (str(exc), now_iso(), now_iso(), job_id),
            )


def extract_and_store_ontology(meeting_id: str) -> dict:
    segments, actions = _meeting_inputs(meeting_id)
    if not segments and not actions:
        graph = {"entities": [], "relations": []}
    else:
        graph = _extract_with_llm_or_rules(meeting_id, segments, actions)
    _store_ontology_graph(meeting_id, graph)
    return ontology_graph(meeting_id)


def ontology_graph(meeting_id: str) -> dict:
    with get_db() as db:
        entity_rows = db.execute(
            """
            SELECT * FROM ontology_entities
            WHERE meeting_id = ?
            ORDER BY entity_type, label
            """,
            (meeting_id,),
        ).fetchall()
        relation_rows = db.execute(
            """
            SELECT relations.*, source.label AS source_label, source.entity_type AS source_type,
                   target.label AS target_label, target.entity_type AS target_type
            FROM ontology_relations AS relations
            JOIN ontology_entities AS source ON source.id = relations.source_entity_id
            JOIN ontology_entities AS target ON target.id = relations.target_entity_id
            WHERE relations.meeting_id = ?
            ORDER BY relations.relation_type, relations.created_at
            """,
            (meeting_id,),
        ).fetchall()
    nodes = []
    for row in entity_rows:
        item = row_to_dict(row)
        nodes.append(
            {
                "id": item["id"],
                "type": item["entity_type"],
                "label": item["label"],
                "description": item.get("description", ""),
                "confidence": item.get("confidence"),
                "evidence": _json_list(item.get("evidence")),
                "metadata": _json_dict(item.get("metadata")),
                "source": item.get("source", "rule"),
            }
        )
    edges = []
    for row in relation_rows:
        item = row_to_dict(row)
        edges.append(
            {
                "id": item["id"],
                "source": item["source_entity_id"],
                "target": item["target_entity_id"],
                "source_label": item.get("source_label", ""),
                "target_label": item.get("target_label", ""),
                "source_type": item.get("source_type", ""),
                "target_type": item.get("target_type", ""),
                "type": item["relation_type"],
                "label": item["label"],
                "confidence": item.get("confidence"),
                "evidence": _json_list(item.get("evidence")),
                "metadata": _json_dict(item.get("metadata")),
                "source_kind": item.get("source", "rule"),
            }
        )
    return {
        "nodes": nodes,
        "edges": edges,
        "ontology": {
            "entityTypes": ["person", "place", "time", "matter", "action"],
            "relationTypes": sorted({edge["type"] for edge in edges}),
        },
        "status": "ready" if nodes else "empty",
    }


def _meeting_inputs(meeting_id: str) -> tuple[list[dict], list[dict]]:
    with get_db() as db:
        segment_rows = db.execute(
            """
            SELECT * FROM transcript_segments
            WHERE meeting_id = ?
            ORDER BY start_ms, id
            """,
            (meeting_id,),
        ).fetchall()
        action_rows = db.execute(
            """
            SELECT * FROM action_items
            WHERE meeting_id = ?
            ORDER BY created_at, id
            """,
            (meeting_id,),
        ).fetchall()
    segments = [row_to_dict(row) for row in segment_rows]
    actions = [row_to_dict(row) for row in action_rows]
    return segments, actions


def _extract_with_llm_or_rules(meeting_id: str, segments: list[dict], actions: list[dict]) -> dict:
    values = _config_values()
    try:
        graph = extract_ontology_with_llm(
            segments,
            actions,
            llm_options_from_settings_and_db(values),
        )
        return _merge_graphs(
            _rule_extract_ontology(segments, actions),
            _normalize_ontology_payload(graph, "llm"),
        )
    except Exception as exc:
        with get_db() as db:
            db.execute(
                """
                INSERT INTO audit_logs
                (id, actor_user_id, action, resource_type, resource_id, metadata, created_at)
                VALUES (?, 'system', 'ontology.extract.fallback', 'meeting', ?, ?, ?)
                """,
                (
                    new_id("audlog"),
                    meeting_id,
                    json.dumps({"error": str(exc)[:180]}, ensure_ascii=False),
                    now_iso(),
                ),
            )
        return _rule_extract_ontology(segments, actions)


def _rule_extract_ontology(segments: list[dict], actions: list[dict]) -> dict:
    entities: list[dict] = []
    relations: list[dict] = []
    entity_by_key: dict[tuple[str, str], dict] = {}
    action_records: list[dict] = []

    def add_entity(
        entity_type: str,
        label: str,
        *,
        evidence: list[dict] | None = None,
        description: str = "",
        confidence: float = 0.7,
        source: str = "rule",
        metadata: dict | None = None,
    ) -> dict | None:
        label = _clean_label(label)
        if not label or entity_type not in ENTITY_TYPES:
            return None
        key = (entity_type, _normalize_label(label))
        if key in entity_by_key:
            current = entity_by_key[key]
            current["evidence"] = _merge_evidence(current.get("evidence", []), evidence or [])
            current["confidence"] = max(float(current.get("confidence") or 0), confidence)
            return current
        entity = {
            "id": _entity_id(entity_type, label),
            "type": entity_type,
            "label": label,
            "description": description,
            "confidence": confidence,
            "evidence": evidence or [],
            "metadata": metadata or {},
            "source_kind": source,
        }
        entity_by_key[key] = entity
        entities.append(entity)
        return entity

    def add_relation(
        source_entity: dict | None,
        target_entity: dict | None,
        relation_type: str,
        *,
        label: str | None = None,
        evidence: list[dict] | None = None,
        confidence: float = 0.7,
        source: str = "rule",
        metadata: dict | None = None,
    ) -> None:
        if not source_entity or not target_entity:
            return
        relations.append(
            {
                "source": source_entity["id"],
                "target": target_entity["id"],
                "type": relation_type,
                "label": label or RELATION_LABELS.get(relation_type, relation_type),
                "confidence": confidence,
                "evidence": evidence or [],
                "metadata": metadata or {},
                "source_kind": source,
            }
        )

    def remember_action(
        action_entity: dict | None,
        *,
        task: str,
        matters: list[str],
        evidence: list[dict],
        source_text: str = "",
        source: str = "rule",
    ) -> None:
        if not action_entity:
            return
        action_records.append(
            {
                "entity": action_entity,
                "task": _clean_label(task),
                "matters": [_normalize_label(item) for item in matters if _clean_label(item)],
                "evidence": evidence,
                "source_text": source_text,
                "source": source,
            }
        )

    speakers: dict[str, dict] = {}
    for segment in segments:
        if _non_substantive(segment):
            continue
        evidence = [_segment_evidence(segment)]
        text = str(segment.get("text") or "")
        speaker = _clean_label(segment.get("display_name") or segment.get("speaker_id") or "")
        if speaker:
            speakers[speaker] = add_entity("person", speaker, evidence=evidence, confidence=0.72)
        for person in mentioned_people_candidates([segment], limit=8):
            add_entity("person", person, evidence=evidence, confidence=0.68)
        segment_places = [
            add_entity("place", place, evidence=evidence, confidence=0.62)
            for place in _extract_places(text)
        ]
        segment_times = [
            add_entity("time", time_label, evidence=evidence, confidence=0.64)
            for time_label in _extract_times(text)
        ]
        segment_matters = [
            add_entity("matter", matter, evidence=evidence, confidence=0.64)
            for matter in _extract_matters(text)
        ]
        for place_entity in segment_places:
            add_relation(speakers.get(speaker), place_entity, "mentioned", evidence=evidence, confidence=0.55)
        for time_entity in segment_times:
            add_relation(speakers.get(speaker), time_entity, "mentioned", evidence=evidence, confidence=0.52)
        for matter_entity in segment_matters:
            add_relation(speakers.get(speaker), matter_entity, "discussed", evidence=evidence, confidence=0.62)
            for place_entity in segment_places:
                add_relation(matter_entity, place_entity, "located_at", evidence=evidence, confidence=0.5)
            for time_entity in segment_times:
                add_relation(matter_entity, time_entity, "scheduled_at", evidence=evidence, confidence=0.5)
        for frame in _extract_action_frames(text, speaker):
            action_entity = add_entity(
                "action",
                frame["task"],
                evidence=evidence,
                description=frame["task"],
                confidence=frame.get("confidence", 0.68),
                metadata={"source": "transcript_frame"},
            )
            owner = frame.get("owner", "")
            if owner:
                owner_entity = add_entity("person", owner, evidence=evidence, confidence=0.72)
                add_relation(owner_entity, action_entity, "responsible_for", evidence=evidence, confidence=0.72)
            else:
                add_relation(speakers.get(speaker), action_entity, "mentioned", evidence=evidence, confidence=0.5)
            for time_label in frame.get("times", []):
                time_entity = add_entity("time", time_label, evidence=evidence, confidence=0.7)
                add_relation(action_entity, time_entity, "due_at", label="截止", evidence=evidence, confidence=0.68)
            for place in frame.get("places", []):
                place_entity = add_entity("place", place, evidence=evidence, confidence=0.64)
                add_relation(action_entity, place_entity, "located_at", evidence=evidence, confidence=0.62)
            frame_matters = frame.get("matters", []) or _extract_matters(frame["task"])
            remember_action(
                action_entity,
                task=frame["task"],
                matters=frame_matters,
                evidence=evidence,
                source_text=text,
            )
            for matter in frame_matters:
                if _normalize_label(matter) == _normalize_label(frame["task"]):
                    continue
                matter_entity = add_entity("matter", matter, evidence=evidence, confidence=0.66)
                add_relation(matter_entity, action_entity, "related_to", label="关联待办", evidence=evidence, confidence=0.64)
                for time_entity in segment_times:
                    add_relation(matter_entity, time_entity, "scheduled_at", evidence=evidence, confidence=0.48)
                for place_entity in segment_places:
                    add_relation(matter_entity, place_entity, "located_at", evidence=evidence, confidence=0.48)

    for action in actions:
        if _is_system_review_action(action):
            continue
        task = _clean_label(action.get("task", ""))
        if not task:
            continue
        evidence = [_action_evidence(action)]
        action_entity = add_entity(
            "action",
            task,
            evidence=evidence,
            description=task,
            confidence=0.82,
            metadata={
                "action_id": action.get("id", ""),
                "status": action.get("status", "open"),
            },
        )
        owner = _clean_label(action.get("owner", ""))
        if owner and owner != "待确认":
            owner_entity = add_entity("person", owner, evidence=evidence, confidence=0.8)
            add_relation(owner_entity, action_entity, "responsible_for", evidence=evidence, confidence=0.82)
        due = _clean_label(action.get("due", ""))
        if due:
            time_entity = add_entity("time", due, evidence=evidence, confidence=0.82)
            add_relation(action_entity, time_entity, "due_at", label="截止", evidence=evidence, confidence=0.82)
        for time_label in _extract_times(task):
            time_entity = add_entity("time", time_label, evidence=evidence, confidence=0.74)
            add_relation(action_entity, time_entity, "due_at", label="截止", evidence=evidence, confidence=0.72)
        for place in _extract_places(task):
            place_entity = add_entity("place", place, evidence=evidence, confidence=0.74)
            add_relation(action_entity, place_entity, "located_at", label="地点", evidence=evidence, confidence=0.72)
        task_matters = _infer_action_matters(task)
        remember_action(
            action_entity,
            task=task,
            matters=task_matters,
            evidence=evidence,
            source_text=task,
        )
        for matter in task_matters:
            if _normalize_label(matter) == _normalize_label(task):
                continue
            matter_entity = add_entity("matter", matter, evidence=evidence, confidence=0.72)
            add_relation(matter_entity, action_entity, "related_to", label="关联待办", evidence=evidence, confidence=0.7)
    for dependent, prerequisite in _infer_action_dependencies(action_records):
        add_relation(
            dependent["entity"],
            prerequisite["entity"],
            "depends_on",
            label="依赖",
            evidence=_merge_evidence(
                dependent.get("evidence", []),
                prerequisite.get("evidence", []),
            )[:4],
            confidence=0.68,
            metadata={
                "dependent_task": dependent.get("task", ""),
                "prerequisite_task": prerequisite.get("task", ""),
            },
        )
    return {"entities": entities, "relations": _dedupe_relations(relations)}


def _normalize_ontology_payload(payload: dict, source: str) -> dict:
    entities: list[dict] = []
    entity_id_by_input: dict[str, str] = {}
    for item in payload.get("entities") or []:
        if not isinstance(item, dict):
            continue
        entity_type = _entity_type(item.get("type") or item.get("entity_type"))
        label = _clean_label(item.get("label") or item.get("name") or "")
        if not entity_type or not label:
            continue
        entity_id = _entity_id(entity_type, label)
        raw_id = str(item.get("id") or "").strip()
        if raw_id:
            entity_id_by_input[raw_id] = entity_id
        entities.append(
            {
                "id": entity_id,
                "type": entity_type,
                "label": label,
                "description": str(item.get("description") or "").strip(),
                "confidence": _confidence(item.get("confidence"), 0.74),
                "evidence": _normalize_evidence(item.get("evidence")),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                "source_kind": source,
            }
        )
    known_ids = {item["id"] for item in entities}
    relations: list[dict] = []
    for item in payload.get("relations") or payload.get("edges") or []:
        if not isinstance(item, dict):
            continue
        source_id = _relation_endpoint(item.get("source") or item.get("source_id"), entity_id_by_input)
        target_id = _relation_endpoint(item.get("target") or item.get("target_id"), entity_id_by_input)
        if source_id not in known_ids or target_id not in known_ids or source_id == target_id:
            continue
        relation_type = _relation_type(item.get("type") or item.get("relation_type"))
        relations.append(
            {
                "source": source_id,
                "target": target_id,
                "type": relation_type,
                "label": str(item.get("label") or RELATION_LABELS.get(relation_type, relation_type)).strip(),
                "confidence": _confidence(item.get("confidence"), 0.72),
                "evidence": _normalize_evidence(item.get("evidence")),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                "source_kind": source,
            }
        )
    return {"entities": _dedupe_entities(entities), "relations": _dedupe_relations(relations)}


def _merge_graphs(base: dict, extra: dict) -> dict:
    entities = _dedupe_entities([*(base.get("entities") or []), *(extra.get("entities") or [])])
    entity_ids = {item["id"] for item in entities}
    relations = [
        item
        for item in [*(base.get("relations") or []), *(extra.get("relations") or [])]
        if item.get("source") in entity_ids and item.get("target") in entity_ids
    ]
    return {"entities": entities, "relations": _dedupe_relations(relations)}


def _store_ontology_graph(meeting_id: str, graph: dict) -> None:
    now = now_iso()
    with get_db() as db:
        db.execute("DELETE FROM ontology_relations WHERE meeting_id = ?", (meeting_id,))
        db.execute("DELETE FROM ontology_entities WHERE meeting_id = ?", (meeting_id,))
        id_map: dict[str, str] = {}
        for entity in _dedupe_entities(graph.get("entities") or []):
            entity_id = new_id("ent")
            id_map[entity["id"]] = entity_id
            db.execute(
                """
                INSERT INTO ontology_entities
                (id, meeting_id, entity_type, label, normalized_label,
                 description, confidence, evidence, metadata, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    meeting_id,
                    entity["type"],
                    entity["label"],
                    _normalize_label(entity["label"]),
                    entity.get("description", ""),
                    entity.get("confidence"),
                    json.dumps(entity.get("evidence", []), ensure_ascii=False),
                    json.dumps(entity.get("metadata", {}), ensure_ascii=False),
                    entity.get("source_kind", "rule"),
                    now,
                    now,
                ),
            )
        for relation in _dedupe_relations(graph.get("relations") or []):
            source_id = id_map.get(relation.get("source"))
            target_id = id_map.get(relation.get("target"))
            if not source_id or not target_id or source_id == target_id:
                continue
            db.execute(
                """
                INSERT INTO ontology_relations
                (id, meeting_id, source_entity_id, target_entity_id, relation_type,
                 label, confidence, evidence, metadata, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(meeting_id, source_entity_id, target_entity_id, relation_type)
                DO UPDATE SET label=excluded.label, confidence=excluded.confidence,
                    evidence=excluded.evidence, metadata=excluded.metadata,
                    source=excluded.source, updated_at=excluded.updated_at
                """,
                (
                    new_id("rel"),
                    meeting_id,
                    source_id,
                    target_id,
                    relation["type"],
                    relation.get("label") or RELATION_LABELS.get(relation["type"], relation["type"]),
                    relation.get("confidence"),
                    json.dumps(relation.get("evidence", []), ensure_ascii=False),
                    json.dumps(relation.get("metadata", {}), ensure_ascii=False),
                    relation.get("source_kind", "rule"),
                    now,
                    now,
                ),
            )


def _dedupe_entities(entities: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for item in entities:
        entity_type = _entity_type(item.get("type"))
        label = _clean_label(item.get("label", ""))
        if not entity_type or not label:
            continue
        key = (entity_type, _normalize_label(label))
        current = merged.get(key)
        normalized = {
            **item,
            "id": _entity_id(entity_type, label),
            "type": entity_type,
            "label": label,
            "confidence": _confidence(item.get("confidence"), 0.7),
            "evidence": _normalize_evidence(item.get("evidence")),
        }
        if not current:
            merged[key] = normalized
            continue
        current["confidence"] = max(float(current.get("confidence") or 0), float(normalized.get("confidence") or 0))
        current["evidence"] = _merge_evidence(current.get("evidence", []), normalized.get("evidence", []))
        if normalized.get("source_kind") == "llm":
            current["source_kind"] = "llm"
            if normalized.get("description"):
                current["description"] = normalized["description"]
    return sorted(merged.values(), key=lambda item: (item["type"], item["label"]))


def _dedupe_relations(relations: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str, str], dict] = {}
    for item in relations:
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        relation_type = _relation_type(item.get("type"))
        if not source or not target or source == target:
            continue
        key = (source, target, relation_type)
        current = merged.get(key)
        normalized = {
            **item,
            "source": source,
            "target": target,
            "type": relation_type,
            "label": str(item.get("label") or RELATION_LABELS.get(relation_type, relation_type)).strip(),
            "confidence": _confidence(item.get("confidence"), 0.68),
            "evidence": _normalize_evidence(item.get("evidence")),
        }
        if not current:
            merged[key] = normalized
            continue
        current["confidence"] = max(float(current.get("confidence") or 0), float(normalized.get("confidence") or 0))
        current["evidence"] = _merge_evidence(current.get("evidence", []), normalized.get("evidence", []))
        if normalized.get("source_kind") == "llm":
            current["source_kind"] = "llm"
            current["label"] = normalized["label"]
    return list(merged.values())


def _segment_evidence(segment: dict) -> dict:
    return {
        "kind": "transcript_segment",
        "segment_id": segment.get("id", ""),
        "source_id": segment.get("source_id") or "",
        "source_segment_no": segment.get("source_segment_no"),
        "speaker": segment.get("display_name") or segment.get("speaker_id") or "",
        "start_ms": int(segment.get("start_ms") or 0),
        "end_ms": int(segment.get("end_ms") or 0),
        "text": _compact(segment.get("text", ""), 140),
    }


def _action_evidence(action: dict) -> dict:
    return {
        "kind": "action_item",
        "action_id": action.get("id", ""),
        "owner": action.get("owner", ""),
        "task": action.get("task", ""),
        "due": action.get("due", ""),
        "status": action.get("status", "open"),
    }


def _extract_places(text: str) -> list[str]:
    value = str(text or "")
    found = [word for word in PLACE_WORDS if word in value]
    for match in re.finditer(
        r"(?:在|到|去|于|地点是|地点为)?([\u4e00-\u9fa5A-Za-z0-9]{2,12}(?:会议室|展厅|现场|工作区|办公室|园区|机房))",
        value,
    ):
        found.append(match.group(1))
    for phrase in MATTER_PHRASES:
        if phrase in value and re.search(r"(会议室|展厅|现场|工作区|办公室|园区|机房)$", phrase):
            found.append(phrase)
    refined: list[str] = []
    for item in found:
        label = re.sub(r"^(?:在|到|去|于|和|与|以及|要求|安排|通知|请|让|由)?", "", item)
        label = re.sub(r"^[\u4e00-\u9fa5A-Za-z0-9]{2,8}?(?:在|到|去|于)", "", label)
        if label and len(label) <= 12:
            refined.append(label)
    found = refined
    unique = list(dict.fromkeys(found))
    unique.sort(key=len, reverse=True)
    return _remove_subsumed_labels(unique)[:5]


def _extract_times(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in TIME_PATTERN.finditer(str(text or ""))))[:8]


def _extract_action_frames(text: str, speaker: str = "") -> list[dict]:
    value = str(text or "")
    frames: list[dict] = []
    for pattern in ACTION_FRAME_PATTERNS:
        for match in pattern.finditer(value):
            owner = _clean_person_like(match.group("owner"))
            body = _clean_action_body(match.group("body"))
            if not body or _looks_like_invalid_owner(owner):
                continue
            frames.append(_action_frame(owner, body, value, match.start(), match.end()))
    if not frames and _looks_like_person_name(speaker):
        for match in re.finditer(
            r"(?:我来|我负责|我这边|我们负责|我们这边)"
            r"(?P<body>[^，,。；;！？!?\n\r]{2,36})",
            value,
        ):
            body = _clean_action_body(match.group("body"))
            if body:
                frames.append(_action_frame(speaker, body, value, match.start(), match.end()))
    return _dedupe_action_frames(frames)


def _action_frame(owner: str, body: str, full_text: str, start: int, end: int) -> dict:
    window = full_text[max(0, start - 24) : min(len(full_text), end + 24)]
    times = _extract_times(window)
    places = _extract_places(window)
    task = _clean_action_task(body, times, places)
    matters = _infer_action_matters(task, full_text)
    return {
        "owner": owner,
        "task": task,
        "times": times,
        "places": places,
        "matters": matters,
        "confidence": 0.72 if owner else 0.62,
    }


def _infer_action_matters(task: str, full_text: str = "") -> list[str]:
    matters = _extract_matters(task)
    action_object = _matter_from_action_task(task)
    if action_object:
        matters.insert(0, action_object)
    value = f"{task}\n{full_text}"
    if "报价明细" in value and "报价明细" not in matters:
        matters.append("报价明细")
    if "合同条款" in value and "合同条款" not in matters:
        matters.append("合同条款")
    if "接口联调" in value and "接口联调" not in matters:
        matters.append("接口联调")
    if "测试账号" in value and "测试账号" not in matters:
        matters.append("测试账号")
    return _filter_matter_candidates(matters)


def _matter_from_action_task(task: str) -> str:
    value = _clean_label(task)
    if not value:
        return ""
    value = re.sub(r"^(?:" + "|".join(map(re.escape, ACTION_VERBS)) + r")", "", value)
    value = re.sub(r"^(?:到|至|给|把|将|先|相关)", "", value)
    value = re.sub(r"^(?:客户现场|现场|会议室|工作区|办公室)", "", value)
    value = re.sub(r"(?:并|同时|然后).*$", "", value)
    return _clean_label(value)


def _clean_action_body(value: str) -> str:
    body = _clean_label(value)
    body = ACTION_BODY_PREFIX.sub("", body)
    body = ACTION_TRAILING_NOISE.sub("", body)
    return _clean_label(body)


def _clean_action_task(value: str, times: list[str], places: list[str]) -> str:
    task = _clean_label(value)
    for time_label in sorted(times, key=len, reverse=True):
        task = task.replace(time_label, "")
    task = re.sub(r"^(?:前|后|之前|以前|以后)", "", task)
    task = _clean_label(task)
    if not task:
        return _clean_label(value)
    return task


def _dedupe_action_frames(frames: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for frame in frames:
        task = _clean_label(frame.get("task", ""))
        owner = _clean_label(frame.get("owner", ""))
        if not task or len(task) < 2 or _is_generic_action_task(task):
            continue
        key = (_normalize_label(owner), _normalize_label(task))
        if key in seen:
            continue
        seen.add(key)
        result.append({**frame, "owner": owner, "task": task})
    return result[:8]


def _infer_action_dependencies(action_records: list[dict]) -> list[tuple[dict, dict]]:
    pairs: list[tuple[dict, dict]] = []
    for context in action_records:
        text = _normalize_label(str(context.get("source_text") or ""))
        marker_index = _dependency_marker_index(text)
        if marker_index < 0:
            continue
        before_marker = text[:marker_index]
        after_marker = text[marker_index:]
        for left in action_records:
            if left is context and not _record_mentioned_in_text(left, before_marker):
                continue
            if not _record_mentioned_in_text(left, before_marker):
                continue
            for right in action_records:
                if right is left:
                    continue
                if _record_mentioned_in_text(right, after_marker):
                    pairs.append((left, right))
    pairs.extend(_infer_dependency_fallbacks(action_records))
    return _dedupe_dependency_pairs(pairs)


def _dependency_marker_index(value: str) -> int:
    positions = [
        position
        for marker in ("依赖", "需要", "等待", "先", "等")
        if (position := value.find(marker)) >= 0
    ]
    return min(positions) if positions else -1


def _record_mentioned_in_text(record: dict, text: str) -> bool:
    value = _normalize_label(text)
    if not value:
        return False
    task = _normalize_label(record.get("task", ""))
    if task and task in value:
        return True
    for matter in record.get("matters") or []:
        if matter and matter in value:
            return True
    return False


def _infer_dependency_fallbacks(action_records: list[dict]) -> list[tuple[dict, dict]]:
    pairs: list[tuple[dict, dict]] = []
    for dependent in action_records:
        dependent_text = _normalize_label(
            f"{dependent.get('task', '')} {dependent.get('source_text', '')}"
        )
        marker_index = _dependency_marker_index(dependent_text)
        if marker_index < 0:
            continue
        for prerequisite in action_records:
            if prerequisite is dependent:
                continue
            if _record_mentioned_in_text(prerequisite, dependent_text[marker_index:]):
                pairs.append((dependent, prerequisite))
    return pairs


def _dedupe_dependency_pairs(pairs: list[tuple[dict, dict]]) -> list[tuple[dict, dict]]:
    result: list[tuple[dict, dict]] = []
    seen: set[tuple[str, str]] = set()
    for dependent, prerequisite in pairs:
        key = (dependent["entity"]["id"], prerequisite["entity"]["id"])
        if key in seen or key[0] == key[1]:
            continue
        seen.add(key)
        result.append((dependent, prerequisite))
    return result[:12]


def _is_generic_action_task(task: str) -> bool:
    value = re.sub(r"\s+", "", str(task or ""))
    return value in {"发过来", "同步过来", "给过来", "弄一下", "看一下", "处理一下"}


def _clean_person_like(value: str) -> str:
    label = _clean_label(value)
    label = re.sub(r"^(?:要求|安排|通知|请|让|交给|找|拉上)", "", label)
    label = re.sub(r"(?:你|您|这边|那边|负责|确认|处理|跟进|来|去|把|帮)+$", "", label)
    return _clean_label(label)


def _looks_like_person_name(value: str) -> bool:
    label = _clean_person_like(value)
    return bool(label) and not _looks_like_invalid_owner(label)


def _looks_like_invalid_owner(value: str) -> bool:
    label = _clean_person_like(value)
    if not label or len(label) < 2 or len(label) > 8:
        return True
    if label.lower().startswith("speaker"):
        return True
    if any(marker in label for marker in ("在", "到", "去", "于", "会议室", "现场", "工作区", "办公室")):
        return True
    if label in {
        "待确认",
        "发言人",
        "负责人",
        "相关负责人",
        "主持人",
        "我们",
        "大家",
        "客户",
        "团队",
        "合同",
        "报价",
        "测试",
        "模型",
        "销售",
        "工作区",
    }:
        return True
    return _looks_like_matter(label)


def _extract_matters(text: str) -> list[str]:
    value = str(text or "")
    candidates: list[str] = []
    candidates.extend(phrase for phrase in MATTER_PHRASES if phrase in value)
    for phrase in re.split(r"[，,。；;！？!?\n\r]", value):
        phrase = phrase.strip()
        if not phrase:
            continue
        candidates.extend(_matters_from_clause(phrase))
    tokens = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_+-]{2,16}", value)
    counter = Counter(token for token in tokens if _looks_like_matter(token))
    candidates.extend(token for token, _count in counter.most_common(6))
    candidates = [item for item in candidates if not _looks_like_person_name_token(item)]
    return _filter_matter_candidates(candidates)


def _matters_from_clause(phrase: str) -> list[str]:
    results: list[str] = []
    verb_pattern = "|".join(map(re.escape, ACTION_VERBS))
    for match in re.finditer(rf"(?:{verb_pattern})([^，,。；;！？!?\n\r]{{2,28}})", phrase):
        raw_object = match.group(1)
        raw_object = re.sub(r"^(?:到|至|给|把|将|一下|一下子|相关|这个|那个)", "", raw_object)
        raw_object = re.sub(
            r"^(?:[\u4e00-\u9fa5A-Za-z0-9]{{2,8}})?(?:今天|明天|后天|下周[一二三四五六日]?|周[一二三四五六日]|月底)(?:前|后)?",
            "",
            raw_object,
        )
        raw_object = re.sub(r"(?:给大家看|给客户|发给大家|同步给大家|这块|这个部分).*", "", raw_object)
        for part in re.split(r"(?:和|及|以及|、|/|并)", raw_object):
            label = _clean_label(part)
            if label:
                results.append(label)
    fallback = _matter_from_phrase(phrase)
    if fallback:
        results.append(fallback)
    return results


def _matter_from_phrase(phrase: str) -> str:
    cleaned = re.sub(r"^(我这边|我们|大家|然后|另外|还有|这块|那块|关于|针对)", "", phrase)
    verb_match = re.search("|".join(map(re.escape, ACTION_VERBS)), cleaned)
    if verb_match:
        cleaned = cleaned[verb_match.start() :]
    cleaned = re.sub(r"^(?:要求|安排|通知|请|让|由|交给)", "", cleaned)
    cleaned = re.sub(r"^(?:" + "|".join(map(re.escape, ACTION_VERBS)) + r")", "", cleaned)
    cleaned = re.sub(r"^(?:到|至|给|把|将)", "", cleaned)
    cleaned = re.sub(r"(今天|明天|后天|下周[一二三四五六日]?|周[一二三四五六日]|月底前?|上午|下午|晚上).*", "", cleaned)
    return _compact(cleaned, 28)


def _filter_matter_candidates(candidates: list[str]) -> list[str]:
    cleaned = []
    for item in candidates:
        label = _clean_label(item)
        if not label or len(label) < 2:
            continue
        if _looks_like_person_name_token(label):
            continue
        if re.match(r"^(要求|安排|通知|请|让|由|交给)", label):
            continue
        if re.search(r"[\u4e00-\u9fa5]{2,6}(?:在|要求|安排|通知|请|让)", label):
            continue
        if len(label) > 8 and any(verb in label for verb in ACTION_VERBS):
            continue
        if label in {"一下", "结果", "相关"}:
            continue
        cleaned.append(label)
    deduped = list(dict.fromkeys(cleaned))
    result = []
    for item in sorted(deduped, key=lambda label: _matter_rank(label)):
        if _is_action_like_matter(item) and any(
            _normalize_label(_matter_from_action_task(item)) == _normalize_label(other)
            for other in result
        ):
            continue
        result.append(item)
    return result[:8]


def _matter_rank(label: str) -> tuple[int, int, str]:
    return (1 if _is_action_like_matter(label) else 0, len(label), label)


def _is_action_like_matter(label: str) -> bool:
    value = str(label or "").strip()
    return any(value.startswith(verb) for verb in ACTION_VERBS)


def _remove_subsumed_labels(labels: list[str]) -> list[str]:
    result: list[str] = []
    for label in sorted(labels, key=len, reverse=True):
        if not label:
            continue
        if any(label != other and label in other for other in result):
            continue
        result.append(label)
    return result


def _looks_like_matter(token: str) -> bool:
    if len(token) < 2:
        return False
    stop = {"我们", "大家", "今天", "明天", "这个", "那个", "会议", "问题", "事情", "负责"}
    if token in stop:
        return False
    if _looks_like_person_name_token(token):
        return False
    markers = {"客户", "名单", "报价", "合同", "测试", "覆盖", "模型", "部署", "接口", "图谱", "纪要", "待办", "转写", "销售", "工作区"}
    return any(marker in token for marker in markers)


def _looks_like_person_name_token(value: str) -> bool:
    label = str(value or "").strip()
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", label):
        return False
    if any(marker in label for marker in ("客户", "报价", "合同", "测试", "接口", "图谱", "数据", "账号", "名单")):
        return False
    common_surnames = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方任袁柳鲍史唐费廉岑薛雷贺倪汤罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程嵇邢裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘斜厉戎祖武符刘景詹龙叶幸司黎溥印怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴欎胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕冀浦尚农温别庄晏柴瞿阎连习容向古易廖庾终暨居衡步都耿满弘匡国文寇广禄阙东殴殳沃利蔚越隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公万俟司马上官欧阳夏侯诸葛闻人东方赫连皇甫尉迟公羊澹台公冶宗政濮阳淳于单于太叔申屠公孙仲孙轩辕令狐钟离宇文长孙慕容司徒司空"
    return label[0] in common_surnames


def _non_substantive(segment: dict) -> bool:
    flags = _json_list(segment.get("flags"))
    return any(flag in {"mock_asr", "empty_asr", "missing_audio", "source_coverage_gap"} for flag in flags)


def _is_system_review_action(action: dict) -> bool:
    task = str(action.get("task") or "")
    return task.startswith("检查转写结果并补充真实会议纪要") or task.startswith("按转写原文复核待办")


def _entity_type(value) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "people": "person",
        "speaker": "person",
        "member": "person",
        "location": "place",
        "site": "place",
        "datetime": "time",
        "date": "time",
        "topic": "matter",
        "issue": "matter",
        "task": "action",
        "todo": "action",
    }
    text = aliases.get(text, text)
    return text if text in ENTITY_TYPES else ""


def _relation_type(value) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "owns": "responsible_for",
        "owner": "responsible_for",
        "assigned_to": "responsible_for",
        "deadline": "due_at",
        "due": "due_at",
        "time": "scheduled_at",
        "place": "located_at",
        "location": "located_at",
        "topic_action": "related_to",
    }
    return aliases.get(text, text) or "related_to"


def _relation_endpoint(value, id_map: dict[str, str]) -> str:
    text = str(value or "").strip()
    return id_map.get(text, text)


def _entity_id(entity_type: str, label: str) -> str:
    return f"{entity_type}:{_normalize_label(label)}"


def _normalize_label(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fa5]+", "_", str(value or "").strip().lower()).strip("_")[:80]


def _clean_label(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^[，,。；;：:、\s]+|[，,。；;：:、\s]+$", "", text)
    return text[:80]


def _confidence(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _normalize_evidence(value) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        result.append(item)
    return result[:8]


def _merge_evidence(left: list[dict], right: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for item in [*left, *right]:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 8:
            break
    return result


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        return parsed if isinstance(parsed, list) else [parsed]
    return [value] if value else []


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _compact(text, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _config_values() -> dict[str, str]:
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
    return {row["key"]: row["value"] for row in rows}
