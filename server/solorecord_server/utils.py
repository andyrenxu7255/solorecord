import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(16)}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_existing_file(path_value: str | Path | None) -> Path | None:
    if not path_value:
        return None
    raw = Path(path_value)
    candidates: list[Path] = [raw] if raw.is_absolute() else [Path.cwd() / raw, raw]
    if not raw.is_absolute():
        from .config import get_settings

        settings = get_settings()
        candidates.extend(
            [
                settings.data_dir.parent / raw,
                settings.storage_dir.parent.parent / raw,
            ]
        )
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def row_to_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
