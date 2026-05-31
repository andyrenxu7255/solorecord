import importlib
import json
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


def parse_flags(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]
    return [str(value)] if value else []


def login_named_user(client: TestClient, name: str, email: str) -> dict:
    response = client.post(
        "/api/auth/demo-login",
        json={"display_name": name, "email": email},
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
    assert post.call_args_list[0].kwargs["data"]["model"] == "funasr-paraformer-zh"


def test_remote_stt_adapter_keeps_funasr_speaker_segments(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    import solorecord_server.asr_adapters as asr_adapters

    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    payload = {
        "sentence_info": [
            {"text": "任旭确认客户名单。", "start": 0.0, "end": 2.4, "spk": 0},
            {"text": "李娜准备物料。", "start": 2.4, "end": 4.0, "spk": 1},
        ]
    }
    with patch("httpx.Client.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = payload
        post.return_value.raise_for_status.return_value = None
        segments = asr_adapters.transcribe_with_openai_compatible(
            "http://asr.example.com/v1",
            "test-key",
            "funasr-paraformer-zh",
            [str(audio)],
        )
    assert post.call_args.kwargs["data"]["diarization"] == "true"
    assert post.call_args.kwargs["data"]["spk_model"] == "cam++"
    assert [item["speaker_id"] for item in segments] == ["SPEAKER_01", "SPEAKER_02"]
    assert all("asr_speaker" in item["flags"] for item in segments)


def test_remote_stt_adapter_keeps_funasr_timestamp_segments(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    import solorecord_server.asr_adapters as asr_adapters

    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    payload = {
        "sentence_info": [
            {
                "text": "任旭确认客户名单。",
                "timestamp": [[120, 480], [480, 2360]],
                "spk": 0,
            },
            {
                "text": "李娜准备物料。",
                "timestamps": [2360, 4100],
                "spk": 1,
            },
        ]
    }
    with patch("httpx.Client.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = payload
        post.return_value.raise_for_status.return_value = None
        segments = asr_adapters.transcribe_with_openai_compatible(
            "http://asr.example.com/v1",
            "test-key",
            "funasr-paraformer-zh",
            [str(audio)],
        )
    assert [(item["start_ms"], item["end_ms"]) for item in segments] == [
        (120, 2360),
        (2360, 4100),
    ]
    assert [item["speaker_id"] for item in segments] == ["SPEAKER_01", "SPEAKER_02"]
    assert all("asr_speaker" in item["flags"] for item in segments)


def test_remote_stt_adapter_reads_nested_funasr_data(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    import solorecord_server.asr_adapters as asr_adapters

    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    payload = {
        "data": {
            "result": {
                "sentence_info": [
                    {
                        "sentence": "围城同步风险清单。",
                        "start": 12,
                        "end": 15,
                        "speakerLabel": "spk1",
                    }
                ]
            }
        }
    }
    with patch("httpx.Client.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = payload
        post.return_value.raise_for_status.return_value = None
        segments = asr_adapters.transcribe_with_openai_compatible(
            "http://asr.example.com/v1",
            "test-key",
            "funasr-paraformer-zh",
            [str(audio)],
        )
    assert segments[0]["text"] == "围城同步风险清单。"
    assert segments[0]["speaker_id"] == "SPEAKER_02"
    assert (segments[0]["start_ms"], segments[0]["end_ms"]) == (12000, 15000)
    assert "asr_speaker" in segments[0]["flags"]


def test_funasr_native_endpoint_is_used_for_rich_segments(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    import solorecord_server.asr_adapters as asr_adapters

    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    openai_payload = {"text": "任旭说客户名单今天定版。李娜说物料周五前准备好。"}
    native_payload = {
        "text": "任旭说客户名单今天定版。李娜说物料周五前准备好。",
        "segments": [
            {"text": "任旭说客户名单今天定版。", "start": 0.0, "end": 2.0},
            {"text": "李娜说物料周五前准备好。", "start": 2.0, "end": 4.0},
        ],
        "vad_segments": [[0, 2000], [2000, 4000]],
    }

    def fake_post(url, **kwargs):
        class Response:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        return Response(native_payload if url.endswith("/asr/transcribe") else openai_payload)

    with patch("httpx.Client.post", side_effect=fake_post) as post:
        segments = asr_adapters.transcribe_with_openai_compatible(
            "http://asr.example.com/v1",
            "test-key",
            "funasr-paraformer-zh",
            [str(audio)],
        )
    called_urls = [call.args[0] for call in post.call_args_list]
    assert "http://asr.example.com/v1/asr/transcribe" in called_urls
    assert [item["start_ms"] for item in segments] == [0, 2000]
    assert segments[1]["text"] == "李娜说物料周五前准备好。"


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


def test_command_asr_parser_accepts_funasr_sentence_info() -> None:
    import solorecord_server.asr_adapters as asr_adapters

    output = """
    {
      "sentence_info": [
        {
          "text": "海春确认合同。",
          "timestamp": [[0, 640], [640, 1820]],
          "spk_id": 2
        }
      ]
    }
    """
    segments = asr_adapters._parse_segments(output)
    assert segments[0]["speaker_id"] == "SPEAKER_03"
    assert (segments[0]["start_ms"], segments[0]["end_ms"]) == (0, 1820)
    assert "asr_speaker" in segments[0]["flags"]


def test_multi_source_join_uploads_same_local_segment_without_conflict(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    owner_headers = login(client)
    user_headers = login_user(client)

    create = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "大会议室同录",
            "join_code": "room-0601",
            "recording_mode": "multi_source",
            "max_sources": 3,
            "source_label": "会议室前排",
        },
    )
    assert create.status_code == 200
    meeting_id = create.json()["meeting"]["id"]
    assert create.json()["meeting"]["join_code"] == "ROOM0601"
    assert create.json()["recordingSources"][0]["source_id"] == "primary"

    join = client.post(
        "/api/web/meetings/join",
        headers=user_headers,
        json={
            "join_code": "room-0601",
            "source_label": "后排手机",
            "device_name": "Pixel",
        },
    )
    assert join.status_code == 200
    joined_source = join.json()["joinedSource"]
    assert joined_source["source_id"] == "source_02"

    retry_join = client.post(
        "/api/web/meetings/join",
        headers=user_headers,
        json={
            "join_code": "room-0601",
            "source_label": "后排手机",
            "device_name": "Pixel",
        },
    )
    assert retry_join.status_code == 200
    assert retry_join.json()["joinedSource"]["source_id"] == joined_source["source_id"]
    assert len(retry_join.json()["recordingSources"]) == 2

    first = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments",
        headers=owner_headers,
        data={
            "segment_no": "1",
            "source_id": "primary",
            "source_segment_no": "1",
            "start_ms": "0",
            "end_ms": "300000",
            "duration_ms": "300000",
        },
        files={"file": ("front_0001.m4a", b"front source", "audio/mp4")},
    )
    assert first.status_code == 200
    assert first.json()["segmentNo"] == 1
    assert first.json()["sourceSegmentNo"] == 1

    second = client.post(
        f"/api/mobile/meetings/{meeting_id}/segments",
        headers=user_headers,
        data={
            "segment_no": "1",
            "source_id": joined_source["source_id"],
            "source_segment_no": "1",
            "start_ms": "0",
            "end_ms": "300000",
            "duration_ms": "300000",
        },
        files={"file": ("back_0001.m4a", b"back source", "audio/mp4")},
    )
    assert second.status_code == 200
    assert second.json()["segmentNo"] == 2
    assert second.json()["sourceSegmentNo"] == 1

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=owner_headers).json()
    audio = detail["audioSegments"]
    assert [(item["source_id"], item["source_segment_no"], item["segment_no"]) for item in audio] == [
        ("primary", 1, 1),
        ("source_02", 1, 2),
    ]
    assert len(detail["recordingSources"]) == 2
    assert detail["qualityReport"]["metrics"]["recording_source_count"] == 2
    assert detail["qualityReport"]["metrics"]["source_segment_coverage"] == 1

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=owner_headers).json()
    assert {(item["source_id"], item["source_segment_no"]) for item in transcript["segments"]} == {
        ("primary", 1),
        ("source_02", 1),
    }
    assert client.get(
        f"/api/mobile/meetings/{meeting_id}/segments/1/audio",
        headers=owner_headers,
    ).content == b"front source"
    assert client.get(
        f"/api/mobile/meetings/{meeting_id}/segments/2/audio",
        headers=user_headers,
    ).content == b"back source"


def test_create_meeting_returns_conflict_for_duplicate_join_code(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)

    first = client.post(
        "/api/web/meetings",
        headers=headers,
        json={"title": "第一场", "join_code": "same-code"},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/api/web/meetings",
        headers=headers,
        json={"title": "第二场", "join_code": "same-code"},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "join_code already exists"


def test_discover_joinable_multi_source_meetings_returns_metadata_only(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    owner_headers = login(client)
    guest_headers = login_user(client)

    create = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "客户复盘可加入会议",
            "join_code": "discover-1",
            "recording_mode": "multi_source",
            "max_sources": 3,
            "source_label": "前排电脑",
        },
    )
    assert create.status_code == 200
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            UPDATE meetings
            SET summary='内部纪要不应在加入前泄露',
                role_notes='分角色整理不应泄露'
            WHERE id=?
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_discover_hidden', ?, 1, 'primary', 1, 'SPEAKER_01', '任旭',
             0, 1000, '这段转写不能在加入前返回。', 0.8, '[]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items
            (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_discover_hidden', ?, '任旭', '这条待办不能在加入前返回', '', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    response = client.get("/api/web/meetings/discover", headers=guest_headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item == {
        "id": meeting_id,
        "title": "客户复盘可加入会议",
        "join_code": "DISCOVER1",
        "status": "local_recorded",
        "owner_name": "Admin",
        "source_count": 1,
        "max_sources": 3,
        "remaining_sources": 2,
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
    }
    assert "summary" not in item
    assert "role_notes" not in item
    assert "transcriptSegments" not in item
    assert "audioSegments" not in item
    assert "actionItems" not in item


def test_discover_joinable_multi_source_filters_closed_full_and_query(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    owner_headers = login(client)
    guest_headers = login_user(client)

    open_meeting = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "华东现场复盘",
            "join_code": "alpha-42",
            "recording_mode": "multi_source",
            "max_sources": 3,
        },
    )
    ready_meeting = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "已完成会议",
            "join_code": "ready-42",
            "recording_mode": "multi_source",
            "max_sources": 3,
        },
    )
    failed_meeting = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "失败会议",
            "join_code": "failed-42",
            "recording_mode": "multi_source",
            "max_sources": 3,
        },
    )
    ended_meeting = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "已结束会议",
            "join_code": "ended-42",
            "recording_mode": "multi_source",
            "max_sources": 3,
        },
    )
    single_meeting = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={"title": "单源会议", "join_code": "single-42"},
    )
    full_meeting = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "满员会议",
            "join_code": "full-42",
            "recording_mode": "multi_source",
            "max_sources": 1,
        },
    )
    assert all(
        response.status_code == 200
        for response in [
            open_meeting,
            ready_meeting,
            failed_meeting,
            ended_meeting,
            single_meeting,
            full_meeting,
        ]
    )
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            "UPDATE meetings SET status='ready' WHERE id=?",
            (ready_meeting.json()["meeting"]["id"],),
        )
        conn.execute(
            "UPDATE meetings SET status='failed' WHERE id=?",
            (failed_meeting.json()["meeting"]["id"],),
        )
        conn.execute(
            "UPDATE meetings SET ended_at='now' WHERE id=?",
            (ended_meeting.json()["meeting"]["id"],),
        )

    all_items = client.get("/api/web/meetings/discover", headers=guest_headers).json()["items"]
    assert [item["join_code"] for item in all_items] == ["ALPHA42"]

    by_title = client.get(
        "/api/web/meetings/discover?q=华东",
        headers=guest_headers,
    ).json()["items"]
    assert [item["join_code"] for item in by_title] == ["ALPHA42"]

    by_code = client.get(
        "/api/mobile/meetings/discover?q=alpha-42",
        headers=guest_headers,
    ).json()["items"]
    assert [item["title"] for item in by_code] == ["华东现场复盘"]


def test_multi_source_supports_eight_recorders_and_rejects_ninth(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    owner_headers = login(client)
    create = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "八源大会议室",
            "join_code": "room-8",
            "recording_mode": "multi_source",
            "max_sources": 99,
            "source_label": "主持人电脑",
        },
    )
    assert create.status_code == 200
    meeting_id = create.json()["meeting"]["id"]

    uploads = [
        (
            owner_headers,
            "primary",
            b"source primary",
        )
    ]
    for number in range(2, 9):
        headers = login_named_user(client, f"Recorder {number}", f"recorder{number}@example.com")
        join = client.post(
            "/api/web/meetings/join",
            headers=headers,
            json={
                "join_code": "room-8",
                "source_label": f"录音源 {number}",
                "device_name": f"Device {number}",
            },
        )
        assert join.status_code == 200
        joined_source = join.json()["joinedSource"]
        assert joined_source["source_id"] == f"source_{number:02d}"
        uploads.append((headers, joined_source["source_id"], f"source {number}".encode()))

    for index, (headers, source_id, body) in enumerate(uploads, start=1):
        upload = client.post(
            f"/api/mobile/meetings/{meeting_id}/segments",
            headers=headers,
            data={
                "segment_no": "1",
                "source_id": source_id,
                "source_segment_no": "1",
                "start_ms": "0",
                "end_ms": "60000",
                "duration_ms": "60000",
            },
            files={"file": (f"{source_id}_0001.m4a", body, "audio/mp4")},
        )
        assert upload.status_code == 200
        assert upload.json()["segmentNo"] == index
        assert upload.json()["sourceSegmentNo"] == 1

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=owner_headers).json()
    assert len(detail["recordingSources"]) == 8
    assert len(detail["audioSegments"]) == 8
    assert detail["qualityReport"]["metrics"]["recording_source_count"] == 8
    assert [item["segment_no"] for item in detail["audioSegments"]] == list(range(1, 9))
    assert {item["source_segment_no"] for item in detail["audioSegments"]} == {1}

    ninth_headers = login_named_user(client, "Recorder 9", "recorder9@example.com")
    ninth = client.post(
        "/api/web/meetings/join",
        headers=ninth_headers,
        json={
            "join_code": "room-8",
            "source_label": "录音源 9",
            "device_name": "Device 9",
        },
    )
    assert ninth.status_code == 409


def test_multi_source_reuses_retry_but_allows_distinct_sources_for_same_user(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    owner_headers = login(client)
    user_headers = login_user(client)
    create = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "同用户多设备",
            "join_code": "same-user",
            "recording_mode": "multi_source",
            "max_sources": 3,
        },
    )
    assert create.status_code == 200

    first = client.post(
        "/api/web/meetings/join",
        headers=user_headers,
        json={
            "join_code": "same-user",
            "source_label": "手机录音",
            "device_name": "Android",
        },
    )
    assert first.status_code == 200
    first_source = first.json()["joinedSource"]["source_id"]

    retry = client.post(
        "/api/web/meetings/join",
        headers=user_headers,
        json={
            "join_code": "same-user",
            "source_label": "手机录音",
            "device_name": "Android",
        },
    )
    assert retry.status_code == 200
    assert retry.json()["joinedSource"]["source_id"] == first_source
    assert len(retry.json()["recordingSources"]) == 2

    second_device = client.post(
        "/api/web/meetings/join",
        headers=user_headers,
        json={
            "join_code": "same-user",
            "source_label": "电脑录音",
            "device_name": "Android",
        },
    )
    assert second_device.status_code == 200
    assert second_device.json()["joinedSource"]["source_id"] != first_source
    assert len(second_device.json()["recordingSources"]) == 3


