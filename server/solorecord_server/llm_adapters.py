import json
import re

import httpx

from .config import get_settings


class LlmAdapterError(RuntimeError):
    pass


def summarize_with_llm(segments: list[dict], options: dict) -> tuple[str, str, list[dict]]:
    provider = str(options.get("llm_provider") or "mock")
    if provider in {"mock", ""}:
        raise LlmAdapterError("LLM provider is not configured")
    if provider == "ollama":
        return _summarize_with_ollama(segments, options)
    if provider in {"openai-compatible", "internal", "remote-qwen"}:
        return _summarize_with_openai_compatible(segments, options)
    raise LlmAdapterError(f"Unsupported LLM provider: {provider}")


def refine_segments_with_llm(segments: list[dict], options: dict) -> list[dict]:
    provider = str(options.get("llm_provider") or "mock")
    if provider in {"mock", ""}:
        raise LlmAdapterError("LLM provider is not configured")
    if provider == "ollama":
        return _refine_segments_with_ollama(segments, options)
    if provider in {"openai-compatible", "internal", "remote-qwen"}:
        return _refine_segments_with_openai_compatible(segments, options)
    raise LlmAdapterError(f"Unsupported LLM provider: {provider}")


def _summarize_with_openai_compatible(segments: list[dict], options: dict) -> tuple[str, str, list[dict]]:
    endpoint = _chat_endpoint(str(options.get("llm_endpoint") or ""))
    model = str(options.get("llm_model") or "")
    if not endpoint or not model:
        raise LlmAdapterError("LLM endpoint/model is missing")
    headers = {"Content-Type": "application/json"}
    api_key = str(options.get("llm_api_key") or "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(segments)},
        ],
    }
    with httpx.Client(timeout=120) as client:
        response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_summary(content, segments)


def _summarize_with_ollama(segments: list[dict], options: dict) -> tuple[str, str, list[dict]]:
    base = str(options.get("llm_endpoint") or "http://127.0.0.1:11434").rstrip("/")
    model = str(options.get("llm_model") or "")
    if not model:
        raise LlmAdapterError("Ollama model is missing")
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(segments)},
        ],
    }
    with httpx.Client(timeout=180) as client:
        response = client.post(f"{base}/api/chat", json=payload)
        response.raise_for_status()
    content = response.json().get("message", {}).get("content", "")
    return _parse_summary(content, segments)


def _refine_segments_with_openai_compatible(segments: list[dict], options: dict) -> list[dict]:
    endpoint = _chat_endpoint(str(options.get("llm_endpoint") or ""))
    model = str(options.get("llm_model") or "")
    if not endpoint or not model:
        raise LlmAdapterError("LLM endpoint/model is missing")
    headers = {"Content-Type": "application/json"}
    api_key = str(options.get("llm_api_key") or "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _segment_refine_system_prompt()},
            {"role": "user", "content": _segment_refine_user_prompt(segments)},
        ],
    }
    with httpx.Client(timeout=180) as client:
        response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_refined_segments(content, segments)


def _refine_segments_with_ollama(segments: list[dict], options: dict) -> list[dict]:
    base = str(options.get("llm_endpoint") or "http://127.0.0.1:11434").rstrip("/")
    model = str(options.get("llm_model") or "")
    if not model:
        raise LlmAdapterError("Ollama model is missing")
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": _segment_refine_system_prompt()},
            {"role": "user", "content": _segment_refine_user_prompt(segments)},
        ],
    }
    with httpx.Client(timeout=180) as client:
        response = client.post(f"{base}/api/chat", json=payload)
        response.raise_for_status()
    content = response.json().get("message", {}).get("content", "")
    return _parse_refined_segments(content, segments)


