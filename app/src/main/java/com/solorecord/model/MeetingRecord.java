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
                items);
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
                items);
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
                actionItems);
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

    public MeetingRecord withAudioSegments(List<AudioSegment> segments, String newStatus) {
        String firstPath = segments == null || segments.isEmpty() ? audioPath : segments.get(0).getPath();
        return new MeetingRecord(
                id,
                title,
                createdAtMillis,
                firstPath,
                segments,
                newStatus,
                transcriptSegments,
                roleNotes,
                summary,
                actionItems);
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
                actionItems);
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

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }
}
