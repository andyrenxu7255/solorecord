import importlib
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from fastapi.testclient import TestClient


LDAP_ENV_KEYS = [
    "SOLO_LDAP_ENABLED",
    "SOLO_LDAP_SERVER",
    "SOLO_LDAP_BIND_DN_TEMPLATE",
    "SOLO_LDAP_LOOKUP_BIND_DN",
    "SOLO_LDAP_LOOKUP_BIND_PASSWORD",
    "SOLO_LDAP_SEARCH_DN",
    "SOLO_LDAP_SEARCH_FILTER",
    "SOLO_LDAP_USERNAME_KEY",
    "SOLO_LDAP_EMAIL_KEY",
    "SOLO_LDAP_EMAIL_POSTFIX",
    "SOLO_LDAP_DISPLAY_NAME_KEY",
    "SOLO_LDAP_ADMIN_USERS",
    "SOLO_LDAP_ADMIN_GROUP_DN",
    "SOLO_LDAP_DEFAULT_ROLE",
    "SOLO_LDAP_TLS_VALIDATE",
    "SOLO_LDAP_TIMEOUT_SECONDS",
]


def make_client(tmp_path: Path, clear_ldap: bool = True) -> TestClient:
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
    if clear_ldap:
        for key in LDAP_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["SOLO_LDAP_ENABLED"] = "false"
    import solorecord_server.config as config
    import solorecord_server.db as db
    import solorecord_server.main as main

    config.get_settings.cache_clear()
    importlib.reload(db)
    importlib.reload(main)
    main.startup()
    return TestClient(main.app)


def make_ldap_client(tmp_path: Path) -> TestClient:
    os.environ["SOLO_LDAP_ENABLED"] = "true"
    os.environ["SOLO_LDAP_SERVER"] = "ldaps://ldap.example.com:636"
    os.environ["SOLO_LDAP_BIND_DN_TEMPLATE"] = "uid=XXX,cn=users,dc=example,dc=com"
    os.environ["SOLO_LDAP_SEARCH_DN"] = "cn=users,dc=example,dc=com"
    os.environ["SOLO_LDAP_SEARCH_FILTER"] = "(cn={username})"
    os.environ["SOLO_LDAP_USERNAME_KEY"] = "cn"
    os.environ["SOLO_LDAP_EMAIL_KEY"] = "mail"
    os.environ["SOLO_LDAP_DISPLAY_NAME_KEY"] = "displayName"
    os.environ["SOLO_LDAP_ADMIN_USERS"] = "alice"
    return make_client(tmp_path, clear_ldap=False)


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


