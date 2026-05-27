package com.solorecord;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.solorecord.config.PreconfiguredConfig;
import com.solorecord.model.AudioSegment;
import com.solorecord.model.MeetingRecord;
import com.solorecord.model.TranscriptSegment;
import com.solorecord.net.RollingAudioRecorder;
import com.solorecord.net.SoloServerClient;
import com.solorecord.service.RecordingService;
import com.solorecord.storage.MeetingStore;
import com.solorecord.storage.SessionStore;
import com.solorecord.util.TimeFormat;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int REQUEST_RECORD_AUDIO = 1001;
    private static final long SEGMENT_ROTATE_INTERVAL_MS = 5 * 60 * 1000L;

    private final RollingAudioRecorder audioRecorder = new RollingAudioRecorder();
    private final SoloServerClient serverClient = new SoloServerClient();
    private final ExecutorService executorService = Executors.newSingleThreadExecutor();
    private final Handler segmentHandler = new Handler(Looper.getMainLooper());

    private MeetingStore meetingStore;
    private SessionStore sessionStore;
    private LinearLayout root;
    private LinearLayout content;
    private TextView titleText;
    private TextView statusText;
    private Button recordingTab;
    private Button recordsTab;
    private Button loginTab;
    private MeetingRecord currentMeeting;
    private int currentTab = 0;
    private long recordingStartedAt;
    private String recordingMeetingId = "";
    private MediaPlayer mediaPlayer;
    private final Runnable segmentRotation = new Runnable() {
        @Override
        public void run() {
            if (!audioRecorder.isRecording()) {
                return;
            }
            rotateRecordingSegment();
            segmentHandler.postDelayed(this, SEGMENT_ROTATE_INTERVAL_MS);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        meetingStore = new MeetingStore(this);
        sessionStore = new SessionStore(this);
        String configuredServerEndpoint = PreconfiguredConfig.serverEndpoint();
        if (sessionStore.getServerEndpoint().equals("http://127.0.0.1:8000")
                && !configuredServerEndpoint.isEmpty()) {
            sessionStore.setServerEndpoint(configuredServerEndpoint);
        }
        currentMeeting = meetingStore.loadLatestMetadata();
        buildShell();
        handleAuthCallback(getIntent());
        renderCurrentTab();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleAuthCallback(intent);
        renderCurrentTab();
    }

    @Override
    protected void onDestroy() {
        if (audioRecorder.isRecording()) {
            stopRecording();
        }
        releasePlayer();
        segmentHandler.removeCallbacks(segmentRotation);
        executorService.shutdownNow();
        super.onDestroy();
    }

    private void buildShell() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(245, 247, 251));

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(dp(18), dp(20), dp(18), dp(12));
        header.setBackgroundColor(Color.rgb(16, 36, 51));

        titleText = new TextView(this);
        titleText.setText("SoloRecord");
        titleText.setTextColor(Color.WHITE);
        titleText.setTextSize(24);
        titleText.setTypeface(Typeface.DEFAULT_BOLD);
        header.addView(titleText, matchWrap());

        statusText = new TextView(this);
        statusText.setTextColor(Color.rgb(210, 220, 230));
        statusText.setTextSize(14);
        statusText.setPadding(0, dp(6), 0, 0);
        header.addView(statusText, matchWrap());
        root.addView(header, matchWrap());

        ScrollView scrollView = new ScrollView(this);
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(16), dp(16), dp(16), dp(16));
        scrollView.addView(content);
        root.addView(scrollView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1));

        LinearLayout tabs = new LinearLayout(this);
        tabs.setOrientation(LinearLayout.HORIZONTAL);
        tabs.setPadding(dp(8), dp(8), dp(8), dp(8));
        tabs.setBackgroundColor(Color.WHITE);
        recordingTab = tabButton("录音", 0);
        recordsTab = tabButton("记录", 1);
        loginTab = tabButton("登录状态", 2);
        tabs.addView(recordingTab, tabParams());
        tabs.addView(recordsTab, tabParams());
        tabs.addView(loginTab, tabParams());
        root.addView(tabs, matchWrap());

        setContentView(root);
    }

    private Button tabButton(String label, int tab) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextSize(14);
        button.setOnClickListener(view -> {
            currentTab = tab;
            renderCurrentTab();
        });
        return button;
    }

    private void renderCurrentTab() {
        updateHeader();
        updateTabs();
        content.removeAllViews();
        if (currentTab == 0) {
            renderRecordingTab();
        } else if (currentTab == 1) {
            renderRecordsTab();
        } else {
            renderLoginTab();
        }
    }

    private void updateHeader() {
        String login = sessionStore.isLoggedIn()
                ? "已登录：" + sessionStore.getDisplayName()
                : "未登录，录音和同步需要先登录";
        String server = sessionStore.getServerEndpoint();
        statusText.setText(login + "\n服务器：" + server);
    }

    private void updateTabs() {
        paintTab(recordingTab, currentTab == 0);
        paintTab(recordsTab, currentTab == 1);
        paintTab(loginTab, currentTab == 2);
    }

    private void paintTab(Button button, boolean active) {
        button.setTextColor(active ? Color.WHITE : Color.rgb(23, 32, 51));
        button.setBackgroundColor(active ? Color.rgb(23, 107, 135) : Color.rgb(230, 237, 243));
    }

    private void renderRecordingTab() {
        addSectionTitle("录音");
        if (!sessionStore.isLoggedIn()) {
            addHint("请先登录后再录音。");
            Button login = primaryButton("去登录");
            login.setOnClickListener(view -> {
                currentTab = 2;
                renderCurrentTab();
            });
            content.addView(login, spacedParams());
            return;
        }
        addHint("点击开始后会立即保存本地音频。结束或关闭 App 时会停止录音，避免长时间未落盘。");

        TextView state = cardText(audioRecorder.isRecording() ? "录音中" : "准备录音");
        content.addView(state, matchWrap());

        Button recordButton = primaryButton(audioRecorder.isRecording() ? "结束录音" : "开始录音");
        recordButton.setOnClickListener(view -> toggleRecording());
        content.addView(recordButton, spacedParams());

        Button syncButton = secondaryButton("同步最新会议到服务器");
        syncButton.setOnClickListener(view -> syncLatestMeeting());
        content.addView(syncButton, spacedParams());

        Button restoreButton = secondaryButton("从服务器恢复记录");
        restoreButton.setOnClickListener(view -> syncFromServer());
        content.addView(restoreButton, spacedParams());

        if (currentMeeting != null) {
            addMeetingSummary(currentMeeting);
        }
    }

    private void renderRecordsTab() {
        addSectionTitle("记录");
        if (!sessionStore.isLoggedIn()) {
            addHint("请先登录后查看会议记录。");
            Button login = primaryButton("去登录");
            login.setOnClickListener(view -> {
                currentTab = 2;
                renderCurrentTab();
            });
            content.addView(login, spacedParams());
            return;
        }
        List<MeetingRecord> records = meetingStore.loadAll();
        if (records.isEmpty()) {
            addHint("暂无会议记录");
            Button restore = primaryButton("从服务器恢复记录");
            restore.setOnClickListener(view -> syncFromServer());
            content.addView(restore, spacedParams());
            return;
        }
        for (MeetingRecord record : records) {
            LinearLayout card = card();
            TextView title = text(record.getTitle(), 18, true);
            card.addView(title, matchWrap());
            card.addView(text(TimeFormat.display(record.getCreatedAtMillis()) + " · " + statusLabel(record.getStatus()), 13, false));
            card.addView(text("音频分段：" + record.getAudioSegments().size(), 13, false));

            Button detail = secondaryButton("查看详情");
            detail.setOnClickListener(view -> renderRecordDetail(record));
            card.addView(detail, spacedParams());
            content.addView(card, spacedParams());
        }
    }

    private void renderRecordDetail(MeetingRecord record) {
        content.removeAllViews();
        currentMeeting = record;
        addSectionTitle(record.getTitle());
        Button back = secondaryButton("返回记录列表");
        back.setOnClickListener(view -> renderCurrentTab());
        content.addView(back, spacedParams());

        addMeetingSummary(record);
        addAudioPlayback(record);

        Button sync = primaryButton("同步/重新处理");
        sync.setOnClickListener(view -> syncMeeting(record));
        content.addView(sync, spacedParams());

        if (!record.getTranscriptSegments().isEmpty()) {
            addSectionTitle("转写");
            for (TranscriptSegment segment : record.getTranscriptSegments()) {
                addTranscriptSegment(record, segment);
            }
        }

        if (!record.getSummary().isEmpty()) {
            addSectionTitle("纪要");
            content.addView(cardText(record.getSummary()), matchWrap());
        }

        if (!record.getActionItems().isEmpty()) {
            addSectionTitle("待办");
            record.getActionItems().forEach(item ->
                    content.addView(cardText(item.getOwner() + "：" + item.getTask() + " " + item.getDue()), spacedParams()));
        }
    }

    private void addTranscriptSegment(MeetingRecord record, TranscriptSegment segment) {
        LinearLayout card = card();
        card.addView(text(segment.getSpeaker() + "  " + time(segment.getStartMillis()), 14, true), matchWrap());
        card.addView(text(segment.getText(), 15, false), matchWrap());
        EditText speakerName = input(segment.getSpeaker(), "角色名称");
        card.addView(speakerName, spacedParams());
        Button rename = secondaryButton("应用到该角色全部段落");
        rename.setOnClickListener(view -> {
            MeetingRecord renamed = record.withSpeakerName(segment.getSpeakerId(), speakerName.getText().toString());
            try {
                meetingStore.upsert(renamed);
                currentMeeting = renamed;
                if (sessionStore.isLoggedIn()) {
                    renameSpeakerOnServer(renamed.getId(), segment.getSpeakerId(), speakerName.getText().toString());
                }
                toast("角色名称已替换");
                renderRecordDetail(renamed);
            } catch (IOException exception) {
                toast(exception.getMessage());
            }
        });
        card.addView(rename, spacedParams());
        content.addView(card, spacedParams());
    }

    private void addAudioPlayback(MeetingRecord record) {
        if (record.getAudioSegments().isEmpty()) {
            return;
        }
        addSectionTitle("录音");
        for (AudioSegment segment : record.getAudioSegments()) {
            File file = new File(segment.getPath());
            LinearLayout card = card();
            card.addView(text(
                    "分段 " + segment.getSegmentNo() + "  " + time(segment.getStartMillis())
                            + "-" + time(segment.getEndMillis()),
                    14,
                    true), matchWrap());
            card.addView(text(file.exists() ? file.getName() : "服务器音频或本机文件不可用", 13, false), matchWrap());
            if (file.exists()) {
                Button play = secondaryButton("播放该段");
                play.setOnClickListener(view -> playAudio(file));
                card.addView(play, spacedParams());
            } else if (!segment.getDownloadUrl().isEmpty()) {
                Button download = secondaryButton("下载并播放");
                download.setOnClickListener(view -> downloadAndPlay(record, segment));
                card.addView(download, spacedParams());
            }
            content.addView(card, spacedParams());
        }
    }

    private void renderLoginTab() {
        addSectionTitle("登录状态");
        EditText serverInput = input(sessionStore.getServerEndpoint(), "服务器地址");
        content.addView(serverInput, spacedParams());

        EditText nameInput = input(
                sessionStore.getDisplayName().isEmpty() ? "Demo User" : sessionStore.getDisplayName(),
                "姓名");
        content.addView(nameInput, spacedParams());

        EditText emailInput = input(
                sessionStore.getEmail().isEmpty() ? "admin@example.com" : sessionStore.getEmail(),
                "邮箱");
        content.addView(emailInput, spacedParams());

        Button saveServer = secondaryButton("保存服务器地址");
        saveServer.setOnClickListener(view -> {
            sessionStore.setServerEndpoint(serverInput.getText().toString());
            updateHeader();
            toast("服务器地址已保存");
        });
        content.addView(saveServer, spacedParams());

        Button login = primaryButton("登录");
        login.setOnClickListener(view -> startSsoLogin(serverInput.getText().toString()));
        content.addView(login, spacedParams());

        Button demoLogin = secondaryButton("演示登录");
        demoLogin.setOnClickListener(view -> login(serverInput.getText().toString(), nameInput.getText().toString(), emailInput.getText().toString()));
        content.addView(demoLogin, spacedParams());

        Button logout = secondaryButton("退出登录");
        logout.setOnClickListener(view -> {
            sessionStore.logout();
            updateHeader();
            toast("已退出");
        });
        content.addView(logout, spacedParams());

        Button checkRelease = secondaryButton("检查 APK 更新");
        checkRelease.setOnClickListener(view -> toast("请在 Web 端下载最新 APK：" + sessionStore.getServerEndpoint()));
        content.addView(checkRelease, spacedParams());
    }

    private void toggleRecording() {
        if (audioRecorder.isRecording()) {
            stopRecording();
            return;
        }
        if (!sessionStore.isLoggedIn()) {
            currentTab = 2;
            renderCurrentTab();
            toast("请先登录");
            return;
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_RECORD_AUDIO);
            return;
        }
        startRecording();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO
                && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startRecording();
        }
    }

    private void startRecording() {
        try {
            recordingStartedAt = System.currentTimeMillis();
            recordingMeetingId = "local_" + recordingStartedAt;
            currentMeeting = new MeetingRecord(
                    recordingMeetingId,
                    "会议 " + TimeFormat.display(recordingStartedAt),
                    recordingStartedAt,
                    "",
                    Collections.emptyList(),
                    "local_recording",
                    Collections.emptyList(),
                    "",
                    "",
                    Collections.emptyList());
            meetingStore.upsert(currentMeeting);
            startRecordingService();
            audioRecorder.start(this, recordingMeetingId);
            segmentHandler.postDelayed(segmentRotation, SEGMENT_ROTATE_INTERVAL_MS);
            renderCurrentTab();
            toast("录音已开始");
        } catch (IOException exception) {
            stopRecordingService();
            toast(exception.getMessage());
        }
    }

    private void stopRecording() {
        try {
            segmentHandler.removeCallbacks(segmentRotation);
            List<AudioSegment> segments = new ArrayList<>(audioRecorder.stop());
            stopRecordingService();
            MeetingRecord base = currentMeeting == null
                    ? new MeetingRecord(
                    recordingMeetingId.isEmpty() ? "local_" + System.currentTimeMillis() : recordingMeetingId,
                    "会议 " + TimeFormat.display(System.currentTimeMillis()),
                    recordingStartedAt,
                    segments.isEmpty() ? "" : segments.get(0).getPath(),
                    Collections.emptyList(),
                    "local_recording",
                    Collections.emptyList(),
                    "",
                    "",
                    Collections.emptyList())
                    : currentMeeting;
            MeetingRecord draft = base.withAudioSegments(segments, "local_recorded");
            currentMeeting = draft;
            meetingStore.upsert(draft);
            renderCurrentTab();
            toast("录音已保存");
        } catch (IOException exception) {
            stopRecordingService();
            toast(exception.getMessage());
        }
    }

    private void rotateRecordingSegment() {
        try {
            List<AudioSegment> segments = new ArrayList<>(audioRecorder.rotate(this));
            if (currentMeeting != null) {
                currentMeeting = currentMeeting.withAudioSegments(segments, "local_recording");
                meetingStore.upsert(currentMeeting);
                if (currentTab == 0) {
                    renderCurrentTab();
                }
            }
        } catch (IOException exception) {
            toast("分段保存失败：" + exception.getMessage());
        }
    }

    private void startRecordingService() {
        Intent intent = new Intent(this, RecordingService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
    }

    private void stopRecordingService() {
        stopService(new Intent(this, RecordingService.class));
    }

    private void syncLatestMeeting() {
        if (currentMeeting == null) {
            toast("请先录制会议");
            return;
        }
        syncMeeting(currentMeeting);
    }

    private void syncMeeting(MeetingRecord record) {
        if (!sessionStore.isLoggedIn()) {
            toast("请先登录");
            currentTab = 2;
            renderCurrentTab();
            return;
        }
        executorService.execute(() -> {
            try {
                String localId = record.getId();
                MeetingRecord processed = serverClient.uploadAndFinishMeeting(
                        sessionStore.getServerEndpoint(),
                        sessionStore.getToken(),
                        record);
                meetingStore.replace(localId, processed);
                runOnUiThread(() -> {
                    currentMeeting = processed;
                    toast("已同步并提交处理");
                    currentTab = 1;
                    renderCurrentTab();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> toast("同步失败：" + exception.getMessage()));
            }
        });
    }

    private void syncFromServer() {
        if (!sessionStore.isLoggedIn()) {
            toast("请先登录");
            currentTab = 2;
            renderCurrentTab();
            return;
        }
        executorService.execute(() -> {
            try {
                List<MeetingRecord> records = serverClient.syncMeetings(
                        sessionStore.getServerEndpoint(),
                        sessionStore.getToken());
                for (MeetingRecord record : records) {
                    meetingStore.upsert(record);
                }
                runOnUiThread(() -> {
                    currentMeeting = meetingStore.loadLatestMetadata();
                    toast("已从服务器恢复 " + records.size() + " 条记录");
                    currentTab = 1;
                    renderCurrentTab();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> toast("恢复失败：" + exception.getMessage()));
            }
        });
    }

    private void renameSpeakerOnServer(String meetingId, String speakerId, String displayName) {
        executorService.execute(() -> {
            try {
                serverClient.renameSpeaker(
                        sessionStore.getServerEndpoint(),
                        sessionStore.getToken(),
                        meetingId,
                        speakerId,
                        displayName);
            } catch (Exception ignored) {
                runOnUiThread(() -> toast("本地已改名，服务器同步稍后重试"));
            }
        });
    }

    private void login(String serverEndpoint, String displayName, String email) {
        sessionStore.setServerEndpoint(serverEndpoint);
        executorService.execute(() -> {
            try {
                SoloServerClient.LoginResult result = serverClient.demoLogin(serverEndpoint, displayName, email);
                sessionStore.saveLogin(result.getToken(), result.getDisplayName(), result.getEmail());
                runOnUiThread(() -> {
                    updateHeader();
                    toast("登录成功");
                    renderCurrentTab();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> toast("登录失败：" + exception.getMessage()));
            }
        });
    }

    private void startSsoLogin(String serverEndpoint) {
        sessionStore.setServerEndpoint(serverEndpoint);
        String base = serverEndpoint == null ? "" : serverEndpoint.trim();
        while (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        Uri uri = Uri.parse(base + "/api/auth/sso/start")
                .buildUpon()
                .appendQueryParameter("redirect_after", "solorecord://auth/callback")
                .build();
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException exception) {
            toast("无法打开统一登录页面");
        }
    }

    private void handleAuthCallback(Intent intent) {
        if (intent == null || intent.getData() == null) {
            return;
        }
        Uri uri = intent.getData();
        if (!"solorecord".equals(uri.getScheme()) || !"auth".equals(uri.getHost())) {
            return;
        }
        String token = uri.getQueryParameter("access_token");
        if (token == null || token.trim().isEmpty()) {
            toast("统一登录未返回会话");
            return;
        }
        sessionStore.saveLogin(
                token,
                valueOrDefault(uri.getQueryParameter("display_name"), "SoloRecord 用户"),
                valueOrDefault(uri.getQueryParameter("email"), ""));
        toast("登录成功");
    }

    private void downloadAndPlay(MeetingRecord record, AudioSegment segment) {
        executorService.execute(() -> {
            try {
                File outputDir = new File(getFilesDir(), "audio-cache/" + record.getId());
                File audio = serverClient.downloadSegment(
                        sessionStore.getServerEndpoint(),
                        sessionStore.getToken(),
                        segment,
                        outputDir);
                runOnUiThread(() -> playAudio(audio));
            } catch (Exception exception) {
                runOnUiThread(() -> toast("下载失败：" + exception.getMessage()));
            }
        });
    }

    private void playAudio(File file) {
        releasePlayer();
        try {
            mediaPlayer = new MediaPlayer();
            mediaPlayer.setDataSource(file.getAbsolutePath());
            mediaPlayer.setOnCompletionListener(player -> releasePlayer());
            mediaPlayer.prepare();
            mediaPlayer.start();
            toast("开始播放");
        } catch (IOException exception) {
            releasePlayer();
            toast("播放失败：" + exception.getMessage());
        }
    }

    private void releasePlayer() {
        if (mediaPlayer == null) {
            return;
        }
        try {
            mediaPlayer.release();
        } finally {
            mediaPlayer = null;
        }
    }

    private void addMeetingSummary(MeetingRecord record) {
        LinearLayout card = card();
        card.addView(text(record.getTitle(), 18, true), matchWrap());
        card.addView(text(statusLabel(record.getStatus()), 14, false), matchWrap());
        card.addView(text("创建：" + TimeFormat.display(record.getCreatedAtMillis()), 13, false), matchWrap());
        card.addView(text("音频分段：" + record.getAudioSegments().size(), 13, false), matchWrap());
        content.addView(card, spacedParams());
    }

    private void addSectionTitle(String label) {
        TextView view = text(label, 20, true);
        view.setPadding(0, dp(8), 0, dp(8));
        content.addView(view, matchWrap());
    }

    private void addHint(String label) {
        TextView view = text(label, 14, false);
        view.setTextColor(Color.rgb(102, 112, 133));
        content.addView(view, matchWrap());
    }

    private LinearLayout card() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(14), dp(14), dp(14), dp(14));
        card.setBackgroundColor(Color.WHITE);
        return card;
    }

    private TextView cardText(String label) {
        TextView view = text(label, 18, true);
        view.setGravity(Gravity.CENTER);
        view.setPadding(dp(16), dp(28), dp(16), dp(28));
        view.setBackgroundColor(Color.WHITE);
        return view;
    }

    private TextView text(String label, int size, boolean bold) {
        TextView view = new TextView(this);
        view.setText(label == null ? "" : label);
        view.setTextSize(size);
        view.setTextColor(Color.rgb(23, 32, 51));
        if (bold) {
            view.setTypeface(Typeface.DEFAULT_BOLD);
        }
        view.setPadding(0, dp(3), 0, dp(3));
        return view;
    }

    private EditText input(String value, String hint) {
        EditText editText = new EditText(this);
        editText.setText(value == null ? "" : value);
        editText.setHint(hint);
        editText.setSingleLine(true);
        editText.setTextSize(15);
        return editText;
    }

    private Button primaryButton(String label) {
        Button button = makeButton(label);
        button.setTextColor(Color.WHITE);
        button.setBackgroundColor(Color.rgb(23, 107, 135));
        return button;
    }

    private Button secondaryButton(String label) {
        Button button = makeButton(label);
        button.setTextColor(Color.rgb(23, 32, 51));
        button.setBackgroundColor(Color.rgb(230, 237, 243));
        return button;
    }

    private Button makeButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextSize(15);
        return button;
    }

    private String statusLabel(String status) {
        if ("ready".equals(status) || "processed".equals(status)) {
            return "已完成";
        }
        if ("queued".equals(status)) {
            return "排队中";
        }
        if ("preprocessing".equals(status)) {
            return "预处理";
        }
        if ("failed".equals(status)) {
            return "失败";
        }
        if ("local_recording".equals(status)) {
            return "录音中";
        }
        if ("local_recorded".equals(status) || "recorded".equals(status)) {
            return "本地已保存";
        }
        return status == null || status.isEmpty() ? "未知" : status;
    }

    private String time(long millis) {
        long seconds = Math.max(0, millis / 1000);
        return String.format("%02d:%02d", seconds / 60, seconds % 60);
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams spacedParams() {
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(0, dp(10), 0, 0);
        return params;
    }

    private LinearLayout.LayoutParams tabParams() {
        return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void toast(String message) {
        Toast.makeText(this, message == null ? "" : message, Toast.LENGTH_SHORT).show();
    }

    private String valueOrDefault(String value, String fallback) {
        return value == null || value.trim().isEmpty() ? fallback : value.trim();
    }
}