def _chat_endpoint(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if not endpoint:
        return ""
    if endpoint.endswith("/chat/completions"):
        return endpoint
    return f"{endpoint}/chat/completions"


def _system_prompt() -> str:
    return (
        "你是企业内部会议纪要助手。只输出 JSON，不要 Markdown。"
        "JSON 字段必须包含 summary、role_notes、action_items。"
        "action_items 是数组，每项包含 owner、task、due、status。"
        "生成待办时必须先阅读全文上下文，识别每个说话人、被点名的人、部门或岗位与任务之间的关系。"
        "owner 优先填写明确的人名、发言人显示名、部门或岗位；只有整场上下文都无法推断时才写待确认。"
        "owner 不要写'负责人'、'相关负责人'、'前端开发'、'UI讨论者'、'主持人'这类过宽泛角色；"
        "如果没有真实人名，要写更具体的团队或事项角色，例如'一键部署团队'、'前端团队'、'模型调优人'。"
        "不要因为任务和负责人不在同一句话或同一转写分段中就写待确认。"
        "不要只根据前半段生成待办；后半段出现的新议题、新人员和交付物也必须覆盖。"
        "如果出现'我来/我们负责/销售跟进/他确认'等指代，要结合最近上下文和发言人推断 owner。"
        "如果同一段里出现'李波部分'、'翼天搞的'、'海春你说一下'、'围城你那个部分'等称呼，"
        "后续相关任务要优先绑定到这些被点名的人。"
        "如果某人被点名负责某议题，下一段继续围绕同一议题说明进度、时间或交付物，"
        "即使没有出现'我'字，也要把它作为强上下文线索，但证据不足时仍保留待确认。"
        "为待办填写 owner 时，必须能从发言人、被点名、'我负责/交给某某'或同一议题上下文找到证据；"
        "如果只能猜测，不要硬填人名，写待确认。"
        "候选人名清单只是线索，不是最终结论；只有能从转写上下文支持时才使用。"
        "due 提取自然语言时间，例如'周三'、'下周一'、'月底前'；status 默认 open。"
    )


def _segment_refine_system_prompt() -> str:
    return (
        "你是企业会议转写后处理助手。只输出 JSON，不要 Markdown。"
        "任务是把 ASR 粗转写重分段为真实对话轮次，并根据上下文判断发言人。"
        "JSON 字段必须包含 segments。segments 是数组，每项包含 speaker、speaker_id、"
        "start_ms、end_ms、text、confidence、scenario、reason；如果输入里有 source_index "
        "或 source_segment_no，输出也要带回。"
        "scenario 只能从 explicit_name、context_bridge、dialogue_logic、task_ownership、"
        "native_speaker、unknown 中选择。"
        "ASR 是证据层，不是结论层；你只能重排、拆分和归属原文，不要摘要化原始 text。"
        "如果原始 ASR 已经有可靠说话人标签，优先保留。"
        "如果文本中出现'张三说'、'李四：'、'我来'、'你负责'、'销售这边'等线索，"
        "要结合前后文推断发言人或角色。"
        "speaker 优先使用转写中真实出现的人名或已识别的 display_name；"
        "不要把 speaker 写成'负责人'、'相关负责人'、'前端开发'、'UI讨论者'、'主持人'这类宽泛角色，"
        "除非整场文本没有任何可用人名。无法确定具体人时，使用原始发言人并降低 confidence。"
        "如果一个 ASR 段落里包含多个议题、多人点名、任务交接或明显的问答切换，必须拆成多个较短段落。"
        "如果前一段点名某人讨论某议题，后一段继续围绕同一议题给进度、时间或交付物，"
        "可以判断为被点名人承接发言，但 confidence 保持中等并写明 reason。"
        "如果只是主持人说'张三你先说/李四你那个部分'，这句话本身通常仍是主持人发言；"
        "只有后续内容体现张三/李四在回应或承接同一议题时，才把后续段归给张三/李四。"
        "无法区分主持人点名和被点名人回应时，可以按任务归属拆出候选段，但 confidence 不要超过 0.7。"
        "不要把整场会议压缩成少数几个人；特别要检查转写后半段是否出现新的被点名人员。"
        "如果一个输出段超过约 90 秒或 350 个中文字符，必须再次检查其中是否包含多个轮次。"
        "分段后的 text 必须保留原始转写事实和主要措辞，不能摘要化、删减后半段或只保留结论。"
        "明确姓名或冒号使用 explicit_name；跨段承接、代词、上一轮关系使用 context_bridge；"
        "根据问答、反驳、确认等对话逻辑判断使用 dialogue_logic；"
        "根据任务、负责人、部门归属判断使用 task_ownership；无法判断用 unknown。"
        "不要凭空发明真实姓名；无法判断时使用原始发言人或'待确认'。"
        "每段 text 要去掉明显的'某某说/某某：'前缀，但保留业务内容。"
        "不要改写事实，不要新增转写中没有的信息。"
    )


def _user_prompt(segments: list[dict]) -> str:
    lines = []
    speaker_names = []
    seen_speakers = set()
    people_notes = _mentioned_people_notes(segments)
    for segment in segments:
        speaker = str(segment.get("display_name") or segment.get("speaker_id") or "发言人").strip()
        speaker_id = str(segment.get("speaker_id") or speaker).strip()
        if speaker_id not in seen_speakers:
            seen_speakers.add(speaker_id)
            speaker_names.append(f"- {speaker_id}: {speaker}")
        lines.append(
            f"[{_time(segment.get('start_ms', 0))}] "
            f"{speaker}: {segment.get('text', '')}"
        )
    return (
        "请整理以下会议转写，输出中文 JSON。\n"
        "已识别的说话人/角色：\n"
        + "\n".join(speaker_names)
        + "\n\n文本中出现的候选被点名人员/对象（仅作上下文线索）：\n"
        + "\n".join(people_notes or ["- 暂未从文本中抽取到候选人名"])
        + "\n\n要求：\n"
        "1. 先做整场上下文理解，再生成纪要和待办。\n"
        "2. 待办 owner 尽量绑定到人、角色、部门或明确发言人，避免无依据地写待确认。\n"
        "3. 不要把 owner 写成负责人、相关负责人、前端开发、UI讨论者、主持人这类泛化词。\n"
        "4. 如果责任人与任务跨分段出现，也要关联。\n"
        "5. role_notes 按人/角色归纳观点和承诺。\n"
        "6. 检查转写后半段，不能遗漏后半段新出现的人员、任务和风险。\n\n"
        "会议转写：\n"
        + "\n".join(lines)
    )


def _segment_refine_user_prompt(segments: list[dict]) -> str:
    lines = []
    people_notes = _mentioned_people_notes(segments)
    for index, segment in enumerate(segments, start=1):
        flags = segment.get("flags") or []
        lines.append(
            json.dumps(
                {
                    "source_index": index,
                    "source_id": segment.get("source_id"),
                    "source_segment_no": segment.get("source_segment_no"),
                    "speaker_id": segment.get("speaker_id") or "SPEAKER_01",
                    "display_name": segment.get("display_name") or segment.get("speaker_id") or "发言人",
                    "start_ms": int(segment.get("start_ms") or 0),
                    "end_ms": int(segment.get("end_ms") or 0),
                    "flags": flags if isinstance(flags, list) else [str(flags)],
                    "text": segment.get("text") or "",
                },
                ensure_ascii=False,
            )
        )
    return (
        "请把下面 ASR 粗转写拆成更准确的会议对话时间线。\n"
        "候选被点名人员/对象（仅作线索，必须结合上下文判断）：\n"
        + "\n".join(people_notes or ["- 暂未从文本中抽取到候选人名"])
        + "\n\n"
        "要求：\n"
        "1. 优先利用原始 speaker_id/display_name；没有多人标签时，根据文本称呼、冒号、"
        "'某某说'、上下文指代和任务归属拆分。\n"
        "1a. speaker 尽量使用文本真实出现的人名；避免负责人、相关负责人、前端开发、UI讨论者、主持人"
        "这类泛化名称。无法确定时保留原始发言人并降低 confidence。\n"
        "1b. 输出每个 segments 项时带回对应的 source_index；如果输入 source_id/source_segment_no 非空，"
        "也要带回，方便系统把最终时间线追溯到具体录音源和原始音频分段。\n"
        "1c. 如果同一会议有多个 source_id，同一时间附近的多个来源可能是同一句话的不同拾音版本；"
        "优先保留更清楚、更完整且不冲突的文本，不要把重复内容机械堆叠成多次发言。\n"
        "2. 保持时间顺序。没有更细时间戳时，可按文本顺序在原段 start_ms/end_ms 范围内均匀分配。\n"
        "3. confidence 范围 0-1；需要人工确认的 speaker 用较低 confidence。\n"
        "4. speaker_id 可复用原始 ID；推断出的新人物可用 MANUAL_姓名拼音或 MANUAL_序号。\n"
        "5. scenario 必须写明推断场景：explicit_name、context_bridge、dialogue_logic、"
        "task_ownership、native_speaker 或 unknown。\n"
        "6. 如果被点名后紧接着出现'我这边/我准备/我负责/我们已经'等回应，可把回应段 speaker 判断为被点名人，"
        "并用 context_bridge 或 task_ownership，confidence 保持 0.55-0.75 以便人工校对。\n"
        "6a. 如果回应段没有'我'，但继续围绕被点名句里的同一议题、交付物或时间节点展开，"
        "也可作为 context_bridge 候选；必须在 reason 里说明依据，confidence 不要超过 0.75。\n"
        "7. 对每个分段在 reason 中写明依据，例如'原文出现姓名前缀'、'上一段点名某人且本段继续同一议题'、"
        "'原 ASR speaker_id 未变但文本无法确认'。\n"
        "8. 只输出 JSON：{\"segments\": [...]}。\n\n"
        "原始 ASR 段落：\n"
        + "\n".join(lines)
    )


def mentioned_people_candidates(segments: list[dict], limit: int = 18) -> dict[str, list[str]]:
    return _mentioned_people(segments, limit=limit)


def _mentioned_people_notes(segments: list[dict], limit: int = 18) -> list[str]:
    people = _mentioned_people(segments, limit=limit)
    if not people:
        return []
    notes = []
    for name, snippets in people.items():
        context = "；".join(snippets[:2])
        notes.append(f"- {name}: {context}" if context else f"- {name}")
    return notes


def _mentioned_people(segments: list[dict], limit: int = 18) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}

    def add(name: str, snippet: str = "") -> None:
        name = _clean_person_name(name)
        if not name or name in found and snippet in found[name]:
            return
        if _is_invalid_person_name(name):
            return
        found.setdefault(name, [])
        if snippet:
            found[name].append(_compact_snippet(snippet))

    for segment in segments:
        speaker = str(segment.get("display_name") or segment.get("speaker_id") or "").strip()
        if speaker and not _is_invalid_person_name(speaker):
            add(speaker, "ASR/人工显示名")
        text = str(segment.get("text") or "")
        for pattern in _PERSON_PATTERNS:
            for match in pattern.finditer(text):
                name = next((group for group in match.groups() if group), "")
                add(name, _window(text, match.start(), match.end()))
                if len(found) >= limit:
                    return dict(found)
    return dict(found)