def test_ldap_login_uses_server_side_bind_and_session(tmp_path: Path) -> None:
    client = make_ldap_client(tmp_path)
    with patch("solorecord_server.auth._ldap_fetch_user") as fetch_user:
        fetch_user.return_value = (
            "uid=alice,cn=users,dc=example,dc=com",
            {
                "cn": ["alice"],
                "mail": ["alice@example.com"],
                "displayName": ["任旭"],
                "memberOf": [],
            },
        )
        response = client.post(
            "/api/auth/ldap-login",
            json={"username": "alice", "password": "test-password"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["user"]["display_name"] == "任旭"
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["role"] == "admin"
    fetch_user.assert_called_once_with(
        "alice",
        "uid=alice,cn=users,dc=example,dc=com",
        "test-password",
    )
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/api/web/me", headers=headers).json()["user"]["display_name"] == "任旭"


def test_ldap_login_can_be_disabled(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/api/auth/ldap-login",
        json={"username": "alice", "password": "test-password"},
    )
    assert response.status_code == 400


def test_ldap_login_escapes_dn_and_filter_input(tmp_path: Path) -> None:
    client = make_ldap_client(tmp_path)
    with patch("solorecord_server.auth._ldap_fetch_user") as fetch_user:
        fetch_user.return_value = (
            r"uid=alice*\,(),cn=users,dc=example,dc=com",
            {"cn": ["alice*"], "mail": [], "displayName": []},
        )
        response = client.post(
            "/api/auth/ldap-login",
            json={"username": r"alice*,()", "password": "test-password"},
        )
    assert response.status_code == 200
    fetch_user.assert_called_once_with(
        r"alice*,()",
        r"uid=alice*\,(),cn=users,dc=example,dc=com",
        "test-password",
    )
    import solorecord_server.auth as auth

    assert auth._ldap_search_filter(r"alice*,()") == r"(cn=alice\2a,\28\29)"


def test_ldap_search_filter_accepts_field_name_and_filter_fragment(tmp_path: Path) -> None:
    client = make_ldap_client(tmp_path)
    assert client.get("/api/health").status_code == 200
    import solorecord_server.auth as auth
    import solorecord_server.config as config

    settings = config.get_settings()
    original_filter = settings.ldap_search_filter
    try:
        settings.ldap_search_filter = "cn"
        assert auth._ldap_search_filter("alice") == "(cn=alice)"
        settings.ldap_search_filter = "&(objectClass=user)(cn=%s)"
        assert auth._ldap_search_filter("alice") == "(&(objectClass=user)(cn=alice))"
    finally:
        settings.ldap_search_filter = original_filter


def test_ldap_email_postfix_fills_missing_mail_attribute(tmp_path: Path) -> None:
    client = make_ldap_client(tmp_path)
    import solorecord_server.auth as auth
    import solorecord_server.config as config

    settings = config.get_settings()
    original_postfix = settings.ldap_email_postfix
    try:
        settings.ldap_email_postfix = "example.com"
        assert auth._ldap_email("alice", {"mail": []}) == "alice@example.com"
        assert auth._ldap_email("alice", {"mail": ["alice"]}) == "alice@example.com"
        assert auth._ldap_email("alice", {"mail": ["alice@corp.example"]}) == "alice@corp.example"
    finally:
        settings.ldap_email_postfix = original_postfix


def test_ldap_lookup_bind_mode_uses_found_dn(tmp_path: Path) -> None:
    client = make_ldap_client(tmp_path)
    import solorecord_server.auth as auth
    import solorecord_server.config as config

    settings = config.get_settings()
    original_lookup_dn = settings.ldap_lookup_bind_dn
    original_lookup_password = settings.ldap_lookup_bind_password
    try:
        settings.ldap_lookup_bind_dn = "uid=lookup,cn=users,dc=example,dc=com"
        settings.ldap_lookup_bind_password = "lookup-password"
        with patch("solorecord_server.auth._ldap_lookup_user") as lookup_user, patch(
            "solorecord_server.auth._ldap_bind_credentials"
        ) as bind_credentials:
            lookup_user.return_value = (
                "uid=alice,cn=users,dc=example,dc=com",
                {"cn": ["alice"], "mail": ["alice@example.com"]},
            )
            user_dn, attrs = auth._ldap_fetch_user(
                "alice",
                "uid=alice-template,cn=users,dc=example,dc=com",
                "user-password",
            )
        assert user_dn == "uid=alice,cn=users,dc=example,dc=com"
        assert attrs["cn"] == ["alice"]
        bind_credentials.assert_called_once_with(
            "uid=alice,cn=users,dc=example,dc=com",
            "user-password",
        )
    finally:
        settings.ldap_lookup_bind_dn = original_lookup_dn
        settings.ldap_lookup_bind_password = original_lookup_password


def test_remote_stt_adapter_normalizes_text_response(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    import solorecord_server.asr_adapters as asr_adapters

    audio = tmp_path / "sample.m4a"
    audio.write_bytes(b"fake audio")
    with patch("httpx.Client.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"text": "这是远程 STT 返回的文本"}
        post.return_value.raise_for_status.return_value = None
        segments = asr_adapters.transcribe_with_openai_compatible(
            "http://asr.example.com/v1",
            "test-key",
            "funasr-paraformer-zh",
            [str(audio)],
        )
    assert segments[0]["text"] == "这是远程 STT 返回的文本"
    assert post.call_args.kwargs["data"]["model"] == "funasr-paraformer-zh"


def test_remote_stt_adapter_keeps_empty_audio_traceable(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    import solorecord_server.asr_adapters as asr_adapters

    audio = tmp_path / "empty.wav"
    audio.write_bytes(b"fake audio")
    with patch("httpx.Client.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"text": ""}
        post.return_value.raise_for_status.return_value = None
        segments = asr_adapters.transcribe_with_openai_compatible(
            "http://asr.example.com/v1",
            "test-key",
            "funasr-paraformer-zh",
            [str(audio)],
        )
    assert segments[0]["flags"] == ["empty_asr"]
    assert "未识别到有效语音" in segments[0]["text"]


def test_release_schema_migrates_existing_apk_table(tmp_path: Path) -> None:
    os.environ["SOLO_DATA_DIR"] = str(tmp_path / "var")
    os.environ["SOLO_DATABASE_PATH"] = str(tmp_path / "var" / "legacy.db")
    os.environ["SOLO_STORAGE_DIR"] = str(tmp_path / "var" / "storage")
    os.environ["SOLO_APK_DIR"] = str(tmp_path / "var" / "apk")
    os.environ["SOLO_STATIC_DIR"] = str(Path(__file__).parents[1] / "static")
    import sqlite3
    import solorecord_server.config as config
    import solorecord_server.db as db

    config.get_settings.cache_clear()
    legacy_path = tmp_path / "var" / "legacy.db"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(legacy_path) as conn:
        conn.execute(
            """
            CREATE TABLE apk_releases (
                id TEXT PRIMARY KEY,
                version_name TEXT NOT NULL,
                version_code INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                release_notes TEXT NOT NULL DEFAULT '',
                force_update INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
    db.init_db()
    with db.get_db() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(apk_releases)").fetchall()}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(apk_releases)").fetchall()}
    assert "platform" in columns
    assert "content_type" in columns
    assert "idx_apk_releases_platform_version" in indexes


def test_full_user_story_permissions_sync_export_and_release(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    user_headers = login_user(client)

    assert client.get("/api/web/meetings").status_code == 401
    assert client.get("/api/admin/providers", headers=user_headers).status_code == 403
    assert client.get("/api/external/meetings", headers={"Authorization": "Bearer wrong-token"}).status_code == 401
    mobile_config = client.get("/api/mobile/config")
    assert mobile_config.status_code == 200
    assert mobile_config.json()["segmentMinutes"] == 5
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
    upload_data = upload.json()
    assert upload_data["sizeBytes"] > 0
    assert upload_data["partial"]["status"] == "succeeded"
    partial_transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    assert partial_transcript.status_code == 200
    partial_segments = partial_transcript.json()["segments"]
    assert len(partial_segments) == 1
    assert partial_segments[0]["start_ms"] == 0
    partial_detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers)
    assert partial_detail.json()["meeting"]["status"] == "partial_ready"

    second_audio = b"fake audio data second segment"
    upload_second = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments",
        headers=headers,
        data={"segment_no": "2", "start_ms": "118000", "end_ms": "240000", "duration_ms": "122000"},
        files={"file": ("part_0002.wav", second_audio, "audio/wav")},
    )
    assert upload_second.status_code == 200
    assert upload_second.json()["partial"]["status"] == "succeeded"
    partial_after_second = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert [item["start_ms"] for item in partial_after_second["segments"]] == [0, 118000]
    audio_denied = client.get(f"/api/mobile/meetings/{meeting_id}/segments/1/audio", headers=user_headers)
    assert audio_denied.status_code == 404
    audio_download = client.get(f"/api/mobile/meetings/{meeting_id}/segments/1/audio", headers=headers)
    assert audio_download.status_code == 200
    assert audio_download.content == b"fake audio data"
    audio_second = client.get(f"/api/mobile/meetings/{meeting_id}/segments/2/audio", headers=headers)
    assert audio_second.status_code == 200
    assert audio_second.content == second_audio

    finish = client.post(f"/api/mobile/meetings/{meeting_id}/finish", headers=headers)
    assert finish.status_code == 200
    finish_data = finish.json()
    assert finish_data["jobId"].startswith("job_")
    assert finish_data["reused"] is False
    finish_retry = client.post(f"/api/mobile/meetings/{meeting_id}/finish", headers=headers)
    assert finish_retry.status_code == 200
    assert finish_retry.json()["jobId"] == finish_data["jobId"]
    assert finish_retry.json()["reused"] is True

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers)
    assert transcript.status_code == 200
    segments = transcript.json()["segments"]
    assert len(segments) == 2
    assert segments[0]["speaker_id"] == "SPEAKER_01"
    assert segments[1]["start_ms"] == 118000

    rename = client.post(
        f"/api/web/meetings/{meeting_id}/speakers/rename",
        headers=headers,
        json={"speaker_id": "SPEAKER_01", "display_name": "张三"},
    )
    assert rename.status_code == 200
    transcript_after = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert transcript_after["segments"][0]["display_name"] == "张三"

    sales_user = client.get("/api/web/me", headers=user_headers).json()["user"]
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO meeting_members (meeting_id, user_id, role) VALUES (?, ?, 'editor')",
            (meeting_id, sales_user["id"]),
        )

    user_trim = client.put(
        f"/api/web/meetings/{meeting_id}/transcript",
        headers=user_headers,
        json={"version": transcript_after["version"], "segments": transcript_after["segments"][:1]},
    )
    assert user_trim.status_code == 403

    edited_segments = transcript_after["segments"]
    edited_segments[0]["text"] = "双方确认报价，并安排下周推进合同。"
    edit_transcript = client.put(
        f"/api/web/meetings/{meeting_id}/transcript",
        headers=headers,
        json={"version": transcript_after["version"], "segments": edited_segments},
    )
    assert edit_transcript.status_code == 200
    assert edit_transcript.json()["segments"][0]["text"] == "双方确认报价，并安排下周推进合同。"

    knowledge_transcript = client.get(
        f"/api/external/meetings/{meeting_id}/transcript?include_history=true",
        headers={"Authorization": "Bearer test-token"},
    )
    assert knowledge_transcript.status_code == 200
    knowledge_data = knowledge_transcript.json()
    assert knowledge_data["client"] == "hermes"
    assert knowledge_data["transcript"]["segment_count"] == 2
    assert "双方确认报价" in knowledge_data["transcript"]["plain_text"]
    assert len(knowledge_data["transcript"]["history"]) >= 2
    assert knowledge_data["transcript"]["history"][0]["archive_reason"] == "user_update"

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
    mobile_config_after_save = client.get("/api/mobile/config")
    assert mobile_config_after_save.json()["segmentMinutes"] == 5

    export = client.post(f"/api/web/meetings/{meeting_id}/exports?export_format=markdown", headers=headers)
    assert export.status_code == 200
    export_path = Path(export.json()["path"])
    assert export_path.exists()
    assert "客户复盘会" in export_path.read_text(encoding="utf-8")

    release = client.post(
        "/api/admin/releases",
        headers=headers,
        data={
            "platform": "android",
            "version_name": "0.7.0",
            "version_code": "7",
            "release_notes": "V0.7",
            "force_update": "false",
        },
        files={"file": ("app.apk", b"fake apk", "application/vnd.android.package-archive")},
    )
    assert release.status_code == 200
    latest = client.get("/api/web/releases/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["release"]["version_name"] == "0.7.0"
    assert latest.json()["release"]["platform"] == "android"
    download = client.get("/downloads/android/0.7.0/app.apk")
    assert download.status_code == 200
    assert download.content == b"fake apk"

    windows_release = client.post(
        "/api/admin/releases",
        headers=headers,
        data={
            "platform": "windows",
            "version_name": "0.7.0",
            "version_code": "7",
            "release_notes": "V0.7 Windows",
            "force_update": "false",
        },
        files={"file": ("SoloRecord-Setup.exe", b"fake exe", "application/vnd.microsoft.portable-executable")},
    )
    assert windows_release.status_code == 200
    windows_latest = client.get("/api/web/releases/latest?platform=windows", headers=headers)
    assert windows_latest.status_code == 200
    assert windows_latest.json()["release"]["platform"] == "windows"
    windows_download = client.get(windows_latest.json()["release"]["downloadUrl"])
    assert windows_download.status_code == 200
    assert windows_download.content == b"fake exe"

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

    admin_trim = client.put(
        f"/api/web/meetings/{meeting_id}/transcript",
        headers=headers,
        json={
            "version": edit_transcript.json()["version"],
            "segments": edit_transcript.json()["segments"][:1],
        },
    )
    assert admin_trim.status_code == 200
    assert len(admin_trim.json()["segments"]) == 1
