import importlib
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient


def make_client(tmp_path: Path) -> TestClient:
    os.environ["SOLO_DATA_DIR"] = str(tmp_path / "var")
    os.environ["SOLO_DATABASE_PATH"] = str(tmp_path / "var" / "test.db")
    os.environ["SOLO_STORAGE_DIR"] = str(tmp_path / "var" / "storage")
    os.environ["SOLO_APK_DIR"] = str(tmp_path / "var" / "apk")
    os.environ["SOLO_STATIC_DIR"] = str(Path(__file__).parents[1] / "static")
    os.environ["SOLO_SECRET_KEY"] = "test-secret"
    os.environ["SOLO_EXTERNAL_API_TOKENS"] = "hermes:test-token"
    os.environ["SOLO_SSO_ISSUER"] = "https://sso.example.com"
    os.environ["SOLO_SSO_CLIENT_ID"] = "solo-test"
    os.environ["SOLO_SSO_REDIRECT_URI"] = "https://record.example.com/api/auth/sso/callback"
    import solorecord_server.config as config
    import solorecord_server.db as db
    import solorecord_server.main as main

    config.get_settings.cache_clear()
    importlib.reload(db)
    importlib.reload(main)
    main.startup()
    return TestClient(main.app)


def login(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/demo-login",
        json={"display_name": "Admin", "email": "admin@example.com"},
    )
    assert response.status_code == 200
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


def login_user(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/demo-login",
        json={"display_name": "Sales", "email": "sales@example.com"},
    )
    assert response.status_code == 200
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


def test_full_user_story_permissions_sync_export_and_release(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    user_headers = login_user(client)

    assert client.get("/api/web/meetings").status_code == 401
    assert client.get("/api/admin/providers", headers=user_headers).status_code == 403
    assert client.get("/api/external/meetings", headers={"Authorization": "Bearer wrong-token"}).status_code == 401
    sso_app = client.get(
        "/api/auth/sso/start?redirect_after=solorecord://auth/callback",
        follow_redirects=False,
    )
    assert sso_app.status_code == 307
    app_state = parse_qs(urlparse(sso_app.headers["location"]).query)["state"][0]
    sso_bad = client.get(
        "/api/auth/sso/start?redirect_after=https://evil.example.com/steal",
        follow_redirects=False,
    )
    assert sso_bad.status_code == 307
    bad_state = parse_qs(urlparse(sso_bad.headers["location"]).query)["state"][0]
    import solorecord_server.db as db

    with db.get_db() as conn:
        app_redirect = conn.execute("SELECT redirect_after FROM sso_states WHERE state=?", (app_state,)).fetchone()
        bad_redirect = conn.execute("SELECT redirect_after FROM sso_states WHERE state=?", (bad_state,)).fetchone()
    assert app_redirect["redirect_after"] == "solorecord://auth/callback"
    assert bad_redirect["redirect_after"] == "/"

    create = client.post("/api/web/meetings", json={"title": "客户复盘会"}, headers=headers)
    assert create.status_code == 200
    meeting_id = create.json()["meeting"]["id"]
    assert create.json()["owner"]["display_name"] == "Admin"
    assert client.get(f"/api/web/meetings/{meeting_id}", headers=user_headers).status_code == 404

    upload = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments",
        headers=headers,
        data={"segment_no": "1", "start_ms": "0", "end_ms": "120000", "duration_ms": "120000"},
        files={"file": ("part_0001.m4a", b"fake audio data", "audio/mp4")},
    )
    assert upload.status_code == 200
    assert upload.json()["sizeBytes"] > 0
    audio_denied = client.get(f"/api/mobile/meetings/{meeting_id}/segments/1/audio", headers=user_headers)
    assert audio_denied.status_code == 404
    audio_download = client.get(f"/api/mobile/meetings/{meeting_id}/segments/1/audio", headers=headers)
    assert audio_download.status_code == 200
    assert audio_download.content == b"fake audio data"

    finish = client.post(f"/api/mobile/meetings/{meeting_id}/finish", headers=headers)
    assert finish.status_code == 200
    assert finish.json()["jobId"].startswith("job_")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    assert transcript.status_code == 200
    segments = transcript.json()["segments"]
    assert segments
    assert segments[0]["speaker_id"] == "SPEAKER_01"

    rename = client.post(
        f"/api/web/meetings/{meeting_id}/speakers/rename",
        headers=headers,
        json={"speaker_id": "SPEAKER_01", "display_name": "张三"},
    )
    assert rename.status_code == 200
    transcript_after = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert transcript_after["segments"][0]["display_name"] == "张三"

    update = client.patch(
        f"/api/web/meetings/{meeting_id}",
        headers=headers,
        json={"summary": "双方确认报价，下周推进合同。"},
    )
    assert update.status_code == 200
    assert update.json()["meeting"]["summary"] == "双方确认报价，下周推进合同。"

    provider_save = client.put(
        "/api/admin/providers",
        headers=headers,
        json={
            "asr_provider": "mock",
            "asr_command": "",
            "llm_provider": "openai-compatible",
            "llm_endpoint": "https://model.example.com/v1",
            "llm_api_key": "secret-llm-key",
            "llm_model": "qwen3",
            "hermes_webhook_url": "https://hermes.example.com/hook",
            "hermes_webhook_token": "secret-hermes-token",
            "es_enabled": False,
            "es_url": "",
            "es_index": "solorecord_meetings",
            "external_api_tokens": "hermes:test-token",
            "audio_segment_minutes": 5,
            "enable_diarization": True,
            "enable_denoise": False,
            "target_sample_rate": 16000,
        },
    )
    assert provider_save.status_code == 200
    provider_read = client.get("/api/admin/providers", headers=headers)
    assert provider_read.status_code == 200
    provider_config = provider_read.json()["config"]
    assert provider_config["llm_api_key_set"] is True
    assert "secret-llm-key" not in str(provider_config)
    assert provider_config["hermes_webhook_token_set"] is True
    assert "secret-hermes-token" not in str(provider_config)

    export = client.post(f"/api/web/meetings/{meeting_id}/exports?export_format=markdown", headers=headers)
    assert export.status_code == 200
    export_path = Path(export.json()["path"])
    assert export_path.exists()
    assert "客户复盘会" in export_path.read_text(encoding="utf-8")

    release = client.post(
        "/api/admin/releases",
        headers=headers,
        data={"version_name": "0.7.0", "version_code": "7", "release_notes": "V0.7", "force_update": "false"},
        files={"file": ("app.apk", b"fake apk", "application/vnd.android.package-archive")},
    )
    assert release.status_code == 200
    latest = client.get("/api/web/releases/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["release"]["version_name"] == "0.7.0"
    download = client.get("/downloads/android/0.7.0/app.apk")
    assert download.status_code == 200
    assert download.content == b"fake apk"

    sync = client.get("/api/mobile/sync", headers=headers)
    assert sync.status_code == 200
    assert sync.json()["user"]["display_name"] == "Admin"
    assert sync.json()["items"][0]["owner"]["display_name"] == "Admin"
    assert sync.json()["items"][0]["transcriptSegments"][0]["display_name"] == "张三"
    assert sync.json()["items"][0]["meeting"]["summary"] == "双方确认报价，下周推进合同。"

    external = client.get("/api/external/meetings", headers={"Authorization": "Bearer test-token"})
    assert external.status_code == 200
    assert external.json()["client"] == "hermes"
    assert external.json()["items"][0]["meeting"]["title"] == "客户复盘会"
