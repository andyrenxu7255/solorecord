package com.solorecord;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.Typeface;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
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
import com.solorecord.log.AppLogger;
import com.solorecord.model.ActionItem;
import com.solorecord.model.AudioSegment;
import com.solorecord.model.MeetingRecord;
import com.solorecord.model.TranscriptSegment;
import com.solorecord.net.RollingAudioRecorder;
import com.solorecord.net.SoloServerClient;
import com.solorecord.service.RecordingService;
import com.solorecord.storage.MeetingStore;
import com.solorecord.storage.SessionStore;
import com.solorecord.util.TimeFormat;

import org.json.JSONArray;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int REQUEST_RECORD_AUDIO = 1001;
    private static final int DEFAULT_SEGMENT_MINUTES = 5;
    private static final int COLOR_BG = 0xFFF1F5F9;
    private static final int COLOR_SURFACE = 0xFFFFFFFF;
    private static final int COLOR_SURFACE_SOFT = 0xFFF8FAFC;
    private static final int COLOR_TEXT = 0xFF101828;
    private static final int COLOR_MUTED = 0xFF667085;
    private static final int COLOR_PRIMARY = 0xFF176B87;
    private static final int COLOR_PRIMARY_DARK = 0xFF0F5066;
    private static final int COLOR_PRIMARY_SOFT = 0xFFE5F4F7;
    private static final int COLOR_LINE = 0xFFD6DDE8;
    private static final int COLOR_SIDEBAR = 0xFF102433;

    private static final RollingAudioRecorder audioRecorder = new RollingAudioRecorder();
    private static volatile String activeRecordingMeetingId = "";
    private static volatile long activeRecordingStartedAt;

    private final SoloServerClient serverClient = new SoloServerClient();
    private final ExecutorService executorService = Executors.newSingleThreadExecutor();
    private final Handler segmentHandler = new Handler(Looper.getMainLooper());
    private final Handler recordingUiHandler = new Handler(Looper.getMainLooper());
    private final Handler retryUploadHandler = new Handler(Looper.getMainLooper());

    private MeetingStore meetingStore;
    private SessionStore sessionStore;
    private AppLogger appLogger;
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
    private boolean autoSyncRunning;
    private EditText recordingTitleInput;
    private EditText recordingJoinCodeInput;
    private EditText recordingSourceLabelInput;
    private boolean recordingStopRequested;
    private long lastLogUploadAt;
    private final Runnable segmentRotation = new Runnable() {
        @Override
        public void run() {
            if (!audioRecorder.isRecording()) {
                return;
            }
            rotateRecordingSegment();
            segmentHandler.postDelayed(this, segmentRotateIntervalMillis());
        }
    };
    private final Runnable recordingCheckpoint = new Runnable() {
        @Override
        public void run() {
            if (!audioRecorder.isRecording()) {
                return;
            }
            checkpointRecording(true);
            recordingUiHandler.postDelayed(this, 5_000L);
        }
    };
    private final Runnable uploadRetry = new Runnable() {
        @Override
        public void run() {
            if (audioRecorder.isRecording() && currentMeeting != null) {
                autoUploadCurrentMeeting(true);
                uploadLogsAsync(false);
                retryUploadHandler.postDelayed(this, 30_000L);
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        meetingStore = new MeetingStore(this);
        sessionStore = new SessionStore(this);
        appLogger = AppLogger.get(this);
        appLogger.info("app_create", "", "MainActivity 创建");
        String configuredServerEndpoint = PreconfiguredConfig.serverEndpoint();
        String savedServerEndpoint = sessionStore.getServerEndpoint();
        if ((savedServerEndpoint.isEmpty() || savedServerEndpoint.equals("http://127.0.0.1:8000"))
                && !configuredServerEndpoint.isEmpty()) {
            sessionStore.setServerEndpoint(configuredServerEndpoint);
        }
        recoverInterruptedRecordings();
        currentMeeting = meetingStore.loadLatestMetadata();
        buildShell();
        handleAuthCallback(getIntent());
        resumeSharedRecordingIfNeeded();
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
        if (audioRecorder.isRecording() && (isFinishing() || recordingStopRequested)) {
            appLogger.warn("activity_destroy_stop_recording", recordingMeetingId, "Activity 销毁，保存并停止录音");
            stopRecording(false);
        } else if (audioRecorder.isRecording()) {
            checkpointRecording(false);
            appLogger.warn("activity_destroy_keep_recording", recordingMeetingId, "Activity 被系统销毁，保留前台录音服务和本地分段");
        }
        releasePlayer();
        segmentHandler.removeCallbacks(segmentRotation);
        recordingUiHandler.removeCallbacks(recordingCheckpoint);
        retryUploadHandler.removeCallbacks(uploadRetry);
        executorService.shutdownNow();
        super.onDestroy();
    }

    public static void stopRecordingFromService(Context context, String reason) {
        if (!audioRecorder.isRecording()) {
            return;
        }
        AppLogger logger = AppLogger.get(context);
        String meetingId = activeRecordingMeetingId;
        try {
            List<AudioSegment> segments = new ArrayList<>(audioRecorder.stop());
            MeetingStore store = new MeetingStore(context.getApplicationContext());
            MeetingRecord base = meetingId.isEmpty() ? store.loadLatestMetadata() : store.findById(meetingId);
            if (base == null) {
                base = store.loadLatestMetadata();
            }
            if (base != null) {
                store.upsert(base.withAudioSegments(segments, "local_recorded"));
            }
            logger.warn("recording_stopped_by_service", meetingId, "录音服务停止并保存分段：" + reason);
        } catch (IOException exception) {
            logger.error("recording_service_stop_failed", meetingId, "录音服务停止保存失败：" + reason, exception);
        } finally {
            activeRecordingMeetingId = "";
            activeRecordingStartedAt = 0L;
        }
    }

    private void buildShell() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(COLOR_BG);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(dp(18), dp(20), dp(18), dp(12));
        header.setBackgroundColor(COLOR_SIDEBAR);

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
        tabs.setBackgroundColor(COLOR_SURFACE);
        recordingTab = tabButton("录音", 0);
        recordsTab = tabButton("记录", 1);
        loginTab = tabButton("登录状态", 2);
        tabs.addView(recordingTab, tabParams());
        tabs.addView(recordsTab, tabParams());
        tabs.addView(loginTab, tabParams());
        root.addView(tabs, matchWrap());

        setContentView(root);
    }

    private void recoverInterruptedRecordings() {
        try {
            List<MeetingRecord> records = meetingStore.loadAll();
            for (MeetingRecord record : records) {
                if (record.openRecordingSegmentCount() > 0 || "local_recording".equals(record.getStatus())) {
                    meetingStore.upsert(record.withClosedOpenAudioSegments());
                }
            }
        } catch (IOException ignored) {
            // Recovery is best effort; the record list remains readable even if one save fails.
        }
    }

    private void resumeSharedRecordingIfNeeded() {
        if (!audioRecorder.isRecording()) {
            return;
        }
        recordingMeetingId = activeRecordingMeetingId;
        recordingStartedAt = activeRecordingStartedAt > 0 ? activeRecordingStartedAt : System.currentTimeMillis();
        if (!recordingMeetingId.isEmpty()) {
            MeetingRecord active = meetingStore.findById(recordingMeetingId);
            if (active != null) {
                currentMeeting = active;
            }
        }
        segmentHandler.removeCallbacks(segmentRotation);
        recordingUiHandler.removeCallbacks(recordingCheckpoint);
        retryUploadHandler.removeCallbacks(uploadRetry);
        segmentHandler.postDelayed(segmentRotation, segmentRotateIntervalMillis());
        recordingUiHandler.postDelayed(recordingCheckpoint, 1_000L);
        retryUploadHandler.postDelayed(uploadRetry, 5_000L);
        appLogger.warn("recording_activity_resumed", recordingMeetingId, "界面重新接管正在进行的录音");
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
        statusText.setText(login + "\n服务器：" + server + serverRuntimeSummary());
    }

    private void updateTabs() {
        paintTab(recordingTab, currentTab == 0);
        paintTab(recordsTab, currentTab == 1);
        paintTab(loginTab, currentTab == 2);
    }

    private void paintTab(Button button, boolean active) {
        button.setTextColor(active ? Color.WHITE : COLOR_TEXT);
        button.setBackground(makeBg(active ? COLOR_PRIMARY : Color.rgb(232, 238, 245), dp(8), 0));
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
        addHint("点击开始后会立即保存本地音频。当前按约 " + sessionStore.getAudioSegmentMinutes()
                + " 分钟滚动分段，每个分段会带约 2 秒重叠；在线时分段完成后自动上传并补充阶段转写。");

        recordingTitleInput = input("", "会议标题（可选）");
        content.addView(recordingTitleInput, spacedParams());
        recordingJoinCodeInput = input(sessionStore.getDefaultJoinCode(), "会议编号（多人同录填同一个编号）");
        content.addView(recordingJoinCodeInput, spacedParams());
        recordingSourceLabelInput = input(defaultSourceLabel(), "录音源名称");
        content.addView(recordingSourceLabelInput, spacedParams());

        TextView state = cardText(audioRecorder.isRecording() ? "录音中" : "准备录音");
        state.setTextColor(audioRecorder.isRecording() ? Color.rgb(180, 35, 24) : COLOR_PRIMARY_DARK);
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
            if (audioRecorder.isRecording()) {
                checkpointRecording(false);
            }
        addMeetingSummary(currentMeeting);
        addRecordingSegmentStatus(currentMeeting);
        if (currentMeeting.hasPendingLocalAudio()) {
            addHint("仍有待上传音频分段，网络恢复后会继续补传。");
        }
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
            card.addView(text(recordProgressText(record), 13, false));

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

        if (!record.getSummary().isEmpty()) {
            addSectionTitle("纪要");
            content.addView(cardText(record.getSummary()), matchWrap());
        }

        if (!record.getActionItems().isEmpty()) {
            addSectionTitle("待办");
            record.getActionItems().forEach(item ->
                    content.addView(actionCardText(item), spacedParams()));
        }

        addSpeakerStats(record);

        if (!record.getTranscriptSegments().isEmpty()) {
            addSectionTitle("转写");
            for (TranscriptSegment segment : record.getTranscriptSegments()) {
                addTranscriptSegment(record, segment);
            }
        }
    }

    private void addSpeakerStats(MeetingRecord record) {
        if (record.getTranscriptSegments().isEmpty()) {
            return;
        }
        addSectionTitle("说话人");
        Map<String, SpeakerStat> stats = new LinkedHashMap<>();
        for (TranscriptSegment segment : record.getTranscriptSegments()) {
            String key = segment.getSpeakerId();
            SpeakerStat stat = stats.get(key);
            if (stat == null) {
                stat = new SpeakerStat(segment.getSpeaker());
                stats.put(key, stat);
            }
            stat.count += 1;
            stat.durationMillis += Math.max(0, segment.getEndMillis() - segment.getStartMillis());
        }
        for (SpeakerStat stat : stats.values()) {
            content.addView(cardText(stat.name + " · " + stat.count + " 段 · " + time(stat.durationMillis)), spacedParams());
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
            String status = segment.isUploaded() ? "已上传" : "待上传";
            if (segment.isOpenRecording()) {
                status = "正在写入";
            }
            card.addView(text(
                    (file.exists() ? file.getName() : "服务器音频或本机文件不可用") + " · " + status,
                    13,
                    false), matchWrap());
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
        String configuredEndpoint = ensureServerEndpoint();
        addHint("公司服务器已配置：" + configuredEndpoint + "。ASR 和大模型由服务器统一配置，App 不内置任何模型密钥。" + serverRuntimeSummary());

        EditText usernameInput = input(
                sessionStore.getUsername(),
                "LDAP 用户名");
        content.addView(usernameInput, spacedParams());

        EditText passwordInput = input("", "LDAP 密码");
        passwordInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        content.addView(passwordInput, spacedParams());

        Button login = primaryButton("LDAP 登录");
        login.setOnClickListener(view -> loginWithLdap(
                ensureServerEndpoint(),
                usernameInput.getText().toString(),
                passwordInput.getText().toString()));
        content.addView(login, spacedParams());

        Button ssoLogin = secondaryButton("浏览器统一登录");
        ssoLogin.setOnClickListener(view -> startSsoLogin(ensureServerEndpoint()));
        content.addView(ssoLogin, spacedParams());

        Button logout = secondaryButton("退出登录");
        logout.setOnClickListener(view -> {
            sessionStore.logout();
            updateHeader();
            toast("已退出");
        });
        content.addView(logout, spacedParams());

        Button checkRelease = secondaryButton("检查 APK 更新");
        checkRelease.setOnClickListener(view -> openLatestRelease());
        content.addView(checkRelease, spacedParams());

        Button advancedServer = secondaryButton("高级：修改服务器地址");
        advancedServer.setOnClickListener(view -> showServerEndpointDialog());
        content.addView(advancedServer, spacedParams());

        addHint("App 版本：" + BuildConfig.VERSION_NAME + "。APK 只保存公司服务器地址和登录会话，不内置 LDAP、ASR、LLM、Hermes、ES 或外部系统 token。");
    }

    private String ensureServerEndpoint() {
        String endpoint = normalizeServerEndpoint(sessionStore.getServerEndpoint());
        if (endpoint.isEmpty() || "http://127.0.0.1:8000".equals(endpoint)) {
            endpoint = normalizeServerEndpoint(PreconfiguredConfig.serverEndpoint());
            if (!endpoint.isEmpty()) {
                sessionStore.setServerEndpoint(endpoint);
            }
        }
        return endpoint;
    }

    private String serverRuntimeSummary() {
        List<String> parts = new ArrayList<>();
        if (!sessionStore.getAsrLabel().isEmpty()) {
            parts.add(sessionStore.getAsrLabel());
        }
        if (!sessionStore.getLlmLabel().isEmpty()) {
            parts.add(sessionStore.getLlmLabel());
        }
        if (parts.isEmpty()) {
            return "";
        }
        return "\n服务器模型：" + join(parts, " / ") + "；分段 " + sessionStore.getAudioSegmentMinutes() + " 分钟";
    }

    private String join(List<String> items, String separator) {
        StringBuilder builder = new StringBuilder();
        for (String item : items) {
            if (item == null || item.isEmpty()) {
                continue;
            }
            if (builder.length() > 0) {
                builder.append(separator);
            }
            builder.append(item);
        }
        return builder.toString();
    }

    private void showServerEndpointDialog() {
        EditText serverInput = input(ensureServerEndpoint(), "服务器地址");
        new AlertDialog.Builder(this)
                .setTitle("高级设置")
                .setMessage("内部员工无需修改。仅在运维要求切换环境时使用。")
                .setView(serverInput)
                .setPositiveButton("保存", (dialog, which) -> {
                    String endpoint = normalizeServerEndpoint(serverInput.getText().toString());
                    if (endpoint.isEmpty()) {
                        toast("服务器地址需要以 http:// 或 https:// 开头");
                        return;
                    }
                    sessionStore.setServerEndpoint(endpoint);
                    updateHeader();
                    renderCurrentTab();
                    toast("服务器地址已保存");
                })
                .setNegativeButton("取消", null)
                .show();
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
            activeRecordingMeetingId = recordingMeetingId;
            activeRecordingStartedAt = recordingStartedAt;
            recordingStopRequested = false;
            String title = inputValue(recordingTitleInput);
            if (title.isEmpty()) {
                title = "会议 " + TimeFormat.display(recordingStartedAt);
            }
            String joinCode = inputValue(recordingJoinCodeInput);
            String sourceLabel = inputValue(recordingSourceLabelInput);
            if (sourceLabel.isEmpty()) {
                sourceLabel = defaultSourceLabel();
            }
            sessionStore.saveRecordingDefaults(joinCode, sourceLabel);
            currentMeeting = new MeetingRecord(
                    recordingMeetingId,
                    title,
                    recordingStartedAt,
                    "",
                    Collections.emptyList(),
                    "local_recording",
                    Collections.emptyList(),
                    "",
                    "",
                    Collections.emptyList(),
                    joinCode,
                    "primary",
                    sourceLabel);
            meetingStore.upsert(currentMeeting);
            startRecordingService();
            audioRecorder.start(this, recordingMeetingId);
            appLogger.info("recording_start", recordingMeetingId, "用户开始录音：" + title);
            refreshMobileConfigAsync();
            segmentHandler.postDelayed(segmentRotation, segmentRotateIntervalMillis());
            recordingUiHandler.postDelayed(recordingCheckpoint, 1_000L);
            retryUploadHandler.postDelayed(uploadRetry, 5_000L);
            uploadLogsAsync(false);
            renderCurrentTab();
            toast("录音已开始");
        } catch (IOException exception) {
            stopRecordingService();
            appLogger.error("recording_start_failed", recordingMeetingId, "录音启动失败", exception);
            toast(exception.getMessage());
        }
    }

    private void stopRecording() {
        stopRecording(true);
    }

    private void stopRecording(boolean submitAfterSave) {
        try {
            recordingStopRequested = true;
            segmentHandler.removeCallbacks(segmentRotation);
            recordingUiHandler.removeCallbacks(recordingCheckpoint);
            retryUploadHandler.removeCallbacks(uploadRetry);
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
            activeRecordingMeetingId = "";
            activeRecordingStartedAt = 0L;
            appLogger.info("recording_stop", draft.getId(), "用户结束录音，分段数：" + segments.size());
            uploadLogsAsync(false);
            if (submitAfterSave) {
                renderCurrentTab();
                toast("录音已保存");
                syncMeeting(draft);
            }
        } catch (IOException exception) {
            stopRecordingService();
            appLogger.error("recording_stop_failed", recordingMeetingId, "停止录音失败", exception);
            uploadLogsAsync(false);
            if (submitAfterSave) {
                toast(exception.getMessage());
            }
        }
    }

    private void rotateRecordingSegment() {
        try {
            List<AudioSegment> segments = new ArrayList<>(audioRecorder.rotate(this));
            if (currentMeeting != null) {
                currentMeeting = currentMeeting.withAudioSegments(segments, "local_recording");
                meetingStore.upsert(currentMeeting);
                appLogger.info("recording_segment_rotated", currentMeeting.getId(), "完成滚动分段，当前分段数：" + segments.size());
                autoUploadCurrentMeeting(true);
                uploadLogsAsync(false);
                if (currentTab == 0) {
                    renderCurrentTab();
                }
            }
        } catch (IOException exception) {
            appLogger.error("recording_segment_rotate_failed", recordingMeetingId, "分段保存失败", exception);
            uploadLogsAsync(false);
            toast("分段保存失败：" + exception.getMessage());
        }
    }

    private void checkpointRecording(boolean refreshUi) {
        if (currentMeeting == null || !audioRecorder.isRecording()) {
            return;
        }
        try {
            List<AudioSegment> segments = new ArrayList<>(audioRecorder.checkpointOpenSegment());
            currentMeeting = currentMeeting.withAudioSegments(segments, "local_recording");
            meetingStore.upsert(currentMeeting);
            if (refreshUi && currentTab == 0) {
                renderCurrentTab();
            }
        } catch (IOException exception) {
            appLogger.error("recording_checkpoint_failed", recordingMeetingId, "录音状态保存失败", exception);
            toast("录音状态保存失败：" + exception.getMessage());
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

    private String defaultSourceLabel() {
        String saved = sessionStore.getDefaultSourceLabel();
        if (!saved.isEmpty()) {
            return saved;
        }
        String name = sessionStore.getDisplayName();
        return name.isEmpty() ? "Android 录音源" : name + "的手机";
    }

    private String inputValue(EditText input) {
        return input == null ? "" : input.getText().toString().trim();
    }

    private void syncLatestMeeting() {
        if (currentMeeting == null) {
            toast("请先录制会议");
            return;
        }
        if (audioRecorder.isRecording()) {
            checkpointRecording(true);
            autoUploadCurrentMeeting(true);
            toast("录音仍在继续，已尝试上传已完成分段");
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
            MeetingRecord latestBeforeSync = meetingStore.findById(record.getId());
            MeetingRecord working = latestBeforeSync == null ? record : latestBeforeSync.withAudioFrom(record);
            if (!working.getId().startsWith("mtg_")) {
                MeetingRecord remoteSuccessor = meetingStore.findRemoteSuccessor(record);
                if (remoteSuccessor != null) {
                    working = remoteSuccessor.withAudioFrom(working);
                }
            }
            final String[] activeRecordId = {working.getId()};
            try {
                String localId = working.getId();
                MeetingRecord processed = serverClient.uploadAndFinishMeeting(
                        sessionStore.getServerEndpoint(),
                        sessionStore.getToken(),
                        working,
                        new SoloServerClient.UploadProgressListener() {
                            @Override
                            public void onSegmentUploadStarted(MeetingRecord uploading, AudioSegment segment) throws Exception {
                                activeRecordId[0] = uploading.getId();
                                meetingStore.upsert(uploading);
                                currentMeeting = uploading;
                                appLogger.info("segment_upload_start", uploading.getId(), segmentLogMessage(segment, "开始上传"));
                                runOnUiThread(() -> renderRecordingIfCurrent());
                            }

                            @Override
                            public void onRemoteMeetingReady(MeetingRecord uploading) throws Exception {
                                activeRecordId[0] = uploading.getId();
                                meetingStore.replace(localId, uploading);
                                currentMeeting = uploading;
                                appLogger.info("remote_meeting_ready", uploading.getId(), "服务器会议已创建");
                                uploadLogsAsync(false);
                            }

                            @Override
                            public void onSegmentUploaded(MeetingRecord uploading, AudioSegment segment) throws Exception {
                                activeRecordId[0] = uploading.getId();
                                meetingStore.upsert(uploading);
                                currentMeeting = uploading;
                                appLogger.info("segment_upload_success", uploading.getId(), segmentLogMessage(segment, "上传成功"));
                                uploadLogsAsync(false);
                                runOnUiThread(() -> renderRecordingIfCurrent());
                            }

                            @Override
                            public void onSegmentUploadFailed(MeetingRecord uploading, AudioSegment segment, Exception exception) throws Exception {
                                activeRecordId[0] = uploading.getId();
                                meetingStore.upsert(uploading);
                                currentMeeting = uploading;
                                appLogger.error("segment_upload_failed", uploading.getId(), segmentLogMessage(segment, "上传失败"), exception);
                                uploadLogsAsync(false);
                                runOnUiThread(() -> renderRecordingIfCurrent());
                            }
                        });
                meetingStore.replace(localId, processed);
                runOnUiThread(() -> {
                    currentMeeting = processed;
                    toast("已同步并提交处理");
                    currentTab = 1;
                    renderCurrentTab();
                });
            } catch (Exception exception) {
                MeetingRecord latest = meetingStore.findById(activeRecordId[0]);
                appLogger.error("meeting_sync_failed", activeRecordId[0], "同步中断，已保留进度", exception);
                uploadLogsAsync(false);
                runOnUiThread(() -> {
                    autoSyncRunning = false;
                    currentMeeting = latest == null ? currentMeeting : latest;
                    toast("同步中断，已保留进度，下次会继续：" + exception.getMessage());
                    renderCurrentTab();
                });
            }
        });
    }

    private void refreshMobileConfigAsync() {
        if (!sessionStore.isLoggedIn()) {
            return;
        }
        executorService.execute(() -> {
            try {
                SoloServerClient.MobileConfig config = serverClient.fetchMobileConfig(
                        sessionStore.getServerEndpoint(),
                        sessionStore.getToken());
                sessionStore.saveServerRuntimeConfig(
                        config.getSegmentMinutes(),
                        config.getAsrLabel(),
                        config.getLlmLabel());
                runOnUiThread(() -> {
                    updateHeader();
                    if (currentTab == 2) {
                        renderCurrentTab();
                    }
                });
            } catch (Exception ignored) {
                sessionStore.setAudioSegmentMinutes(DEFAULT_SEGMENT_MINUTES);
            }
        });
    }

    private void autoUploadCurrentMeeting(boolean refreshAfterUpload) {
        if (!sessionStore.isLoggedIn() || currentMeeting == null || autoSyncRunning) {
            return;
        }
        MeetingRecord record = currentMeeting;
        if (!record.hasPendingLocalAudio()) {
            return;
        }
        autoSyncRunning = true;
        executorService.execute(() -> {
            final String[] activeRecordId = {record.getId()};
            try {
                String localId = record.getId();
                MeetingRecord uploaded = serverClient.uploadPendingSegments(
                        sessionStore.getServerEndpoint(),
                        sessionStore.getToken(),
                        record,
                        new SoloServerClient.UploadProgressListener() {
                            @Override
                            public void onSegmentUploadStarted(MeetingRecord uploading, AudioSegment segment) throws Exception {
                                activeRecordId[0] = uploading.getId();
                                meetingStore.upsert(uploading);
                                currentMeeting = uploading;
                                appLogger.info("segment_auto_upload_start", uploading.getId(), segmentLogMessage(segment, "自动上传开始"));
                                runOnUiThread(() -> renderRecordingIfCurrent());
                            }

                            @Override
                            public void onRemoteMeetingReady(MeetingRecord uploading) throws Exception {
                                activeRecordId[0] = uploading.getId();
                                meetingStore.replace(localId, uploading);
                                currentMeeting = uploading;
                                appLogger.info("remote_meeting_ready", uploading.getId(), "自动上传已创建服务器会议");
                                uploadLogsAsync(false);
                            }

                            @Override
                            public void onSegmentUploaded(MeetingRecord uploading, AudioSegment segment) throws Exception {
                                activeRecordId[0] = uploading.getId();
                                meetingStore.upsert(uploading);
                                currentMeeting = uploading;
                                appLogger.info("segment_auto_upload_success", uploading.getId(), segmentLogMessage(segment, "自动上传成功"));
                                uploadLogsAsync(false);
                                runOnUiThread(() -> renderRecordingIfCurrent());
                            }

                            @Override
                            public void onSegmentUploadFailed(MeetingRecord uploading, AudioSegment segment, Exception exception) throws Exception {
                                activeRecordId[0] = uploading.getId();
                                meetingStore.upsert(uploading);
                                currentMeeting = uploading;
                                appLogger.error("segment_auto_upload_failed", uploading.getId(), segmentLogMessage(segment, "自动上传失败"), exception);
                                uploadLogsAsync(false);
                                runOnUiThread(() -> renderRecordingIfCurrent());
                            }
                        });
                meetingStore.replace(localId, uploaded);
                runOnUiThread(() -> {
                    autoSyncRunning = false;
                    currentMeeting = uploaded;
                    if (refreshAfterUpload) {
                        renderCurrentTab();
                    }
                });
            } catch (Exception exception) {
                MeetingRecord latest = meetingStore.findById(activeRecordId[0]);
                appLogger.error("auto_upload_failed", activeRecordId[0], "自动上传中断，稍后继续", exception);
                uploadLogsAsync(false);
                runOnUiThread(() -> {
                    autoSyncRunning = false;
                    currentMeeting = latest == null ? currentMeeting : latest;
                    if (refreshAfterUpload) {
                        toast("自动上传中断，稍后会继续：" + exception.getMessage());
                        renderCurrentTab();
                    }
                });
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
        String endpoint = normalizeServerEndpoint(serverEndpoint);
        if (endpoint.isEmpty()) {
            toast("公司服务器配置异常，请到高级设置检查");
            return;
        }
        sessionStore.setServerEndpoint(endpoint);
        executorService.execute(() -> {
            try {
                SoloServerClient.LoginResult result = serverClient.demoLogin(endpoint, displayName, email);
                sessionStore.saveLogin(result.getToken(), result.getDisplayName(), result.getEmail());
                refreshMobileConfigAsync();
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

    private void loginWithLdap(String serverEndpoint, String username, String password) {
        String endpoint = normalizeServerEndpoint(serverEndpoint);
        String loginName = username == null ? "" : username.trim();
        if (endpoint.isEmpty()) {
            toast("公司服务器配置异常，请到高级设置检查");
            return;
        }
        if (loginName.isEmpty() || password == null || password.isEmpty()) {
            toast("请输入用户名和密码");
            return;
        }
        sessionStore.setServerEndpoint(endpoint);
        executorService.execute(() -> {
            try {
                SoloServerClient.LoginResult result = serverClient.ldapLogin(endpoint, loginName, password);
                sessionStore.saveLogin(result.getToken(), result.getDisplayName(), result.getEmail(), loginName);
                refreshMobileConfigAsync();
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
        String base = normalizeServerEndpoint(serverEndpoint);
        if (base.isEmpty()) {
            toast("公司服务器配置异常，请到高级设置检查");
            return;
        }
        Uri baseUri = Uri.parse(base);
        if (!"http".equals(baseUri.getScheme()) && !"https".equals(baseUri.getScheme())) {
            toast("服务器地址需要以 http:// 或 https:// 开头");
            return;
        }
        sessionStore.setServerEndpoint(base);
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

    private void openLatestRelease() {
        if (!sessionStore.isLoggedIn()) {
            toast("请先登录");
            return;
        }
        String endpoint = ensureServerEndpoint();
        if (endpoint.isEmpty()) {
            toast("公司服务器配置异常，请到高级设置检查");
            return;
        }
        executorService.execute(() -> {
            try {
                SoloServerClient.ReleaseInfo release = serverClient.latestRelease(endpoint, sessionStore.getToken());
                if (release == null || release.getDownloadUrl().isEmpty()) {
                    runOnUiThread(() -> toast("服务器还没有发布 APK"));
                    return;
                }
                Uri downloadUri = Uri.parse(absoluteUrl(endpoint, release.getDownloadUrl()));
                runOnUiThread(() -> {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, downloadUri));
                        toast("正在打开下载：" + release.getVersionName());
                    } catch (ActivityNotFoundException exception) {
                        toast("无法打开 APK 下载页面");
                    }
                });
            } catch (Exception exception) {
                runOnUiThread(() -> toast("检查更新失败：" + exception.getMessage()));
            }
        });
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

    private String normalizeServerEndpoint(String value) {
        String endpoint = value == null ? "" : value.trim();
        while (endpoint.endsWith("/")) {
            endpoint = endpoint.substring(0, endpoint.length() - 1);
        }
        return endpoint;
    }

    private String absoluteUrl(String endpoint, String pathOrUrl) {
        String value = pathOrUrl == null ? "" : pathOrUrl.trim();
        if (value.startsWith("http://") || value.startsWith("https://")) {
            return value;
        }
        if (!value.startsWith("/")) {
            value = "/" + value;
        }
        return normalizeServerEndpoint(endpoint) + value;
    }

    private long segmentRotateIntervalMillis() {
        return Math.max(1, sessionStore.getAudioSegmentMinutes()) * 60_000L;
    }

    private void addMeetingSummary(MeetingRecord record) {
        LinearLayout card = card();
        card.addView(text(record.getTitle(), 18, true), matchWrap());
        card.addView(text(statusLabel(record.getStatus()), 14, false), matchWrap());
        card.addView(text("创建：" + TimeFormat.display(record.getCreatedAtMillis()), 13, false), matchWrap());
        card.addView(text(recordProgressText(record), 13, false), matchWrap());
        if (audioRecorder.isRecording() && "local_recording".equals(record.getStatus())) {
            long seconds = Math.max(0, (System.currentTimeMillis() - recordingStartedAt) / 1000);
            card.addView(text("已录制：" + (seconds / 60) + " 分 " + (seconds % 60) + " 秒", 13, false), matchWrap());
        }
        if (record.openRecordingSegmentCount() > 0 || record.hasPendingLocalAudio()) {
            card.addView(text("仍有未完成上传的本地音频分段。请保持 App 数据，网络恢复后点击同步会继续补传。", 13, false), matchWrap());
        }
        if ("partial_ready".equals(record.getStatus())) {
            card.addView(text("已有阶段转写，完整纪要和待办会在结束处理后继续补充。", 13, false), matchWrap());
        }
        content.addView(card, spacedParams());
    }

    private void addRecordingSegmentStatus(MeetingRecord record) {
        if (record.getAudioSegments().isEmpty()) {
            return;
        }
        LinearLayout card = card();
        card.addView(text("录音分段与上传状态", 16, true), matchWrap());
        for (AudioSegment segment : record.getAudioSegments()) {
            File file = new File(segment.getPath());
            StringBuilder line = new StringBuilder();
            line.append("分段 ").append(segment.getSegmentNo())
                    .append("  ")
                    .append(time(segment.getStartMillis()))
                    .append("-")
                    .append(time(segment.getEndMillis()))
                    .append(" · ")
                    .append(uploadStatusLabel(segment.getUploadStatus()));
            if (file.exists()) {
                line.append(" · ").append(formatBytes(file.length()));
            } else if (!segment.getDownloadUrl().isEmpty()) {
                line.append(" · 服务器可下载");
            } else {
                line.append(" · 本机文件待确认");
            }
            card.addView(text(line.toString(), 13, false), matchWrap());
        }
        if (autoSyncRunning) {
            card.addView(text("正在自动上传，完成后这里会继续更新。", 13, false), matchWrap());
        } else if (record.hasPendingLocalAudio()) {
            card.addView(text("网络不稳定时会保留在本机，并每 30 秒自动重试。", 13, false), matchWrap());
        }
        content.addView(card, spacedParams());
    }

    private void renderRecordingIfCurrent() {
        if (currentTab == 0) {
            renderCurrentTab();
        }
    }

    private String segmentLogMessage(AudioSegment segment, String prefix) {
        File file = new File(segment.getPath());
        return prefix
                + "：segmentNo=" + segment.getSegmentNo()
                + ", sourceId=" + segment.getSourceId()
                + ", sourceSegmentNo=" + segment.getSourceSegmentNo()
                + ", status=" + segment.getUploadStatus()
                + ", fileExists=" + file.exists()
                + ", size=" + (file.exists() ? file.length() : 0);
    }

    private void uploadLogsAsync(boolean force) {
        if (!sessionStore.isLoggedIn()) {
            return;
        }
        long now = System.currentTimeMillis();
        if (!force && now - lastLogUploadAt < 15_000L) {
            return;
        }
        lastLogUploadAt = now;
        executorService.execute(() -> {
            try {
                JSONArray logs = appLogger.snapshot(200);
                if (logs.length() == 0) {
                    return;
                }
                serverClient.uploadClientLogs(
                        sessionStore.getServerEndpoint(),
                        sessionStore.getToken(),
                        logs);
                appLogger.markUploaded();
            } catch (Exception ignored) {
                // Local logs stay on disk and will be retried later.
            }
        });
    }

    private void addSectionTitle(String label) {
        TextView view = text(label, 20, true);
        view.setPadding(0, dp(12), 0, dp(8));
        content.addView(view, matchWrap());
    }

    private void addHint(String label) {
        TextView view = text(label, 14, false);
        view.setTextColor(COLOR_MUTED);
        content.addView(view, matchWrap());
    }

    private LinearLayout card() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(14), dp(14), dp(14), dp(14));
        card.setBackground(makeBg(COLOR_SURFACE, dp(8), COLOR_LINE));
        return card;
    }

    private TextView cardText(String label) {
        TextView view = text(label, 16, true);
        view.setGravity(Gravity.CENTER_VERTICAL);
        view.setPadding(dp(14), dp(16), dp(14), dp(16));
        view.setBackground(makeBg(COLOR_SURFACE, dp(8), COLOR_LINE));
        return view;
    }

    private TextView actionCardText(ActionItem item) {
        StringBuilder builder = new StringBuilder();
        if (item.isReviewOnly()) {
            builder.append("系统复核提醒，不会作为督办待办\n");
        }
        builder.append(item.getOwner())
                .append("：")
                .append(item.getTask());
        if (!item.getDue().isEmpty()) {
            builder.append(" · ").append(item.getDue());
        }
        builder.append(" · ").append(actionStatusLabel(item.getStatus()));
        String evidenceLabel = actionEvidenceLabel(item);
        if (!evidenceLabel.isEmpty()) {
            builder.append("\n").append(evidenceLabel);
        }
        if (!item.getEvidenceReason().isEmpty()) {
            builder.append("\n").append(item.getEvidenceReason());
        }
        TextView view = cardText(builder.toString());
        view.setTextSize(item.isReviewOnly() ? 15 : 16);
        return view;
    }

    private String actionEvidenceLabel(ActionItem item) {
        String evidenceStatus = item.getEvidenceStatus();
        if ("system_review".equals(evidenceStatus) || item.isReviewOnly()) {
            return "证据状态：系统复核提醒";
        }
        if ("supported".equals(evidenceStatus)) {
            return "证据状态：有转写依据";
        }
        if ("majority".equals(evidenceStatus)) {
            return "证据状态：多数录音源支持，建议抽查";
        }
        if ("weak_owner".equals(evidenceStatus)) {
            return "证据状态：负责人证据弱";
        }
        if ("unsupported".equals(evidenceStatus)) {
            return "证据状态：缺少转写证据";
        }
        if ("conflict".equals(evidenceStatus)) {
            return "证据状态：多源录音存在冲突";
        }
        if ("contradiction".equals(evidenceStatus)) {
            return "证据状态：与转写语义冲突";
        }
        if (item.requiresReview()) {
            return "证据状态：待人工核对";
        }
        return "";
    }

    private TextView text(String label, int size, boolean bold) {
        TextView view = new TextView(this);
        view.setText(label == null ? "" : label);
        view.setTextSize(size);
        view.setTextColor(COLOR_TEXT);
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
        editText.setTextColor(COLOR_TEXT);
        editText.setHintTextColor(COLOR_MUTED);
        editText.setBackground(makeBg(COLOR_SURFACE, dp(8), COLOR_LINE));
        editText.setPadding(dp(12), 0, dp(12), 0);
        return editText;
    }

    private Button primaryButton(String label) {
        Button button = makeButton(label);
        button.setTextColor(Color.WHITE);
        button.setBackground(makeBg(COLOR_PRIMARY, dp(8), 0));
        return button;
    }

    private Button secondaryButton(String label) {
        Button button = makeButton(label);
        button.setTextColor(COLOR_TEXT);
        button.setBackground(makeBg(Color.rgb(232, 238, 245), dp(8), 0));
        return button;
    }

    private Button makeButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextSize(15);
        button.setMinHeight(dp(42));
        return button;
    }

    private String statusLabel(String status) {
        if ("ready".equals(status) || "processed".equals(status)) {
            return "已完成";
        }
        if ("queued".equals(status)) {
            return "排队中";
        }
        if ("partial_ready".equals(status)) {
            return "分段转写中";
        }
        if ("uploaded".equals(status) || "uploading".equals(status)) {
            return "上传中";
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

    private String actionStatusLabel(String status) {
        if ("doing".equals(status)) {
            return "进行中";
        }
        if ("done".equals(status)) {
            return "已完成";
        }
        if ("blocked".equals(status)) {
            return "受阻";
        }
        return "待处理";
    }

    private String recordProgressText(MeetingRecord record) {
        int total = record.getAudioSegments().size();
        int uploaded = record.uploadedAudioSegmentCount();
        int pending = record.pendingUploadSegmentCount();
        int open = record.openRecordingSegmentCount();
        int transcripts = record.getTranscriptSegments().size();
        return "音频分段：" + total
                + " · 已上传：" + uploaded
                + " · 待上传：" + pending
                + (open > 0 ? " · 正在写入：" + open : "")
                + " · 转写段落：" + transcripts;
    }

    private String uploadStatusLabel(String status) {
        if ("uploaded".equals(status)) {
            return "已上传";
        }
        if ("uploading".equals(status)) {
            return "上传中";
        }
        if ("upload_failed".equals(status)) {
            return "上传失败，等待重试";
        }
        if ("local_recording".equals(status)) {
            return "正在写入";
        }
        if ("local".equals(status) || "local_recorded".equals(status)) {
            return "等待上传";
        }
        return status == null || status.isEmpty() ? "等待上传" : status;
    }

    private String formatBytes(long bytes) {
        if (bytes < 1024) {
            return bytes + " B";
        }
        double kb = bytes / 1024.0;
        if (kb < 1024) {
            return String.format("%.1f KB", kb);
        }
        return String.format("%.1f MB", kb / 1024.0);
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

    private GradientDrawable makeBg(int color, int radius, int strokeColor) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(radius);
        if (strokeColor != 0) {
            drawable.setStroke(dp(1), strokeColor);
        }
        return drawable;
    }

    private void toast(String message) {
        Toast.makeText(this, message == null ? "" : message, Toast.LENGTH_SHORT).show();
    }

    private String valueOrDefault(String value, String fallback) {
        return value == null || value.trim().isEmpty() ? fallback : value.trim();
    }

    private static final class SpeakerStat {
        private final String name;
        private int count;
        private long durationMillis;

        private SpeakerStat(String name) {
            this.name = name == null || name.trim().isEmpty() ? "发言人" : name;
        }
    }
}
