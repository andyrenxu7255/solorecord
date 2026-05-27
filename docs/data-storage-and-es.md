# SoloRecord Data Storage And ES/OpenSearch

## Authoritative Storage

The server is the authoritative source of record after login. Android local
storage is only a cache for current-device recording and offline playback.

Server-side stored data:

- `users`: Synology/demo login identity, display name, email, role.
- `sessions`: hashed short-lived server session tokens.
- `meetings`: title, owner user id, status, timestamps, duration, summary,
  role notes, transcript version.
- `meeting_members`: which logged-in users can read/write a meeting.
- `audio_segments`: uploaded audio segment metadata and storage path.
- `transcript_segments`: timestamped transcript rows, stable speaker id,
  display name, confidence, flags.
- `speakers`: corrected speaker-name mapping per meeting.
- `action_items`: owner/task/due/status extracted from the meeting.
- `processing_jobs`: ASR/LLM/index/forwarding progress and failures.
- `audit_logs`: create/update/upload/process/rename/export/admin operations.

Because each meeting has `owner_id` and `meeting_members`, reinstalling the APK
does not lose server data. After login, the app can call:

```text
GET /api/mobile/sync
GET /api/mobile/meetings
GET /api/mobile/meetings/{meetingId}
GET /api/mobile/meetings/{meetingId}/transcript
GET /api/mobile/meetings/{meetingId}/segments/{segmentNo}/audio
```

and rebuild its local records from the server.

The audio endpoint requires the same meeting read permission. It lets a
reinstalled APK download a server-side audio segment on demand before playback,
instead of exposing raw storage paths directly.

## Login User Recording

Every protected API call resolves the current user from the bearer token. The
server records user identity in:

- `meetings.owner_id`
- `meeting_members.user_id`
- `audit_logs.actor_user_id`

Meeting detail responses include:

```json
{
  "owner": {
    "id": "usr_xxx",
    "display_name": "张三",
    "email": "zhangsan@example.com"
  },
  "members": [
    {
      "role": "owner",
      "id": "usr_xxx",
      "display_name": "张三",
      "email": "zhangsan@example.com"
    }
  ]
}
```

## External Business API

Other internal systems can read meeting data through a server-to-server token:

```text
SOLO_EXTERNAL_API_TOKENS=hermes:replace-with-long-random-token,crm:another-token
```

Then call:

```http
GET /api/external/meetings
Authorization: Bearer replace-with-long-random-token
```

or:

```http
GET /api/external/meetings/{meetingId}
Authorization: Bearer replace-with-long-random-token
```

The response contains meeting metadata, owner, members, transcript segments,
speaker mappings, action items, and merged `searchText`.

## ES/OpenSearch

ES/OpenSearch is optional and should be treated as a search/index layer, not the
only copy of business data.

Enable from `server/.env` or Web admin:

```text
SOLO_ES_ENABLED=true
SOLO_ES_URL=http://127.0.0.1:9200
SOLO_ES_INDEX=solorecord_meetings
SOLO_ES_API_KEY=
SOLO_ES_USERNAME=
SOLO_ES_PASSWORD=
```

The server indexes a meeting after:

- ASR/summary processing succeeds.
- Transcript is manually edited.
- Speaker is renamed.
- Meeting title/summary is edited.

Admin can rebuild the index:

```text
POST /api/admin/search/reindex
```

Indexed document shape:

```json
{
  "meeting_id": "mtg_xxx",
  "title": "客户复盘会",
  "status": "ready",
  "owner_id": "usr_xxx",
  "owner_name": "张三",
  "owner_email": "zhangsan@example.com",
  "summary": "会议纪要正文",
  "role_notes": "分角色整理",
  "speakers": [{"speaker_id": "SPEAKER_01", "display_name": "张三"}],
  "transcript": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "张三",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "我们今天确认报价。"
    }
  ],
  "action_items": [
    {"owner": "李四", "task": "整理报价单", "due": "下周一", "status": "open"}
  ],
  "search_text": "标题、纪要、转写、待办合并文本"
}
```

## Recommended Deployment

For tomorrow's first server:

- SQLite is acceptable for validation and demo.
- Mount `var/` to persistent disk.
- Enable external API token if Hermes needs to pull records.
- Enable ES/OpenSearch only if another system needs full-text search or the
  meeting volume is already large.

For production:

- Migrate business DB to PostgreSQL.
- Keep audio/object files on NAS/S3-compatible storage.
- Use ES/OpenSearch for search and downstream analytics.
- Back up DB and object storage separately.
