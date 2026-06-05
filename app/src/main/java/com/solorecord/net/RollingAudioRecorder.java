package com.solorecord.net;

import android.content.Context;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;

import com.solorecord.log.AppLogger;
import com.solorecord.model.AudioSegment;
import com.solorecord.util.TimeFormat;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class RollingAudioRecorder {
    private static final int SAMPLE_RATE = 16_000;
    private static final int CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO;
    private static final int AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT;
    private static final int BYTES_PER_SAMPLE = 2;
    private static final int OVERLAP_MILLIS = 2_000;
    private static final int OVERLAP_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE * OVERLAP_MILLIS / 1000;

    private final Object lock = new Object();
    private final List<AudioSegment> segments = new ArrayList<>();
    private final ByteArrayOutputStream overlapBuffer = new ByteArrayOutputStream(OVERLAP_BYTES);

    private AudioRecord audioRecord;
    private Thread recordThread;
    private File audioDir;
    private WavSegmentWriter currentWriter;
    private boolean recording;
    private AppLogger logger;
    private String activeMeetingId = "";
    private long meetingStartedAt;
    private long currentSegmentStartedAt;
    private int nextSegmentNo = 1;

    public void start(Context context, String meetingId) throws IOException {
        synchronized (lock) {
            if (recording) {
                throw new IOException("录音已经开始");
            }
            logger = AppLogger.get(context);
            activeMeetingId = meetingId == null ? "" : meetingId;
            String safeMeetingDir = activeMeetingId.isEmpty()
                    ? "local_" + System.currentTimeMillis()
                    : activeMeetingId.replaceAll("[^A-Za-z0-9_.-]", "_");
            audioDir = new File(context.getFilesDir(), "audio/" + safeMeetingDir);
            if (!audioDir.exists() && !audioDir.mkdirs()) {
                throw new IOException("无法创建音频目录");
            }
            int minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT);
            if (minBuffer <= 0) {
                throw new IOException("当前设备不支持录音采样配置");
            }
            audioRecord = new AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    SAMPLE_RATE,
                    CHANNEL_CONFIG,
                    AUDIO_FORMAT,
                    Math.max(minBuffer, SAMPLE_RATE * BYTES_PER_SAMPLE));
            if (audioRecord.getState() != AudioRecord.STATE_INITIALIZED) {
                audioRecord.release();
                audioRecord = null;
                throw new IOException("录音设备初始化失败");
            }
            meetingStartedAt = System.currentTimeMillis();
            currentSegmentStartedAt = meetingStartedAt;
            nextSegmentNo = 1;
            segments.clear();
            overlapBuffer.reset();
            currentWriter = openWriter(nextSegmentNo);
            recording = true;
            audioRecord.startRecording();
            recordThread = new Thread(() -> captureLoop(minBuffer), "SoloRecordAudioCapture");
            recordThread.start();
            logInfo("audio_record_start", "录音设备已开始采集");
        }
    }

    public List<AudioSegment> rotate(Context context) throws IOException {
        synchronized (lock) {
            if (!recording) {
                return Collections.emptyList();
            }
            logInfo("audio_segment_rotate", "开始滚动保存分段 " + nextSegmentNo);
            closeCurrentSegmentLocked("local");
            currentWriter = openWriter(nextSegmentNo);
            currentSegmentStartedAt = System.currentTimeMillis() - OVERLAP_MILLIS;
            byte[] overlap = overlapBuffer.toByteArray();
            if (overlap.length > 0) {
                currentWriter.write(overlap, 0, overlap.length);
            }
            return snapshotLocked();
        }
    }

    public List<AudioSegment> stop() throws IOException {
        Thread threadToJoin;
        AudioRecord recorderToStop;
        synchronized (lock) {
            if (!recording) {
                throw new IOException("录音尚未开始");
            }
            recording = false;
            logInfo("audio_record_stop", "正在停止录音设备");
            threadToJoin = recordThread;
            recorderToStop = audioRecord;
        }
        if (recorderToStop != null) {
            try {
                recorderToStop.stop();
            } catch (IllegalStateException ignored) {
                // Recorder may already be stopping on some devices.
            }
        }
        if (threadToJoin != null) {
            try {
                threadToJoin.join(2_000);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new IOException("停止录音被中断", exception);
            }
        }
        synchronized (lock) {
            if (audioRecord != null) {
                audioRecord.release();
                audioRecord = null;
            }
            closeCurrentSegmentLocked("local");
            recordThread = null;
            logInfo("audio_record_stopped", "录音已停止并保存分段");
            return snapshotLocked();
        }
    }

    public boolean isRecording() {
        synchronized (lock) {
            return recording;
        }
    }

    public List<AudioSegment> getSegments() {
        synchronized (lock) {
            return Collections.unmodifiableList(new ArrayList<>(segments));
        }
    }

    public List<AudioSegment> getSegmentsWithOpenSegment() {
        synchronized (lock) {
            return snapshotWithOpenSegmentLocked();
        }
    }

    public List<AudioSegment> checkpointOpenSegment() throws IOException {
        synchronized (lock) {
            if (recording && currentWriter != null) {
                currentWriter.refreshHeader();
            }
            return snapshotWithOpenSegmentLocked();
        }
    }

    private void captureLoop(int minBuffer) {
        byte[] buffer = new byte[Math.max(minBuffer, 4096)];
        while (true) {
            synchronized (lock) {
                if (!recording || audioRecord == null) {
                    break;
                }
            }
            int read = audioRecord.read(buffer, 0, buffer.length);
            if (read <= 0) {
                continue;
            }
            synchronized (lock) {
                if (currentWriter != null) {
                    try {
                        currentWriter.write(buffer, 0, read);
                        rememberOverlap(buffer, read);
                    } catch (IOException exception) {
                        logError("audio_write_failed", "音频写入失败，录音被保护性停止", exception);
                        recording = false;
                    }
                }
            }
        }
    }

    private WavSegmentWriter openWriter(int segmentNo) throws IOException {
        File file = new File(audioDir, String.format(
                "part_%04d_%s.wav",
                segmentNo,
                TimeFormat.filenameNow()));
        return new WavSegmentWriter(file);
    }

    private void closeCurrentSegmentLocked(String uploadStatus) throws IOException {
        WavSegmentWriter writer = currentWriter;
        if (writer == null) {
            return;
        }
        currentWriter = null;
        long startOffset = Math.max(0, currentSegmentStartedAt - meetingStartedAt);
        long endOffset = Math.max(startOffset, System.currentTimeMillis() - meetingStartedAt);
        writer.close();
        if (writer.sizeBytes() > 44) {
            long duration = Math.max(0, writer.pcmBytes() * 1000 / (SAMPLE_RATE * BYTES_PER_SAMPLE));
            long correctedEndOffset = Math.max(startOffset, startOffset + duration);
            segments.add(new AudioSegment(nextSegmentNo, writer.file().getAbsolutePath(), startOffset, correctedEndOffset, uploadStatus));
            logInfo(
                    "audio_segment_closed",
                    "分段 " + nextSegmentNo + " 已落盘，大小 " + writer.sizeBytes() + " 字节，状态 " + uploadStatus);
            nextSegmentNo += 1;
        } else if (writer.file().exists()) {
            writer.file().delete();
            logInfo("audio_segment_empty_deleted", "空音频分段已删除");
        }
    }

    private void logInfo(String event, String message) {
        AppLogger currentLogger = logger;
        if (currentLogger != null) {
            currentLogger.info(event, activeMeetingId, message);
        }
    }

    private void logError(String event, String message, Throwable throwable) {
        AppLogger currentLogger = logger;
        if (currentLogger != null) {
            currentLogger.error(event, activeMeetingId, message, throwable);
        }
    }

    private void rememberOverlap(byte[] buffer, int length) {
        byte[] old = overlapBuffer.toByteArray();
        overlapBuffer.reset();
        int keepOld = Math.max(0, OVERLAP_BYTES - length);
        if (old.length > keepOld) {
            overlapBuffer.write(old, old.length - keepOld, keepOld);
        } else if (old.length > 0) {
            overlapBuffer.write(old, 0, old.length);
        }
        if (length > OVERLAP_BYTES) {
            overlapBuffer.write(buffer, length - OVERLAP_BYTES, OVERLAP_BYTES);
        } else {
            overlapBuffer.write(buffer, 0, length);
        }
    }

    private List<AudioSegment> snapshotLocked() {
        return Collections.unmodifiableList(new ArrayList<>(segments));
    }

    private List<AudioSegment> snapshotWithOpenSegmentLocked() {
        List<AudioSegment> snapshot = new ArrayList<>(segments);
        if (recording && currentWriter != null) {
            long startOffset = Math.max(0, currentSegmentStartedAt - meetingStartedAt);
            long duration = Math.max(0, currentWriter.pcmBytes() * 1000 / (SAMPLE_RATE * BYTES_PER_SAMPLE));
            snapshot.add(new AudioSegment(
                    nextSegmentNo,
                    currentWriter.file().getAbsolutePath(),
                    startOffset,
                    startOffset + duration,
                    "local_recording"));
        }
        return Collections.unmodifiableList(snapshot);
    }

    private static final class WavSegmentWriter {
        private final File file;
        private final RandomAccessFile output;
        private long pcmBytes;

        WavSegmentWriter(File file) throws IOException {
            this.file = file;
            this.output = new RandomAccessFile(file, "rw");
            this.output.setLength(0);
            writeHeader(0);
        }

        File file() {
            return file;
        }

        long sizeBytes() {
            return file.length();
        }

        long pcmBytes() {
            return pcmBytes;
        }

        void write(byte[] buffer, int offset, int length) throws IOException {
            output.write(buffer, offset, length);
            pcmBytes += length;
        }

        void close() throws IOException {
            writeHeader(pcmBytes);
            output.close();
        }

        void refreshHeader() throws IOException {
            long position = output.getFilePointer();
            writeHeader(pcmBytes);
            output.seek(position);
        }

        private void writeHeader(long dataSize) throws IOException {
            output.seek(0);
            long byteRate = (long) SAMPLE_RATE * BYTES_PER_SAMPLE;
            output.writeBytes("RIFF");
            writeLittleEndianInt(output, 36 + dataSize);
            output.writeBytes("WAVE");
            output.writeBytes("fmt ");
            writeLittleEndianInt(output, 16);
            writeLittleEndianShort(output, 1);
            writeLittleEndianShort(output, 1);
            writeLittleEndianInt(output, SAMPLE_RATE);
            writeLittleEndianInt(output, byteRate);
            writeLittleEndianShort(output, BYTES_PER_SAMPLE);
            writeLittleEndianShort(output, 16);
            output.writeBytes("data");
            writeLittleEndianInt(output, dataSize);
            output.seek(output.length());
        }

        private static void writeLittleEndianInt(RandomAccessFile output, long value) throws IOException {
            output.write((int) (value & 0xff));
            output.write((int) ((value >> 8) & 0xff));
            output.write((int) ((value >> 16) & 0xff));
            output.write((int) ((value >> 24) & 0xff));
        }

        private static void writeLittleEndianShort(RandomAccessFile output, int value) throws IOException {
            output.write(value & 0xff);
            output.write((value >> 8) & 0xff);
        }
    }
}
