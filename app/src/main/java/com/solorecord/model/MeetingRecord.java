package com.solorecord.model;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.UUID;

public final class MeetingRecord {
    private final String id;
    private final String title;
    private final long createdAtMillis;
    private final String audioPath;
    private final List<AudioSegment> audioSegments;
    private final String status;
    private final List<TranscriptSegment> transcriptSegments;
    private final String roleNotes;
    private final String summary;
    private final List<ActionItem> actionItems;
    private final String joinCode;
    private final String sourceId;
    private final String sourceLabel;

    public MeetingRecord(
            String id,
            String title,
            long createdAtMillis,
            String audioPath,
            List<AudioSegment> audioSegments,
            String status,
            List<TranscriptSegment> transcriptSegments,
            String roleNotes,
            String summary,
            List<ActionItem> actionItems) {
        this(id, title, createdAtMillis, audioPath, audioSegments, status, transcriptSegments,
                roleNotes, summary, actionItems, "", "primary", "");
    }

    public MeetingRecord(
            String id,
            String title,
            long createdAtMillis,
            String audioPath,
            List<AudioSegment> audioSegments,
            String status,
            List<TranscriptSegment> transcriptSegments,
            String roleNotes,
            String summary,
            List<ActionItem> actionItems,
            String joinCode,
            String sourceId,
            String sourceLabel) {
        this.id = safe(id).isEmpty() ? UUID.randomUUID().toString() : safe(id);
        this.title = safe(title).isEmpty() ? "未命名会议" : safe(title);
        this.createdAtMillis = createdAtMillis <= 0 ? System.currentTimeMillis() : createdAtMillis;
        this.audioPath = safe(audioPath);
        this.audioSegments = immutableAudioSegments(audioSegments);
        this.status = safe(status).isEmpty() ? "draft" : safe(status);
        this.transcriptSegments = immutableSegments(transcriptSegments);
        this.roleNotes = safe(roleNotes);
        this.summary = safe(summary);
        this.actionItems = immutableActionItems(actionItems);
        this.joinCode = safe(joinCode);
        this.sourceId = safe(sourceId).isEmpty() ? "primary" : safe(sourceId);
        this.sourceLabel = safe(sourceLabel);
    }

    public static MeetingRecord createDraft(String title, String audioPath) {
        return new MeetingRecord(
                UUID.randomUUID().toString(),
                title,
                System.currentTimeMillis(),
                audioPath,
                Collections.singletonList(new AudioSegment(1, audioPath, 0, 0, "local")),
                "recorded",
                Collections.emptyList(),
                "",
                "",
                Collections.emptyList());
    }

    public static MeetingRecord fromJson(JSONObject json) {
        JSONArray transcriptJson = json.optJSONArray("transcriptSegments");
        List<TranscriptSegment> segments = new ArrayList<>();
        if (transcriptJson != null) {
            for (int i = 0; i < transcriptJson.length(); i++) {
                JSONObject item = transcriptJson.optJSONObject(i);
                if (item != null) {
                    segments.add(TranscriptSegment.fromJson(item));
                }
            }
        }

        JSONArray actionJson = json.optJSONArray("actionItems");
        List<ActionItem> items = new ArrayList<>();
        if (actionJson != null) {
            for (int i = 0; i < actionJson.length(); i++) {
                JSONObject item = actionJson.optJSONObject(i);
                if (item != null) {
                    items.add(ActionItem.fromJson(item));
                }
            }
        }

        JSONArray audioJson = json.optJSONArray("audioSegments");
        List<AudioSegment> audioSegments = new ArrayList<>();
        if (audioJson != null) {
            for (int i = 0; i < audioJson.length(); i++) {
                JSONObject item = audioJson.optJSONObject(i);
                if (item != null) {
                    audioSegments.add(AudioSegment.fromJson(item));
                }
            }
        } else if (!json.optString("audioPath").isEmpty()) {
            audioSegments.add(new AudioSegment(1, json.optString("audioPath"), 0, 0, "local"));
        }

        return new MeetingRecord(
                json.optString("id"),
                json.optString("title"),
                json.optLong("createdAtMillis"),
                json.optString("audioPath"),
                audioSegments,
                json.optString("status"),
                segments,
                json.optString("roleNotes"),
                json.optString("summary"),
                items,
                json.optString("joinCode", json.optString("join_code")),
                json.optString("sourceId", json.optString("source_id", "primary")),
                json.optString("sourceLabel", json.optString("source_label")));
    }

