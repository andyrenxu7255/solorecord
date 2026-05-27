import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SoloRecord HTTP smoke user story.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--external-token", default="test-token")
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--name", default="Smoke Admin")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    client = httpx.Client(base_url=base_url, timeout=30, follow_redirects=True, trust_env=False)

    health = client.get("/api/health")
    expect(health, 200, "health")

    web_home = client.get("/")
    expect(web_home, 200, "web home")
    assert "SoloRecord" in web_home.text

    unauthorized = client.get("/api/web/meetings")
    expect(unauthorized, 401, "anonymous meetings rejected")

    login = client.post(
        "/api/auth/demo-login",
        json={"display_name": args.name, "email": args.email},
    )
    expect(login, 200, "demo login")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    meeting = client.post("/api/web/meetings", json={"title": "Smoke E2E Meeting"}, headers=headers)
    expect(meeting, 200, "create meeting")
    meeting_id = meeting.json()["meeting"]["id"]

    audio_bytes = b"solo smoke audio"
    upload = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments-json",
        json={
            "segment_no": 1,
            "file_name": "part_0001.m4a",
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "start_ms": 0,
            "end_ms": 120000,
            "duration_ms": 120000,
        },
        headers=headers,
    )
    expect(upload, 200, "upload audio json")
    assert upload.json()["sha256"] == hashlib.sha256(audio_bytes).hexdigest()

    audio = client.get(f"/api/mobile/meetings/{meeting_id}/segments/1/audio", headers=headers)
    expect(audio, 200, "audio download")
    assert audio.content == audio_bytes

    finish = client.post(f"/api/mobile/meetings/{meeting_id}/finish", headers=headers)
    expect(finish, 200, "finish and process")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    expect(transcript, 200, "transcript")
    segments = transcript.json()["segments"]
    assert segments, "expected transcript segments"
    speaker_id = segments[0]["speaker_id"]

    rename = client.post(
        f"/api/web/meetings/{meeting_id}/speakers/rename",
        json={"speaker_id": speaker_id, "display_name": "Smoke Speaker"},
        headers=headers,
    )
    expect(rename, 200, "speaker rename")

    sync = client.get("/api/mobile/sync", headers=headers)
    expect(sync, 200, "mobile sync")
    assert sync.json()["items"], "expected sync items"
    assert sync.json()["items"][0]["transcriptSegments"][0]["display_name"] == "Smoke Speaker"

    export = client.post(f"/api/web/meetings/{meeting_id}/exports?export_format=markdown", headers=headers)
    expect(export, 200, "markdown export")

    release = client.post(
        "/api/admin/releases",
        data={
            "version_name": "9.9.9-smoke",
            "version_code": "9999",
            "release_notes": "smoke",
            "force_update": "false",
        },
        files={"file": ("app.apk", b"fake apk", "application/vnd.android.package-archive")},
        headers=headers,
    )
    expect(release, 200, "release upload")

    latest = client.get("/api/web/releases/latest", headers=headers)
    expect(latest, 200, "latest release")
    download_url = latest.json()["release"]["downloadUrl"]
    downloaded = client.get(download_url)
    expect(downloaded, 200, "apk download")
    assert downloaded.content == b"fake apk"

    external_bad = client.get("/api/external/meetings", headers={"Authorization": "Bearer wrong-token"})
    expect(external_bad, 401, "external bad token rejected")

    external = client.get("/api/external/meetings", headers={"Authorization": f"Bearer {args.external_token}"})
    expect(external, 200, "external meetings")
    assert external.json()["items"], "expected external meeting items"

    print(json.dumps({"ok": True, "meeting_id": meeting_id, "base_url": base_url}, ensure_ascii=False))
    return 0


def expect(response: httpx.Response, status_code: int, label: str) -> None:
    if response.status_code != status_code:
        raise AssertionError(f"{label}: expected HTTP {status_code}, got {response.status_code}: {response.text[:500]}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        raise
