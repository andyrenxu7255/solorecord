import json
import shlex
import subprocess
from pathlib import Path

from .config import get_settings


class AsrAdapterError(RuntimeError):
    pass


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
        speaker_id = str(item.get("speaker_id") or item.get("speaker") or "SPEAKER_01").strip()
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