    public JSONObject toJson() throws JSONException {
        JSONObject json = new JSONObject();
        json.put("id", id);
        json.put("title", title);
        json.put("createdAtMillis", createdAtMillis);
        json.put("audioPath", audioPath);
        json.put("status", status);
        json.put("roleNotes", roleNotes);
        json.put("summary", summary);
        json.put("joinCode", joinCode);
        json.put("sourceId", sourceId);
        json.put("sourceLabel", sourceLabel);

        JSONArray transcriptJson = new JSONArray();
        for (TranscriptSegment segment : transcriptSegments) {
            transcriptJson.put(segment.toJson());
        }
        json.put("transcriptSegments", transcriptJson);

        JSONArray audioJson = new JSONArray();
        for (AudioSegment segment : audioSegments) {
            audioJson.put(segment.toJson());
        }
        json.put("audioSegments", audioJson);

        JSONArray actionJson = new JSONArray();
        for (ActionItem item : actionItems) {
            actionJson.put(item.toJson());
        }
        json.put("actionItems", actionJson);
        return json;
    }

    public MeetingRecord withProcessedContent(
            List<TranscriptSegment> segments,
            String newRoleNotes,
            String newSummary,
            List<ActionItem> items) {
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                audioPath,
                audioSegments,
                "processed",
                segments,
                newRoleNotes,
                newSummary,
                items,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public MeetingRecord withStatus(String newStatus) {
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                audioPath,
                audioSegments,
                newStatus,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public String getId() {
        return id;
    }

    public String getTitle() {
        return title;
    }

    public long getCreatedAtMillis() {
        return createdAtMillis;
    }

    public String getAudioPath() {
        return audioPath;
    }

    public List<AudioSegment> getAudioSegments() {
        return audioSegments;
    }

    public String getStatus() {
        return status;
    }

    public List<TranscriptSegment> getTranscriptSegments() {
        return transcriptSegments;
    }

    public String getRoleNotes() {
        return roleNotes;
    }

    public String getSummary() {
        return summary;
    }

    public List<ActionItem> getActionItems() {
        return actionItems;
    }

    public String getJoinCode() {
        return joinCode;
    }

    public String getSourceId() {
        return sourceId;
    }

    public String getSourceLabel() {
        return sourceLabel;
    }

    public MeetingRecord withAudioSegments(List<AudioSegment> segments, String newStatus) {
        List<AudioSegment> normalized = normalizeLocalAudioSegments(segments);
        String firstPath = normalized.isEmpty() ? audioPath : normalized.get(0).getPath();
        List<AudioSegment> merged = mergeUploadStatuses(normalized);
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                firstPath,
                merged,
                newStatus,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public MeetingRecord withId(String newId, String newStatus) {
        return new MeetingRecord(
                newId,
                title,
                createdAtMillis,
                audioPath,
                audioSegments,
                newStatus,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public MeetingRecord withAudioFrom(MeetingRecord other) {
        if (other == null) {
            return this;
        }
        String mergedAudioPath = other.getAudioPath().isEmpty() ? audioPath : other.getAudioPath();
        List<AudioSegment> mergedSegments = mergeAudioSegmentsByNumber(audioSegments, other.getAudioSegments());
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                mergedAudioPath,
                mergedSegments,
                status,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public MeetingRecord withSegmentUploadStatus(int segmentNo, String uploadStatus) {
        return withSegmentUploadStatus(segmentNo, "", 0, uploadStatus);
    }

    public MeetingRecord withSegmentUploadStatus(
            int segmentNo,
            String uploadedSourceId,
            int uploadedSourceSegmentNo,
            String uploadStatus) {
        List<AudioSegment> updated = new ArrayList<>();
        for (AudioSegment segment : audioSegments) {
            if (matchesAudioSegment(segment, segmentNo, uploadedSourceId, uploadedSourceSegmentNo)) {
                updated.add(segment.withUploadStatus(uploadStatus));
            } else {
                updated.add(segment);
            }
        }
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                audioPath,
                updated,
                status,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public MeetingRecord withUploadedSegment(AudioSegment uploadedSegment, int serverSegmentNo) {
        String uploadedSourceId = uploadedSegment == null ? "" : uploadedSegment.getSourceId();
        int uploadedSourceSegmentNo = uploadedSegment == null ? 0 : uploadedSegment.getSourceSegmentNo();
        List<AudioSegment> updated = new ArrayList<>();
        boolean replaced = false;
        for (AudioSegment segment : audioSegments) {
            if (matchesAudioSegment(segment, serverSegmentNo, uploadedSourceId, uploadedSourceSegmentNo)) {
                updated.add(segment.withServerSegmentNo(serverSegmentNo, "uploaded"));
                replaced = true;
            } else {
                updated.add(segment);
            }
        }
        if (!replaced && uploadedSegment != null) {
            updated.add(uploadedSegment.withServerSegmentNo(serverSegmentNo, "uploaded"));
        }
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                audioPath,
                updated,
                status,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public MeetingRecord withClosedOpenAudioSegments() {
        boolean wasRecording = "local_recording".equals(status);
        if (openRecordingSegmentCount() == 0 && !wasRecording) {
            return this;
        }
        List<AudioSegment> updated = new ArrayList<>();
        for (AudioSegment segment : audioSegments) {
            updated.add(segment.isOpenRecording() ? segment.withUploadStatus("local") : segment);
        }
        String nextStatus = wasRecording ? "local_recorded" : status;
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                audioPath,
                updated,
                nextStatus,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public boolean hasPendingLocalAudio() {
        for (AudioSegment segment : audioSegments) {
            if (segment.isReadyForUpload()) {
                return true;
            }
        }
        return false;
    }

    public int uploadedAudioSegmentCount() {
        int count = 0;
        for (AudioSegment segment : audioSegments) {
            if (segment.isUploaded()) {
                count += 1;
            }
        }
        return count;
    }

    public int pendingUploadSegmentCount() {
        int count = 0;
        for (AudioSegment segment : audioSegments) {
            if (segment.isReadyForUpload()) {
                count += 1;
            }
        }
        return count;
    }

    public int openRecordingSegmentCount() {
        int count = 0;
        for (AudioSegment segment : audioSegments) {
            if (segment.isOpenRecording()) {
                count += 1;
            }
        }
        return count;
    }

    public MeetingRecord withSpeakerName(String speakerId, String displayName) {
        List<TranscriptSegment> renamed = new ArrayList<>();
        for (TranscriptSegment segment : transcriptSegments) {
            if (segment.getSpeakerId().equals(speakerId)) {
                renamed.add(segment.withSpeaker(displayName));
            } else {
                renamed.add(segment);
            }
        }
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                audioPath,
                audioSegments,
                status,
                renamed,
                roleNotes,
                summary,
                actionItems,
                joinCode,
                sourceId,
                sourceLabel);
    }

    public MeetingRecord withRecordingSource(String newJoinCode, String newSourceId, String newSourceLabel) {
        List<AudioSegment> sourcedAudio = new ArrayList<>();
        for (AudioSegment segment : audioSegments) {
            String segmentSourceId = segment.getSourceId();
            if (segmentSourceId.equals("primary") || segmentSourceId.isEmpty()) {
                sourcedAudio.add(segment.withRecordingSource(newSourceId, newSourceLabel));
            } else {
                sourcedAudio.add(segment);
            }
        }
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                audioPath,
                sourcedAudio,
                status,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems,
                newJoinCode,
                newSourceId,
                newSourceLabel);
    }

    private static List<AudioSegment> immutableAudioSegments(List<AudioSegment> segments) {
        if (segments == null) {
            return Collections.emptyList();
        }
        return Collections.unmodifiableList(new ArrayList<>(segments));
    }

    private static List<TranscriptSegment> immutableSegments(List<TranscriptSegment> segments) {
        if (segments == null) {
            return Collections.emptyList();
        }
        return Collections.unmodifiableList(new ArrayList<>(segments));
    }

    private static List<ActionItem> immutableActionItems(List<ActionItem> items) {
        if (items == null) {
            return Collections.emptyList();
        }
        return Collections.unmodifiableList(new ArrayList<>(items));
    }

    private List<AudioSegment> mergeUploadStatuses(List<AudioSegment> segments) {
        if (segments == null) {
            return Collections.emptyList();
        }
        List<AudioSegment> merged = new ArrayList<>();
        for (AudioSegment next : segments) {
            AudioSegment previous = findAudioSegment(next);
            if (previous != null && previous.isUploaded()) {
                merged.add(new AudioSegment(
                        previous.getSegmentNo(),
                        next.getPath(),
                        next.getStartMillis(),
                        next.getEndMillis(),
                        previous.getUploadStatus(),
                        previous.getDownloadUrl(),
                        next.getSourceId(),
                        next.getSourceSegmentNo(),
                        next.getSourceLabel()));
            } else {
                merged.add(next);
            }
        }
        return merged;
    }

    private List<AudioSegment> normalizeLocalAudioSegments(List<AudioSegment> segments) {
        if (segments == null) {
            return Collections.emptyList();
        }
        List<AudioSegment> normalized = new ArrayList<>();
        for (AudioSegment segment : segments) {
            if (!sourceId.equals("primary") && segment.getSourceId().equals("primary")) {
                normalized.add(segment.withRecordingSource(sourceId, sourceLabel));
            } else if (!sourceLabel.isEmpty() && segment.getSourceLabel().isEmpty()) {
                normalized.add(segment.withRecordingSource(segment.getSourceId(), sourceLabel));
            } else {
                normalized.add(segment);
            }
        }
        return normalized;
    }

    private AudioSegment findAudioSegment(AudioSegment target) {
        for (AudioSegment segment : audioSegments) {
            if (sameSourceSegment(segment, target)) {
                return segment;
            }
        }
        return null;
    }

    private static List<AudioSegment> mergeAudioSegmentsByNumber(
            List<AudioSegment> first,
            List<AudioSegment> second) {
        List<AudioSegment> merged = new ArrayList<>();
        appendMissingAudioSegments(merged, first);
        appendMissingAudioSegments(merged, second);
        Collections.sort(merged, (left, right) -> left.getSegmentNo() - right.getSegmentNo());
        return merged;
    }

    private static void appendMissingAudioSegments(List<AudioSegment> target, List<AudioSegment> source) {
        if (source == null) {
            return;
        }
        for (AudioSegment segment : source) {
            AudioSegment previous = findAudioSegment(target, segment);
            if (previous == null) {
                target.add(segment);
            } else if (segment.isUploaded()) {
                replaceAudioSegment(target, previous, segment);
            }
        }
    }

    private static AudioSegment findAudioSegment(List<AudioSegment> segments, AudioSegment target) {
        for (AudioSegment segment : segments) {
            if (sameSourceSegment(segment, target)) {
                return segment;
            }
        }
        return null;
    }

    private static void replaceAudioSegment(List<AudioSegment> segments, AudioSegment original, AudioSegment replacement) {
        for (int i = 0; i < segments.size(); i++) {
            if (segments.get(i) == original || sameSourceSegment(segments.get(i), original)) {
                segments.set(i, replacement);
                return;
            }
        }
    }

    private static boolean sameSourceSegment(AudioSegment left, AudioSegment right) {
        return left != null
                && right != null
                && left.getSourceId().equals(right.getSourceId())
                && left.getSourceSegmentNo() == right.getSourceSegmentNo();
    }

    private static boolean matchesAudioSegment(
            AudioSegment segment,
            int segmentNo,
            String uploadedSourceId,
            int uploadedSourceSegmentNo) {
        String normalizedSourceId = safe(uploadedSourceId);
        if (!normalizedSourceId.isEmpty() && uploadedSourceSegmentNo > 0) {
            return segment.getSourceId().equals(normalizedSourceId)
                    && segment.getSourceSegmentNo() == uploadedSourceSegmentNo;
        }
        return segment.getSegmentNo() == segmentNo;
    }

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }
}