def test_multi_source_limit_is_enforced(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    owner_headers = login(client)
    user_headers = login_user(client)
    create = client.post(
        "/api/web/meetings",
        headers=owner_headers,
        json={
            "title": "双源会议",
            "join_code": "limit2",
            "recording_mode": "multi_source",
            "max_sources": 2,
        },
    )
    assert create.status_code == 200
    assert client.post(
        "/api/web/meetings/join",
        headers=user_headers,
        json={"join_code": "limit2", "source_label": "第二源"},
    ).status_code == 200
    overflow = client.post(
        f"/api/web/meetings/{create.json()['meeting']['id']}/sources",
        headers=owner_headers,
        json={"label": "第三源"},
    )
    assert overflow.status_code == 409

    upload_overflow = client.post(
        f"/api/mobile/meetings/{create.json()['meeting']['id']}/segments",
        headers=owner_headers,
        data={
            "segment_no": "1",
            "source_id": "third",
            "source_segment_no": "1",
            "start_ms": "0",
            "end_ms": "1000",
            "duration_ms": "1000",
        },
        files={"file": ("third.wav", b"third", "audio/wav")},
    )
    assert upload_overflow.status_code == 409


def test_multi_source_final_processing_merges_duplicate_evidence(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        headers=headers,
        json={
            "title": "多源校对",
            "recording_mode": "multi_source",
            "max_sources": 2,
        },
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_ms_1', ?, 'front', 1, 1, 'front.wav', 'missing1.wav',
             'audio/wav', 1, 'sha1', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_ms_2', ?, 'back', 1, 2, 'back.wav', 'missing2.wav',
             'audio/wav', 1, 'sha2', 60000, 0, 60000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_ms_1', ?, 1, 'front', 1, 'SPEAKER_01', '任旭', 0, 60000,
             '客户名单今天定版，销售逐个通知客户。', 0.82,
             '["semantic_partial"]', 'now'),
            ('seg_ms_2', ?, 1, 'back', 1, 'SPEAKER_01', '任旭', 300, 60300,
             '客户名单今天定版，销售逐个通知客户，下午发消息。', 0.88,
             '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_final', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_final")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert len(transcript["segments"]) == 1
    segment = transcript["segments"][0]
    assert "multi_source_merged" in segment["flags"]
    assert segment["source_id"] == "back+front"
    assert "下午发消息" in segment["text"]
    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    assert detail["qualityReport"]["metrics"]["multi_source_merged_count"] == 1
    assert detail["qualityReport"]["metrics"]["multi_source_conflict_count"] == 0
    assert detail["qualityReport"]["metrics"]["source_segment_coverage"] == 1
    assert detail["qualityReport"]["sourceCoverage"]["weakSegments"] == []


def test_multi_source_final_processing_complements_partial_text(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        headers=headers,
        json={
            "title": "多源互补",
            "recording_mode": "multi_source",
            "max_sources": 3,
        },
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_complement_front', ?, 'front', 1, 1, 'front.wav', 'front.wav',
             'audio/wav', 1, 'sha-front-c', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_complement_back', ?, 'back', 1, 2, 'back.wav', 'back.wav',
             'audio/wav', 1, 'sha-back-c', 60000, 0, 60000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_complement_front', ?, 1, 'front', 1, 'SPEAKER_01', '任旭',
             0, 60000, '客户名单今天定版，销售逐个通知客户，物料清单同步。',
             0.84, '["semantic_partial"]', 'now'),
            ('seg_complement_back', ?, 1, 'back', 1, 'SPEAKER_01', '任旭',
             300, 60300, '客户名单今天定版，销售逐个通知客户，下午发消息。',
             0.88, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_complement', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_complement")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert len(transcript["segments"]) == 1
    segment = transcript["segments"][0]
    assert "multi_source_merged" in segment["flags"]
    assert "multi_source_complemented" in segment["flags"]
    assert "销售逐个通知客户" in segment["text"]
    assert "下午发消息" in segment["text"]
    assert "物料清单同步" in segment["text"]
    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    assert detail["qualityReport"]["metrics"]["multi_source_complemented_count"] == 1


def test_multi_source_final_processing_flags_critical_fact_conflicts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源事实冲突", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing
    import solorecord_server.repository as repository

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_conflict_front', ?, 'front', 1, 1, 'front.m4a',
             'front.m4a', 'audio/mp4', 1, 'sha-front', 120000, 0, 120000, 'uploaded', 'now'),
            ('aud_conflict_back', ?, 'back', 1, 2, 'back.m4a',
             'back.m4a', 'audio/mp4', 1, 'sha-back', 120000, 0, 120000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_conflict_front', ?, 1, 'front', 1, 'SPEAKER_01', '翼天',
             0, 60000, '错误样例周三前补三类，自动测试同步补完。',
             0.84, '["semantic_partial"]', 'now'),
            ('seg_conflict_back', ?, 1, 'back', 1, 'SPEAKER_02', '翼天',
             0, 60000, '错误样例周五前补五类，自动测试同步补完。',
             0.84, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_conflict', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_conflict")
    transcript = repository.transcript_document(meeting_id)
    segments = transcript["transcript"]["segments"]

    assert len(segments) == 2
    assert all("multi_source_conflict" in item["flags"] for item in segments)
    assert all("speaker_review" in item["flags"] for item in segments)
    assert {item["source_id"] for item in segments} == {"front", "back"}
    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]
    assert report["metrics"]["multi_source_conflict_count"] == 2
    assert "multi_source_conflict" in {item["type"] for item in report["issues"]}


def test_multi_source_final_processing_keeps_parallel_turns_not_conflicts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源并行发言", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_parallel_front', ?, 'front', 1, 1, 'front.m4a',
             'front.m4a', 'audio/mp4', 1, 'sha-parallel-front', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_parallel_back', ?, 'back', 1, 2, 'back.m4a',
             'back.m4a', 'audio/mp4', 1, 'sha-parallel-back', 60000, 0, 60000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_parallel_front', ?, 1, 'front', 1, 'SPEAKER_01', '傲寒',
             0, 60000, '今天先过整体节奏，客户名单和现场动线都要补齐。',
             0.84, '["semantic_partial"]', 'now'),
            ('seg_parallel_back', ?, 1, 'back', 1, 'SPEAKER_02', '翼天',
             500, 60500, '错误样例今天补三类，自动测试明天补完。',
             0.86, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_parallel', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_parallel")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert len(transcript["segments"]) == 2
    assert all("multi_source_conflict" not in item["flags"] for item in transcript["segments"])
    assert all("multi_source_merged" not in item["flags"] for item in transcript["segments"])
    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]
    assert report["metrics"]["multi_source_conflict_count"] == 0
    assert report["metrics"]["source_segment_coverage"] == 1


def test_multi_source_final_processing_preserves_third_source_fact_conflicts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源三方冲突", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_three_middle', ?, 'middle', 1, 1, 'middle.wav', 'middle.wav',
             'audio/wav', 1, 'sha-middle', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_three_front', ?, 'front', 1, 2, 'front.wav', 'front.wav',
             'audio/wav', 1, 'sha-front-three', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_three_back', ?, 'back', 1, 3, 'back.wav', 'back.wav',
             'audio/wav', 1, 'sha-back-three', 60000, 0, 60000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_three_middle', ?, 1, 'middle', 1, 'SPEAKER_01', '翼天',
             0, 60000, '客户名单今天定版，销售逐个通知客户。',
             0.84, '["semantic_partial"]', 'now'),
            ('seg_three_front', ?, 1, 'front', 1, 'SPEAKER_01', '翼天',
             200, 60200, '客户名单今天定版，销售逐个通知客户，周三前完成。',
             0.86, '["semantic_partial"]', 'now'),
            ('seg_three_back', ?, 1, 'back', 1, 'SPEAKER_01', '翼天',
             300, 60300, '客户名单今天定版，销售逐个通知客户，周五前完成。',
             0.87, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_three_conflict', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_three_conflict")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert len(transcript["segments"]) == 3
    assert all("multi_source_conflict" in item["flags"] for item in transcript["segments"])
    assert all("multi_source_merged" not in item["flags"] for item in transcript["segments"])


def test_multi_source_final_processing_marks_majority_when_two_sources_agree(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源多数一致", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_majority_front', ?, 'front', 1, 1, 'front.wav', 'front.wav',
             'audio/wav', 1, 'sha-front-majority', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_majority_middle', ?, 'middle', 1, 2, 'middle.wav', 'middle.wav',
             'audio/wav', 1, 'sha-middle-majority', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_majority_back', ?, 'back', 1, 3, 'back.wav', 'back.wav',
             'audio/wav', 1, 'sha-back-majority', 60000, 0, 60000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_majority_front', ?, 1, 'front', 1, 'SPEAKER_01', '翼天',
             0, 60000, '错误样例周三前补三类，自动测试同步补完。',
             0.88, '["semantic_partial"]', 'now'),
            ('seg_majority_middle', ?, 1, 'middle', 1, 'SPEAKER_01', '翼天',
             100, 60100, '错误样例周三前补三类，自动测试同步补完。',
             0.87, '["semantic_partial"]', 'now'),
            ('seg_majority_back', ?, 1, 'back', 1, 'SPEAKER_01', '翼天',
             200, 60200, '错误样例周五前补五类，自动测试同步补完。',
             0.86, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_majority', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_majority")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    majority = [
        item for item in transcript["segments"]
        if "multi_source_majority" in item["flags"]
    ]
    conflict = [
        item for item in transcript["segments"]
        if "multi_source_conflict" in item["flags"]
    ]
    assert len(transcript["segments"]) == 2
    assert len(majority) == 1
    assert "multi_source_merged" in majority[0]["flags"]
    assert "multi_source_conflict" not in majority[0]["flags"]
    assert "front:1" in majority[0]["flags"]
    assert "middle:1" in majority[0]["flags"]
    assert len(conflict) == 1
    assert conflict[0]["source_id"] == "back"

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]
    assert report["metrics"]["multi_source_merged_count"] == 1
    assert report["metrics"]["multi_source_majority_count"] == 1
    assert report["metrics"]["multi_source_conflict_count"] == 1


