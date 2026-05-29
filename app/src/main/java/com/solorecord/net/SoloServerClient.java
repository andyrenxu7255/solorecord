package com.solorecord.net;

import com.solorecord.model.ActionItem;
import com.solorecord.model.AudioSegment;
import com.solorecord.model.MeetingRecord;
import com.solorecord.model.TranscriptSegment;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class SoloServerClient {
    private final HttpJsonClient httpJsonClient = new HttpJsonClient();

    public interface UploadProgressListener {
        void onRemoteMeetingReady(MeetingRecord record) throws Exception;

        void onSegmentUploaded(MeetingRecord record, AudioSegment segment) throws Exception;
    }

    public LoginResult ldapLogin(String serverEndpoint, String username, String password) throws Exception {
        JSONObject body = new JSONObject();
        body.put("username", username);
        body.put("password", password);
        JSONObject response = httpJsonClient.postJson(url(serverEndpoint, "/api/auth/ldap-login"), "", body);
        JSONObject user = response.optJSONObject("user");
        return new LoginResult(
                response.optString("access_token"),
                user == null ? username : user.optString("display_name", username),
                user == null ? "" : user.optString("email", ""));
    }

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
        return uploadAndFinishMeeting(serverEndpoint, token, record, null);
    }

    public MeetingRecord uploadAndFinishMeeting(
            String serverEndpoint,
            String token,
            MeetingRecord record,
            UploadProgressListener listener) throws Exception {
        String remoteMeetingId = record.getId().startsWith("mtg_") ? record.getId() : "";
        MeetingRecord remote = remoteMeetingId.isEmpty()
                ? createMeeting(serverEndpoint, token, record.getTitle())
                : getMeeting(serverEndpoint, token, remoteMeetingId);
        if (remoteMeetingId.isEmpty()) {
            record = record.withId(remote.getId(), "uploading");
            if (listener != null) {
                listener.onRemoteMeetingReady(record);
            }
        }
        for (AudioSegment segment : record.getAudioSegments()) {
            if (segment.isUploaded()) {
                continue;
            }
            File file = new File(segment.getPath());
            if (file.exists()) {
                uploadSegment(serverEndpoint, token, remote.getId(), segment);
                record = record.withSegmentUploadStatus(segment.getSegmentNo(), "uploaded");
                if (listener != null) {
                    listener.onSegmentUploaded(record, segment.withUploadStatus("uploaded"));
                }
            } else {
                throw new java.io.IOException("本地音频分段不可用：" + segment.getSegmentNo());
            }
        }
        MeetingRecord finished = finishMeeting(serverEndpoint, token, remote.getId());
        return preserveLocalAudioPaths(finished, record);
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

    public void uploadSegment(
            String serverEndpoint,
            String token,
            String meetingId,
            AudioSegment segment) throws Exception {
        File file = new File(segment.getPath());
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("segment_no", String.valueOf(segment.getSegmentNo()));
        fields.put("start_ms", String.valueOf(segment.getStartMillis()));
        fields.put("end_ms", String.valueOf(segment.getEndMillis()));
        fields.put("duration_ms", String.valueOf(segment.getEndMillis() - segment.getStartMillis()));
        httpJsonClient.postMultipartFile(
                url(serverEndpoint, "/api/mobile/meetings/" + meetingId + "/segments"),
                token,
                fields,
                "file",
                file,
                "audio/mp4");
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

    private MeetingRecord preserveLocalAudioPaths(MeetingRecord serverRecord, MeetingRecord localRecord) {
        List<AudioSegment> merged = new ArrayList<>();
        for (AudioSegment serverSegment : serverRecord.getAudioSegments()) {
            AudioSegment localSegment = findSegment(localRecord, serverSegment.getSegmentNo());
            if (localSegment != null && new File(localSegment.getPath()).exists()) {
                merged.add(new AudioSegment(
                        serverSegment.getSegmentNo(),
                        localSegment.getPath(),
                        localSegment.getStartMillis(),
                        localSegment.getEndMillis(),
                        "uploaded",
                        serverSegment.getDownloadUrl()));
            } else {
                merged.add(serverSegment);
            }
        }
        if (merged.isEmpty()) {
            for (AudioSegment localSegment : localRecord.getAudioSegments()) {
                merged.add(localSegment.withUploadStatus("uploaded"));
            }
        }
        return serverRecord.withAudioSegments(merged, serverRecord.getStatus());
    }

    private AudioSegment findSegment(MeetingRecord record, int segmentNo) {
        for (AudioSegment segment : record.getAudioSegments()) {
            if (segment.getSegmentNo() == segmentNo) {
                return segment;
            }
        }
        return null;
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
