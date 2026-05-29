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
        this.segmentNo = Math.max(1, segmentNo);
        this.path = path == null ? "" : path;
        this.startMillis = Math.max(0, startMillis);
        this.endMillis = Math.max(this.startMillis, endMillis);
        this.uploadStatus = uploadStatus == null || uploadStatus.trim().isEmpty()
                ? "local"
                : uploadStatus.trim();
        this.downloadUrl = downloadUrl == null ? "" : downloadUrl.trim();
    }

    public static AudioSegment fromJson(JSONObject json) {
        return new AudioSegment(
                json.optInt("segmentNo", 1),
                json.optString("path"),
                json.optLong("startMillis"),
                json.optLong("endMillis"),
                json.optString("uploadStatus", "local"),
                json.optString("downloadUrl", json.optString("download_url")));
    }

    public JSONObject toJson() throws JSONException {
        JSONObject json = new JSONObject();
        json.put("segmentNo", segmentNo);
        json.put("path", path);
        json.put("startMillis", startMillis);
        json.put("endMillis", endMillis);
        json.put("uploadStatus", uploadStatus);
        json.put("downloadUrl", downloadUrl);
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

    public boolean isUploaded() {
        return "uploaded".equals(uploadStatus);
    }

    public AudioSegment withUploadStatus(String status) {
        return new AudioSegment(segmentNo, path, startMillis, endMillis, status, downloadUrl);
    }
}