def test_multi_source_refs_preserve_all_eight_source_segments(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "八源完整覆盖", "recording_mode": "multi_source", "max_sources": 8},
        headers=headers,
    )
    meeting = create.json()["meeting"]
    meeting_id = meeting["id"]
    owner_id = meeting["owner_id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    source_ids = [
        f"room_recorder_{index:02d}_north_side_microphone"
        for index in range(1, 9)
    ]
    audio_values = []
    transcript_values = []
    source_values = []
    audio_params: list[str] = []
    transcript_params: list[str] = []
    source_params: list[str] = []
    for index, source_id in enumerate(source_ids, start=1):
        source_values.append("(?, ?, ?, ?, ?, ?, 'active', 'now', 'now')")
        source_params.extend(
            [
                f"src_eight_{index}",
                meeting_id,
                source_id,
                f"会议室第 {index} 台录音设备",
                f"device-{index}",
                owner_id,
            ]
        )
        audio_values.append(
            "(?, ?, ?, ?, ?, ?, ?, 'audio/wav', 1, ?, 60000, 0, 60000, 'uploaded', 'now')"
        )
        audio_params.extend(
            [
                f"aud_eight_{index}",
                meeting_id,
                source_id,
                str(index),
                str(index),
                f"{source_id}.wav",
                f"{source_id}.wav",
                f"sha-eight-{index}",
            ]
        )
        transcript_values.append(
            "(?, ?, 1, ?, ?, 'SPEAKER_01', '任旭', ?, ?, "
            "'客户名单今天定版，销售逐个通知客户，下午发消息。', "
            "0.88, '[\"semantic_partial\"]', 'now')"
        )
        transcript_params.extend(
            [
                f"seg_eight_{index}",
                meeting_id,
                source_id,
                str(index),
                str(index * 100),
                str(index * 100 + 60000),
            ]
        )
    with db.get_db() as conn:
        conn.execute(
            f"""
            INSERT INTO recording_sources
            (id, meeting_id, source_id, label, device_name, user_id, status, created_at, updated_at)
            VALUES {",".join(source_values)}
            """,
            source_params,
        )
        conn.execute(
            f"""
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES {",".join(audio_values)}
            """,
            audio_params,
        )
        conn.execute(
            f"""
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES {",".join(transcript_values)}
            """,
            transcript_params,
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_eight_refs', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_eight_refs")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert len(transcript["segments"]) == 1
    segment = transcript["segments"][0]
    flags = parse_flags(segment["flags"])
    assert "multi_source_merged" in flags
    refs_flag = next(flag for flag in flags if flag.startswith("multi_source_refs:"))
    for index, source_id in enumerate(source_ids, start=1):
        assert f"{source_id}:{index}" in refs_flag

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    report = detail["qualityReport"]
    assert report["metrics"]["recording_source_count"] == 8
    assert report["metrics"]["source_segment_coverage"] == 1
    assert report["sourceCoverage"]["weakSegments"] == []


def test_multi_source_final_processing_aligns_sources_started_late(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源错峰起录", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_offset_front', ?, 'front', 1, 1, 'front.m4a',
             'front.m4a', 'audio/mp4', 1, 'sha-front', 180000, 0, 180000, 'uploaded', 'now'),
            ('aud_offset_back', ?, 'back', 1, 2, 'back.m4a',
             'back.m4a', 'audio/mp4', 1, 'sha-back', 180000, 45000, 225000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_offset_front', ?, 1, 'front', 1, 'SPEAKER_01', '李娜',
             10000, 26000, '客户名单今天定版，销售逐个通知客户，下午发消息。',
             0.83, '["semantic_partial"]', 'now'),
            ('seg_offset_back', ?, 1, 'back', 1, 'SPEAKER_03', '李娜',
             55000, 71000, '客户名单今天定版，销售逐个通知客户，下午发消息。',
             0.91, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_offset', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_offset")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert len(transcript["segments"]) == 1
    segment = transcript["segments"][0]
    assert "multi_source_merged" in segment["flags"]
    assert "multi_source_time_aligned" in segment["flags"]
    assert segment["source_id"] == "back+front"
    assert segment["start_ms"] == 55000
    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    assert detail["qualityReport"]["metrics"]["multi_source_merged_count"] == 1
    assert detail["qualityReport"]["metrics"]["multi_source_conflict_count"] == 0
    assert detail["qualityReport"]["metrics"]["source_segment_coverage"] == 1


def test_multi_source_offset_alignment_preserves_fact_conflicts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源错峰冲突", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_offset_conflict_front', ?, 'front', 1, 1, 'front.m4a',
             'front.m4a', 'audio/mp4', 1, 'sha-front', 180000, 0, 180000, 'uploaded', 'now'),
            ('aud_offset_conflict_back', ?, 'back', 1, 2, 'back.m4a',
             'back.m4a', 'audio/mp4', 1, 'sha-back', 180000, 45000, 225000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_offset_conflict_front', ?, 1, 'front', 1, 'SPEAKER_01', '翼天',
             10000, 24000, '错误样例周三前补三类，自动测试同步补完。',
             0.84, '["semantic_partial"]', 'now'),
            ('seg_offset_conflict_back', ?, 1, 'back', 1, 'SPEAKER_02', '翼天',
             55000, 69000, '错误样例周五前补五类，自动测试同步补完。',
             0.86, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_offset_conflict', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_offset_conflict")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert len(transcript["segments"]) == 2
    assert all("multi_source_conflict" in item["flags"] for item in transcript["segments"])
    assert all("multi_source_merged" not in item["flags"] for item in transcript["segments"])


def test_multi_source_offset_alignment_keeps_short_acknowledgements_separate(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源短句不错合", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_offset_short_front', ?, 'front', 1, 1, 'front.m4a',
             'front.m4a', 'audio/mp4', 1, 'sha-front-short', 180000, 0, 180000, 'uploaded', 'now'),
            ('aud_offset_short_back', ?, 'back', 1, 2, 'back.m4a',
             'back.m4a', 'audio/mp4', 1, 'sha-back-short', 180000, 45000, 225000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_offset_short_front', ?, 1, 'front', 1, 'SPEAKER_01', '李娜',
             10000, 12000, '好的。',
             0.84, '["semantic_partial"]', 'now'),
            ('seg_offset_short_back', ?, 1, 'back', 1, 'SPEAKER_02', '翼天',
             55000, 57000, '好的。',
             0.86, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_multisource_offset_short', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_multisource_offset_short")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert len(transcript["segments"]) == 2
    assert all("multi_source_merged" not in item["flags"] for item in transcript["segments"])


def test_transcript_update_preserves_source_id_for_multisource_rows(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        headers=headers,
        json={"title": "多源人工校对", "recording_mode": "multi_source", "max_sources": 2},
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_source_front', ?, 1, 'front', 1, 'SPEAKER_01', '任旭', 0, 60000,
             '前排录音确认客户名单。', 0.82, '["semantic_final"]', 'now'),
            ('seg_source_back', ?, 1, 'back', 1, 'SPEAKER_02', '李娜', 0, 60000,
             '后排录音补充物料准备。', 0.81, '["semantic_final"]', 'now')
            """,
            (meeting_id, meeting_id),
        )

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    edited = transcript["segments"]
    edited[0]["text"] = "前排录音确认客户名单，销售今天通知。"
    response = client.put(
        f"/api/web/meetings/{meeting_id}/transcript",
        headers=headers,
        json={"version": transcript["version"], "segments": edited},
    )

    assert response.status_code == 200
    rows = response.json()["segments"]
    assert {(item["source_id"], item["source_segment_no"]) for item in rows} == {
        ("front", 1),
        ("back", 1),
    }


def test_semantic_segmentation_rule_fallback_splits_speaker_markers(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "六一筹备会"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 9000,
            "text": "任旭说客户名单今天定版。李娜说物料周五前准备好。王强说舞台音响周三给报价。",
            "confidence": 0.8,
            "flags": [],
        }
    ]
    refined = processing._refine_segments(meeting_id, segments)
    assert [item["display_name"] for item in refined] == ["任旭", "李娜", "王强"]
    assert refined[0]["text"] == "客户名单今天定版。"
    assert all("semantic_rule" in item["flags"] for item in refined)
    assert all(item["source_segment_no"] == 1 for item in refined)


def test_semantic_segmentation_rule_fallback_splits_addressed_speakers(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "点名式分段"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "傲寒",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 120000,
            "text": (
                "傲寒先过整体节奏。"
                "翼天你先说一下错误样例和自动测试。"
                "围城你那个部分，MySQL、PostgreSQL、Oracle 外接数据源要确认。"
                "海春你来讲 deep flash 模型调优。"
            ),
            "confidence": 0.8,
            "flags": [],
        }
    ]
    refined = processing._refine_segments(meeting_id, segments)
    names = [item["display_name"] for item in refined]
    assert names == ["傲寒", "翼天", "围城", "海春"]
    assert refined[0]["text"] == "先过整体节奏。"
    assert "错误样例" in refined[1]["text"]
    assert "外接数据源" in refined[2]["text"]
    assert "个部分" not in refined[2]["text"]
    assert "模型调优" in refined[3]["text"]
    assert all("semantic_rule" in item["flags"] for item in refined)
    assert "source_prefix_before_callout" in refined[0]["flags"]
    assert "scenario:native_speaker" in refined[0]["flags"]
    assert "scenario:context_bridge" in refined[1]["flags"]
    assert "scenario:task_ownership" in refined[2]["flags"]


def test_semantic_segmentation_does_not_promote_due_times_to_speakers(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "日期不是人名"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 120000,
            "text": (
                "李波部分报价还差一版，今天下午发给销售；"
                "赵敏负责合同，周五前确认审批意见。"
            ),
            "confidence": 0.82,
            "flags": ["asr_speaker"],
        }
    ]

    refined = processing._refine_segments(meeting_id, segments)

    assert [item["display_name"] for item in refined] == ["李波", "赵敏"]
    assert "今天下午" in refined[0]["text"]
    assert "周五前" in refined[1]["text"]
    assert all("今天" not in item["display_name"] for item in refined)
    assert all("周五" not in item["display_name"] for item in refined)


def test_semantic_segmentation_cleans_address_prefixes(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "点名前缀清理"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 120000,
            "text": (
                "任旭你先说客户名单，客户名单今天定版，"
                "围城你那个外接数据源，已经接上两个字段，周三前输出截图。"
            ),
            "confidence": 0.82,
            "flags": ["asr_speaker"],
        }
    ]

    refined = processing._refine_segments(meeting_id, segments)

    assert [item["display_name"] for item in refined] == ["任旭", "围城"]
    assert refined[0]["text"].startswith("客户名单")
    assert refined[1]["text"].startswith("外接数据源")
    assert "先说" not in refined[0]["text"]
    assert "你那个" not in refined[1]["text"]
    assert "周三前" in refined[1]["text"]


def test_semantic_segmentation_refines_long_native_speaker_segments(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "ASR 长段再拆"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 20000,
            "text": "今天先看六一筹备整体节奏，现场动线和客户名单都要补齐。",
            "confidence": 0.86,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_02",
            "display_name": "发言人 2",
            "source_segment_no": 1,
            "start_ms": 20000,
            "end_ms": 180000,
            "text": (
                "我先把客户名单今天定版，确保销售能逐个通知到位。"
                "李波你再看一下下载链接和 APK 分发页面，最好明天给一版截图。"
                "围城你那个部分，MySQL、PostgreSQL、Oracle 外接数据源要确认。"
                "海春你来讲模型调优和质量检查，周三前给大家一个结果。"
                "这些事项后面都要进入待办清单，不能只写成相关负责人。"
            ),
            "confidence": 0.84,
            "flags": ["asr_speaker"],
        },
    ]

    refined = processing._refine_segments(meeting_id, segments)
    names = [item["display_name"] for item in refined]

    assert "李波" in names
    assert "围城" in names
    assert "海春" in names
    assert len(refined) > len(segments)
    assert any("semantic_rule" in item["flags"] for item in refined)
    assert any("speaker_review" in item["flags"] for item in refined)


def test_contextual_speaker_inference_links_called_person_response(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "点名回应"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 5000,
            "text": "翼天你先说一下错误样例和自动测试。",
            "confidence": 0.86,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_02",
            "display_name": "发言人 2",
            "source_segment_no": 1,
            "start_ms": 5000,
            "end_ms": 13000,
            "text": "我这边准备了三个错误样例，自动测试明天能补完。",
            "confidence": 0.84,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "source_segment_no": 1,
            "start_ms": 13000,
            "end_ms": 18000,
            "text": "好的，那围城你那个部分继续确认外接数据源。",
            "confidence": 0.83,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_03",
            "display_name": "发言人 3",
            "source_segment_no": 1,
            "start_ms": 18000,
            "end_ms": 26000,
            "text": "我负责 MySQL、PostgreSQL、Oracle 的连通性检查。",
            "confidence": 0.82,
            "flags": ["asr_speaker"],
        },
    ]

    refined = processing._refine_segments(meeting_id, segments)

    assert [item["display_name"] for item in refined] == ["发言人 1", "翼天", "发言人 1", "围城"]
    assert "contextual_speaker_inference" in refined[1]["flags"]
    assert "speaker_review" in refined[1]["flags"]
    assert "contextual_speaker_inference" in refined[3]["flags"]
    assert refined[1]["speaker_id"] == "SPEAKER_02"
    assert refined[3]["speaker_id"] == "SPEAKER_03"


def test_semantic_segmentation_splits_inline_addressed_response(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "单段点名回应"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "主持人",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 18000,
            "text": (
                "翼天你先说一下错误样例和自动测试。"
                "我这边准备了三个错误样例，自动测试明天能补完。"
            ),
            "confidence": 0.86,
            "flags": ["asr_speaker"],
        }
    ]

    refined = processing._refine_segments(meeting_id, segments)

    assert [item["display_name"] for item in refined] == ["主持人", "翼天"]
    assert refined[0]["speaker_id"] == "SPEAKER_01"
    assert refined[1]["speaker_id"] == "MANUAL_翼天"
    assert "inline_address_prompt" in refined[0]["flags"]
    assert "inline_addressed_response" in refined[1]["flags"]
    assert "speaker_review" in refined[1]["flags"]
    assert refined[1]["source_segment_no"] == 1
    assert "错误样例" in refined[1]["text"]


def test_semantic_segmentation_splits_inline_addressed_response_without_punctuation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "无标点点名回应"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "主持人",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 18000,
            "text": (
                "翼天你先说一下错误样例和自动测试"
                "我这边准备了三个错误样例自动测试明天能补完"
            ),
            "confidence": 0.86,
            "flags": ["asr_speaker"],
        }
    ]

    refined = processing._refine_segments(meeting_id, segments)

    assert [item["display_name"] for item in refined] == ["主持人", "翼天"]
    assert refined[0]["text"] == "错误样例和自动测试"
    assert refined[1]["text"] == "我这边准备了三个错误样例自动测试明天能补完"
    assert "inline_addressed_response" in refined[1]["flags"]
    assert "speaker_review" in refined[1]["flags"]


def test_contextual_speaker_inference_links_topic_continuation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "议题承接"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 5000,
            "text": "翼天你先说一下错误样例和自动测试。",
            "confidence": 0.86,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_02",
            "display_name": "发言人 2",
            "source_segment_no": 1,
            "start_ms": 5000,
            "end_ms": 12000,
            "text": "错误样例今天补三类，自动测试明天补完。",
            "confidence": 0.84,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "source_segment_no": 1,
            "start_ms": 12000,
            "end_ms": 17000,
            "text": "李波你再看一下下载页面。",
            "confidence": 0.84,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_03",
            "display_name": "发言人 3",
            "source_segment_no": 1,
            "start_ms": 17000,
            "end_ms": 22000,
            "text": "赵敏：我来确认客户名单。",
            "confidence": 0.84,
            "flags": ["asr_speaker"],
        },
    ]

    refined = processing._refine_segments(meeting_id, segments)

    assert [item["display_name"] for item in refined] == ["发言人 1", "翼天", "发言人 1", "赵敏"]
    assert refined[1]["speaker_id"] == "SPEAKER_02"
    assert "contextual_speaker_inference" in refined[1]["flags"]
    assert "speaker_review" in refined[1]["flags"]
    assert any(flag.startswith("reason:") for flag in refined[1]["flags"])
    assert refined[3]["display_name"] != "李波"
    assert "scenario:explicit_name" in refined[3]["flags"]


def test_contextual_speaker_inference_does_not_use_speaker_change_alone(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "点名不过度归属"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "主持人",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 5000,
            "text": "翼天你先说一下错误样例和自动测试。",
            "confidence": 0.86,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_02",
            "display_name": "发言人 2",
            "source_segment_no": 1,
            "start_ms": 5000,
            "end_ms": 9000,
            "text": "好的，我们继续下一个议题。",
            "confidence": 0.84,
            "flags": ["asr_speaker"],
        },
    ]

    refined = processing._refine_segments(meeting_id, segments)

    assert [item["display_name"] for item in refined] == ["主持人", "发言人 2"]
    assert "contextual_speaker_inference" not in refined[1]["flags"]
    assert "speaker_review" not in refined[1]["flags"]


def test_semantic_segmentation_runs_when_asr_speakers_leave_named_cues(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "原生 speaker 后处理"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "主持人",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 5000,
            "text": "先过一下进度。",
            "confidence": 0.86,
            "flags": ["asr_speaker"],
        },
        {
            "speaker_id": "SPEAKER_02",
            "display_name": "发言人 2",
            "source_segment_no": 1,
            "start_ms": 5000,
            "end_ms": 11000,
            "text": "李波后面看登录界面，围城负责外接数据源。海春确认模型调优结果。",
            "confidence": 0.84,
            "flags": ["asr_speaker"],
        },
    ]

    refined = processing._refine_segments(meeting_id, segments)
    names = [item["display_name"] for item in refined]

    assert "李波" in names
    assert "围城" in names
    assert "海春" in names
    assert len(refined) > len(segments)
    assert any("semantic_rule" in item["flags"] for item in refined)
    assert all(item.get("source_segment_no") == 1 for item in refined)


def test_finish_rewrites_reused_partial_with_semantic_segments(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "跨段发言人"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_1', ?, 1, 1, 'SPEAKER_01', '发言人 1', 0, 9000, ?, 0.8, '[]', 'now')
            """,
            (
                meeting_id,
                "任旭说客户名单今天定版。李娜说物料周五前准备好。王强说舞台音响周三给报价。",
            ),
        )
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, segment_no, file_name, storage_path, mime_type, size_bytes,
             sha256, duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES ('aud_1', ?, 1, 'part.m4a', 'missing.m4a', 'audio/mp4', 1,
                    'sha', 9000, 0, 9000, 'uploaded', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_finish', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_finish")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert [item["display_name"] for item in transcript["segments"]] == ["任旭", "李娜", "王强"]
    assert all("semantic_rule" in item["flags"] for item in transcript["segments"])
    assert all("semantic_final" in item["flags"] for item in transcript["segments"])
    assert all(item["source_segment_no"] == 1 for item in transcript["segments"])


def test_final_processing_rechecks_reused_partial_context(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "整场复核"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, segment_no, file_name, storage_path, mime_type, size_bytes,
             sha256, duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES
            ('aud_ctx_1', ?, 1, 'part1.wav', 'missing1.wav', 'audio/wav', 1,
             'sha1', 5000, 0, 5000, 'uploaded', 'now'),
            ('aud_ctx_2', ?, 2, 'part2.wav', 'missing2.wav', 'audio/wav', 1,
             'sha2', 5000, 5000, 10000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_ctx_1', ?, 1, 1, 'SPEAKER_01', '主持人', 0, 5000,
             '翼天你先说一下错误样例和自动测试。', 0.82,
             '["semantic_partial"]', 'now'),
            ('seg_ctx_2', ?, 1, 2, 'SPEAKER_02', '发言人 2', 5000, 10000,
             '我这边准备了三个错误样例，自动测试明天能补完。', 0.81,
             '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_ctx_final', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_ctx_final")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert [item["display_name"] for item in transcript["segments"]] == ["主持人", "翼天"]
    assert "semantic_final" in transcript["segments"][1]["flags"]
    assert "contextual_speaker_inference" in transcript["segments"][1]["flags"]
    assert transcript["segments"][1]["speaker_id"] == "SPEAKER_02"


def test_final_processing_keeps_called_person_followup_commitments(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "跨分段连续承接"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, segment_no, file_name, storage_path, mime_type, size_bytes,
             sha256, duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES
            ('aud_follow_1', ?, 1, 'part1.wav', 'missing1.wav', 'audio/wav', 1,
             'sha-follow-1', 5000, 0, 5000, 'uploaded', 'now'),
            ('aud_follow_2', ?, 2, 'part2.wav', 'missing2.wav', 'audio/wav', 1,
             'sha-follow-2', 5000, 5000, 10000, 'uploaded', 'now'),
            ('aud_follow_3', ?, 3, 'part3.wav', 'missing3.wav', 'audio/wav', 1,
             'sha-follow-3', 6000, 10000, 16000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_follow_1', ?, 1, 1, 'SPEAKER_01', '主持人', 0, 5000,
             '翼天你先说一下错误样例和自动测试。', 0.82,
             '["semantic_partial"]', 'now'),
            ('seg_follow_2', ?, 1, 2, 'SPEAKER_01', '发言人 1', 5000, 10000,
             '错误样例已经准备了三个，自动测试明天能补完。', 0.81,
             '["semantic_partial"]', 'now'),
            ('seg_follow_3', ?, 1, 3, 'SPEAKER_01', '发言人 1', 10000, 16000,
             '周三前我会把可观测截图一起发出来。', 0.8,
             '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO processing_jobs
            (id, meeting_id, type, status, current_stage, progress, asr_provider, created_at, updated_at)
            VALUES ('job_followup_final', ?, 'transcribe', 'queued', 'queued', 0, 'mock', 'now', 'now')
            """,
            (meeting_id,),
        )

    processing.process_transcription_job("job_followup_final")

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert [item["display_name"] for item in transcript["segments"]] == ["主持人", "翼天", "翼天"]
    assert transcript["segments"][2]["source_segment_no"] == 3
    assert "contextual_speaker_inference" in transcript["segments"][2]["flags"]
    assert "speaker_review" in transcript["segments"][2]["flags"]


def test_insert_transcript_preserves_manual_speaker_names_only(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "人工姓名记忆"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO speakers (id, meeting_id, speaker_id, display_name, created_at, updated_at)
            VALUES
            ('spk_manual', ?, 'SPEAKER_02', '翼天', 'now', 'now'),
            ('spk_generic', ?, 'SPEAKER_03', '发言人 3', 'now', 'now')
            """,
            (meeting_id, meeting_id),
        )
        processing._insert_transcript_segments(
            conn,
            meeting_id,
            [
                {
                    "speaker_id": "SPEAKER_02",
                    "display_name": "发言人 2",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": "人工改名应保留。",
                    "confidence": 0.8,
                    "flags": [],
                },
                {
                    "speaker_id": "SPEAKER_03",
                    "display_name": "海春",
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "text": "泛化旧名不应覆盖模型新名。",
                    "confidence": 0.8,
                    "flags": [],
                },
            ],
            1,
            None,
        )

    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert [item["display_name"] for item in transcript["segments"]] == ["翼天", "海春"]


def test_speaker_rename_replace_text_uses_existing_display_name_alias(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "姓名统一"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_rename_alias_1', ?, 1, 1, 'SPEAKER_01', '发言人 1', 0, 60000,
             '发言人 1确认报价，SPEAKER_01后续继续推进。',
             0.82, '["asr_speaker"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            UPDATE meetings
            SET summary = '发言人 1确认报价。',
                role_notes = 'SPEAKER_01：推进合同。'
            WHERE id = ?
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_rename_alias_1', ?, '发言人 1', 'SPEAKER_01补充报价明细', '周三', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    rename = client.post(
        f"/api/web/meetings/{meeting_id}/speakers/rename",
        headers=headers,
        json={"speaker_id": "SPEAKER_01", "display_name": "张三", "replace_text": True},
    )

    assert rename.status_code == 200
    detail = rename.json()
    transcript = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert transcript["segments"][0]["display_name"] == "张三"
    assert "发言人 1" not in transcript["segments"][0]["text"]
    assert "SPEAKER_01" not in transcript["segments"][0]["text"]
    assert detail["meeting"]["summary"] == "张三确认报价。"
    assert detail["meeting"]["role_notes"] == "张三：推进合同。"
    assert detail["actionItems"][0]["owner"] == "张三"
    assert detail["actionItems"][0]["task"] == "张三补充报价明细"


def test_llm_refinement_repairs_compressed_timeline(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "长会压缩时间轴"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.processing as processing

    with db.get_db() as conn:
        conn.execute("UPDATE meetings SET duration_ms=? WHERE id=?", (180000, meeting_id))
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, segment_no, file_name, storage_path, mime_type, size_bytes,
             sha256, duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES ('aud_long', ?, 1, 'part.m4a', 'missing.m4a', 'audio/mp4', 1,
                    'sha', 180000, 0, 180000, 'uploaded', 'now')
            """,
            (meeting_id,),
        )

    refined = processing._repair_refined_timeline(
        [
            {"speaker_id": "A", "display_name": "任旭", "start_ms": 0, "end_ms": 50, "text": "第一段", "flags": []},
            {"speaker_id": "B", "display_name": "李娜", "start_ms": 50, "end_ms": 100, "text": "第二段", "flags": []},
            {"speaker_id": "C", "display_name": "王强", "start_ms": 100, "end_ms": 150, "text": "第三段", "flags": []},
        ],
        [{"start_ms": 0, "end_ms": 1000, "text": "压缩时间轴"}],
        processing._meeting_duration_ms(meeting_id),
    )
    assert refined[-1]["end_ms"] == 180000
    assert refined[1]["start_ms"] == 60000
    assert all("timeline_repaired" in item["flags"] for item in refined)


def test_llm_refinement_rejects_dropped_source_segment() -> None:
    import solorecord_server.processing as processing

    original = [
        {
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "任旭说客户名单今天定版，销售逐个通知客户。",
        },
        {
            "source_segment_no": 2,
            "start_ms": 60000,
            "end_ms": 120000,
            "text": "李娜说物料周五前准备好，王强说舞台音响周三给报价。",
        },
        {
            "source_segment_no": 3,
            "start_ms": 120000,
            "end_ms": 180000,
            "text": "赵敏补充直播推流要提前彩排，法务合同条款周一确认。",
        },
    ]
    refined = [
        {
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "客户名单今天定版，销售逐个通知客户。",
        },
        {
            "source_segment_no": 2,
            "start_ms": 60000,
            "end_ms": 120000,
            "text": "物料周五前准备好，舞台音响周三给报价。",
        },
    ]

    assert not processing._refined_segments_cover_source(refined, original)


def test_llm_refinement_coverage_uses_source_id_for_multisource_segments() -> None:
    import solorecord_server.processing as processing

    original = [
        {
            "source_id": "front",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "前排录音确认客户名单今天定版并通知销售。",
        },
        {
            "source_id": "back",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "后排录音确认物料清单下午同步给客户。",
        },
    ]
    refined = [
        {
            "source_id": "front",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "前排录音确认客户名单今天定版并通知销售。",
        }
    ]

    assert processing._refined_segments_cover_each_source(refined, original) is False

    refined.append(
        {
            "source_id": "back",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "后排录音确认物料清单下午同步给客户。",
        }
    )
    assert processing._refined_segments_cover_each_source(refined, original) is True


def test_action_owner_normalization_replaces_generic_roles() -> None:
    import solorecord_server.processing as processing

    actions = [
        {"owner": "前端开发", "task": "调整登录界面和图标", "due": "周日", "status": "open"},
        {"owner": "一键部署负责人", "task": "准备一键部署截图", "due": "", "status": "open"},
        {"owner": "翼天", "task": "演示错误样例", "due": "", "status": "open"},
    ]
    segments = [
        {"display_name": "李波", "text": "我今天主要就是调那个风格，包括登录界面和图标。"},
        {"display_name": "傲寒", "text": "一键部署要准备截图和下载链接。"},
        {"display_name": "翼天", "text": "我准备了三个错误样例。"},
    ]
    normalized = processing._normalize_action_owners(actions, segments)
    assert normalized[0]["owner"] == "李波"
    assert normalized[1]["owner"] == "傲寒"
    assert normalized[2]["owner"] == "翼天"


def test_action_owner_normalization_replaces_pronoun_owner_from_context() -> None:
    import solorecord_server.processing as processing

    actions = [
        {"owner": "我", "task": "补充错误样例和自动测试覆盖", "due": "明天", "status": "open"},
        {"owner": "我们", "task": "准备无法从上下文确认的材料", "due": "", "status": "open"},
    ]
    segments = [
        {
            "display_name": "翼天",
            "text": "我这边补充错误样例和自动测试覆盖，明天给大家看结果。",
        },
        {
            "display_name": "傲寒",
            "text": "今天先把会议节奏过一下。",
        },
    ]

    normalized = processing._normalize_action_owners(actions, segments)

    assert normalized[0]["owner"] == "翼天"
    assert normalized[1]["owner"] == "待确认"


def test_action_owner_normalization_uses_department_owner_context() -> None:
    import solorecord_server.processing as processing

    actions = [
        {"owner": "待确认", "task": "周五前跟进客户名单并同步销售工作区", "due": "周五", "status": "open"},
    ]
    segments = [
        {
            "display_name": "任旭",
            "text": "销售这边周五前跟进客户名单，同步到销售工作区，后续由客户经理接着处理。",
        },
        {
            "display_name": "李娜",
            "text": "物料清单我这边今天定版。",
        },
    ]

    normalized = processing._normalize_action_owners(actions, segments)

    assert normalized[0]["owner"] == "销售"


def test_action_owner_normalization_uses_addressed_followup_not_host() -> None:
    import solorecord_server.processing as processing

    actions = [
        {
            "owner": "待确认",
            "task": "补完自动测试覆盖脚本",
            "due": "明天",
            "status": "open",
        },
    ]
    segments = [
        {
            "display_name": "傲寒",
            "text": "翼天你先说一下错误样例和自动测试。",
        },
        {
            "display_name": "发言人 2",
            "text": "这块覆盖脚本明天补完，质量检查也一起跑。",
        },
    ]

    normalized = processing._normalize_action_owners(actions, segments)

    assert normalized[0]["owner"] == "翼天"


def test_action_owner_normalization_does_not_promote_time_phrase_owner() -> None:
    import solorecord_server.processing as processing

    actions = [
        {"owner": "待确认", "task": "下午发消息", "due": "下午", "status": "open"},
    ]
    segments = [
        {
            "display_name": "任旭",
            "text": "客户名单今天定版，销售逐个通知客户，下午发消息。",
        },
    ]

    normalized = processing._normalize_action_owners(actions, segments)

    assert normalized[0]["owner"] == "任旭"


def test_action_owner_normalization_uses_compact_org_deadline_context() -> None:
    import solorecord_server.processing as processing

    actions = [
        {"owner": "相关负责人", "task": "改登录页面并补自动化覆盖", "due": "下周一", "status": "open"},
        {"owner": "待确认", "task": "确认合同条款并给审批意见", "due": "月底前", "status": "open"},
    ]
    segments = [
        {
            "display_name": "发言人 1",
            "text": "产品这边负责整理需求，前端周三前改登录页面，测试下周一补自动化覆盖。",
        },
        {
            "display_name": "发言人 2",
            "text": "法务确认合同条款，月底前给审批意见。",
        },
    ]

    normalized = processing._normalize_action_owners(actions, segments)

    assert normalized[0]["owner"] == "前端"
    assert normalized[1]["owner"] == "法务"


def test_action_normalization_dedupes_tasks_and_statuses() -> None:
    import solorecord_server.processing as processing

    actions = [
        {"owner": "李娜", "task": "确认客户名单", "due": "", "status": "todo"},
        {"owner": "李娜", "task": "请确认客户名单事项", "due": "周三", "status": "in_progress"},
        {"owner": "王强", "task": "准备舞台音响报价", "due": "", "status": "completed"},
    ]
    segments = [
        {"display_name": "李娜", "text": "我确认客户名单，周三给结果。"},
        {"display_name": "王强", "text": "舞台音响报价我已经准备好了。"},
    ]

    normalized = processing._normalize_action_owners(actions, segments)

    assert len(normalized) == 2
    assert normalized[0]["owner"] == "李娜"
    assert normalized[0]["due"] == "周三"
    assert normalized[0]["status"] == "doing"
    assert normalized[1]["status"] == "done"


def test_llm_prompts_include_named_people_candidates() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "傲寒",
            "start_ms": 0,
            "end_ms": 120000,
            "text": (
                "翼天你先说一下错误样例和自动测试。"
                "围城你那个部分，MySQL、PostgreSQL、Oracle 外接数据源要确认。"
                "海春你来讲 deep flash 模型调优。"
                "李波后面看登录界面和图标。"
            ),
        }
    ]
    prompt = llm_adapters._segment_refine_user_prompt(segments)
    assert "- 翼天" in prompt
    assert "- 围城" in prompt
    assert "- 海春" in prompt
    assert "- 李波" in prompt
    assert "翼天你" not in llm_adapters.mentioned_people_candidates(segments)
    assert "海春你来" not in llm_adapters.mentioned_people_candidates(segments)
    assert "李波后面" not in llm_adapters.mentioned_people_candidates(segments)
    noisy_segments = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "发言人 1",
            "text": "李娜说物料周五前准备好。王强说舞台音响周三给报价。",
        }
    ]
    noisy_people = llm_adapters.mentioned_people_candidates(noisy_segments)
    assert "李娜" in noisy_people
    assert "王强" in noisy_people
    assert "物料周五前" not in noisy_people
    assert "舞台音响周三" not in noisy_people
    time_people = llm_adapters.mentioned_people_candidates(
        [{"speaker_id": "SPEAKER_01", "display_name": "发言人 1", "text": "下午发消息通知销售。"}]
    )
    assert "下午" not in time_people


def test_action_owner_normalization_uses_context_when_model_over_collapses() -> None:
    import solorecord_server.processing as processing

    actions = [
        {"owner": "傲寒", "task": "补充错误样例、可观测和自动测试覆盖", "due": "", "status": "open"},
        {"owner": "傲寒", "task": "确认 MySQL、PostgreSQL、Oracle 外接数据源方案", "due": "", "status": "open"},
    ]
    segments = [
        {"display_name": "傲寒", "text": "今天先把六一筹备会整体节奏过一下，大家按模块说明。"},
        {"display_name": "翼天", "text": "翼天你讲一下错误样例，可观测和自动测试这块你负责补齐。"},
        {"display_name": "围城", "text": "围城你那个部分，MySQL、PostgreSQL、Oracle 外接数据源要确认。"},
    ]
    normalized = processing._normalize_action_owners(actions, segments)
    assert normalized[0]["owner"] == "翼天"
    assert normalized[1]["owner"] == "围城"


def test_action_owner_normalization_preserves_collaborators() -> None:
    import solorecord_server.processing as processing

    actions = [
        {
            "owner": "任旭",
            "task": "确认客户名单并通知销售",
            "due": "今天",
            "status": "open",
        }
    ]
    segments = [
        {"display_name": "任旭", "text": "客户名单今天我来定版并通知销售。"},
        {"display_name": "李娜", "text": "我这边配合客户名单核对，补充缺失联系方式。"},
        {"display_name": "王强", "text": "舞台音响报价我周三给。"},
    ]

    normalized = processing._normalize_action_owners(actions, segments)

    assert normalized[0]["owner"] == "任旭"
    assert "协同：李娜" in normalized[0]["task"]
    assert "王强" not in normalized[0]["task"]


def test_llm_refinement_rejects_summary_like_text_loss() -> None:
    import solorecord_server.processing as processing

    original = [
        {
            "text": (
                "翼天说明错误样例、可观测、自动测试覆盖。"
                "围城确认 MySQL PostgreSQL Oracle 外接数据源。"
                "海春讨论 deep flash 模型调优和质量检查。"
                "李波调整登录界面、图标、时间线窗口和待办复制。"
            )
        }
    ]
    refined = [{"text": "大家讨论了系统优化和后续待办。"}]
    assert processing._refined_segments_cover_source(refined, original) is False


def test_llm_summary_normalizes_generic_action_owners() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "summary": "会议确认交付事项。",
      "role_notes": "销售：跟进客户名单。",
      "action_items": [
        {"owner": "销售", "task": "跟进客户名单", "due": "周五", "status": "open"},
        {"owner": "销售负责人", "task": "确认客户名单负责人", "due": "", "status": "open"},
        {"owner": "前端开发", "task": "调整登录页面", "due": "", "status": "open"},
        {"owner": "主持人", "task": "汇总会议纪要", "due": "", "status": "open"}
      ]
    }
    """

    _, _, actions = llm_adapters._parse_summary(content, [])

    assert [item["owner"] for item in actions] == ["销售", "待确认", "待确认", "待确认"]


def test_meeting_quality_report_flags_llm_review_risks(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "质量检查会"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_quality_1', ?, 1, 1, 'SPEAKER_01', '傲寒', 0, 200000,
             '傲寒说先过整体节奏。翼天你说错误样例和自动测试。围城你那个部分讲外接数据源。',
             0.62, ?, 'now'),
            ('seg_quality_2', ?, 1, 1, 'SPEAKER_01', '傲寒', 200000, 260000,
             '海春你来讲 deep flash 模型调优。',
             0.66, ?, 'now')
            """,
            (
                meeting_id,
                '["llm_refined","semantic_llm","speaker_review","scenario:context_bridge"]',
                meeting_id,
                '["llm_refined","semantic_llm","timeline_repaired","scenario:task_ownership"]',
            ),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES ('act_quality_1', ?, '待确认', '补充错误样例和自动测试', '', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers)
    assert detail.status_code == 200
    report = detail.json()["qualityReport"]
    assert report["status"] == "needs_review"
    assert report["metrics"]["speaker_review_count"] == 1
    assert report["metrics"]["generic_owner_count"] == 1
    assert report["metrics"]["timeline_repaired_count"] == 1
    assert {"翼天", "围城", "海春"}.issubset(set(report["candidatePeople"]))
    assert "翼天你" not in report["candidatePeople"]
    assert "海春你来" not in report["candidatePeople"]
    issue_types = {item["type"] for item in report["issues"]}
    assert "generic_owner" in issue_types
    assert "long_segment" in issue_types


def test_quality_probe_is_read_only_and_reports_current_quality(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "探测会"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.quality_probe as quality_probe

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_probe_1', ?, 1, 1, 'SPEAKER_01', '傲寒', 0, 200000,
             '翼天你说错误样例。围城你那个部分讲外接数据源。海春你来讲模型调优。',
             0.6, '["speaker_review"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES ('act_probe_1', ?, '待确认', '补充错误样例', '', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )
        before = conn.execute(
            "SELECT COUNT(*) AS count FROM transcript_segments WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()["count"]

    result = quality_probe.probe_meeting(meeting_id, run_llm=False)
    assert result["ok"] is True
    assert result["mode"] == "current"
    assert {"翼天", "围城", "海春"}.issubset(set(result["source"]["candidate_people"]))
    assert result["source"]["quality_report"]["status"] == "needs_review"
    assert result["source"]["knowledge_readiness"]["status"] == "hold"
    assert "generic_owner" in result["source"]["knowledge_readiness"]["blockers"]
    review_evidence = result["source"]["knowledge_readiness"]["reviewEvidence"]
    assert review_evidence["speakerEvidence"][0]["segment_id"] == "seg_probe_1"
    assert review_evidence["actionEvidence"][0]["status"] == "weak_owner"

    with db.get_db() as conn:
        after = conn.execute(
            "SELECT COUNT(*) AS count FROM transcript_segments WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()["count"]
    assert after == before


def test_quality_probe_postprocess_simulates_residual_splits_read_only(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "后处理探测会"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.quality_probe as quality_probe

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_probe_post_1', ?, 1, 1, 'SPEAKER_01', '傲寒', 0, 240000,
             '今天先过整体节奏。翼天你先说错误样例和自动测试。围城你那个部分讲外接数据源。海春你来讲模型调优。李波后面看登录界面。',
             0.7, '["llm_refined","semantic_llm"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES ('act_probe_post_1', ?, '待确认', '补充自动测试错误样例', '', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )
        before = conn.execute(
            "SELECT COUNT(*) AS count FROM transcript_segments WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()["count"]

    result = quality_probe.probe_meeting(
        meeting_id,
        run_llm=False,
        run_postprocess=True,
    )
    post = result["postprocess"]
    assert result["mode"] == "postprocess"
    assert post["segment_count"] == 5
    assert {item[0] for item in post["speaker_counts"]} == {"傲寒", "翼天", "围城", "海春", "李波"}
    assert post["quality_report"]["metrics"]["long_segment_count"] == 0
    assert post["quality_report"]["metrics"]["mixed_marker_segment_count"] == 0
    assert post["quality_report"]["metrics"]["speaker_review_count"] == 5
    delta = post["delta"]
    assert delta["segment_count_delta"] == 4
    assert delta["speaker_count_delta"] == 4
    assert delta["metrics"]["mixed_marker_segment_count"]["delta"] == -1
    assert "mixed_marker_segment_count" in delta["improved_metrics"]
    assert "翼天" in delta["speaker_names_added"]
    assert delta["suggested_owner_changed_count"] == 1
    assert delta["suggested_owner_changes"][0]["from"] == "傲寒"
    assert delta["suggested_owner_changes"][0]["to"] == "翼天"

    with db.get_db() as conn:
        after = conn.execute(
            "SELECT COUNT(*) AS count FROM transcript_segments WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()["count"]
    assert after == before


def test_quality_probe_postprocess_preserves_multisource_coverage_keys(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        headers=headers,
        json={"title": "多源探测会", "recording_mode": "multi_source", "max_sources": 2},
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db
    import solorecord_server.quality_probe as quality_probe

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, source_id, source_segment_no, segment_no, file_name,
             storage_path, mime_type, size_bytes, sha256, duration_ms, start_ms,
             end_ms, upload_status, created_at)
            VALUES
            ('aud_probe_front', ?, 'front', 1, 1, 'front.wav', 'front.wav',
             'audio/wav', 1, 'sha-front-probe', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_probe_back', ?, 'back', 1, 2, 'back.wav', 'back.wav',
             'audio/wav', 1, 'sha-back-probe', 60000, 0, 60000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id,
             display_name, start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_probe_front', ?, 1, 'front', 1, 'SPEAKER_01', '任旭',
             0, 60000, '前排录音确认客户名单今天定版。',
             0.84, '["semantic_partial"]', 'now'),
            ('seg_probe_back', ?, 1, 'back', 1, 'SPEAKER_02', '李娜',
             0, 60000, '后排录音确认物料清单下午同步。',
             0.84, '["semantic_partial"]', 'now')
            """,
            (meeting_id, meeting_id),
        )

    result = quality_probe.probe_meeting(
        meeting_id,
        run_llm=False,
        run_postprocess=True,
    )
    coverage = result["postprocess"]["quality_report"]["sourceCoverage"]
    assert coverage["coverage"] == 1
    assert {
        (item["source_id"], item["source_segment_no"], item["status"])
        for item in coverage["segments"]
    } == {("front", 1, "covered"), ("back", 1, "covered")}


def test_quality_report_flags_action_owner_over_concentration(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "负责人集中"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_owner_1', ?, 1, 1, 'SPEAKER_01', '傲寒', 0, 200000,
             '翼天你说错误样例。围城你那个部分讲外接数据源。海春你来讲模型调优。李波后面看登录界面。',
             0.8, '["semantic_llm"]', 'now')
            """,
            (meeting_id,),
        )
        for index, task in enumerate(
            [
                "补充错误样例",
                "确认外接数据源方案",
                "检查模型调优质量",
                "调整登录界面",
                "准备演示说明",
            ],
            start=1,
        ):
            conn.execute(
                """
                INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
                VALUES (?, ?, '傲寒', ?, '', 'open', 'now', 'now')
                """,
                (f"act_owner_{index}", meeting_id, task),
            )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers)
    report = detail.json()["qualityReport"]
    assert report["metrics"]["owner_distribution"]["傲寒"] == 5
    assert report["metrics"]["top_owner_ratio"] == 1
    issue_types = {item["type"] for item in report["issues"]}
    assert "owner_over_concentrated" in issue_types
    assert any("逐条复核负责人" in item for item in report["recommendations"])


def test_quality_report_flags_action_items_without_transcript_evidence(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "待办证据"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_evidence_1', ?, 1, 1, 'MANUAL_yt', '翼天', 0, 60000,
             '翼天你补充错误样例和自动测试覆盖，明天给大家看结果。',
             0.82, '["semantic_llm","scenario:task_ownership"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_evidence_ok', ?, '翼天', '补充错误样例和自动测试覆盖', '明天', 'open', 'now', 'now'),
            ('act_evidence_bad', ?, '李娜', '联系法务审批合同条款', '周五', 'open', 'now', 'now')
            """,
            (meeting_id, meeting_id),
        )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers)
    report = detail.json()["qualityReport"]
    assert report["metrics"]["unsupported_action_count"] == 1
    assert report["metrics"]["action_evidence_coverage"] == 0.5
    evidence_by_id = {item["id"]: item for item in report["actionEvidence"]}
    assert evidence_by_id["act_evidence_ok"]["status"] == "supported"
    assert evidence_by_id["act_evidence_ok"]["evidence"]
    assert evidence_by_id["act_evidence_ok"]["evidence"][0]["segment_id"] == "seg_evidence_1"
    assert evidence_by_id["act_evidence_ok"]["evidence"][0]["source_segment_no"] == 1
    assert evidence_by_id["act_evidence_bad"]["status"] == "unsupported"
    assert report["unsupportedActions"][0]["id"] == "act_evidence_bad"
    assert report["unsupportedActions"][0]["evidence"] == []
    issue_types = {item["type"] for item in report["issues"]}
    assert "unsupported_action_evidence" in issue_types
    assert any("不是模型补写" in item for item in report["recommendations"])


def test_quality_evidence_contains_source_id_for_multisource_navigation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "多源证据"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            UPDATE meetings
            SET summary = '会议确认客户名单今天定版。'
            WHERE id = ?
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_front_evidence', ?, 1, 'front', 1, 'MANUAL_renxu', '任旭', 0, 60000,
             '客户名单今天定版，销售逐个通知客户。', 0.9, '["semantic_final"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES ('act_front_evidence', ?, '任旭', '客户名单今天定版并通知销售', '今天', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]
    action_evidence = report["actionEvidence"][0]["evidence"][0]
    summary_evidence = report["summaryEvidence"]["supportedClaims"][0]["evidence"][0]
    assert action_evidence["source_id"] == "front"
    assert action_evidence["source_segment_no"] == 1
    assert summary_evidence["source_id"] == "front"
    assert summary_evidence["source_segment_no"] == 1


def test_quality_report_marks_conflicting_multisource_actions_for_review(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源冲突待办", "recording_mode": "multi_source", "max_sources": 2},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_conflict_action_front', ?, 1, 'front', 1, 'MANUAL_yitian', '翼天',
             0, 60000, '错误样例周三前补三类，自动测试同步补完。',
             0.82, '["semantic_final","multi_source_conflict","speaker_review"]', 'now'),
            ('seg_conflict_action_back', ?, 1, 'back', 1, 'MANUAL_yitian', '翼天',
             200, 60200, '错误样例周五前补五类，自动测试同步补完。',
             0.82, '["semantic_final","multi_source_conflict","speaker_review"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_conflict_action', ?, '翼天', '补充错误样例和自动测试', '周三', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    evidence = {item["id"]: item for item in detail["qualityReport"]["actionEvidence"]}
    item = evidence["act_conflict_action"]

    assert item["status"] == "conflict"
    assert "多源同录" in item["reason"]
    assert item["evidence"]
    assert detail["actionItems"][0]["evidenceStatus"] == "conflict"
    assert detail["actionItems"][0]["knowledgeSafe"] is False
    assert detail["actionItems"][0]["requiresReview"] is True
    assert "multi_source_conflict" in detail["knowledgeReadiness"]["reviewWarnings"]
    conflict_items = detail["qualityReport"]["multiSourceConflicts"]
    assert len(conflict_items) == 2
    assert {item["source_id"] for item in conflict_items} == {"front", "back"}
    assert all(item["source_segment_no"] == 1 for item in conflict_items)
    assert all("multi_source_conflict" in item["flags"] for item in conflict_items)
    assert all(item["nearby"] for item in conflict_items)
    assert conflict_items[0]["nearby"][0]["segment_id"] in {
        "seg_conflict_action_front",
        "seg_conflict_action_back",
    }
    readiness_evidence = detail["knowledgeReadiness"]["reviewEvidence"]
    assert len(readiness_evidence["multiSourceConflicts"]) == 2
    assert readiness_evidence["actionEvidence"][0]["id"] == "act_conflict_action"
    assert readiness_evidence["actionEvidence"][0]["status"] == "conflict"

    external = client.get(
        f"/api/external/meetings/{meeting_id}",
        headers={"Authorization": "Bearer test-token"},
    ).json()
    external_action = external["actionItems"][0]
    assert external_action["evidenceStatus"] == "conflict"
    assert external_action["knowledgeSafe"] is False
    assert external_action["requiresReview"] is True
    assert len(external["qualityReport"]["multiSourceConflicts"]) == 2
    assert len(external["knowledgeReadiness"]["reviewEvidence"]["multiSourceConflicts"]) == 2


def test_quality_report_marks_conflicting_multisource_summary_for_review(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多源冲突纪要", "recording_mode": "multi_source", "max_sources": 2},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            UPDATE meetings
            SET summary = '会议确认错误样例周三前补三类。'
            WHERE id = ?
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_conflict_summary_front', ?, 1, 'front', 1, 'MANUAL_yitian', '翼天',
             0, 60000, '错误样例周三前补三类，自动测试同步补完。',
             0.82, '["semantic_final","multi_source_conflict","speaker_review"]', 'now'),
            ('seg_conflict_summary_back', ?, 1, 'back', 1, 'MANUAL_yitian', '翼天',
             200, 60200, '错误样例周五前补五类，自动测试同步补完。',
             0.82, '["semantic_final","multi_source_conflict","speaker_review"]', 'now')
            """,
            (meeting_id, meeting_id),
        )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    summary_evidence = detail["qualityReport"]["summaryEvidence"]
    supported = summary_evidence["supportedClaims"][0]

    assert supported["status"] == "conflict"
    assert "多源冲突" in supported["reason"]
    assert summary_evidence["conflict_count"] == 1
    assert summary_evidence["unqualified_conflict_count"] == 1
    assert detail["qualityReport"]["metrics"]["summary_conflict_count"] == 1
    assert detail["qualityReport"]["metrics"]["summary_unqualified_conflict_count"] == 1
    assert "summary_multisource_conflict" in {
        item["type"] for item in detail["qualityReport"]["issues"]
    }
    assert "summary_multisource_conflict" in detail["knowledgeReadiness"]["reviewWarnings"]


def test_quality_report_allows_majority_multisource_actions_with_review(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多数源待办", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_majority_action', ?, 1, 'front+middle', 1, 'MANUAL_yitian', '翼天',
             0, 60000, '错误样例周三前补三类，自动测试同步补完。',
             0.9, '["semantic_final","multi_source_merged","multi_source_majority","multi_source_refs:front:1,middle:1"]', 'now'),
            ('seg_minority_conflict_action', ?, 1, 'back', 1, 'MANUAL_yitian', '翼天',
             200, 60200, '错误样例周五前补五类，自动测试同步补完。',
             0.82, '["semantic_final","multi_source_conflict","speaker_review"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_majority_action', ?, '翼天', '补充错误样例和自动测试', '周三', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    evidence = {item["id"]: item for item in detail["qualityReport"]["actionEvidence"]}
    item = evidence["act_majority_action"]

    assert item["status"] == "majority"
    assert "多数录音源" in item["reason"]
    assert detail["actionItems"][0]["evidenceStatus"] == "majority"
    assert detail["actionItems"][0]["knowledgeSafe"] is True
    assert detail["actionItems"][0]["requiresReview"] is True

    external = client.get(
        f"/api/external/meetings/{meeting_id}",
        headers={"Authorization": "Bearer test-token"},
    ).json()
    external_action = external["actionItems"][0]
    assert external_action["evidenceStatus"] == "majority"
    assert external_action["knowledgeSafe"] is True
    assert external_action["requiresReview"] is True


def test_quality_report_keeps_generic_owner_weak_even_with_majority_evidence(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多数源但负责人待确认", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_majority_action_generic_owner', ?, 1, 'front+middle', 1, 'MANUAL_yitian', '翼天',
             0, 60000, '错误样例周三前补三类，自动测试同步补完。',
             0.9, '["semantic_final","multi_source_merged","multi_source_majority","multi_source_refs:front:1,middle:1"]', 'now'),
            ('seg_minority_generic_owner_conflict', ?, 1, 'back', 1, 'MANUAL_yitian', '翼天',
             200, 60200, '错误样例周五前补五类，自动测试同步补完。',
             0.82, '["semantic_final","multi_source_conflict","speaker_review"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_majority_generic_owner', ?, '待确认', '补充错误样例和自动测试', '周三', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    evidence = {item["id"]: item for item in detail["qualityReport"]["actionEvidence"]}
    item = evidence["act_majority_generic_owner"]

    assert item["status"] == "weak_owner"
    assert item["suggested_owner"] == "翼天"
    assert item["suggested_owner_evidence"]
    assert detail["actionItems"][0]["evidenceStatus"] == "weak_owner"
    assert detail["actionItems"][0]["knowledgeSafe"] is False
    assert detail["actionItems"][0]["requiresReview"] is True
    assert detail["qualityReport"]["metrics"]["generic_owner_count"] == 1
    assert detail["qualityReport"]["metrics"]["weak_action_owner_count"] == 0

    external = client.get(
        f"/api/external/meetings/{meeting_id}",
        headers={"Authorization": "Bearer test-token"},
    ).json()
    external_action = external["actionItems"][0]
    assert external_action["evidenceStatus"] == "weak_owner"
    assert external_action["knowledgeSafe"] is False
    assert external_action["requiresReview"] is True
    assert external_action["suggestedOwner"] == "翼天"


def test_quality_report_marks_majority_multisource_summary_with_review(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post(
        "/api/web/meetings",
        json={"title": "多数源纪要", "recording_mode": "multi_source", "max_sources": 3},
        headers=headers,
    )
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            UPDATE meetings
            SET summary = '会议确认错误样例周三前补三类，自动测试同步补完。'
            WHERE id = ?
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_majority_summary', ?, 1, 'front+middle', 1, 'MANUAL_yitian', '翼天',
             0, 60000, '错误样例周三前补三类，自动测试同步补完。',
             0.9, '["semantic_final","multi_source_merged","multi_source_majority","multi_source_refs:front:1,middle:1"]', 'now'),
            ('seg_minority_summary_conflict', ?, 1, 'back', 1, 'MANUAL_yitian', '翼天',
             200, 60200, '错误样例周五前补五类，自动测试同步补完。',
             0.82, '["semantic_final","multi_source_conflict","speaker_review"]', 'now')
            """,
            (meeting_id, meeting_id),
        )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    summary_evidence = detail["qualityReport"]["summaryEvidence"]
    supported = summary_evidence["supportedClaims"][0]

    assert supported["status"] == "majority"
    assert "多数录音源" in supported["reason"]
    assert summary_evidence["majority_count"] == 1
    assert summary_evidence["conflict_count"] == 0
    assert detail["qualityReport"]["metrics"]["summary_majority_count"] == 1


def test_quality_report_treats_pronoun_owner_as_generic(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "代词负责人"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_pronoun_owner_1', ?, 1, 1, 'MANUAL_yitian', '翼天', 0, 60000,
             '我这边补充错误样例和自动测试覆盖，明天给大家看结果。',
             0.82, '["semantic_llm"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_pronoun_owner', ?, '我们', '补充错误样例和自动测试覆盖', '明天', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]

    assert report["metrics"]["generic_owner_count"] == 1
    assert report["metrics"]["owner_distribution"]["我们"] == 1
    issue_types = {item["type"] for item in report["issues"]}
    assert "generic_owner" in issue_types


def test_quality_report_treats_due_time_owner_as_generic(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "时间负责人"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_due_owner_1', ?, 1, 1, 'MANUAL_renxu', '任旭', 0, 60000,
             '客户名单今天定版，销售逐个通知客户，下午发消息。',
             0.82, '["semantic_llm"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_due_owner', ?, '下午', '发消息通知销售', '下午', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]

    assert report["metrics"]["generic_owner_count"] == 1
    assert report["actionEvidence"][0]["status"] in {"weak_owner", "unsupported"}
    issue_types = {item["type"] for item in report["issues"]}
    assert "generic_owner" in issue_types


def test_quality_report_flags_duplicate_action_items(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "重复待办"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_dup_action_1', ?, 1, 1, 'MANUAL_lina', '李娜', 0, 60000,
             '李娜确认客户名单，周三给结果。',
             0.82, '["semantic_llm"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_dup_1', ?, '李娜', '确认客户名单', '周三', 'open', 'now', 'now'),
            ('act_dup_2', ?, '李娜', '请确认客户名单事项', '周三', 'open', 'now', 'now')
            """,
            (meeting_id, meeting_id),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]

    assert report["metrics"]["duplicate_action_count"] == 1
    assert report["duplicateActions"][0]["id"] == "act_dup_2"
    issue_types = {item["type"] for item in report["issues"]}
    assert "duplicate_action" in issue_types
    assert any("合并重复项" in item for item in report["recommendations"])


def test_quality_report_flags_action_owner_without_context_evidence(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "负责人证据"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_owner_evidence_1', ?, 1, 1, 'MANUAL_yitian', '翼天', 0, 60000,
             '翼天你补充错误样例和自动测试覆盖，明天给大家看结果。',
             0.82, '["semantic_llm","scenario:task_ownership"]', 'now'),
            ('seg_owner_evidence_2', ?, 1, 1, 'MANUAL_lina', '李娜', 61000, 90000,
             '李娜这边先确认客户名单。',
             0.82, '["semantic_llm","scenario:native_speaker"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_owner_evidence_ok', ?, '翼天', '补充错误样例和自动测试覆盖', '明天', 'open', 'now', 'now'),
            ('act_owner_evidence_weak', ?, '李娜', '补充错误样例和自动测试覆盖', '明天', 'open', 'now', 'now')
            """,
            (meeting_id, meeting_id),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]
    assert report["metrics"]["weak_action_owner_count"] == 1
    assert report["weakActionOwners"][0]["id"] == "act_owner_evidence_weak"
    assert report["weakActionOwners"][0]["suggested_owner"] == "翼天"
    assert report["weakActionOwners"][0]["suggested_owner_evidence"]
    evidence = report["weakActionOwners"][0]["evidence"]
    assert {item["speaker"] for item in evidence} >= {"翼天", "李娜"}
    evidence_by_id = {item["id"]: item for item in report["actionEvidence"]}
    assert evidence_by_id["act_owner_evidence_weak"]["suggested_owner"] == "翼天"
    issue_types = {item["type"] for item in report["issues"]}
    assert "weak_action_owner_evidence" in issue_types
    assert any("负责人和任务" in item for item in report["recommendations"])


def test_quality_report_accepts_department_owner_with_assignment_evidence(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "部门负责人证据"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_dept_owner_1', ?, 1, 1, 'MANUAL_renxu', '任旭', 0, 60000,
             '销售这边周五前跟进客户名单，同步到销售工作区，后续由客户经理接着处理。',
             0.82, '["semantic_llm","scenario:task_ownership"]', 'now')
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_dept_owner_ok', ?, '销售', '周五前跟进客户名单并同步销售工作区', '周五', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]

    assert report["metrics"]["generic_owner_count"] == 0
    assert report["metrics"]["weak_action_owner_count"] == 0
    assert report["metrics"]["unsupported_action_count"] == 0
    evidence_by_id = {item["id"]: item for item in report["actionEvidence"]}
    assert evidence_by_id["act_dept_owner_ok"]["status"] == "supported"
    assert evidence_by_id["act_dept_owner_ok"]["evidence"]


def test_external_action_items_embed_evidence_for_agents(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "外部待办证据"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_agent_evidence_1', ?, 1, 'phone-a', 1, 'MANUAL_renxu', '任旭',
             0, 60000, '任旭负责整理客户名单，并在周三前同步销售工作区。',
             0.9, '["semantic_final"]', 'now')
            """,
            (meeting_id,),
        )
        rows = [
            (
                f"act_agent_{index:02d}",
                meeting_id,
                "任旭",
                f"整理客户名单第{index:02d}项",
                "周三",
                "open",
                f"now {index:02d}",
                f"now {index:02d}",
            )
            for index in range(1, 23)
        ]
        conn.executemany(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    external = client.get(
        f"/api/external/meetings/{meeting_id}/transcript?include_history=true",
        headers={"Authorization": "Bearer test-token"},
    )

    assert external.status_code == 200
    data = external.json()
    assert len(data["actionItems"]) == 22
    assert len(data["qualityReport"]["actionEvidence"]) == 22
    last_action = data["actionItems"][-1]
    assert last_action["id"] == "act_agent_22"
    assert last_action["evidenceStatus"] == "supported"
    assert last_action["knowledgeSafe"] is True
    assert last_action["requiresReview"] is False
    assert last_action["evidence"][0]["segment_id"] == "seg_agent_evidence_1"
    assert last_action["evidence"][0]["source_id"] == "phone-a"
    assert last_action["evidence"][0]["source_segment_no"] == 1
    assert last_action["evidence"][0]["start_ms"] == 0
    assert last_action["evidence"][0]["end_ms"] == 60000
    assert last_action["evidence"][0]["speaker"] == "任旭"
    assert "客户名单" in last_action["evidence"][0]["text"]


def test_quality_report_flags_summary_without_transcript_evidence(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "纪要证据"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            UPDATE meetings
            SET summary = '会议确认客户名单和物料准备。另决定启动海外法务审批和预算冻结。',
                role_notes = '李娜负责客户名单，王强负责物料。'
            WHERE id = ?
            """,
            (meeting_id,),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_summary_evidence_1', ?, 1, 1, 'MANUAL_lina', '李娜', 0, 60000,
             '李娜确认客户名单今天定版，王强说物料周五前准备好。',
             0.82, '["semantic_llm"]', 'now')
            """,
            (meeting_id,),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]
    assert report["metrics"]["summary_unsupported_count"] >= 1
    assert report["metrics"]["summary_evidence_coverage"] < 1
    assert any(
        "客户名单" in item["claim"] and item["evidence"]
        for item in report["summaryEvidence"]["supportedClaims"]
    )
    first_supported = report["summaryEvidence"]["supportedClaims"][0]
    assert {"speaker", "start_ms", "text", "matched_terms"}.issubset(
        first_supported["evidence"][0]
    )
    assert first_supported["evidence"][0]["segment_id"] == "seg_summary_evidence_1"
    assert first_supported["evidence"][0]["source_segment_no"] == 1
    assert any(
        "海外法务审批" in item["claim"]
        for item in report["summaryEvidence"]["unsupportedClaims"]
    )
    issue_types = {item["type"] for item in report["issues"]}
    assert "summary_evidence_weak" in issue_types
    assert any("纪要要点" in item for item in report["recommendations"])


def test_llm_summary_falls_back_when_not_grounded() -> None:
    import solorecord_server.processing as processing
    import solorecord_server.repository as repository

    segments = [
        {
            "speaker_id": "MANUAL_yitian",
            "display_name": "翼天",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "错误样例今天补三类，自动测试明天补完。",
            "confidence": 0.82,
            "flags": ["semantic_final"],
        },
        {
            "speaker_id": "MANUAL_weicheng",
            "display_name": "围城",
            "source_segment_no": 1,
            "start_ms": 60000,
            "end_ms": 120000,
            "text": "MySQL、PostgreSQL、Oracle 外接数据源要确认。",
            "confidence": 0.82,
            "flags": ["semantic_final"],
        },
    ]
    summary, role_notes, actions = processing._grounded_summary_result(
        "会议决定启动海外法务审批和预算冻结。",
        "法务团队负责海外审批。",
        [
            {
                "owner": "待确认",
                "task": "补充错误样例和自动测试",
                "due": "明天",
                "status": "open",
            },
            {
                "owner": "傲寒",
                "task": "确认外接数据源方案",
                "due": "",
                "status": "open",
            },
        ],
        segments,
    )

    assert "海外法务审批" not in summary
    assert "基于转写原文的保守整理" in summary
    assert "翼天：错误样例今天补三类" in summary
    assert "围城：MySQL、PostgreSQL、Oracle 外接数据源要确认" in role_notes
    assert actions[0]["owner"] == "翼天"
    assert actions[1]["owner"] == "围城"
    report = repository.build_quality_report(
        [processing._segment_row_like(item) for item in segments],
        [processing._action_row_like(item) for item in actions],
        [],
        summary,
        role_notes,
    )
    assert report["metrics"]["summary_evidence_coverage"] == 1
    assert report["metrics"]["summary_unsupported_count"] == 0


def test_grounded_summary_prefers_suggested_action_owner_without_fallback() -> None:
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "MANUAL_host",
            "display_name": "傲寒",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 18000,
            "text": "今天先过整体节奏。翼天你先说错误样例和自动测试。",
            "confidence": 0.86,
            "flags": ["semantic_final", "source_prefix_before_callout"],
        },
        {
            "speaker_id": "MANUAL_yitian",
            "display_name": "翼天",
            "source_segment_no": 1,
            "start_ms": 18000,
            "end_ms": 42000,
            "text": "错误样例今天补三类，自动测试明天补完。",
            "confidence": 0.86,
            "flags": ["semantic_final", "contextual_speaker_inference", "speaker_review"],
        },
    ]

    summary, _, actions = processing._grounded_summary_result(
        "翼天负责补充错误样例和自动测试。",
        "",
        [
            {
                "owner": "傲寒",
                "task": "补充错误样例和自动测试",
                "due": "明天",
                "status": "open",
            }
        ],
        segments,
    )

    assert summary == "翼天负责补充错误样例和自动测试。"
    assert actions[0]["owner"] == "翼天"


def test_llm_summary_falls_back_when_multisource_conflict_is_definite() -> None:
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "MANUAL_yitian",
            "display_name": "翼天",
            "source_id": "front",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "错误样例周三前补三类，自动测试同步补完。",
            "confidence": 0.82,
            "flags": ["semantic_final", "multi_source_conflict", "speaker_review"],
        },
        {
            "speaker_id": "MANUAL_yitian",
            "display_name": "翼天",
            "source_id": "back",
            "source_segment_no": 1,
            "start_ms": 200,
            "end_ms": 60200,
            "text": "错误样例周五前补五类，自动测试同步补完。",
            "confidence": 0.82,
            "flags": ["semantic_final", "multi_source_conflict", "speaker_review"],
        },
    ]

    summary, role_notes, actions = processing._grounded_summary_result(
        "会议确认错误样例周三前补三类。",
        "翼天负责错误样例。",
        [
            {
                "owner": "翼天",
                "task": "补充错误样例和自动测试",
                "due": "周三",
                "status": "open",
            }
        ],
        segments,
    )

    assert "会议确认错误样例周三前补三类" not in summary
    assert "基于转写原文的保守整理" in summary
    assert "错误样例周三前补三类" in summary
    assert "错误样例周五前补五类" in summary
    assert role_notes
    assert actions[0]["owner"] == "翼天"


def test_llm_summary_keeps_conflict_claim_with_review_language() -> None:
    import solorecord_server.processing as processing

    segments = [
        {
            "speaker_id": "MANUAL_yitian",
            "display_name": "翼天",
            "source_id": "front",
            "source_segment_no": 1,
            "start_ms": 0,
            "end_ms": 60000,
            "text": "错误样例周三前补三类，自动测试同步补完。",
            "confidence": 0.82,
            "flags": ["semantic_final", "multi_source_conflict", "speaker_review"],
        },
        {
            "speaker_id": "MANUAL_yitian",
            "display_name": "翼天",
            "source_id": "back",
            "source_segment_no": 1,
            "start_ms": 200,
            "end_ms": 60200,
            "text": "错误样例周五前补五类，自动测试同步补完。",
            "confidence": 0.82,
            "flags": ["semantic_final", "multi_source_conflict", "speaker_review"],
        },
    ]

    summary, _, _ = processing._grounded_summary_result(
        "错误样例周三前补三类待确认，建议回听确认。",
        "",
        [
            {
                "owner": "翼天",
                "task": "补充错误样例和自动测试",
                "due": "周三",
                "status": "open",
            }
        ],
        segments,
    )

    assert summary == "错误样例周三前补三类待确认，建议回听确认。"


def test_quality_report_flags_source_segment_coverage_gaps(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "覆盖检查"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audio_segments
            (id, meeting_id, segment_no, file_name, storage_path, mime_type, size_bytes,
             sha256, duration_ms, start_ms, end_ms, upload_status, created_at)
            VALUES
            ('aud_cover_1', ?, 1, 'part1.m4a', 'missing1.m4a', 'audio/mp4', 1,
             'sha1', 60000, 0, 60000, 'uploaded', 'now'),
            ('aud_cover_2', ?, 2, 'part2.m4a', 'missing2.m4a', 'audio/mp4', 1,
             'sha2', 60000, 60000, 120000, 'uploaded', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_cover_1', ?, 1, 1, 'MANUAL_renxu', '任旭', 0, 60000,
             '客户名单今天定版，销售逐个通知客户。', 0.9, '["semantic_final"]', 'now')
            """,
            (meeting_id,),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]

    assert report["metrics"]["source_segment_coverage"] == 0.5
    assert report["metrics"]["source_segment_weak_count"] == 1
    assert report["sourceCoverage"]["weakSegments"][0]["segment_no"] == 2
    assert "source_segment_coverage_weak" in {item["type"] for item in report["issues"]}


def test_llm_refinement_flags_speakers_without_source_evidence() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "speaker": "赵敏",
          "speaker_id": "MANUAL_zhaomin",
          "start_ms": 0,
          "end_ms": 3000,
          "text": "客户名单今天定版。",
          "confidence": 0.92,
          "scenario": "context_bridge",
          "reason": "模型推断"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "speaker_id": "SPEAKER_01",
                "display_name": "发言人 1",
                "start_ms": 0,
                "end_ms": 3000,
                "text": "客户名单今天定版。",
            }
        ],
    )
    assert "speaker_evidence_weak" in refined[0]["flags"]
    assert "speaker_review" in refined[0]["flags"]
    assert refined[0]["confidence"] <= 0.68