_PERSON_PATTERNS = [
    re.compile(
        r"(?:^|[\s，,。！？!?；;、])"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
        r"(?:你|您)(?:先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调|那|这)"
    ),
    re.compile(
        r"(?:^|[\s，,。！？!?；;、])"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
        r"(?:说|讲|提到|补充|确认|负责|跟进|准备|搞|做|处理|给|发|看|改|调)"
    ),
    re.compile(
        r"(?:^|[\s，,。！？!?；;、])"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
        r"(?:的)?(?:部分|那块|这块|那边|这边|那个部分|这个部分)"
    ),
    re.compile(
        r"(?:交给|让|找|通知|安排)"
        r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})"
        r"(?:来|去|做|处理|确认|跟进|负责|补|改|发)"
    ),
    re.compile(r"(?:^|[\n\r。！？!?；;])\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,5})\s*[:：]"),
]


_PERSON_STOPWORDS = {
    "ASR",
    "SPEAKER",
    "unknown",
    "待确认",
    "发言人",
    "负责人",
    "相关负责人",
    "主持人",
    "前端开发",
    "UI讨论者",
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
    "下周",
    "本周",
    "这个",
    "那个",
    "这些",
    "那些",
    "就是",
    "然后",
    "但是",
    "所以",
    "我们",
    "你们",
    "他们",
    "大家",
    "客户",
    "问题",
    "场景",
    "模型",
    "数据",
    "前端",
    "后端",
    "产品",
    "销售",
    "部门",
    "团队",
    "会议",
    "系统",
    "服务",
    "平台",
    "应用",
    "部署",
    "测试",
    "功能",
    "页面",
    "任务",
    "时间",
    "待办",
}


