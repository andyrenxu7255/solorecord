package com.solorecord.model;

import org.json.JSONException;
import org.json.JSONObject;

public final class ActionItem {
    private final String owner;
    private final String task;
    private final String due;
    private final String status;

    public ActionItem(String owner, String task, String due, String status) {
        this.owner = safe(owner).isEmpty() ? "待分配" : safe(owner);
        this.task = safe(task);
        this.due = safe(due);
        this.status = safe(status).isEmpty() ? "open" : safe(status);
    }

    public static ActionItem fromJson(JSONObject json) {
        return new ActionItem(
                json.optString("owner"),
                json.optString("task"),
                json.optString("due"),
                json.optString("status", "open"));
    }

    public JSONObject toJson() throws JSONException {
        JSONObject json = new JSONObject();
        json.put("owner", owner);
        json.put("task", task);
        json.put("due", due);
        json.put("status", status);
        return json;
    }

    public String getOwner() {
        return owner;
    }

    public String getTask() {
        return task;
    }

    public String getDue() {
        return due;
    }

    public String getStatus() {
        return status;
    }

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }
}