def test_llm_refinement_flags_topic_phrase_as_speaker() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "speaker": "物料周五前",
          "start_ms": 0,
          "end_ms": 3000,
          "text": "准备好。",
          "confidence": 0.9,
          "scenario": "explicit_name",
          "reason": "误把业务短语当人名"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "speaker_id": "SPEAKER_01",
                "display_name": "发言人 1",
                "start_ms": 0,
                "end_ms": 3000,
                "text": "李娜说物料周五前准备好。",
            }
        ],
    )
    assert "speaker_evidence_weak" in refined[0]["flags"]
    assert "speaker_review" in refined[0]["flags"]


def test_quality_report_flags_weak_speaker_evidence(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "发言人证据"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_speaker_evidence_1', ?, 1, 1, 'MANUAL_zhaomin', '赵敏', 0, 60000,
             '客户名单今天定版。',
             0.68, '["llm_refined","speaker_review","speaker_evidence_weak"]', 'now')
            """,
            (meeting_id,),
        )

    report = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["qualityReport"]
    assert report["metrics"]["speaker_evidence_weak_count"] == 1
    assert report["speakerEvidence"][0]["segment_id"] == "seg_speaker_evidence_1"
    assert report["speakerEvidence"][0]["risk"] == "weak_evidence"
    assert report["speakerEvidence"][0]["reason"]
    assert report["speakerEvidence"][0]["context"][0]["current"] is True
    issue_types = {item["type"] for item in report["issues"]}
    assert "speaker_evidence_weak" in issue_types
    assert any("误听词当成人名" in item for item in report["recommendations"])


def test_quality_report_flags_same_name_multiple_speaker_ids(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "同名多标签"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_alias_1', ?, 1, 1, 'SPEAKER_02', '翼天', 0, 5000,
             '错误样例今天补三类。', 0.72,
             '["semantic_rule","speaker_review","contextual_speaker_inference"]', 'now'),
            ('seg_alias_2', ?, 1, 1, 'MANUAL_翼天', '翼天', 6000, 12000,
             '自动测试明天补完。', 0.76,
             '["llm_refined","speaker_review"]', 'now')
            """,
            (meeting_id, meeting_id),
        )

    detail = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()
    report = detail["qualityReport"]
    assert report["metrics"]["speaker_alias_conflict_count"] == 1
    assert report["speakerAliasConflicts"][0]["display_name"] == "翼天"
    assert set(report["speakerAliasConflicts"][0]["speaker_ids"]) == {"SPEAKER_02", "MANUAL_翼天"}
    issue_types = {item["type"] for item in report["issues"]}
    assert "speaker_alias_conflict" in issue_types
    assert any("同名多标签" in item for item in report["recommendations"])

    graph = detail["knowledgeGraph"]
    yitian_nodes = [
        node for node in graph["nodes"]
        if node["type"] == "speaker" and node["label"] == "翼天"
    ]
    assert len(yitian_nodes) == 1
    assert set(yitian_nodes[0]["speaker_ids"]) == {"SPEAKER_02", "MANUAL_翼天"}


