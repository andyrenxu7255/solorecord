import argparse
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
        f"/api/mobile/meetings/{meeting_id}/segments",
        data={
            "segment_no": "1",
            "start_ms": 0,
            "end_ms": 120000,
            "duration_ms": 120000,
        },
        files={"file": ("part_0001.m4a", audio_bytes, "audio/mp4")},
        headers=headers,
    )
    expect(upload, 200, "upload audio multipart")
    upload_payload = upload.json()
    assert upload_payload["sha256"] == hashlib.sha256(audio_bytes).hexdigest()
    assert upload_payload["partial"]["status"] == "succeeded"

    partial = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    expect(partial, 200, "partial transcript after first segment")
    assert len(partial.json()["segments"]) == 1, "expected first partial transcript"

    second_audio = b"solo smoke audio second segment"
    upload_second = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments",
        data={
            "segment_no": "2",
            "start_ms": 118000,
            "end_ms": 240000,
            "duration_ms": 122000,
        },
        files={"file": ("part_0002.wav", second_audio, "audio/wav")},
        headers=headers,
    )
    expect(upload_second, 200, "upload second overlapped segment")
    assert upload_second.json()["partial"]["status"] == "succeeded"
    partial_second = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    expect(partial_second, 200, "partial transcript after second segment")
    starts = [item["start_ms"] for item in partial_second.json()["segments"]]
    assert starts == [0, 118000], f"expected overlapped segment starts, got {starts}"

    audio = client.get(f"/api/mobile/meetings/{meeting_id}/segments/1/audio", headers=headers)
    expect(audio, 200, "audio download")
    assert audio.content == audio_bytes
    audio_second = client.get(f"/api/mobile/meetings/{meeting_id}/segments/2/audio", headers=headers)
    expect(audio_second, 200, "second audio download")
    assert audio_second.content == second_audio

    finish = client.post(f"/api/mobile/meetings/{meeting_id}/finish", headers=headers)
    expect(finish, 200, "finish and process")
    finish_payload = finish.json()
    retry_finish = client.post(f"/api/mobile/meetings/{meeting_id}/finish", headers=headers)
    expect(retry_finish, 200, "finish retry reuses job")
    assert retry_finish.json()["jobId"] == finish_payload["jobId"]
    assert retry_finish.json()["reused"] is True

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    expect(transcript, 200, "transcript")
    segments = transcript.json()["segments"]
    assert len(segments) == 2, "expected both transcript segments"
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
            "platform": "android",
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

    windows_release = client.post(
        "/api/admin/releases",
        data={
            "platform": "windows",
            "version_name": "9.9.9-smoke",
            "version_code": "9999",
            "release_notes": "windows smoke",
            "force_update": "false",
        },
        files={"file": ("SoloRecord-Setup.exe", b"fake exe", "application/vnd.microsoft.portable-executable")},
        headers=headers,
    )
    expect(windows_release, 200, "windows release upload")
    windows_latest = client.get("/api/web/releases/latest?platform=windows", headers=headers)
    expect(windows_latest, 200, "latest windows release")
    windows_download = client.get(windows_latest.json()["release"]["downloadUrl"])
    expect(windows_download, 200, "windows exe download")
    assert windows_download.content == b"fake exe"

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
