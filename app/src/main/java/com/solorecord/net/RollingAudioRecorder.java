package com.solorecord.net;

import android.content.Context;
import android.media.MediaRecorder;
import android.os.Build;

import com.solorecord.model.AudioSegment;
import com.solorecord.util.TimeFormat;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class RollingAudioRecorder {
    private MediaRecorder recorder;
    private File currentFile;
    private File audioDir;
    private long meetingStartedAt;
    private long currentSegmentStartedAt;
    private int nextSegmentNo = 1;
    private final List<AudioSegment> segments = new ArrayList<>();

    public synchronized void start(Context context, String meetingId) throws IOException {
        if (recorder != null) {
            throw new IOException("录音已经开始");
        }
        audioDir = new File(context.getFilesDir(), "audio/" + meetingId);
        if (!audioDir.exists() && !audioDir.mkdirs()) {
            throw new IOException("无法创建音频目录");
        }
        meetingStartedAt = System.currentTimeMillis();
        nextSegmentNo = 1;
        segments.clear();
        startNextSegment(context);
    }

    public synchronized List<AudioSegment> rotate(Context context) throws IOException {
        if (recorder == null) {
            return Collections.emptyList();
        }
        stopCurrentSegment("local");
        startNextSegment(context);
        return getSegments();
    }

    public synchronized List<AudioSegment> stop() throws IOException {
        if (recorder == null) {
            throw new IOException("录音尚未开始");
        }
        stopCurrentSegment("local");
        return getSegments();
    }

    public synchronized boolean isRecording() {
        return recorder != null;
    }

    public synchronized List<AudioSegment> getSegments() {
        return Collections.unmodifiableList(new ArrayList<>(segments));
    }

    private void startNextSegment(Context context) throws IOException {
        currentFile = new File(audioDir, String.format(
                "part_%04d_%s.m4a",
                nextSegmentNo,
                TimeFormat.filenameNow()));
        MediaRecorder nextRecorder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                ? new MediaRecorder(context)
                : new MediaRecorder();
        nextRecorder.setAudioSource(MediaRecorder.AudioSource.MIC);
        nextRecorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
        nextRecorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
        nextRecorder.setAudioEncodingBitRate(96_000);
        nextRecorder.setAudioSamplingRate(44_100);
        nextRecorder.setOutputFile(currentFile.getAbsolutePath());
        nextRecorder.prepare();
        nextRecorder.start();
        recorder = nextRecorder;
        currentSegmentStartedAt = System.currentTimeMillis();
    }

    private void stopCurrentSegment(String uploadStatus) {
        MediaRecorder current = recorder;
        File stoppedFile = currentFile;
        if (current == null) {
            return;
        }
        long startOffset = Math.max(0, currentSegmentStartedAt - meetingStartedAt);
        long endOffset = Math.max(startOffset, System.currentTimeMillis() - meetingStartedAt);
        boolean hasValidAudio = true;
        try {
            current.stop();
        } catch (RuntimeException exception) {
            hasValidAudio = false;
        } finally {
            current.release();
            recorder = null;
            currentFile = null;
        }
        if (stoppedFile != null && hasValidAudio && stoppedFile.length() > 0) {
            segments.add(new AudioSegment(nextSegmentNo, stoppedFile.getAbsolutePath(), startOffset, endOffset, uploadStatus));
            nextSegmentNo += 1;
        } else if (stoppedFile != null && stoppedFile.exists()) {
            stoppedFile.delete();
        }
    }
}