def test_knowledge_graph_links_speakers_topics_actions_and_times(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "主题图谱"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_topic_1', ?, 1, 1, 'MANUAL_yitian', '翼天', 0, 5000,
             '我这边补充错误样例和自动测试覆盖，明天给大家看结果。',
             0.82, '["semantic_llm"]', 'now'),
            ('seg_topic_2', ?, 1, 1, 'MANUAL_weicheng', '围城', 6000, 12000,
             '外接数据源这块 MySQL、PostgreSQL、Oracle 都要确认。',
             0.82, '["semantic_llm"]', 'now')
            """,
            (meeting_id, meeting_id),
        )
        conn.execute(
            """
            INSERT INTO action_items (id, meeting_id, owner, task, due, status, created_at, updated_at)
            VALUES
            ('act_topic_1', ?, '翼天', '补充错误样例和自动测试覆盖', '明天', 'open', 'now', 'now')
            """,
            (meeting_id,),
        )

    graph = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["knowledgeGraph"]
    graph_nodes = {(node["type"], node["label"]) for node in graph["nodes"]}
    graph_edges = {
        (edge["source_label"], edge["target_label"], edge["label"])
        for edge in graph["edges"]
    }

    assert any(node_type == "topic" and "错误" in label for node_type, label in graph_nodes)
    assert any(node_type == "topic" and "测试" in label for node_type, label in graph_nodes)
    assert any(source == "翼天" and label == "讨论" for source, _target, label in graph_edges)
    assert any(target == "补充错误样例和自动测试覆盖" and label == "产生待办" for _source, target, label in graph_edges)
    assert ("补充错误样例和自动测试覆盖", "明天", "截止") in graph_edges


def test_knowledge_graph_topic_evidence_preserves_source_refs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    headers = login(client)
    create = client.post("/api/web/meetings", json={"title": "图谱证据源"}, headers=headers)
    meeting_id = create.json()["meeting"]["id"]
    import solorecord_server.db as db

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO transcript_segments
            (id, meeting_id, version, source_id, source_segment_no, speaker_id, display_name,
             start_ms, end_ms, text, confidence, flags, created_at)
            VALUES
            ('seg_graph_source_1', ?, 1, 'front', 2, 'MANUAL_renxu', '任旭', 120000, 180000,
             '客户名单今天定版，销售工作区后续同步。',
             0.82, '["semantic_llm"]', 'now')
            """,
            (meeting_id,),
        )

    graph = client.get(f"/api/web/meetings/{meeting_id}", headers=headers).json()["knowledgeGraph"]
    topic = next(node for node in graph["nodes"] if node["type"] == "topic" and node["label"] == "客户名单")
    evidence = topic["evidence"][0]

    assert evidence["segment_id"] == "seg_graph_source_1"
    assert evidence["source_id"] == "front"
    assert evidence["source_segment_no"] == 2
    assert evidence["start_ms"] == 120000
    assert evidence["end_ms"] == 180000