def _clean_person_name(name: str) -> str:
    value = re.sub(
        r"^[\s，,。！？!?；;、:：]+|[\s，,。！？!?；;、:：]+$",
        "",
        str(name or ""),
    )
    value = re.sub(
        r"(?:你|您|这边|那边|后面|先|再|来|把|帮|看|说|讲|分享|确认|负责|处理|弄|搞|发|补|改|调)+$",
        "",
        value,
    )
    value = re.sub(r"(?:要|需要|得|应该|必须)$", "", value)
    return value.strip()


def _is_invalid_person_name(name: str) -> bool:
    if not name or len(name) < 2 or len(name) > 8:
        return True
    lowered = name.lower()
    if lowered.startswith("speaker") or name.startswith("发言人"):
        return True
    if name in _PERSON_STOPWORDS:
        return True
    if any(word in name for word in ("部分", "负责", "相关", "这个", "那个")):
        return True
    if _looks_like_topic_or_time_phrase(name):
        return True
    return not re.search(r"[\u4e00-\u9fa5A-Za-z]", name)


def _looks_like_topic_or_time_phrase(name: str) -> bool:
    if not re.fullmatch(r"[\u4e00-\u9fa5]{3,8}", name):
        return False
    time_words = {
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
        "下周",
        "本周",
        "月底",
        "月初",
        "年前",
        "年后",
    }
    topic_words = {
        "物料",
        "名单",
        "客户",
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
        "质量",
        "一键",
        "部署",
        "截图",
        "下载",
    }
    return any(word in name for word in time_words) or any(
        word in name for word in topic_words
    )


