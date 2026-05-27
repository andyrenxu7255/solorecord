package com.solorecord.net;

import android.content.Context;
import android.media.MediaRecorder;
import android.os.Build;

import com.solorecord.util.TimeFormat;

import java.io.File;
import java.io.IOException;

public final class AudioRecorder {
    private MediaRecorder recorder;
    private File currentFile;

    public synchronized File start(Context context) throws IOException {
        if (recorder != null) {
            throw new IOException("录音已经开始");
        }
        File audioDir = new File(context.getFilesDir(), "audio");
        if (!audioDir.exists() && !audioDir.mkdirs()) {
            throw new IOException("无法创建音频目录");
        }
        currentFile = new File(audioDir, "meeting_" + TimeFormat.filenameNow() + ".m4a");
        MediaRecorder nextRecorder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                ? new MediaRecorder(context)
                : new MediaRecorder();
        nextRecorder.setAudioSource(MediaRecorder.AudioSource.MIC);
        nextRecorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
        nextRecorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
        nextRecorder.setAudioEncodingBitRate(128_000);
        nextRecorder.setAudioSamplingRate(44_100);
        nextRecorder.setOutputFile(currentFile.getAbsolutePath());
        nextRecorder.prepare();
        nextRecorder.start();
        recorder = nextRecorder;
        return currentFile;
    }

    public synchronized File stop() throws IOException {
        if (recorder == null || currentFile == null) {
            throw new IOException("录音尚未开始");
        }
        try {
            recorder.stop();
            return currentFile;
        } finally {
            recorder.release();
            recorder = null;
            currentFile = null;
        }
    }

    public synchronized boolean isRecording() {
        return recorder != null;
    }
}
