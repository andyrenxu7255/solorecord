package com.solorecord.model;

import org.json.JSONException;
import org.json.JSONObject;

public final class ActionItem {
    private final String owner;
    private final String task;
    private final String due;
    private final String status;
    private final String evidenceStatus;
    private final String evidenceReason;
    private final String actionKind;
    private final boolean reviewOnly;
    private final boolean autoActionable;
    private final boolean reminderSafe;
    private final boolean knowledgeSafe;
    private final boolean requiresReview;

    public ActionItem(String owner, String task, String due, String status) {
        this(owner, task, due, status, "", "", "meeting_action", false, true, false, false, false);
    }

    public ActionItem(
            String owner,
            String task,
            String due,
            String status,
            String evidenceStatus,
            String evidenceReason,
            String actionKind,
            boolean reviewOnly,
            boolean autoActionable,
            boolean reminderSafe,
            boolean knowledgeSafe,
            boolean requiresReview) {
        this.owner = safe(owner).isEmpty() ? "待分配" : safe(owner);
        this.task = safe(task);
        this.due = safe(due);
        this.status = safe(status).isEmpty() ? "open" : safe(status);
        this.evidenceStatus = safe(evidenceStatus);
        this.evidenceReason = safe(evidenceReason);
        this.actionKind = safe(actionKind).isEmpty() ? "meeting_action" : safe(actionKind);
        this.reviewOnly = reviewOnly || "system_review".equals(this.actionKind)
                || "system_review".equals(this.evidenceStatus);
        this.autoActionable = autoActionable && !this.reviewOnly;
        this.reminderSafe = reminderSafe && !this.reviewOnly;
        this.knowledgeSafe = knowledgeSafe && !this.reviewOnly;
        this.requiresReview = requiresReview || this.reviewOnly || needsEvidenceReview(this.evidenceStatus);
    }

    public static ActionItem fromJson(JSONObject json) {
        return new ActionItem(
                json.optString("owner"),
                json.optString("task"),
                json.optString("due"),
                json.optString("status", "open"),
                json.optString("evidenceStatus", json.optString("evidence_status")),
                json.optString("evidenceReason", json.optString("evidence_reason")),
                json.optString("actionKind", json.optString("action_kind", "meeting_action")),
                json.optBoolean("reviewOnly", json.optBoolean("review_only", false)),
                json.optBoolean("autoActionable", json.optBoolean("auto_actionable", true)),
                json.optBoolean("reminderSafe", json.optBoolean("reminder_safe", false)),
                json.optBoolean("knowledgeSafe", json.optBoolean("knowledge_safe", false)),
                json.optBoolean("requiresReview", json.optBoolean("requires_review", false)));
    }

    public JSONObject toJson() throws JSONException {
        JSONObject json = new JSONObject();
        json.put("owner", owner);
        json.put("task", task);
        json.put("due", due);
        json.put("status", status);
        json.put("evidenceStatus", evidenceStatus);
        json.put("evidenceReason", evidenceReason);
        json.put("actionKind", actionKind);
        json.put("reviewOnly", reviewOnly);
        json.put("autoActionable", autoActionable);
        json.put("reminderSafe", reminderSafe);
        json.put("knowledgeSafe", knowledgeSafe);
        json.put("requiresReview", requiresReview);
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

    public String getEvidenceStatus() {
        return evidenceStatus;
    }

    public String getEvidenceReason() {
        return evidenceReason;
    }

    public String getActionKind() {
        return actionKind;
    }

    public boolean isReviewOnly() {
        return reviewOnly;
    }

    public boolean isAutoActionable() {
        return autoActionable;
    }

    public boolean isReminderSafe() {
        return reminderSafe;
    }

    public boolean isKnowledgeSafe() {
        return knowledgeSafe;
    }

    public boolean requiresReview() {
        return requiresReview;
    }

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }

    private static boolean needsEvidenceReview(String status) {
        String value = safe(status);
        return "unsupported".equals(value)
                || "weak_owner".equals(value)
                || "conflict".equals(value)
                || "contradiction".equals(value)
                || "majority".equals(value)
                || "system_review".equals(value)
                || "unknown".equals(value);
    }
}