def _window(text: str, start: int, end: int, radius: int = 34) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def _compact_snippet(text: str, limit: int = 72) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit]


def _parse_summary(content: str, segments: list[dict]) -> tuple[str, str, list[dict]]:
    payload = _extract_json(content)
    summary = str(payload.get("summary") or "").strip()
    role_notes = str(payload.get("role_notes") or "").strip()
    raw_actions = payload.get("action_items") or []
    actions: list[dict] = []
    if isinstance(raw_actions, list):
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            task = str(item.get("task") or "").strip()
            if not task:
                continue
            actions.append(
                {
                    "owner": _normalize_owner(str(item.get("owner") or "").strip()),
                    "task": task,
                    "due": str(item.get("due") or "").strip(),
                    "status": _normalize_action_status(item.get("status")),
                }
            )
    if not summary:
        summary = "模型已返回结果，但未给出明确纪要，请人工检查转写。"
    if not role_notes:
        role_notes = "\n".join(f"{item['display_name']}：{item['text']}" for item in segments)
    return summary, role_notes, actions


def _parse_refined_segments(content: str, original_segments: list[dict]) -> list[dict]:
    payload = _extract_json(content)
    raw_segments = payload.get("segments") or []
    if not isinstance(raw_segments, list):
        raise LlmAdapterError("LLM refined segments must be an array")
    refined: list[dict] = []
    for index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        fallback = _fallback_segment_for_refined_item(item, index, original_segments)
        speaker = str(item.get("speaker") or item.get("display_name") or "").strip()
        speaker_id = str(item.get("speaker_id") or "").strip()
        if not speaker:
            speaker = str(fallback.get("display_name") or fallback.get("speaker_id") or "待确认").strip()
        if not speaker_id:
            fallback_speaker_id = str(fallback.get("speaker_id") or "").strip()
            fallback_names = {
                str(fallback.get("display_name") or "").strip(),
                str(fallback.get("speaker") or "").strip(),
                fallback_speaker_id,
            }
            if fallback_speaker_id and speaker in {name for name in fallback_names if name}:
                speaker_id = fallback_speaker_id
            else:
                speaker_id = _speaker_id_from_name(speaker, fallback_speaker_id)
        start_ms = _int_value(item.get("start_ms"), fallback.get("start_ms", index * 1000))
        end_ms = _int_value(item.get("end_ms"), fallback.get("end_ms", start_ms + 1000))
        confidence = _float_value(item.get("confidence"), 0.65)
        flags = ["llm_refined"]
        invalid_speaker_name = _is_invalid_person_name(speaker)
        scenario = _scenario_value(item.get("scenario"))
        inferred_speaker = _speaker_differs_from_source(speaker, fallback)
        if (
            confidence < 0.75
            or speaker in {"待确认", "未知", "不确定"}
            or (inferred_speaker and scenario in {"context_bridge", "dialogue_logic", "task_ownership", "unknown"})
        ):
            flags.append("speaker_review")
        if inferred_speaker and scenario in {"context_bridge", "dialogue_logic", "task_ownership"}:
            confidence = min(confidence, 0.78)
        if invalid_speaker_name or not _speaker_supported_by_original(speaker, fallback, original_segments):
            confidence = min(confidence, 0.68)
            for flag in ("speaker_review", "speaker_evidence_weak"):
                if flag not in flags:
                    flags.append(flag)
        flags.append(f"scenario:{scenario}")
        reason = str(item.get("reason") or "").strip()
        if reason:
            flags.append(f"reason:{reason[:80]}")
        source_segment_no = _source_segment_no_for_refined_item(item, fallback)
        source_id = str(item.get("source_id") or fallback.get("source_id") or "").strip()
        refined.append(
            {
                "source_id": source_id,
                "speaker_id": speaker_id,
                "display_name": speaker,
                "source_segment_no": source_segment_no,
                "start_ms": max(0, start_ms),
                "end_ms": max(max(0, start_ms), end_ms),
                "text": text,
                "confidence": confidence,
                "flags": flags,
            }
        )
    if not refined:
        raise LlmAdapterError("LLM returned no refined transcript segments")
    return refined


