package com.solorecord.log;

import android.content.Context;
import android.os.Build;
import android.util.Log;

import com.solorecord.BuildConfig;
import com.solorecord.storage.FileStore;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;

public final class AppLogger {
    private static final String TAG = "SoloRecord";
    private static final String LOG_FILE = "debug/mobile_logs.jsonl";
    private static final int MAX_LINES = 600;
    private static volatile AppLogger instance;

    private final File file;

    private AppLogger(Context context) {
        this.file = new File(context.getApplicationContext().getFilesDir(), LOG_FILE);
    }

    public static AppLogger get(Context context) {
        AppLogger local = instance;
        if (local == null) {
            synchronized (AppLogger.class) {
                local = instance;
                if (local == null) {
                    local = new AppLogger(context);
                    instance = local;
                }
            }
        }
        return local;
    }

    public synchronized void info(String event, String meetingId, String message) {
        append("info", event, meetingId, message, null);
    }

    public synchronized void warn(String event, String meetingId, String message) {
        append("warn", event, meetingId, message, null);
    }

    public synchronized void error(String event, String meetingId, String message, Throwable throwable) {
        append("error", event, meetingId, message, throwable);
    }

    public synchronized JSONArray snapshot(int limit) {
        JSONArray items = new JSONArray();
        String[] lines = readLines();
        int start = Math.max(0, lines.length - Math.max(1, limit));
        for (int i = start; i < lines.length; i++) {
            try {
                items.put(new JSONObject(lines[i]));
            } catch (Exception ignored) {
                // Skip malformed legacy/debug rows without blocking upload.
            }
        }
        return items;
    }

    public synchronized void markUploaded() {
        try {
            FileStore.writeText(file, "");
        } catch (IOException exception) {
            Log.w(TAG, "clear log failed", exception);
        }
    }

    private void append(String level, String event, String meetingId, String message, Throwable throwable) {
        try {
            JSONObject item = new JSONObject();
            item.put("client_ts", System.currentTimeMillis());
            item.put("level", level);
            item.put("event", safe(event));
            item.put("meeting_id", safe(meetingId));
            item.put("message", safe(message));
            item.put("app_version", BuildConfig.VERSION_NAME);
            item.put("app_version_code", BuildConfig.VERSION_CODE);
            item.put("device", Build.MANUFACTURER + " " + Build.MODEL);
            item.put("android_sdk", Build.VERSION.SDK_INT);
            if (throwable != null) {
                item.put("exception", throwable.getClass().getName());
                item.put("exception_message", safe(throwable.getMessage()));
            }
            appendLine(item.toString());
            Log.d(TAG, item.toString());
        } catch (Exception exception) {
            Log.w(TAG, "append log failed", exception);
        }
    }

    private void appendLine(String line) throws IOException {
        String[] lines = readLines();
        StringBuilder builder = new StringBuilder();
        int start = Math.max(0, lines.length - MAX_LINES + 1);
        for (int i = start; i < lines.length; i++) {
            if (!lines[i].trim().isEmpty()) {
                builder.append(lines[i]).append('\n');
            }
        }
        builder.append(line).append('\n');
        FileStore.writeText(file, builder.toString());
    }

    private String[] readLines() {
        try {
            if (!file.exists()) {
                return new String[0];
            }
            String raw = FileStore.readText(file);
            if (raw.trim().isEmpty()) {
                return new String[0];
            }
            return raw.split("\\r?\\n");
        } catch (Exception ignored) {
            return new String[0];
        }
    }

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }
}