def test_web_quality_ui_surfaces_weak_speaker_evidence() -> None:
    app_js = (Path(__file__).parents[1] / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    styles = (Path(__file__).parents[1] / "static" / "styles.css").read_text(
        encoding="utf-8"
    )
    assert "speaker_evidence_weak_count" in app_js
    assert "weak_action_owner_count" in app_js
    assert "source_segment_coverage" in app_js
    assert "sourceCoverage" in app_js
    assert "multi_source_complemented_count" in app_js
    assert "multi_source_majority_count" in app_js
    assert "多数源确认" in app_js
    assert "flag:multi_source_majority" in app_js
    assert "多源互补" in app_js
    assert "flag:multi_source_complemented" in app_js
    assert "sourceKey" in app_js
    assert "parseSourceKey" in app_js
    assert "data-source-id" in app_js
    assert "risk:source_coverage" in app_js
    assert "音频分段待核对" in app_js
    assert "weakActionOwners" in app_js
    assert "summary_evidence_coverage" in app_js
    assert "duplicate_action_count" in app_js
    assert "查看纪要风险" in app_js
    assert "summary:evidence_weak" in app_js
    assert "summary-risk-list" in app_js
    assert "supportedClaims" in app_js
    assert "renderSummaryEvidenceRefs" in app_js
    assert "纪要有依据" in app_js
    assert "纪要多数源确认" in app_js
    assert "纪要多源冲突待核对" in app_js
    assert "summaryEvidenceStatusLabel" in app_js
    assert "knowledgeReadiness" in app_js
    assert "reviewEvidence" in app_js
    assert "renderKnowledgeReadiness" in app_js
    assert "knowledgeReviewEvidenceItems" in app_js
    assert "knowledgeIssueLabel" in app_js
    assert "知识入库复核" in app_js
    assert "先复核再入库" in app_js
    assert "暂缓入库" in app_js
    assert "sourceCoverageWeakSegments" in app_js
    assert "multiSourceConflicts" in app_js
    assert "renderMultiSourceConflicts" in app_js
    assert "sourceConflictLabel" in app_js
    assert ".summary-evidence-item.majority" in styles
    assert ".summary-evidence-item.conflict" in styles
    assert ".knowledge-readiness" in styles
    assert ".knowledge-review-item" in styles
    assert ".knowledge-readiness-tags .blocker" in styles
    assert ".summary-evidence-item p" in styles
    assert "detailRoleNotes" in app_js
    assert "分角色整理" in app_js
    assert "role_notes" in app_js
    assert "缺转写证据" in app_js
    assert "负责人证据弱" in app_js
    assert "多源冲突待核对" in app_js
    assert "action-risk-evidence" in app_js
    assert "actionEvidence" in app_js
    assert "定位转写" in app_js
    assert "jumpToTranscriptEvidence" in app_js
    assert "filterChanged && state.currentMeetingDetail" in app_js
    assert "renderMeetingDetail(state.currentMeetingDetail, state.currentTranscriptSegments)" in app_js
    assert "renderEvidenceJumpButton" in app_js
    assert "dedupeActionEvidence" in app_js
    assert "有转写依据" in app_js
    assert "建议负责人" in app_js
    assert "applySuggestedActionOwner" in app_js
    assert "applyAllSuggestedActionOwners" in app_js
    assert "应用全部建议负责人" in app_js
    assert "apply-suggested-owner" in app_js
    assert "未找到相关转写片段" in app_js
    assert "action-row-wrap" in app_js
    assert "发言人证据风险" in app_js
    assert "发言人证据弱" in app_js
    assert "speakerEvidence" in app_js
    assert "speakerAliasConflicts" in app_js
    assert "speaker_alias_conflict_count" in app_js
    assert "同名多标签" in app_js
    assert "buildSpeakerEvidenceMap" in app_js
    assert "renderSpeakerEvidenceHint" in app_js
    assert "推断依据" in app_js
    assert "查看证据弱段落" in app_js
    assert "matchesTranscriptFilter" in app_js
    assert ".quality-shortcut" in styles
    assert ".speaker-evidence" in styles
    assert ".speaker-alias-conflict" in styles
    assert ".action-risk-line" in styles
    assert ".action-risk-line.supported" in styles
    assert ".action-risk-line.conflict" in styles
    assert ".action-suggestion" in styles
    assert ".action-risk-evidence" in styles
    assert ".evidence-jump" in styles
    assert ".transcript-row.highlight" in styles
    assert ".summary-risk-list" in styles
    assert ".summary-evidence-item" in styles
    assert ".summary-evidence-refs" in styles



def test_llm_semantic_segmentation_parses_structured_segments() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "speaker": "任旭",
          "speaker_id": "MANUAL_renxu",
          "start_ms": 0,
          "end_ms": 3000,
          "text": "客户名单今天定版。",
          "confidence": 0.9,
          "scenario": "explicit_name",
          "reason": "任旭被点名负责客户名单"
        },
        {
          "speaker": "李娜",
          "start_ms": 3000,
          "end_ms": 6000,
          "text": "物料周五前准备好。",
          "confidence": 0.72,
          "scenario": "context_bridge",
          "reason": "根据上一句李娜说推断"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "speaker_id": "SPEAKER_01",
                "display_name": "发言人 1",
                "start_ms": 0,
                "end_ms": 6000,
                "text": "任旭说客户名单今天定版。李娜说物料周五前准备好。",
            }
        ],
    )
    assert [item["display_name"] for item in refined] == ["任旭", "李娜"]
    assert refined[1]["speaker_id"].startswith("MANUAL_")
    assert "speaker_review" in refined[1]["flags"]
    assert "scenario:explicit_name" in refined[0]["flags"]
    assert "scenario:context_bridge" in refined[1]["flags"]
    assert refined[0]["source_segment_no"] is None


