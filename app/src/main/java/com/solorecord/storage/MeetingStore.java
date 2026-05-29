package com.solorecord.storage;

import android.content.Context;

import com.solorecord.model.MeetingRecord;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

public final class MeetingStore {
    private final File meetingFile;

    public MeetingStore(Context context) {
        this.meetingFile = new File(context.getFilesDir(), "meetings.json");
    }

    public List<MeetingRecord> loadAll() {
        try {
            if (!meetingFile.exists()) {
                return Collections.emptyList();
            }
            JSONArray array = new JSONArray(FileStore.readText(meetingFile));
            List<MeetingRecord> records = new ArrayList<>();
            for (int i = 0; i < array.length(); i++) {
                JSONObject item = array.optJSONObject(i);
                if (item != null) {
                    records.add(MeetingRecord.fromJson(item));
                }
            }
            records.sort(Comparator.comparingLong(MeetingRecord::getCreatedAtMillis).reversed());
            return records;
        } catch (Exception ignored) {
            return Collections.emptyList();
        }
    }

    public void upsert(MeetingRecord record) throws IOException {
        List<MeetingRecord> records = new ArrayList<>(loadAll());
        boolean replaced = false;
        for (int i = 0; i < records.size(); i++) {
            if (records.get(i).getId().equals(record.getId())) {
                records.set(i, record);
                replaced = true;
                break;
            }
        }
        if (!replaced) {
            records.add(record);
        }
        saveAll(records);
    }

    public void replace(String oldId, MeetingRecord record) throws IOException {
        List<MeetingRecord> records = new ArrayList<>(loadAll());
        List<MeetingRecord> next = new ArrayList<>();
        boolean added = false;
        for (MeetingRecord item : records) {
            if (item.getId().equals(oldId) || item.getId().equals(record.getId())) {
                if (!added) {
                    next.add(record);
                    added = true;
                }
            } else {
                next.add(item);
            }
        }
        if (!added) {
            next.add(record);
        }
        saveAll(next);
    }

    public MeetingRecord loadLatestMetadata() {
        List<MeetingRecord> records = loadAll();
        return records.isEmpty() ? null : records.get(0);
    }

    public MeetingRecord findById(String id) {
        if (id == null || id.trim().isEmpty()) {
            return null;
        }
        for (MeetingRecord record : loadAll()) {
            if (record.getId().equals(id)) {
                return record;
            }
        }
        return null;
    }

    public void saveMetadataOnly(MeetingRecord record) throws IOException {
        upsert(new MeetingRecord(
                record.getId(),
                record.getTitle(),
                record.getCreatedAtMillis(),
                record.getAudioPath(),
                record.getAudioSegments(),
                record.getStatus(),
                Collections.emptyList(),
                "",
                "",
                Collections.emptyList()));
    }

    private void saveAll(List<MeetingRecord> records) throws IOException {
        try {
            JSONArray array = new JSONArray();
            for (MeetingRecord record : records) {
                array.put(record.toJson());
            }
            FileStore.writeText(meetingFile, array.toString(2));
        } catch (Exception exception) {
            throw new IOException("会议保存失败", exception);
        }
    }
}
