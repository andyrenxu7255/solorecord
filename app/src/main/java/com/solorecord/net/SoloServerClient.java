package com.solorecord.net;

import android.util.Base64;

import com.solorecord.model.ActionItem;
import com.solorecord.model.AudioSegment;
import com.solorecord.model.MeetingRecord;
import com.solorecord.model.TranscriptSegment;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class SoloServerClient {
    private final HttpJsonClient httpJsonClient = new HttpJsonClient();

    public LoginResult demoLogin(String serverEndpoint, String displayName, String email) throws Exception {
        JSONObject body = new JSONObject();
        body.put("display_name", displayName);
        body.put("email", email);
        JSONObject response = httpJsonClient.postJson(url(serverEndpoint, "/api/auth/demo-login"), "", body);
        JSONObject user = response.optJSONObject("user");
        return new LoginResult(
                response.optString("access_token"),
                user == null ? displayName : user.optString("display_name", displayName),
                user == null ? email : user.optString("email", email));
    }

    public List<MeetingRecord> syncMeetings(String serverEndpoint, String token) throws Exception {
        JSONObject response = httpJsonClient.getJson(url(serverEndpoint, "/api/mobile/sync"), token);
        JSONArray items = response.optJSONArray("items");
        if (items == null) {
            return Collections.emptyList();
        }
        List<MeetingRecord> records = new ArrayList<>();
        for (int i = 0; i < items.length(); i++) {
            JSONObject item = items.optJSONObject(i);
            if (item != null) {
                records.add(parseMeetingResponse(item));
            }
        }
        return records;
    }

    public MeetingRecord createMeeting(String serverEndpoint, String token, String title) throws Exception {
        JSONObject body = new JSONObject();
        body.put("title", title);
        JSONObject response = httpJsonClient.postJson(url(serverEndpoint, "/api/mobile/meetings"), token, body);
        return parseMeetingResponse(response);
    }

    public MeetingRecord uploadAndFinishMeeting(String serverEndpoint, String token, MeetingRecord record) throws Exception {
        String remoteMeetingId = record.getId().startsWith("mtg_") ? record.getId() : "";
        MeetingRecord remote = remoteMeetingId.isEmpty()
                ? createMeeting(serverEndpoint, token, record.getTitle())
                : getMeeting(serverEndpoint, token, remoteMeetingId);
        for (AudioSegment segment : record.getAudioSegments()) {
            File file = new File(segment.getPath());
            if (file.exists()) {
                uploadSegmentBase64(serverEndpoint, token, remote.getId(), segment);
            }
        }
        return finishMeeting(serverEndpoint, token, remote.getId());
    }

    public MeetingRecord finishMeeting(String serverEndpoint, String token, String meetingId) throws Exception {
        httpJsonClient.postJson(url(serverEndpoint, "/api/mobile/meetings/" + meetingId + "/finish"), token, new JSONObject());
        return getMeeting(serverEndpoint, token, meetingId);
    }

    public MeetingRecord processMeeting(String serverEndpoint, String token, String meetingId) throws Exception {
        httpJsonClient.postJson(url(serverEndpoint, "/api/mobile/meetings/" + meetingId + "/process"), token, new JSONObject());
        return getMeeting(serverEndpoint, token, meetingId);
    }

    public MeetingRecord getMeeting(String serverEndpoint, String token, String meetingId) throws Exception {
        JSONObject response = httpJsonClient.getJson(url(serverEndpoint, "/api/mobile/meetings/" + meetingId), token);
        MeetingRecord base = parseMeetingResponse(response);
        JSONObject transcript = httpJsonClient.getJson(url(serverEndpoint, "/api/mobile/meetings/" + meetingId + "/transcript"), token);
        return mergeTranscript(base, transcript);
    }

    public List<MeetingRecord> listMeetings(String serverEndpoint, String token) throws Exception {
        JSONObject response = httpJsonClient.getJson(url(serverEndpoint, "/api/mobile/meetings"), token);
        JSONArray items = response.optJSONArray("items");
        if (items == null) {
            return Collections.emptyList();
        }
        List<MeetingRecord> records = new ArrayList<>();
        for (int i = 0; i < items.length(); i++) {
            JSONObject item = items.optJSONObject(i);
            if (item != null) {
                records.add(MeetingRecord.fromJson(serverMeetingToLocal(item, null, null, null)));
            }
        }
        return records;
    }

    public void renameSpeaker(String serverEndpoint, String token, String meetingId, String speakerId, String displayName)
            throws Exception {
        JSONObject body = new JSONObject();
        body.put("speaker_id", speakerId);
        body.put("display_name", displayName);
        httpJsonClient.postJson(
                url(serverEndpoint, "/api/mobile/meetings/" + meetingId + "/speakers/rename"),
                token,
                body);
    }

    public void uploadSegmentBase64(
            String serverEndpoint,
            String token,
            String meetingId,
            AudioSegment segment) throws Exception {
        File file = new File(segment.getPath());
        JSONObject body = new JSONObject();
        body.put("segment_no", segment.getSegmentNo());
        body.put("start_ms", segment.getStartMillis());
        body.put("end_ms", segment.getEndMillis());
        body.put("duration_ms", segment.getEndMillis() - segment.getStartMillis());
        body.put("file_name", file.getName());
        body.put("audio_base64", readBase64(file));
        httpJsonClient.postJson(
                url(serverEndpoint, "/api/mobile/meetings/" + meetingId + "/segments-json"),
                token,
                body);
    }

    public File downloadSegment(String serverEndpoint, String token, AudioSegment segment, File outputDir) throws Exception {
        String downloadUrl = segment.getDownloadUrl();
        if (downloadUrl.isEmpty()) {
            throw new Exception("服务器音频地址不可用");
        }
        if (!outputDir.exists() && !outputDir.mkdirs()) {
            throw new Exception("无法创建音频缓存目录");
        }
        File output = new File(outputDir, String.format("remote_part_%04d.m4a", segment.getSegmentNo()));
        byte[] bytes = httpJsonClient.getBytes(url(serverEndpoint, downloadUrl), token);
        try (FileOutputStream stream = new FileOutputStream(output)) {
            stream.write(bytes);
        }
        return output;
    }

    public ReleaseInfo latestRelease(String serverEndpoint, String token) throws Exception {
        JSONObject response = httpJsonClient.getJson(url(serverEndpoint, "/api/mobile/releases/latest"), token);
        JSONObject release = response.optJSONObject("release");
        if (release == null) {
            return null;
        }
        return new ReleaseInfo(
                release.optString("version_name"),
                release.optInt("version_code"),
                release.optString("downloadUrl"),
                release.optString("release_notes"));
    }

    private MeetingRecord parseMeetingResponse(JSONObject response) {
        JSONObject meeting = response.optJSONObject("meeting");
        JSONArray audioSegments = response.optJSONArray("audioSegments");
        JSONArray transcriptSegments = response.optJSONArray("transcriptSegments");
        JSONArray actions = response.optJSONArray("actionItems");
        return MeetingRecord.fromJson(serverMeetingToLocal(meeting, audioSegments, transcriptSegments, actions));
    }

    private MeetingRecord mergeTranscript(MeetingRecord base, JSONObject transcript) {
        JSONObject local = baseToJson(base);
        try {
            JSONArray serverSegments = transcript.optJSONArray("segments");
            JSONArray localSegments = new JSONArray();
            if (serverSegments != null) {
                for (int i = 0; i < serverSegments.length(); i++) {
                    JSONObject item = serverSegments.optJSONObject(i);
                    if (item != null) {
                        JSONObject segment = new JSONObject();
                        segment.put("speakerId", item.optString("speaker_id"));
                        segment.put("speaker", item.optString("display_name", item.optString("speaker_id")));
                        segment.put("text", item.optString("text"));
                        segment.put("startMillis", item.optLong("start_ms"));
                        segment.put("endMillis", item.optLong("end_ms"));
                        localSegments.put(segment);
                    }
                }
            }
            local.put("transcriptSegments", localSegments);
            return MeetingRecord.fromJson(local);
        } catch (Exception ignored) {
            return base;
        }
    }

    private JSONObject serverMeetingToLocal(
            JSONObject meeting,
            JSONArray serverAudioSegments,
            JSONArray serverTranscriptSegments,
            JSONArray serverActionItems) {
        JSONObject local = new JSONObject();
        try {
            if (meeting == null) {
                return local;
            }
            local.put("id", meeting.optString("id"));
            local.put("title", meeting.optString("title"));
            local.put("createdAtMillis", System.currentTimeMillis());
            local.put("status", meeting.optString("status"));
            local.put("summary", meeting.optString("summary"));
            local.put("roleNotes", meeting.optString("role_notes"));
            JSONArray audio = new JSONArray();
            if (serverAudioSegments != null) {
                for (int i = 0; i < serverAudioSegments.length(); i++) {
                    JSONObject item = serverAudioSegments.optJSONObject(i);
                    if (item != null) {
                        JSONObject segment = new JSONObject();
                        segment.put("segmentNo", item.optInt("segment_no", i + 1));
                        segment.put("path", item.optString("storage_path"));
                        segment.put("downloadUrl", item.optString("download_url"));
                        segment.put("startMillis", item.optLong("start_ms"));
                        segment.put("endMillis", item.optLong("end_ms"));
                        segment.put("uploadStatus", item.optString("upload_status", "uploaded"));
                        audio.put(segment);
                    }
                }
            }
            local.put("audioSegments", audio);
            local.put("transcriptSegments", serverTranscriptSegments == null ? new JSONArray() : serverTranscriptSegments);
            local.put("actionItems", serverActionItems == null ? new JSONArray() : serverActionItems);
        } catch (Exception ignored) {
            return local;
        }
        return local;
    }

    private JSONObject baseToJson(MeetingRecord record) {
        try {
            return record.toJson();
        } catch (Exception ignored) {
            return new JSONObject();
        }
    }

    private String readBase64(File audioFile) throws Exception {
        byte[] bytes = new byte[(int) audioFile.length()];
        int offset = 0;
        try (FileInputStream inputStream = new FileInputStream(audioFile)) {
            while (offset < bytes.length) {
                int read = inputStream.read(bytes, offset, bytes.length - offset);
                if (read < 0) {
                    break;
                }
                offset += read;
            }
        }
        return Base64.encodeToString(bytes, Base64.NO_WRAP);
    }

    private String url(String serverEndpoint, String path) {
        String base = serverEndpoint == null ? "" : serverEndpoint.trim();
        while (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        return base + path;
    }

    public static final class LoginResult {
        private final String token;
        private final String displayName;
        private final String email;

        LoginResult(String token, String displayName, String email) {
            this.token = token == null ? "" : token;
            this.displayName = displayName == null ? "" : displayName;
            this.email = email == null ? "" : email;
        }

        public String getToken() {
            return token;
        }

        public String getDisplayName() {
            return displayName;
        }

        public String getEmail() {
            return email;
        }
    }

    public static final class ReleaseInfo {
        private final String versionName;
        private final int versionCode;
        private final String downloadUrl;
        private final String releaseNotes;

        ReleaseInfo(String versionName, int versionCode, String downloadUrl, String releaseNotes) {
            this.versionName = versionName == null ? "" : versionName;
            this.versionCode = versionCode;
            this.downloadUrl = downloadUrl == null ? "" : downloadUrl;
            this.releaseNotes = releaseNotes == null ? "" : releaseNotes;
        }

        public String getVersionName() {
            return versionName;
        }

        public int getVersionCode() {
            return versionCode;
        }

        public String getDownloadUrl() {
            return downloadUrl;
        }

        public String getReleaseNotes() {
            return releaseNotes;
        }
    }
}