def test_llm_refinement_uses_timestamps_to_match_original_evidence() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "speaker": "李娜",
          "start_ms": 9000,
          "end_ms": 11000,
          "text": "物料周五前准备好。",
          "confidence": 0.91,
          "scenario": "explicit_name",
          "reason": "李娜在原文中明确出现"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "speaker_id": "SPEAKER_01",
                "display_name": "发言人 1",
                "start_ms": 0,
                "end_ms": 5000,
                "text": "任旭说客户名单今天定版。",
            },
            {
                "speaker_id": "SPEAKER_02",
                "display_name": "发言人 2",
                "start_ms": 8000,
                "end_ms": 13000,
                "text": "李娜说物料周五前准备好。",
            },
        ],
    )

    assert refined[0]["display_name"] == "李娜"
    assert "speaker_evidence_weak" not in refined[0]["flags"]
    assert refined[0]["confidence"] == 0.91


def test_llm_refinement_matches_source_id_before_duplicate_segment_no() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "source_id": "back",
          "source_segment_no": 1,
          "start_ms": 2500,
          "end_ms": 4500,
          "text": "后排听到销售负责人确认周五提交方案。",
          "confidence": 0.88,
          "scenario": "native_speaker"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "source_id": "front",
                "speaker_id": "SPEAKER_FRONT",
                "display_name": "前排设备",
                "source_segment_no": 1,
                "start_ms": 0,
                "end_ms": 5000,
                "text": "前排只听到主持人介绍背景。",
            },
            {
                "source_id": "back",
                "speaker_id": "SPEAKER_BACK",
                "display_name": "后排设备",
                "source_segment_no": 1,
                "start_ms": 1000,
                "end_ms": 6000,
                "text": "后排听到销售负责人确认周五提交方案。",
            },
        ],
    )

    assert refined[0]["source_id"] == "back"
    assert refined[0]["source_segment_no"] == 1
    assert refined[0]["display_name"] == "后排设备"
    assert refined[0]["speaker_id"] == "SPEAKER_BACK"
    assert "speaker_evidence_weak" not in refined[0]["flags"]


def test_llm_refinement_preserves_multisource_evidence_flags() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "source_index": 1,
          "speaker": "任旭",
          "speaker_id": "SPEAKER_01",
          "start_ms": 0,
          "end_ms": 30000,
          "text": "客户名单今天定版，销售逐个通知客户，下午发消息。",
          "confidence": 0.91,
          "scenario": "native_speaker"
        },
        {
          "source_index": 1,
          "speaker": "任旭",
          "speaker_id": "SPEAKER_01",
          "start_ms": 30000,
          "end_ms": 60000,
          "text": "物料清单同步。",
          "confidence": 0.88,
          "scenario": "native_speaker"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "source_id": "back+front",
                "speaker_id": "SPEAKER_01",
                "display_name": "任旭",
                "source_segment_no": 1,
                "start_ms": 0,
                "end_ms": 60000,
                "text": "客户名单今天定版，销售逐个通知客户，下午发消息，物料清单同步。",
                "flags": [
                    "semantic_partial",
                    "multi_source_merged",
                    "multi_source_complemented",
                    "multi_source_majority",
                    "multi_source_count:2",
                    "multi_source_refs:back:1,front:1",
                ],
            }
        ],
    )

    assert len(refined) == 2
    for segment in refined:
        assert "multi_source_merged" in segment["flags"]
        assert "multi_source_complemented" in segment["flags"]
        assert "multi_source_majority" in segment["flags"]
        assert "multi_source_count:2" in segment["flags"]
        assert "multi_source_refs:back:1,front:1" in segment["flags"]
        assert "semantic_partial" not in segment["flags"]


def test_llm_refinement_preserves_native_asr_speaker_evidence() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "source_index": 1,
          "speaker": "发言人 2",
          "speaker_id": "SPEAKER_02",
          "start_ms": 0,
          "end_ms": 30000,
          "text": "错误样例周三前补三类。",
          "confidence": 0.91,
          "scenario": "native_speaker"
        },
        {
          "source_index": 1,
          "speaker": "发言人 2",
          "speaker_id": "SPEAKER_02",
          "start_ms": 30000,
          "end_ms": 60000,
          "text": "自动测试同步补完。",
          "confidence": 0.89,
          "scenario": "native_speaker"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "source_id": "front",
                "source_segment_no": 1,
                "speaker_id": "SPEAKER_02",
                "display_name": "发言人 2",
                "start_ms": 0,
                "end_ms": 60000,
                "text": "错误样例周三前补三类，自动测试同步补完。",
                "flags": ["asr_speaker", "semantic_partial"],
            }
        ],
    )

    assert len(refined) == 2
    for segment in refined:
        assert segment["speaker_id"] == "SPEAKER_02"
        assert "asr_speaker" in segment["flags"]
        assert "scenario:native_speaker" in segment["flags"]
        assert "semantic_partial" not in segment["flags"]


def test_llm_refinement_does_not_mark_context_inference_as_asr_speaker() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "source_index": 2,
          "speaker": "翼天",
          "speaker_id": "MANUAL_yitian",
          "start_ms": 5000,
          "end_ms": 12000,
          "text": "错误样例今天补三类，自动测试明天补完。",
          "confidence": 0.86,
          "scenario": "context_bridge",
          "reason": "上一段点名翼天，当前段继续错误样例和自动测试议题"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "source_id": "front",
                "source_segment_no": 1,
                "speaker_id": "SPEAKER_01",
                "display_name": "主持人",
                "start_ms": 0,
                "end_ms": 5000,
                "text": "翼天你先说一下错误样例和自动测试。",
                "flags": ["asr_speaker"],
            },
            {
                "source_id": "front",
                "source_segment_no": 2,
                "speaker_id": "SPEAKER_02",
                "display_name": "发言人 2",
                "start_ms": 5000,
                "end_ms": 12000,
                "text": "错误样例今天补三类，自动测试明天补完。",
                "flags": ["asr_speaker"],
            },
        ],
    )

    assert refined[0]["display_name"] == "翼天"
    assert "asr_speaker" not in refined[0]["flags"]
    assert "speaker_review" in refined[0]["flags"]
    assert "scenario:context_bridge" in refined[0]["flags"]


def test_llm_refinement_preserves_multisource_conflict_review_flag() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "source_index": 1,
          "speaker": "翼天",
          "speaker_id": "SPEAKER_02",
          "start_ms": 0,
          "end_ms": 60000,
          "text": "错误样例周三前补三类，自动测试同步补完。",
          "confidence": 0.86,
          "scenario": "native_speaker"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "source_id": "front",
                "source_segment_no": 1,
                "speaker_id": "SPEAKER_02",
                "display_name": "翼天",
                "start_ms": 0,
                "end_ms": 60000,
                "text": "错误样例周三前补三类，自动测试同步补完。",
                "flags": ["multi_source_conflict", "speaker_review"],
            }
        ],
    )

    assert "multi_source_conflict" in refined[0]["flags"]
    assert "speaker_review" in refined[0]["flags"]


