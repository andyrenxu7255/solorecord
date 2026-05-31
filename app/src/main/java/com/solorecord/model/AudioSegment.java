package com.solorecord.model;

import org.json.JSONException;
import org.json.JSONObject;

public final class AudioSegment {
    private final int segmentNo;
    private final String path;
    private final long startMillis;
    private final long endMillis;
    private final String uploadStatus;
    private final String downloadUrl;
    private final String sourceId;
    private final int sourceSegmentNo;
    private final String sourceLabel;

    public AudioSegment(int segmentNo, String path, long startMillis, long endMillis, String uploadStatus) {
        this(segmentNo, path, startMillis, endMillis, uploadStatus, "");
    }

    public AudioSegment(
            int segmentNo,
            String path,
            long startMillis,
            long endMillis,
            String uploadStatus,
            String downloadUrl) {
        this(segmentNo, path, startMillis, endMillis, uploadStatus, downloadUrl, "primary", segmentNo, "");
    }

    public AudioSegment(
            int segmentNo,
            String path,
            long startMillis,
            long endMillis,
            String uploadStatus,
            String downloadUrl,
            String sourceId,
            int sourceSegmentNo,
            String sourceLabel) {
        this.segmentNo = Math.max(1, segmentNo);
        this.path = path == null ? "" : path;
        this.startMillis = Math.max(0, startMillis);
        this.endMillis = Math.max(this.startMillis, endMillis);
        this.uploadStatus = uploadStatus == null || uploadStatus.trim().isEmpty()
                ? "local"
                : uploadStatus.trim();
        this.downloadUrl = downloadUrl == null ? "" : downloadUrl.trim();
        this.sourceId = sourceId == null || sourceId.trim().isEmpty() ? "primary" : sourceId.trim();
        this.sourceSegmentNo = Math.max(1, sourceSegmentNo <= 0 ? this.segmentNo : sourceSegmentNo);
        this.sourceLabel = sourceLabel == null ? "" : sourceLabel.trim();
    }

    public static AudioSegment fromJson(JSONObject json) {
        return new AudioSegment(
                json.optInt("segmentNo", 1),
                json.optString("path"),
                json.optLong("startMillis"),
                json.optLong("endMillis"),
                json.optString("uploadStatus", "local"),
                json.optString("downloadUrl", json.optString("download_url")),
                json.optString("sourceId", json.optString("source_id", "primary")),
                json.optInt("sourceSegmentNo", json.optInt("source_segment_no", json.optInt("segmentNo", 1))),
                json.optString("sourceLabel", json.optString("source_label")));
    }

    public JSONObject toJson() throws JSONException {
        JSONObject json = new JSONObject();
        json.put("segmentNo", segmentNo);
        json.put("path", path);
        json.put("startMillis", startMillis);
        json.put("endMillis", endMillis);
        json.put("uploadStatus", uploadStatus);
        json.put("downloadUrl", downloadUrl);
        json.put("sourceId", sourceId);
        json.put("sourceSegmentNo", sourceSegmentNo);
        json.put("sourceLabel", sourceLabel);
        return json;
    }

    public int getSegmentNo() {
        return segmentNo;
    }

    public String getPath() {
        return path;
    }

    public long getStartMillis() {
        return startMillis;
    }

    public long getEndMillis() {
        return endMillis;
    }

    public String getUploadStatus() {
        return uploadStatus;
    }

    public String getDownloadUrl() {
        return downloadUrl;
    }

    public String getSourceId() {
        return sourceId;
    }

    public int getSourceSegmentNo() {
        return sourceSegmentNo;
    }

    public String getSourceLabel() {
        return sourceLabel;
    }

    public boolean isUploaded() {
        return "uploaded".equals(uploadStatus);
    }

    public boolean isOpenRecording() {
        return "local_recording".equals(uploadStatus);
    }

    public boolean isReadyForUpload() {
        return !isUploaded() && !isOpenRecording() && !path.isEmpty();
    }

    public AudioSegment withUploadStatus(String status) {
        return new AudioSegment(segmentNo, path, startMillis, endMillis, status, downloadUrl,
                sourceId, sourceSegmentNo, sourceLabel);
    }

    public AudioSegment withUploadStatus(String status, String newDownloadUrl) {
        return new AudioSegment(segmentNo, path, startMillis, endMillis, status, newDownloadUrl,
                sourceId, sourceSegmentNo, sourceLabel);
    }

    public AudioSegment withServerSegmentNo(int newSegmentNo, String status) {
        return new AudioSegment(newSegmentNo, path, startMillis, endMillis, status, downloadUrl,
                sourceId, sourceSegmentNo, sourceLabel);
    }

    public AudioSegment withRecordingSource(String newSourceId, String newSourceLabel) {
        return new AudioSegment(segmentNo, path, startMillis, endMillis, uploadStatus, downloadUrl,
                newSourceId, sourceSegmentNo, newSourceLabel);
    }
}
