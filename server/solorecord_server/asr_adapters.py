import json
import shlex
import subprocess
from pathlib import Path

import httpx

from .config import get_settings


class AsrAdapterError(RuntimeError):
    pass


def transcribe_with_openai_compatible(
    endpoint: str,
    api_key: str,
    model: str,
    audio_paths: list[str],
) -> list[dict]:
    base = endpoint.rstrip("/")
    if not base or not model:
        raise AsrAdapterError("ASR endpoint/model is missing")
    existing_paths = [Path(path) for path in audio_paths if Path(path).exists()]
    if not existing_paths:
        raise AsrAdapterError("No uploaded audio files are available for ASR")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    segments: list[dict] = []
    cursor_ms = 0
    for path in existing_paths:
        result = _post_transcription(base, headers, model, path)
        parsed = _segments_from_remote_result(result, cursor_ms)
        if parsed:
            segments.extend(parsed)
            cursor_ms = max(cursor_ms, max(item["end_ms"] for item in parsed))
        else:
            segments.append(
                {
                    "speaker_id": "SPEAKER_01",
                    "display_name": "发言人 1",
                    "start_ms": cursor_ms,
                    "end_ms": cursor_ms + 1000,
                    "text": f"音频分段 {path.name} 未识别到有效语音，请人工确认录音内容。",
                    "confidence": 0.0,
                    "flags": ["empty_asr"],
                }
            )
            cursor_ms += 1000
    if not segments:
        raise AsrAdapterError("ASR service returned no transcript text")
    return segments


def transcribe_with_command(
    command_template: str,
    audio_paths: list[str],
    meeting_id: str,
    options: dict,
) -> list[dict]:
    if not command_template.strip():
        raise AsrAdapterError("ASR command is empty")
    existing_paths = [str(Path(path)) for path in audio_paths if Path(path).exists()]
    if not existing_paths:
        raise AsrAdapterError("No uploaded audio files are available for ASR")
    command = _render_command(command_template, existing_paths, meeting_id, options)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=get_settings().asr_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise AsrAdapterError("ASR command timed out") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise AsrAdapterError(f"ASR command failed: {message[:1000]}")
    return _parse_segments(completed.stdout)


def _post_transcription(base: str, headers: dict[str, str], model: str, path: Path) -> dict:
    url = f"{base}/audio/transcriptions"
    is_funasr = "funasr" in model.lower() or "paraformer" in model.lower()
    data = {
        "model": model,
        "response_format": "json",
        "timestamp_granularities[]": "segment",
    }
    if is_funasr:
        data.update(
            {
                "vad": "true",
                "punc": "true",
                "diarization": "true",
                "speaker_diarization": "true",
                "spk_model": "cam++",
            }
        )
    try:
        with path.open("rb") as audio:
            files = {"file": (path.name, audio, "application/octet-stream")}
            with httpx.Client(timeout=get_settings().asr_timeout_seconds) as client:
                response = client.post(url, headers=headers, data=data, files=files)
        if response.status_code == 404:
            with path.open("rb") as audio:
                files = {"audio": (path.name, audio, "application/octet-stream")}
                with httpx.Client(timeout=get_settings().asr_timeout_seconds) as client:
                    response = client.post(f"{base}/asr", headers=headers, data=data, files=files)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AsrAdapterError(f"ASR HTTP request failed: {exc}") from exc
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise AsrAdapterError("ASR HTTP response must be JSON") from exc
    if not isinstance(payload, dict):
        raise AsrAdapterError("ASR HTTP response JSON must be an object")
    if is_funasr and not _payload_has_rich_segments(payload):
        native_payload = _post_funasr_native_transcription(base, headers, path)
        if native_payload and _payload_has_rich_segments(native_payload):
            return native_payload
    return payload


def _post_funasr_native_transcription(base: str, headers: dict[str, str], path: Path) -> dict | None:
    candidates = [f"{base}/asr/transcribe"]
    if not base.rstrip("/").endswith("/v1"):
        candidates.append(f"{base}/v1/asr/transcribe")
    for url in candidates:
        try:
            with path.open("rb") as audio:
                files = {"file": (path.name, audio, "application/octet-stream")}
                data = {"return_raw": "true"}
                with httpx.Client(timeout=get_settings().asr_timeout_seconds) as client:
                    response = client.post(url, headers=headers, data=data, files=files)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _payload_has_rich_segments(payload: dict) -> bool:
    for key in ("segments", "sentence_info", "sentences", "result"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            text = str(
                item.get("text")
                or item.get("sentence")
                or item.get("onebest")
                or item.get("value")
                or ""
            ).strip()
            has_time = any(time_key in item for time_key in ("start", "end", "start_ms", "end_ms"))
            has_speaker = any(
                speaker_key in item
                for speaker_key in ("spk", "spk_id", "speaker", "speaker_id", "speakerLabel")
            )
            if text and (has_time or has_speaker):
                return True
    return False


def _segments_from_remote_result(payload: dict, offset_ms: int) -> list[dict]:
    if isinstance(payload.get("segments"), list):
        return _normalize_segments(payload["segments"], offset_ms)
    if isinstance(payload.get("sentence_info"), list):
        return _normalize_segments(payload["sentence_info"], offset_ms)
    if isinstance(payload.get("sentences"), list):
        return _normalize_segments(payload["sentences"], offset_ms)
    if isinstance(payload.get("result"), list):
        return _normalize_segments(payload["result"], offset_ms)
    text = str(
        payload.get("text")
        or payload.get("transcript")
        or payload.get("result")
        or payload.get("data")
        or ""
    ).strip()
    if not text:
        return []
    return [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "start_ms": offset_ms,
            "end_ms": offset_ms + 1000,
            "text": text,
            "confidence": payload.get("confidence"),
            "flags": [],
        }
    ]