def _fallback_segment_for_refined_item(
    item: dict,
    index: int,
    original_segments: list[dict],
) -> dict:
    if not original_segments:
        return {}
    source_index = _int_value(item.get("source_index") or item.get("index"), 0)
    indexed_segment = None
    if 1 <= source_index <= len(original_segments):
        indexed_segment = original_segments[source_index - 1]
    source_id = str(item.get("source_id") or "").strip()
    source_segment_no = _int_value(item.get("source_segment_no"), -1)
    start_ms = _int_value(item.get("start_ms"), -1)
    if source_id and source_segment_no >= 0:
        for segment in original_segments:
            if (
                str(segment.get("source_id") or "").strip() == source_id
                and _int_value(segment.get("source_segment_no"), -2) == source_segment_no
            ):
                return segment
    if source_id and start_ms >= 0:
        source_timeline_matches = [
            segment
            for segment in original_segments
            if str(segment.get("source_id") or "").strip() == source_id
            and _segment_contains_time(segment, start_ms)
        ]
        if len(source_timeline_matches) == 1:
            return source_timeline_matches[0]
    if source_id:
        source_matches = [
            segment
            for segment in original_segments
            if str(segment.get("source_id") or "").strip() == source_id
        ]
        if len(source_matches) == 1:
            return source_matches[0]
    if indexed_segment is not None:
        return indexed_segment
    if source_segment_no >= 0:
        segment_no_matches = [
            segment
            for segment in original_segments
            if _int_value(segment.get("source_segment_no"), -2) == source_segment_no
        ]
        if start_ms >= 0:
            timeline_matches = [
                segment
                for segment in segment_no_matches
                if _segment_contains_time(segment, start_ms)
            ]
            if len(timeline_matches) == 1:
                return timeline_matches[0]
        if len(segment_no_matches) == 1:
            return segment_no_matches[0]
    if start_ms >= 0:
        for segment in original_segments:
            if _segment_contains_time(segment, start_ms):
                return segment
    return original_segments[min(index, len(original_segments) - 1)]


