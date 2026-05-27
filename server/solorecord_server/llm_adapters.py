import json

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
        "如果信息不明确，owner 写待确认，status 写 open。"
    )


def _user_prompt(segments: list[dict]) -> str:
    lines = []
    for segment in segments:
        lines.append(
            f"[{_time(segment.get('start_ms', 0))}] "
            f"{segment.get('display_name') or segment.get('speaker_id')}: {segment.get('text', '')}"
        )
    return "请整理以下会议转写，输出中文 JSON：\n" + "\n".join(lines)


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
                    "owner": str(item.get("owner") or "待确认").strip(),
                    "task": task,
                    "due": str(item.get("due") or "").strip(),
                    "status": str(item.get("status") or "open").strip(),
                }
            )
    if not summary:
        summary = "模型已返回结果，但未给出明确纪要，请人工检查转写。"
    if not role_notes:
        role_notes = "\n".join(f"{item['display_name']}：{item['text']}" for item in segments)
    return summary, role_notes, actions


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
