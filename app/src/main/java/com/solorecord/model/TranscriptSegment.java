package com.solorecord.model;

import org.json.JSONException;
import org.json.JSONObject;

public final class TranscriptSegment {
    private final String speakerId;
    private final String speaker;
    private final String text;
    private final long startMillis;
    private final long endMillis;

    public TranscriptSegment(String speaker, String text, long startMillis, long endMillis) {
        this(speaker, speaker, text, startMillis, endMillis);
    }

    public TranscriptSegment(String speakerId, String speaker, String text, long startMillis, long endMillis) {
        this.speakerId = safe(speakerId).isEmpty() ? safe(speaker) : safe(speakerId);
        this.speaker = safe(speaker).isEmpty() ? "发言人" : safe(speaker);
        this.text = safe(text);
        this.startMillis = Math.max(0, startMillis);
        this.endMillis = Math.max(this.startMillis, endMillis);
    }

    public static TranscriptSegment fromJson(JSONObject json) {
        return new TranscriptSegment(
                json.optString("speakerId", json.optString("speaker_id", json.optString("speaker"))),
                json.optString("speaker", json.optString("display_name", json.optString("displayName"))),
                json.optString("text"),
                json.optLong("startMillis", json.optLong("start_ms")),
                json.optLong("endMillis", json.optLong("end_ms")));
    }

    public JSONObject toJson() throws JSONException {
        JSONObject json = new JSONObject();
        json.put("speakerId", speakerId);
        json.put("speaker", speaker);
        json.put("text", text);
        json.put("startMillis", startMillis);
        json.put("endMillis", endMillis);
        return json;
    }

    public String getSpeakerId() {
        return speakerId;
    }

    public String getSpeaker() {
        return speaker;
    }

    public String getText() {
        return text;
    }

    public long getStartMillis() {
        return startMillis;
    }

    public long getEndMillis() {
        return endMillis;
    }

    public TranscriptSegment withSpeaker(String newSpeaker) {
        return new TranscriptSegment(speakerId, newSpeaker, text, startMillis, endMillis);
    }

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }
}