def _segment_contains_time(segment: dict, start_ms: int) -> bool:
    segment_start = _int_value(segment.get("start_ms"), 0)
    segment_end = _int_value(segment.get("end_ms"), segment_start)
    return segment_start <= start_ms <= segment_end


def _source_segment_no_for_refined_item(item: dict, fallback: dict) -> int | None:
    raw = item.get("source_segment_no")
    if raw is not None and str(raw).strip() != "":
        value = _int_value(raw, -1)
        if value >= 0:
            return value
    raw = fallback.get("source_segment_no")
    if raw is not None and str(raw).strip() != "":
        value = _int_value(raw, -1)
        if value >= 0:
            return value
    return None


def _speaker_differs_from_source(speaker: str, fallback: dict) -> bool:
    speaker = str(speaker or "").strip()
    if not speaker:
        return False
    source_names = {
        str(fallback.get("display_name") or "").strip(),
        str(fallback.get("speaker") or "").strip(),
        str(fallback.get("speaker_id") or "").strip(),
    }
    return speaker not in {name for name in source_names if name}


def _scenario_value(value) -> str:
    scenario = str(value or "").strip()
    allowed = {
        "explicit_name",
        "context_bridge",
        "dialogue_logic",
        "task_ownership",
        "native_speaker",
        "unknown",
    }
    return scenario if scenario in allowed else "unknown"


def _normalize_owner(owner: str) -> str:
    lowered = owner.lower()
    if not owner or lowered in {
        "unknown",
        "n/a",
        "none",
        "null",
        "未明确",
        "不明确",
    } or _is_pronoun_owner(owner):
        return "待确认"
    return owner


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


def _speaker_supported_by_original(
    speaker: str,
    fallback: dict,
    original_segments: list[dict],
) -> bool:
    speaker = str(speaker or "").strip()
    if not speaker or speaker in {"待确认", "未知", "不确定"}:
        return True
    if _is_invalid_person_name(speaker):
        return True
    fallback_names = {
        str(fallback.get("display_name") or "").strip(),
        str(fallback.get("speaker") or "").strip(),
        str(fallback.get("speaker_id") or "").strip(),
    }
    if speaker in {name for name in fallback_names if name}:
        return True
    source_text = "\n".join(str(item.get("text") or "") for item in original_segments)
    if speaker and speaker in source_text:
        return True
    source_people = _mentioned_people(
        [
            {
                **item,
                "display_name": "",
                "speaker_id": "",
            }
            for item in original_segments
        ],
        limit=64,
    )
    return speaker in source_people


def _speaker_id_from_name(name: str, fallback: str | None = None) -> str:
    if fallback and name and name in {fallback, "待确认"}:
        return str(fallback)
    if not name or name == "待确认":
        return str(fallback or "SPEAKER_01")
    token = "".join(char for char in name if char.isalnum())
    if not token:
        return str(fallback or "SPEAKER_01")
    return f"MANUAL_{token[:24]}"


def _int_value(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default or 0)


def _float_value(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _extract_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end >= start:
        content = content[start : end + 1]
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmAdapterError("LLM response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LlmAdapterError("LLM response JSON must be an object")
    return payload


def _time(ms: int) -> str:
    seconds = max(0, int(ms / 1000))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def llm_options_from_settings_and_db(values: dict[str, str]) -> dict:
    settings = get_settings()
    return {
        "llm_provider": values.get("llm_provider", settings.llm_provider),
        "llm_endpoint": values.get("llm_endpoint", settings.llm_endpoint),
        "llm_api_key": values.get("llm_api_key", settings.llm_api_key),
        "llm_model": values.get("llm_model", settings.llm_model),
    }
