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

    public int fetchAudioSegmentMinutes(String serverEndpoint, String token) throws Exception {
        return fetchMobileConfig(serverEndpoint, token).getSegmentMinutes();
    }

    public MobileConfig fetchMobileConfig(String serverEndpoint, String token) throws Exception {
        JSONObject response = httpJsonClient.getJson(url(serverEndpoint, "/api/mobile/config"), token);
        int minutes = response.optInt("segmentMinutes", 5);
        JSONObject asr = response.optJSONObject("asr");
        JSONObject llm = response.optJSONObject("llm");
        return new MobileConfig(
                Math.max(1, Math.min(30, minutes)),
                asr == null ? "" : asr.optString("label", ""),
                llm == null ? "" : llm.optString("label", ""));
    }

    public MeetingRecord createMeeting(String serverEndpoint, String token, String title) throws Exception {
        return createMeeting(serverEndpoint, token, title, "", "", 1);
    }

    public MeetingRecord createMeeting(
            String serverEndpoint,
            String token,
            String title,
            String joinCode,
            String sourceLabel,
            int maxSources) throws Exception {
        JSONObject body = new JSONObject();
        body.put("title", title);
        body.put("join_code", joinCode == null ? "" : joinCode);
        body.put("recording_mode", joinCode == null || joinCode.trim().isEmpty() ? "single" : "multi_source");
        body.put("max_sources", Math.max(1, Math.min(8, maxSources)));
        body.put("source_label", sourceLabel == null ? "" : sourceLabel);
        JSONObject response = httpJsonClient.postJson(url(serverEndpoint, "/api/mobile/meetings"), token, body);
        return parseMeetingResponse(response);
    }

    public MeetingRecord joinMeeting(
            String serverEndpoint,
            String token,
            String title,
            String joinCode,
            String sourceLabel,
            String deviceName) throws Exception {
        JSONObject body = new JSONObject();
        body.put("title", title == null ? "" : title);
        body.put("join_code", joinCode == null ? "" : joinCode);
        body.put("source_label", sourceLabel == null ? "" : sourceLabel);
        body.put("device_name", deviceName == null ? "" : deviceName);
        JSONObject response = httpJsonClient.postJson(url(serverEndpoint, "/api/mobile/meetings/join"), token, body);
        return parseMeetingResponse(response);
    }

    public MeetingRecord uploadAndFinishMeeting(String serverEndpoint, String token, MeetingRecord record) throws Exception {
        return uploadAndFinishMeeting(serverEndpoint, token, record, null);
    }

    public MeetingRecord uploadPendingSegments(
            String serverEndpoint,
            String token,
            MeetingRecord record,
            UploadProgressListener listener) throws Exception {
        UploadContext context = ensureRemoteMeeting(serverEndpoint, token, record, listener);
        MeetingRecord uploaded = uploadPendingSegmentsOnly(serverEndpoint, token, context.record, context.remoteId, listener);
        MeetingRecord refreshed = getMeeting(serverEndpoint, token, context.remoteId);
        return preserveLocalAudioPaths(refreshed, uploaded);
    }

    public MeetingRecord uploadAndFinishMeeting(
            String serverEndpoint,
            String token,
            MeetingRecord record,
            UploadProgressListener listener) throws Exception {
        UploadContext context = ensureRemoteMeeting(serverEndpoint, token, record, listener);
        MeetingRecord uploaded = uploadPendingSegmentsOnly(serverEndpoint, token, context.record, context.remoteId, listener);
        MeetingRecord finished = finishMeeting(serverEndpoint, token, context.remoteId);
        return preserveLocalAudioPaths(finished, uploaded);
    }

    private UploadContext ensureRemoteMeeting(
            String serverEndpoint,
            String token,
            MeetingRecord record,
            UploadProgressListener listener) throws Exception {
        String remoteMeetingId = record.getId().startsWith("mtg_") ? record.getId() : "";
        if (remoteMeetingId.isEmpty()) {
            MeetingRecord remote = record.getJoinCode().isEmpty()
                    ? createMeeting(serverEndpoint, token, record.getTitle(), "", record.getSourceLabel(), 1)
                    : joinMeeting(
                    serverEndpoint,
                    token,
                    record.getTitle(),
                    record.getJoinCode(),
                    record.getSourceLabel(),
                    "Android");
            String sourceId = remote.getSourceId().isEmpty() ? record.getSourceId() : remote.getSourceId();
            String sourceLabel = remote.getSourceLabel().isEmpty() ? record.getSourceLabel() : remote.getSourceLabel();
            record = record.withId(remote.getId(), "uploading")
                    .withRecordingSource(record.getJoinCode(), sourceId, sourceLabel);
            if (listener != null) {
                listener.onRemoteMeetingReady(record);
            }
            return new UploadContext(record, remote.getId());
        }
        return new UploadContext(record, remoteMeetingId);
    }

    private MeetingRecord uploadPendingSegmentsOnly(
            String serverEndpoint,
            String token,
            MeetingRecord record,
            String remoteMeetingId,
            UploadProgressListener listener) throws Exception {
        for (AudioSegment segment : record.getAudioSegments()) {
            if (segment.isUploaded()) {
                continue;
            }
            if (segment.isOpenRecording()) {
                continue;
            }
            File file = new File(segment.getPath());
            if (file.exists()) {
                JSONObject upload = uploadSegment(serverEndpoint, token, remoteMeetingId, record, segment);
                int serverSegmentNo = upload.optInt("segmentNo", segment.getSegmentNo());
                record = record.withUploadedSegment(segment, serverSegmentNo);
                if (listener != null) {
                    listener.onSegmentUploaded(record, segment.withServerSegmentNo(serverSegmentNo, "uploaded"));
                }
            } else {
                throw new java.io.IOException("本地音频分段不可用：" + segment.getSegmentNo());
            }
        }
        return record;
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

    public JSONObject uploadSegment(
            String serverEndpoint,
            String token,
            String meetingId,
            AudioSegment segment) throws Exception {
        return uploadSegment(serverEndpoint, token, meetingId, null, segment);
    }

    public JSONObject uploadSegment(
            String serverEndpoint,
            String token,
            String meetingId,
            MeetingRecord record,
            AudioSegment segment) throws Exception {
        File file = new File(segment.getPath());
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("segment_no", String.valueOf(segment.getSegmentNo()));
        fields.put("source_id", record == null ? "primary" : record.getSourceId());
        fields.put("source_label", record == null ? "" : record.getSourceLabel());
        fields.put("source_segment_no", String.valueOf(segment.getSourceSegmentNo()));
        fields.put("start_ms", String.valueOf(segment.getStartMillis()));
        fields.put("end_ms", String.valueOf(segment.getEndMillis()));
        fields.put("duration_ms", String.valueOf(segment.getEndMillis() - segment.getStartMillis()));
        return httpJsonClient.postMultipartFile(
                url(serverEndpoint, "/api/mobile/meetings/" + meetingId + "/segments"),
                token,
                fields,
                "file",
                file,
                mimeTypeFor(file));
    }

    public File downloadSegment(String serverEndpoint, String token, AudioSegment segment, File outputDir) throws Exception {
        String downloadUrl = segment.getDownloadUrl();
        if (downloadUrl.isEmpty()) {
            throw new Exception("服务器音频地址不可用");
        }
        if (!outputDir.exists() && !outputDir.mkdirs()) {
            throw new Exception("无法创建音频缓存目录");
        }
        File output = new File(outputDir, String.format(
                "remote_part_%04d%s",
                segment.getSegmentNo(),
                extensionFor(segment)));
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
        JSONObject local = serverMeetingToLocal(meeting, audioSegments, transcriptSegments, actions);
        JSONArray sources = response.optJSONArray("recordingSources");
        if (sources != null && sources.length() > 0) {
            JSONObject source = sources.optJSONObject(0);
            if (source != null) {
                try {
                    local.put("sourceId", source.optString("source_id", "primary"));
                    local.put("sourceLabel", source.optString("label"));
                } catch (Exception ignored) {
                    // Optional source metadata should not block meeting sync.
                }
            }
        }
        JSONObject joinedSource = response.optJSONObject("joinedSource");
        if (joinedSource != null) {
            try {
                local.put("sourceId", joinedSource.optString("source_id", local.optString("sourceId", "primary")));
                local.put("sourceLabel", joinedSource.optString("label", local.optString("sourceLabel")));
            } catch (Exception ignored) {
                // Optional source metadata should not block meeting sync.
            }
        }
        return MeetingRecord.fromJson(local);
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
            local.put("joinCode", meeting.optString("join_code"));
            JSONArray audio = new JSONArray();
            if (serverAudioSegments != null) {
                for (int i = 0; i < serverAudioSegments.length(); i++) {
                    JSONObject item = serverAudioSegments.optJSONObject(i);
                    if (item != null) {
                        JSONObject segment = new JSONObject();
                        segment.put("segmentNo", item.optInt("segment_no", i + 1));
                        segment.put("path", item.optString("storage_path"));
                        segment.put("downloadUrl", item.optString("download_url"));
                        segment.put("sourceId", item.optString("source_id", "primary"));
                        segment.put("sourceSegmentNo", item.optInt("source_segment_no", item.optInt("segment_no", i + 1)));
                        segment.put("sourceLabel", item.optString("source_label"));
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
            AudioSegment localSegment = findMatchingLocalSegment(localRecord.getAudioSegments(), serverSegment);
            if (localSegment != null && new File(localSegment.getPath()).exists()) {
                merged.add(new AudioSegment(
                        serverSegment.getSegmentNo(),
                        localSegment.getPath(),
                        localSegment.getStartMillis(),
                        localSegment.getEndMillis(),
                        "uploaded",
                        serverSegment.getDownloadUrl(),
                        serverSegment.getSourceId(),
                        serverSegment.getSourceSegmentNo(),
                        serverSegment.getSourceLabel()));
            } else {
                merged.add(serverSegment);
            }
        }
        for (AudioSegment localSegment : localRecord.getAudioSegments()) {
            if (findMatchingLocalSegment(merged, localSegment) == null) {
                merged.add(localSegment);
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
        return findSegment(record.getAudioSegments(), segmentNo);
    }

    private AudioSegment findSegment(List<AudioSegment> segments, int segmentNo) {
        for (AudioSegment segment : segments) {
            if (segment.getSegmentNo() == segmentNo) {
                return segment;
            }
        }
        return null;
    }

    private AudioSegment findMatchingLocalSegment(List<AudioSegment> segments, AudioSegment serverSegment) {
        for (AudioSegment segment : segments) {
            if (segment.getSourceId().equals(serverSegment.getSourceId())
                    && segment.getSourceSegmentNo() == serverSegment.getSourceSegmentNo()) {
                return segment;
            }
        }
        if ("primary".equals(serverSegment.getSourceId())) {
            return findSegment(segments, serverSegment.getSourceSegmentNo());
        }
        return null;
    }

    private String mimeTypeFor(File file) {
        String name = file.getName().toLowerCase();
        if (name.endsWith(".wav")) {
            return "audio/wav";
        }
        if (name.endsWith(".m4a") || name.endsWith(".mp4")) {
            return "audio/mp4";
        }
        return "application/octet-stream";
    }

    private String extensionFor(AudioSegment segment) {
        String path = segment.getPath().toLowerCase();
        String downloadUrl = segment.getDownloadUrl().toLowerCase();
        if (path.endsWith(".wav") || downloadUrl.endsWith(".wav")) {
            return ".wav";
        }
        return ".m4a";
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

    private static final class UploadContext {
        private final MeetingRecord record;
        private final String remoteId;

        UploadContext(MeetingRecord record, String remoteId) {
            this.record = record;
            this.remoteId = remoteId;
        }
    }

    public static final class MobileConfig {
        private final int segmentMinutes;
        private final String asrLabel;
        private final String llmLabel;

        MobileConfig(int segmentMinutes, String asrLabel, String llmLabel) {
            this.segmentMinutes = segmentMinutes;
            this.asrLabel = asrLabel == null ? "" : asrLabel;
            this.llmLabel = llmLabel == null ? "" : llmLabel;
        }

        public int getSegmentMinutes() {
            return segmentMinutes;
        }

        public String getAsrLabel() {
            return asrLabel;
        }

        public String getLlmLabel() {
            return llmLabel;
        }
    }
}
