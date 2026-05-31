import argparse
import hashlib
import io
import json
import math
import struct
import sys
import time
import uuid
import wave
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SoloRecord HTTP smoke user story.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--external-token", default="test-token")
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--name", default="Smoke Admin")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--job-timeout", type=float, default=300)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    client = httpx.Client(base_url=base_url, timeout=args.timeout, follow_redirects=True, trust_env=False)

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

    audio_bytes = _valid_wav_bytes()
    upload = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments",
        data={
            "segment_no": "1",
            "start_ms": 0,
            "end_ms": 120000,
            "duration_ms": 120000,
        },
        files={"file": ("part_0001.wav", audio_bytes, "audio/wav")},
        headers=headers,
    )
    expect(upload, 200, "upload audio multipart")
    upload_payload = upload.json()
    assert upload_payload["sha256"] == hashlib.sha256(audio_bytes).hexdigest()
    assert upload_payload["partial"]["status"] in {"succeeded", "failed"}

    partial = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    expect(partial, 200, "partial transcript after first segment")
    if upload_payload["partial"]["status"] == "succeeded":
        assert len(partial.json()["segments"]) == 1, "expected first partial transcript"

    second_audio = _valid_wav_bytes(frequency=660)
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
    assert upload_second.json()["partial"]["status"] in {"succeeded", "failed"}
    partial_second = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    expect(partial_second, 200, "partial transcript after second segment")
    if upload_payload["partial"]["status"] == "succeeded" and upload_second.json()["partial"]["status"] == "succeeded":
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
    wait_for_job(client, headers, meeting_id, args.job_timeout)

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    expect(transcript, 200, "transcript")
    segments = transcript.json()["segments"]
    assert segments, "expected transcript evidence or traceable ASR placeholder"
    speaker_id = segments[0]["speaker_id"]

    rename = client.post(
        f"/api/web/meetings/{meeting_id}/speakers/rename",
        json={"speaker_id": speaker_id, "display_name": "Smoke Speaker"},
        headers=headers,
    )
    expect(rename, 200, "speaker rename")

    actions = client.put(
        f"/api/web/meetings/{meeting_id}/actions",
        json={
            "items": [
                {"owner": "Smoke Speaker", "task": "Review meeting notes", "due": "", "status": "open"},
                {"owner": "Ops", "task": "Verify deployment package", "due": "Monday", "status": "doing"},
            ]
        },
        headers=headers,
    )
    expect(actions, 200, "edit action items")
    assert len(actions.json()["actionItems"]) == 2

    sync = client.get("/api/mobile/sync", headers=headers)
    expect(sync, 200, "mobile sync")
    assert sync.json()["items"], "expected sync items"
    assert sync.json()["items"][0]["transcriptSegments"][0]["display_name"] == "Smoke Speaker"
    assert sync.json()["items"][0]["actionItems"][0]["task"] == "Review meeting notes"

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

    smoke_run_id = uuid.uuid4().hex[:8].upper()
    multi = _run_multi_source_story(client, headers, smoke_run_id, args.external_token, args.job_timeout)

    print(
        json.dumps(
            {
                "ok": True,
                "meeting_id": meeting_id,
                "multi_source_meeting_id": multi["meeting_id"],
                "base_url": base_url,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _valid_wav_bytes(frequency: int = 440) -> bytes:
    buffer = io.BytesIO()
    sample_rate = 16000
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = []
        for index in range(sample_rate):
            sample = int(1200 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.append(struct.pack("<h", sample))
        wav.writeframes(b"".join(frames))
    return buffer.getvalue()


def _run_multi_source_story(
    client: httpx.Client,
    owner_headers: dict[str, str],
    run_id: str,
    external_token: str,
    job_timeout: float,
) -> dict:
    join_code = f"SMK{run_id}"
    user_login = client.post(
        "/api/auth/demo-login",
        json={"display_name": "Smoke Source B", "email": "source-b@example.com"},
    )
    expect(user_login, 200, "multi-source second user login")
    user_headers = {"Authorization": f"Bearer {user_login.json()['access_token']}"}

    create = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "Smoke Multi Source Meeting",
            "join_code": join_code,
            "recording_mode": "multi_source",
            "max_sources": 3,
            "source_label": "front recorder",
        },
    )
    expect(create, 200, "multi-source create")
    meeting_id = create.json()["meeting"]["id"]

    discover = client.get(f"/api/web/meetings/discover?q={join_code}", headers=user_headers)
    expect(discover, 200, "multi-source discover")
    discover_items = discover.json()["items"]
    assert len(discover_items) == 1, "expected one joinable multi-source meeting"
    discover_item = discover_items[0]
    assert discover_item["join_code"] == join_code
    assert discover_item["source_count"] == 1
    assert discover_item["remaining_sources"] == 2
    for hidden_key in ("summary", "role_notes", "transcriptSegments", "audioSegments", "actionItems"):
        assert hidden_key not in discover_item, f"discover leaked {hidden_key}"

    join = client.post(
        "/api/web/meetings/join",
        headers=user_headers,
        json={
            "join_code": join_code,
            "source_label": "back recorder",
            "device_name": "smoke device",
        },
    )
    expect(join, 200, "multi-source join")
    source_id = join.json()["joinedSource"]["source_id"]

    first_audio = _valid_wav_bytes(frequency=330)
    upload_first = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments",
        data={
            "segment_no": "1",
            "source_id": "primary",
            "source_segment_no": "1",
            "start_ms": "0",
            "end_ms": "60000",
            "duration_ms": "60000",
        },
        files={"file": ("front_0001.wav", first_audio, "audio/wav")},
        headers=owner_headers,
    )
    expect(upload_first, 200, "multi-source upload first source")

    second_audio = _valid_wav_bytes(frequency=550)
    upload_second = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments",
        data={
            "segment_no": "1",
            "source_id": source_id,
            "source_segment_no": "1",
            "start_ms": "0",
            "end_ms": "60000",
            "duration_ms": "60000",
        },
        files={"file": ("back_0001.wav", second_audio, "audio/wav")},
        headers=user_headers,
    )
    expect(upload_second, 200, "multi-source upload second source")
    assert upload_first.json()["segmentNo"] != upload_second.json()["segmentNo"]
    assert upload_second.json()["sourceSegmentNo"] == 1

    finish = client.post(f"/api/mobile/meetings/{meeting_id}/finish", headers=owner_headers)
    expect(finish, 200, "multi-source finish")
    wait_for_job(client, owner_headers, meeting_id, job_timeout)

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=owner_headers)
    expect(detail, 200, "multi-source detail")
    payload = detail.json()
    assert len(payload["recordingSources"]) == 2, "expected two recording sources"
    assert len(payload["audioSegments"]) == 2, "expected two audio segments"
    assert payload["qualityReport"]["metrics"]["recording_source_count"] == 2

    external = client.get(
        f"/api/external/meetings/{meeting_id}/transcript?include_history=true",
        headers={"Authorization": f"Bearer {external_token}"},
    )
    expect(external, 200, "multi-source external transcript")
    transcript = external.json()["transcript"]
    assert transcript["segments"], "expected multi-source transcript rows"
    assert all("source_id" in item for item in transcript["segments"])
    return {"meeting_id": meeting_id, "source_id": source_id}


def expect(response: httpx.Response, status_code: int, label: str) -> None:
    if response.status_code != status_code:
        raise AssertionError(f"{label}: expected HTTP {status_code}, got {response.status_code}: {response.text[:500]}")


def wait_for_job(
    client: httpx.Client,
    headers: dict[str, str],
    meeting_id: str,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/web/meetings/{meeting_id}/status", headers=headers)
        expect(response, 200, "meeting job status")
        last_payload = response.json()
        job = last_payload.get("job") or {}
        status = job.get("status")
        if status in {"succeeded", "succeeded_with_publish_warning"}:
            return
        if status == "failed":
            raise AssertionError(f"job failed: {job.get('error_message') or job}")
        time.sleep(2)
    raise AssertionError(f"job did not finish within {timeout_seconds}s: {last_payload}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        raise