def _normalize_segments(raw_segments: list, offset_ms: int) -> list[dict]:
    normalized: list[dict] = []
    for index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            continue
        text = str(
            item.get("text")
            or item.get("sentence")
            or item.get("onebest")
            or item.get("value")
            or ""
        ).strip()
        if not text:
            continue
        speaker = (
            item.get("speaker_id")
            or item.get("speaker")
            or item.get("spk")
            or item.get("spk_id")
            or item.get("speakerLabel")
            or "SPEAKER_01"
        )
        speaker_id = _normalize_speaker_id(speaker)
        start_ms = offset_ms + _millis(item, "start_ms", "startMillis", "start", default=index * 1000)
        end_ms = offset_ms + _millis(item, "end_ms", "endMillis", "end", default=start_ms + 1000 - offset_ms)
        flags = item.get("flags", [])
        if not isinstance(flags, list):
            flags = [str(flags)]
        if any(key in item for key in ("spk", "spk_id", "speaker", "speaker_id", "speakerLabel")):
            flags = [*flags, "asr_speaker", "scenario:native_speaker"]
        normalized.append(
            {
                "speaker_id": speaker_id or "SPEAKER_01",
                "display_name": str(item.get("display_name") or item.get("speaker_name") or speaker_id or "发言人 1"),
                "start_ms": max(0, start_ms),
                "end_ms": max(max(0, start_ms), end_ms),
                "text": text,
                "confidence": item.get("confidence"),
                "flags": flags,
            }
        )
    return normalized


def _render_command(command_template: str, audio_paths: list[str], meeting_id: str, options: dict) -> list[str]:
    context = {
        "audio": audio_paths[0],
        "audio_json": json.dumps(audio_paths, ensure_ascii=False),
        "audios": " ".join(audio_paths),
        "meeting_id": meeting_id,
        "sample_rate": str(options.get("target_sample_rate", 16000)),
        "diarization": "true" if options.get("enable_diarization", True) else "false",
        "denoise": "true" if options.get("enable_denoise", False) else "false",
    }
    try:
        rendered = command_template.format(**context)
    except KeyError as exc:
        raise AsrAdapterError(f"Unknown ASR command placeholder: {exc}") from exc
    return shlex.split(rendered, posix=False)


def _parse_segments(output: str) -> list[dict]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise AsrAdapterError("ASR command must print JSON to stdout") from exc
    raw_segments = data.get("segments", data) if isinstance(data, dict) else data
    if not isinstance(raw_segments, list):
        raise AsrAdapterError("ASR JSON must be a list or an object with a segments list")
    segments: list[dict] = []
    for index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        speaker_id = _normalize_speaker_id(item.get("speaker_id") or item.get("speaker") or item.get("spk") or "SPEAKER_01")
        display_name = str(item.get("display_name") or item.get("speaker_name") or speaker_id).strip()
        start_ms = _millis(item, "start_ms", "startMillis", "start", default=index * 1000)
        end_ms = _millis(item, "end_ms", "endMillis", "end", default=start_ms + 1000)
        segments.append(
            {
                "speaker_id": speaker_id or "SPEAKER_01",
                "display_name": display_name or speaker_id or "SPEAKER_01",
                "start_ms": max(0, start_ms),
                "end_ms": max(max(0, start_ms), end_ms),
                "text": text,
                "confidence": item.get("confidence"),
                "flags": item.get("flags", []),
            }
        )
    if not segments:
        raise AsrAdapterError("ASR command returned no transcript segments")
    return segments


def _millis(item: dict, *keys: str, default: int) -> int:
    for key in keys:
        if key not in item:
            continue
        value = item[key]
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return int(number * 1000) if key in {"start", "end"} and number < 100_000 else int(number)
    return default


def _normalize_speaker_id(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "SPEAKER_01"
    if text.upper().startswith("SPEAKER_"):
        return text.upper()
    if text.lower().startswith("spk"):
        suffix = "".join(char for char in text if char.isdigit())
        if suffix:
            return f"SPEAKER_{int(suffix) + 1:02d}"
    if text.isdigit():
        return f"SPEAKER_{int(text) + 1:02d}"
    return text