def test_summary_prompt_exposes_multisource_context_to_llm() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    prompt = llm_adapters._user_prompt(
        [
            {
                "source_id": "front",
                "source_segment_no": 1,
                "speaker_id": "SPEAKER_01",
                "display_name": "翼天",
                "start_ms": 0,
                "end_ms": 60000,
                "text": "错误样例周三前补三类。",
                "flags": ["multi_source_conflict", "speaker_review"],
            },
            {
                "source_id": "back",
                "source_segment_no": 1,
                "speaker_id": "SPEAKER_02",
                "display_name": "翼天",
                "start_ms": 200,
                "end_ms": 60200,
                "text": "错误样例周五前补五类。",
                "flags": ["multi_source_conflict", "speaker_review"],
            },
            {
                "source_id": "front+middle",
                "source_segment_no": 1,
                "speaker_id": "SPEAKER_01",
                "display_name": "翼天",
                "start_ms": 0,
                "end_ms": 60000,
                "text": "错误样例周三前补三类。",
                "flags": ["multi_source_majority", "multi_source_merged"],
            },
        ]
    )

    assert "source=front#1" in prompt
    assert "source=back#1" in prompt
    assert "multi_source_conflict" in prompt
    assert "multi_source_majority" in prompt
    assert "multi_source_majority 表示至少两个录音源一致" in prompt
    assert "不要把互相冲突的多源事实合并为单一结论" in prompt


def test_llm_refinement_prefers_source_id_over_wrong_source_index() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "source_index": 1,
          "source_id": "back",
          "source_segment_no": 1,
          "start_ms": 2500,
          "end_ms": 4500,
          "text": "后排听到销售负责人确认周五提交方案。",
          "confidence": 0.88,
          "scenario": "native_speaker"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "source_id": "front",
                "speaker_id": "SPEAKER_FRONT",
                "display_name": "前排设备",
                "source_segment_no": 1,
                "start_ms": 0,
                "end_ms": 5000,
                "text": "前排只听到主持人介绍背景。",
            },
            {
                "source_id": "back",
                "speaker_id": "SPEAKER_BACK",
                "display_name": "后排设备",
                "source_segment_no": 1,
                "start_ms": 1000,
                "end_ms": 6000,
                "text": "后排听到销售负责人确认周五提交方案。",
            },
        ],
    )

    assert refined[0]["source_id"] == "back"
    assert refined[0]["display_name"] == "后排设备"
    assert refined[0]["speaker_id"] == "SPEAKER_BACK"


def test_llm_refinement_uses_time_when_duplicate_segment_no_is_ambiguous() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "source_segment_no": 1,
          "start_ms": 12000,
          "end_ms": 14000,
          "text": "后排第二句话记录到交付风险。",
          "confidence": 0.86,
          "scenario": "native_speaker"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "source_id": "front",
                "speaker_id": "SPEAKER_FRONT",
                "display_name": "前排设备",
                "source_segment_no": 1,
                "start_ms": 0,
                "end_ms": 5000,
                "text": "前排只听到主持人介绍背景。",
            },
            {
                "source_id": "back",
                "speaker_id": "SPEAKER_BACK",
                "display_name": "后排设备",
                "source_segment_no": 1,
                "start_ms": 10000,
                "end_ms": 15000,
                "text": "后排第二句话记录到交付风险。",
            },
        ],
    )

    assert refined[0]["source_id"] == "back"
    assert refined[0]["display_name"] == "后排设备"
    assert refined[0]["speaker_id"] == "SPEAKER_BACK"


def test_llm_refinement_preserves_source_segment_no_and_marks_context_review() -> None:
    import solorecord_server.llm_adapters as llm_adapters

    content = """
    {
      "segments": [
        {
          "source_index": 2,
          "source_segment_no": 7,
          "speaker": "翼天",
          "speaker_id": "SPEAKER_02",
          "start_ms": 5000,
          "end_ms": 12000,
          "text": "错误样例今天补三类，自动测试明天补完。",
          "confidence": 0.92,
          "scenario": "context_bridge",
          "reason": "上一段点名翼天，当前段继续错误样例和自动测试议题"
        }
      ]
    }
    """
    refined = llm_adapters._parse_refined_segments(
        content,
        [
            {
                "speaker_id": "SPEAKER_01",
                "display_name": "主持人",
                "source_segment_no": 6,
                "start_ms": 0,
                "end_ms": 5000,
                "text": "翼天你先说一下错误样例和自动测试。",
            },
            {
                "speaker_id": "SPEAKER_02",
                "display_name": "发言人 2",
                "source_segment_no": 7,
                "start_ms": 5000,
                "end_ms": 12000,
                "text": "错误样例今天补三类，自动测试明天补完。",
            },
        ],
    )

    assert refined[0]["source_segment_no"] == 7
    assert refined[0]["display_name"] == "翼天"
    assert refined[0]["confidence"] <= 0.78
    assert "speaker_review" in refined[0]["flags"]
    assert "speaker_evidence_weak" not in refined[0]["flags"]
    assert "scenario:context_bridge" in refined[0]["flags"]


def test_llm_residual_rule_refinement_splits_mixed_callout_segment() -> None:
    import solorecord_server.processing as processing

    refined = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "傲寒",
            "start_ms": 0,
            "end_ms": 180000,
            "text": (
                "今天先过整体节奏。"
                "翼天你先说一下错误样例和自动测试。"
                "围城你那个部分，MySQL、PostgreSQL、Oracle 外接数据源要确认。"
                "海春你来讲模型调优和质量检查。"
                "李波后面看登录界面和图标。"
            ),
            "confidence": 0.82,
            "flags": ["llm_refined", "semantic_llm"],
        }
    ]

    split = processing._rule_refine_residual_mixed_segments(refined)

    assert [item["display_name"] for item in split] == ["傲寒", "翼天", "围城", "海春", "李波"]
    assert "整体节奏" in split[0]["text"]
    assert "source_prefix_before_callout" in split[0]["flags"]
    assert "错误样例" in split[1]["text"]
    assert "外接数据源" in split[2]["text"]
    assert "模型调优" in split[3]["text"]
    assert "登录界面" in split[4]["text"]
    assert all("llm_residual_rule_refined" in item["flags"] for item in split)
    assert all("speaker_review" in item["flags"] for item in split)
    assert all(float(item["confidence"]) <= 0.74 for item in split)


def test_llm_residual_rule_refinement_splits_inline_addressed_response() -> None:
    import solorecord_server.processing as processing

    refined = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "主持人",
            "start_ms": 0,
            "end_ms": 18000,
            "text": (
                "翼天你先说一下错误样例和自动测试。"
                "我这边准备了三个错误样例，自动测试明天能补完。"
            ),
            "confidence": 0.82,
            "flags": ["llm_refined", "semantic_llm"],
        }
    ]

    split = processing._rule_refine_residual_mixed_segments(refined)

    assert [item["display_name"] for item in split] == ["主持人", "翼天"]
    assert split[0]["speaker_id"] == "SPEAKER_01"
    assert split[1]["speaker_id"] == "MANUAL_翼天"
    assert "inline_address_prompt" in split[0]["flags"]
    assert "inline_addressed_response" in split[1]["flags"]
    assert "llm_residual_rule_refined" in split[1]["flags"]
    assert "speaker_review" in split[1]["flags"]
    assert split[1]["text"].startswith("我这边准备")


def test_llm_residual_rule_refinement_splits_single_prefixed_callout() -> None:
    import solorecord_server.processing as processing

    refined = [
        {
            "speaker_id": "SPEAKER_01",
            "display_name": "主持人",
            "start_ms": 0,
            "end_ms": 16000,
            "text": "先过整体节奏。翼天你先说一下错误样例和自动测试。",
            "confidence": 0.82,
            "flags": ["llm_refined", "semantic_llm"],
        }
    ]

    split = processing._rule_refine_residual_mixed_segments(refined)

    assert [item["display_name"] for item in split] == ["主持人", "翼天"]
    assert split[0]["text"] == "先过整体节奏。"
    assert split[1]["text"] == "错误样例和自动测试。"
    assert "source_prefix_before_callout" in split[0]["flags"]
    assert all("llm_residual_rule_refined" in item["flags"] for item in split)
    assert all("speaker_review" in item["flags"] for item in split)


def test_quality_report_flags_inline_addressed_response_as_mixed_segment() -> None:
    import solorecord_server.repository as repository

    report = repository.build_quality_report(
        [
            {
                "id": "seg_inline_mixed_1",
                "meeting_id": "meeting_inline_mixed",
                "version": 1,
                "source_id": "primary",
                "source_segment_no": 1,
                "speaker_id": "SPEAKER_01",
                "display_name": "主持人",
                "start_ms": 0,
                "end_ms": 18000,
                "text": (
                    "翼天你先说一下错误样例和自动测试。"
                    "我这边准备了三个错误样例，自动测试明天能补完。"
                ),
                "confidence": 0.82,
                "flags": '["semantic_llm"]',
                "created_at": "now",
            }
        ],
        [],
        [],
        "",
        "",
    )

    assert report["metrics"]["mixed_marker_segment_count"] == 1
    assert any(
        item["type"] == "mixed_speaker_markers"
        for item in report["issues"]
    )


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
    rename_with_alias = client.post(
        f"/api/web/meetings/{meeting_id}/speakers/rename",
        headers=headers,
        json={
            "speaker_id": "SPEAKER_01",
            "display_name": "任旭",
            "aliases": ["报价"],
            "replace_text": True,
        },
    )
    assert rename_with_alias.status_code == 200
    transcript_alias = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    assert transcript_alias["segments"][0]["display_name"] == "任旭"

    sales_user = client.get("/api/web/me", headers=user_headers).json()["user"]
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO meeting_members (meeting_id, user_id, role) VALUES (?, ?, 'editor')",
            (meeting_id, sales_user["id"]),
        )

    user_trim = client.put(
        f"/api/web/meetings/{meeting_id}/transcript",
        headers=user_headers,
        json={"version": transcript_alias["version"], "segments": transcript_alias["segments"][:1]},
    )
    assert user_trim.status_code == 403

    edited_segments = transcript_alias["segments"]
    edited_segments[0]["text"] = "双方确认报价，并安排下周推进合同。"
    edit_transcript = client.put(
        f"/api/web/meetings/{meeting_id}/transcript",
        headers=headers,
        json={"version": transcript_alias["version"], "segments": edited_segments},
    )
    assert edit_transcript.status_code == 200
    assert edit_transcript.json()["segments"][0]["text"] == "双方确认报价，并安排下周推进合同。"
    assert edit_transcript.json()["segments"][0]["display_name"] == "任旭"

    knowledge_transcript = client.get(
        f"/api/external/meetings/{meeting_id}/transcript?include_history=true",
        headers={"Authorization": "Bearer test-token"},
    )
    assert knowledge_transcript.status_code == 200
    knowledge_data = knowledge_transcript.json()
    assert knowledge_data["client"] == "hermes"
    assert knowledge_data["transcript"]["segment_count"] == 2
    assert "双方确认报价" in knowledge_data["transcript"]["plain_text"]
    assert "qualityReport" in knowledge_data
    assert "knowledgeReadiness" in knowledge_data
    assert knowledge_data["knowledgeReadiness"]["evidenceApi"]["transcript"].endswith(
        "/transcript?include_history=true"
    )
    assert len(knowledge_data["transcript"]["history"]) >= 2
    history_reasons = {item["archive_reason"] for item in knowledge_data["transcript"]["history"]}
    assert "user_update" in history_reasons

    update = client.patch(
        f"/api/web/meetings/{meeting_id}",
        headers=headers,
        json={
            "summary": "双方确认报价，下周推进合同。",
            "role_notes": "任旭：确认报价并推进合同。",
        },
    )
    assert update.status_code == 200
    assert update.json()["meeting"]["summary"] == "双方确认报价，下周推进合同。"
    assert update.json()["meeting"]["role_notes"] == "任旭：确认报价并推进合同。"

    actions_update = client.put(
        f"/api/web/meetings/{meeting_id}/actions",
        headers=headers,
        json={
            "items": [
                {
                    "owner": "张三",
                    "task": "周三前补充报价明细",
                    "due": "周三",
                    "status": "doing",
                },
                {
                    "owner": "李四",
                    "task": "确认合同条款",
                    "due": "",
                    "status": "open",
                },
            ]
        },
    )
    assert actions_update.status_code == 200
    action_items = actions_update.json()["actionItems"]
    assert len(action_items) == 2
    assert action_items[0]["owner"] == "张三"
    assert action_items[0]["status"] == "doing"
    graph = actions_update.json()["knowledgeGraph"]
    graph_nodes = {(node["type"], node["label"]) for node in graph["nodes"]}
    graph_edges = {(edge["source_label"], edge["target_label"], edge["label"]) for edge in graph["edges"]}
    assert ("speaker", "张三") in graph_nodes
    assert ("action", "周三前补充报价明细") in graph_nodes
    assert ("time", "周三") in graph_nodes
    assert ("张三", "周三前补充报价明细", "负责") in graph_edges
    assert ("周三前补充报价明细", "周三", "截止") in graph_edges
    guest_login = client.post(
        "/api/auth/demo-login",
        json={"display_name": "Guest", "email": "guest@example.com"},
    ).json()
    guest_headers = {"Authorization": f"Bearer {guest_login['access_token']}"}
    guest_user = client.get("/api/web/me", headers=guest_headers).json()["user"]
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO meeting_members (meeting_id, user_id, role) VALUES (?, ?, 'viewer')",
            (meeting_id, guest_user["id"]),
        )
    assert client.put(
        f"/api/web/meetings/{meeting_id}/actions",
        headers=guest_headers,
        json={"items": [{"owner": "Guest", "task": "无权限改待办", "status": "open"}]},
    ).status_code == 403

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
            "enable_semantic_segmentation": True,
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
    assert provider_config["enable_semantic_segmentation"] is True

    export = client.post(f"/api/web/meetings/{meeting_id}/exports?export_format=markdown", headers=headers)
    assert export.status_code == 200
    assert export.json()["download_url"].startswith("/api/web/exports/")
    export_path = Path(export.json()["path"])
    assert export_path.exists()
    markdown_text = export_path.read_text(encoding="utf-8")
    assert "客户复盘会" in markdown_text
    assert "## 分角色整理" in markdown_text
    assert "任旭：确认报价并推进合同。" in markdown_text
    export_download = client.get(export.json()["download_url"], headers=headers)
    assert export_download.status_code == 200
    json_export = client.post(
        f"/api/web/meetings/{meeting_id}/exports?export_format=json",
        headers=headers,
    )
    assert json_export.status_code == 200
    import json

    exported_json = json.loads(Path(json_export.json()["path"]).read_text(encoding="utf-8"))
    assert exported_json["meeting"]["role_notes"] == "任旭：确认报价并推进合同。"
    assert "qualityReport" in exported_json
    assert "summaryEvidence" in exported_json["qualityReport"]
    detail_after_export = client.get(f"/api/web/meetings/{meeting_id}", headers=headers)
    assert detail_after_export.json()["exports"][0]["download_url"].startswith("/api/web/exports/")
    exported_files = detail_after_export.json()["exports"]
    assert any(item["file_name"].endswith(".md") for item in exported_files)
    assert any(item["file_name"].endswith(".json") for item in exported_files)
    assert all(item["size_bytes"] > 0 for item in exported_files[:2])

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
    assert sync.json()["items"][0]["transcriptSegments"][0]["display_name"] == "任旭"
    assert sync.json()["items"][0]["meeting"]["summary"] == "双方确认报价，下周推进合同。"
    assert sync.json()["items"][0]["meeting"]["role_notes"] == "任旭：确认报价并推进合同。"

    external = client.get("/api/external/meetings", headers={"Authorization": "Bearer test-token"})
    assert external.status_code == 200
    assert external.json()["client"] == "hermes"
    assert external.json()["items"][0]["meeting"]["title"] == "客户复盘会"
    readiness = external.json()["items"][0]["knowledgeReadiness"]
    assert readiness["status"] in {"ready", "review_first", "hold"}
    assert "unsupportedActionCount" in readiness["metrics"]
    assert "reviewEvidence" in readiness
    assert "actionEvidence" in readiness["reviewEvidence"]

    latest_transcript_for_admin = client.get(f"/api/web/meetings/{meeting_id}/transcript", headers=headers).json()
    admin_trim = client.put(
        f"/api/web/meetings/{meeting_id}/transcript",
        headers=headers,
        json={
            "version": latest_transcript_for_admin["version"],
            "segments": latest_transcript_for_admin["segments"][:1],
        },
    )
    assert admin_trim.status_code == 200
    assert len(admin_trim.json()["segments"]) == 1
