const TRANSCRIPT_INITIAL_ROWS = 80;
const TRANSCRIPT_LOAD_MORE_ROWS = 80;

const state = {
  token: localStorage.getItem("solo_token") || "",
  user: JSON.parse(localStorage.getItem("solo_user") || "null"),
  meetings: [],
  joinableMeetings: [],
  selectedMeetingId: "",
  loadingMeetingId: "",
  meetingOverviewController: null,
  meetingDetailController: null,
  meetingTranscriptController: null,
  meetingLoadSeq: 0,
  selectedTranscriptVersion: 1,
  selectedDownloadPlatform: "android",
  selectedTranscriptFilter: "all",
  transcriptRenderLimit: TRANSCRIPT_INITIAL_ROWS,
  currentTranscriptSegments: [],
  recorder: {
    mediaRecorder: null,
    stream: null,
    meetingId: "",
    sourceId: "primary",
    sourceLabel: "",
    startedAt: 0,
    segmentStartedAt: 0,
    segmentNo: 0,
    chunks: [],
    timer: null,
    segmentMs: 5 * 60 * 1000,
    uploads: [],
    pendingBlobs: [],
    mimeType: "",
    continueAfterStop: false,
  },
};

const PLATFORM_LABELS = {
  android: "Android APK",
  windows: "Windows EXE",
  macos: "macOS DMG",
  ios: "iOS IPA",
  harmony: "HarmonyOS HAP",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const IS_DESKTOP_CLIENT = new URLSearchParams(window.location.search).get("client") === "desktop";

function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.add("show");
  setTimeout(() => box.classList.remove("show"), 2600);
}

function extractErrorDetail(text) {
  const raw = String(text || "");
  if (!raw) return "";
  try {
    const payload = JSON.parse(raw);
    const detail = payload.detail || payload.message || payload.error || "";
    if (Array.isArray(detail)) {
      return detail.map((item) => item?.msg || item?.message || String(item)).join("；");
    }
    if (detail && typeof detail === "object") {
      return detail.msg || detail.message || JSON.stringify(detail);
    }
    return String(detail || raw);
  } catch (error) {
    return raw;
  }
}

function httpError(status, text) {
  const detail = extractErrorDetail(text) || `HTTP ${status}`;
  const error = new Error(detail);
  error.status = status;
  error.detail = detail;
  error.raw = String(text || "");
  return error;
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const text = await response.text();
    throw httpError(response.status, text);
  }
  const text = await response.text();
  return text ? JSON.parse(text) : {};
}

function clearSessionState() {
  localStorage.removeItem("solo_token");
  localStorage.removeItem("solo_user");
  state.token = "";
  state.user = null;
  state.meetings = [];
  state.joinableMeetings = [];
}

function renderLoggedOutState() {
  renderAccount();
  renderMeetingList();
  renderMeetingSummaryStrip();
  renderJoinableMeetingLists();
}

function isAuthError(error) {
  const text = `${error?.status || ""} ${error?.detail || ""} ${error?.message || ""} ${error?.raw || ""}`;
  return Number(error?.status) === 401
    || text.includes("Missing access token")
    || text.includes("Invalid access token")
    || text.includes("Not authenticated")
    || text.includes("Could not validate credentials")
    || text.includes("Unauthorized");
}

function promptLogin(message = "登录状态已过期，请重新登录") {
  clearSessionState();
  renderLoggedOutState();
  showLogin();
  toast(message);
}

function requireLoginForAction(message = "请先登录后再继续") {
  if (state.token) return true;
  promptLogin(message);
  return false;
}

function setView(name) {
  if (IS_DESKTOP_CLIENT && ["downloads", "admin"].includes(name)) {
    name = "recorder";
  }
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  if (name === "downloads") loadRelease();
  if (name === "admin") loadAdmin();
  if (name === "recorder") loadRecorderConfig();
  if (name === "status") renderAccount();
}

function showLogin() {
  $("#loginModal").classList.remove("hidden");
  $("#loginUsername").focus();
}

function hideLogin() {
  $("#loginPassword").value = "";
  $("#loginModal").classList.add("hidden");
}

async function ldapLogin(event) {
  event.preventDefault();
  const username = $("#loginUsername").value.trim();
  const password = $("#loginPassword").value;
  if (!username || !password) {
    toast("请输入用户名和密码");
    return;
  }
  try {
    const data = await api("/api/auth/ldap-login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    state.token = data.access_token;
    state.user = data.user;
    localStorage.setItem("solo_token", state.token);
    localStorage.setItem("solo_user", JSON.stringify(state.user));
    hideLogin();
    renderAccount();
    await loadMeetings();
    await loadJoinableMeetings();
    toast("已登录");
  } catch (error) {
    toast("登录失败，请检查用户名、密码或服务器配置");
  }
}

async function demoLogin() {
  const displayName = prompt("姓名", state.user?.display_name || "Demo User") || "Demo User";
  const email = prompt("邮箱：admin@example.com 会获得管理员权限", state.user?.email || "admin@example.com") || "admin@example.com";
  const data = await api("/api/auth/demo-login", {
    method: "POST",
    body: JSON.stringify({ display_name: displayName, email }),
  });
  state.token = data.access_token;
  state.user = data.user;
  localStorage.setItem("solo_token", state.token);
  localStorage.setItem("solo_user", JSON.stringify(state.user));
  renderAccount();
  await loadMeetings();
  await loadJoinableMeetings();
  toast("已登录");
}

function renderAccount() {
  $("#accountName").textContent = state.user ? `${state.user.display_name} (${state.user.role})` : "未登录";
  $("#loginButton").textContent = state.user ? "切换账号" : "统一登录";
  const desktopStatus = $("#desktopAccountStatus");
  const desktopHint = $("#desktopAccountHint");
  if (desktopStatus && desktopHint) {
    desktopStatus.textContent = state.user ? `${state.user.display_name} (${state.user.role})` : "未登录";
    desktopHint.textContent = state.user ? "可以录音、同步和查看会议记录。" : "录音和查看记录需要先登录。";
  }
}

function ssoLogin() {
  window.location.href = `/api/auth/sso/start?redirect_after=${encodeURIComponent("/")}`;
}

function configureClientMode() {
  document.body.classList.toggle("desktop-client", IS_DESKTOP_CLIENT);
  renderRecordCapabilityHint();
  if (!IS_DESKTOP_CLIENT) return;
  document.title = "SoloRecord 录音工具";
  document.querySelector('[data-view="meetings"]').textContent = "记录";
  document.querySelector('[data-view="recorder"]').textContent = "录音";
  document.querySelectorAll('[data-view="downloads"], [data-view="admin"]').forEach((item) => {
    item.hidden = true;
  });
  setView("recorder");
}

function logout() {
  clearSessionState();
  renderLoggedOutState();
  toast("已退出登录");
}

async function loadMeetings(query = "") {
  if (!state.token) return;
  const data = query ? await api(`/api/web/search?q=${encodeURIComponent(query)}`) : await api("/api/web/meetings");
  state.meetings = data.items || [];
  renderMeetingList();
  renderMeetingSummaryStrip();
}

async function loadJoinableMeetings(query = "") {
  if (!state.token) {
    state.joinableMeetings = [];
    renderJoinableMeetingLists();
    return;
  }
  try {
    const data = await api(`/api/web/meetings/discover?q=${encodeURIComponent(query || "")}`);
    state.joinableMeetings = data.items || [];
  } catch (error) {
    state.joinableMeetings = [];
  }
  renderJoinableMeetingLists();
}

function renderJoinableMeetingLists() {
  renderJoinableMeetings("record");
  renderJoinableMeetings("upload");
}

function renderJoinableMeetings(target) {
  const container = $(`#${target}DiscoverList`);
  const input = target === "record" ? $("#recordJoinCode") : $("#uploadJoinCode");
  if (!container || !input) return;
  const query = input.value.trim();
  const normalizedQuery = normalizeJoinQuery(query);
  const titleQuery = query.toLowerCase();
  const items = state.joinableMeetings.filter((item) => {
    if (!query) return true;
    return String(item.join_code || "").includes(normalizedQuery)
      || String(item.title || "").toLowerCase().includes(titleQuery);
  });
  if (!state.token) {
    container.innerHTML = "";
    return;
  }
  if (!items.length) {
    container.innerHTML = `<div class="join-discovery-empty">暂无可加入会议</div>`;
    return;
  }
  container.innerHTML = `
    <div class="join-discovery-title">可加入会议</div>
    <div class="join-discovery-list">
      ${items.slice(0, 8).map((item) => `
        <button type="button" class="join-discovery-item" data-join-code="${escapeAttr(item.join_code || "")}">
          <span>
            <b>${escapeHtml(item.title || "未命名会议")}</b>
            <small>${escapeHtml(item.owner_name || "发起人")} · ${escapeHtml(statusLabel(item.status))}</small>
          </span>
          <span class="join-discovery-meta">
            <b>${escapeHtml(item.join_code || "")}</b>
            <small>${Number(item.source_count || 0)}/${Number(item.max_sources || 1)}</small>
          </span>
        </button>
      `).join("")}
    </div>
  `;
  container.querySelectorAll(".join-discovery-item").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.joinCode || "";
      input.focus();
      renderJoinableMeetings(target);
    });
  });
}

function scheduleJoinableMeetingLoad(input) {
  window.clearTimeout(input._soloDiscoverTimer);
  input._soloDiscoverTimer = window.setTimeout(() => {
    loadJoinableMeetings(input.value.trim());
  }, 220);
}

function normalizeJoinQuery(value) {
  return String(value || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
}

function renderMeetingList() {
  const list = $("#meetingList");
  if (!state.meetings.length) {
    list.innerHTML = `<div class="empty-state">暂无会议记录</div>`;
    return;
  }
  list.innerHTML = state.meetings.map((meeting) => `
    <article class="meeting-card ${meeting.id === state.selectedMeetingId ? "active" : ""} ${meeting.id === state.loadingMeetingId ? "loading" : ""}" data-id="${meeting.id}" aria-busy="${meeting.id === state.loadingMeetingId ? "true" : "false"}">
      <h3>${escapeHtml(meeting.title)}</h3>
      <div class="meta-row">
        <span>${formatDate(meeting.created_at)}</span>
        <span class="status-pill">${statusLabel(meeting.status)}</span>
      </div>
      <div class="meeting-card-foot">
        <span>${formatTime(meeting.duration_ms || 0)}</span>
        <span>${meeting.id === state.loadingMeetingId ? "<i class=\"mini-spinner\" aria-hidden=\"true\"></i>打开中" : `v${meeting.version || 1}`}</span>
      </div>
    </article>
  `).join("");
  $$(".meeting-card").forEach((card) => {
    card.addEventListener("click", () => selectMeeting(card.dataset.id));
  });
}

function renderMeetingSummaryStrip() {
  const box = $("#meetingSummaryStrip");
  if (!box) return;
  if (!state.token) {
    box.innerHTML = "";
    return;
  }
  const total = state.meetings.length;
  const ready = state.meetings.filter((meeting) => meeting.status === "ready").length;
  const active = state.meetings.filter((meeting) => ["partial_ready", "queued", "preprocessing", "transcribing", "summarizing", "uploaded"].includes(meeting.status)).length;
  const failed = state.meetings.filter((meeting) => meeting.status === "failed").length;
  box.innerHTML = `
    <div class="summary-tile"><b>${total}</b><span>全部会议</span></div>
    <div class="summary-tile"><b>${ready}</b><span>已完成</span></div>
    <div class="summary-tile"><b>${active}</b><span>处理中</span></div>
    <div class="summary-tile"><b>${failed}</b><span>需处理</span></div>
  `;
}

async function selectMeeting(id) {
  if (!id) return;
  const meeting = state.meetings.find((item) => item.id === id) || null;
  const loadSeq = state.meetingLoadSeq + 1;
  const isCurrentLoad = () => loadSeq === state.meetingLoadSeq && id === state.selectedMeetingId;
  abortMeetingLoadControllers();
  state.meetingLoadSeq = loadSeq;
  state.selectedMeetingId = id;
  state.loadingMeetingId = id;
  state.selectedTranscriptFilter = "all";
  state.transcriptRenderLimit = TRANSCRIPT_INITIAL_ROWS;
  state.currentMeetingDetail = null;
  state.currentTranscriptSegments = [];
  renderMeetingList();
  renderMeetingLoading(meeting);
  scrollMeetingDetailToTop();
  await nextFrame();
  if (!isCurrentLoad()) return;
  try {
    state.meetingOverviewController = new AbortController();
    state.meetingDetailController = new AbortController();
    state.meetingTranscriptController = new AbortController();
    const overviewTask = api(`/api/web/meetings/${id}/overview`, {
      signal: state.meetingOverviewController.signal,
    });
    const overview = await overviewTask;
    if (!isCurrentLoad()) return;
    state.selectedTranscriptVersion = overview.meeting?.version || 1;
    let latestDetail = overview;
    let latestTranscript = [];
    let detailDone = false;
    let transcriptDone = false;
    let detailError = "";
    let transcriptError = "";
    const renderProgress = () => {
      if (!isCurrentLoad()) return;
      renderMeetingDetail(latestDetail, latestTranscript, {
        detailLoading: !detailDone,
        transcriptLoading: !transcriptDone,
        transcriptUnavailable: Boolean(transcriptError),
        loadError: detailError || transcriptError,
      });
    };
    renderProgress();
    scrollMeetingDetailToTop();
    const detailTask = api(`/api/web/meetings/${id}`, {
      signal: state.meetingDetailController.signal,
    })
      .then((data) => {
        if (!isCurrentLoad()) return;
        latestDetail = data;
      })
      .catch((error) => {
        if (!isCurrentLoad()) return;
        detailError = `质量证据暂未加载完成：${error.message}`;
      })
      .finally(() => {
        if (!isCurrentLoad()) return;
        detailDone = true;
        renderProgress();
      });
    const transcriptTask = api(`/api/web/meetings/${id}/transcript`, {
      signal: state.meetingTranscriptController.signal,
    })
      .then((transcript) => {
        if (!isCurrentLoad()) return;
        state.selectedTranscriptVersion = transcript.version || state.selectedTranscriptVersion;
        latestTranscript = transcript.segments || [];
      })
      .catch((error) => {
        if (!isCurrentLoad()) return;
        transcriptError = `转写时间线暂未加载完成：${error.message}`;
      })
      .finally(() => {
        if (!isCurrentLoad()) return;
        transcriptDone = true;
        renderProgress();
      });
    await Promise.all([detailTask, transcriptTask]);
    if (!isCurrentLoad()) return;
    state.loadingMeetingId = "";
    clearMeetingLoadControllers();
    renderMeetingList();
    if (detailError || transcriptError) {
      toast("会议已打开，部分内容稍后可刷新重试");
    }
  } catch (error) {
    if (!isCurrentLoad()) return;
    if (isAbortError(error)) return;
    state.loadingMeetingId = "";
    clearMeetingLoadControllers();
    renderMeetingList();
    renderMeetingLoadError(meeting, error);
  }
}

function scrollMeetingDetailToTop() {
  const scrollBox = $("#meetingDetail .meeting-detail-scroll");
  if (scrollBox) {
    scrollBox.scrollTo({ top: 0, left: 0 });
    return;
  }
  const panel = $("#meetingDetail")?.closest(".detail-panel");
  if (panel) panel.scrollTo({ top: 0, left: 0 });
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function abortMeetingLoadControllers() {
  [
    state.meetingOverviewController,
    state.meetingDetailController,
    state.meetingTranscriptController,
  ].forEach((controller) => controller?.abort?.());
  clearMeetingLoadControllers();
}

function clearMeetingLoadControllers() {
  state.meetingOverviewController = null;
  state.meetingDetailController = null;
  state.meetingTranscriptController = null;
}

function isAbortError(error) {
  return error?.name === "AbortError" || String(error?.message || "").includes("aborted");
}

function renderMeetingLoading(meeting) {
  const title = meeting?.title || "会议详情";
  const status = meeting?.status ? statusLabel(meeting.status) : "准备打开";
  const duration = formatTime(meeting?.duration_ms || 0);
  const version = meeting?.version || 1;
  $("#meetingDetail").innerHTML = `
    <div class="detail-loading" role="status" aria-live="polite">
      <div class="loading-head">
        <span class="loading-spinner" aria-hidden="true"></span>
        <div>
          <b>正在打开会议记录</b>
          <span>${escapeHtml(title)}</span>
        </div>
      </div>
      <div class="loading-meeting-card">
        <div>
          <b>${escapeHtml(title)}</b>
          <span>${escapeHtml(status)} · ${duration} · v${version}</span>
        </div>
        <span>已收到点击，正在连接服务器</span>
      </div>
      <div class="loading-steps">
        <span><i></i>读取会议信息</span>
        <span><i></i>读取转写时间线</span>
        <span><i></i>整理质量与证据</span>
      </div>
      <div class="skeleton-stack" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </div>
    </div>
  `;
}

function renderMeetingLoadError(meeting, error) {
  const title = meeting?.title || "会议详情";
  $("#meetingDetail").innerHTML = `
    <div class="empty-state detail-error">
      <div>
        <b>${escapeHtml(title)} 加载失败</b>
        <p>${escapeHtml(friendlyError(error))}</p>
        <button type="button" id="retryMeetingLoad" class="button secondary">重新加载</button>
      </div>
    </div>
  `;
  $("#retryMeetingLoad")?.addEventListener("click", () => selectMeeting(state.selectedMeetingId));
  toast("会议详情加载失败，请稍后重试");
}

function renderMeetingDetail(data, transcriptSegments, options = {}) {
  const meeting = data.meeting;
  state.currentMeetingDetail = data;
  state.currentTranscriptSegments = transcriptSegments;
  const detailLoading = Boolean(options.detailLoading);
  const transcriptLoading = Boolean(options.transcriptLoading);
  const transcriptUnavailable = Boolean(options.transcriptUnavailable);
  const isLoadingMore = detailLoading || transcriptLoading;
  const loadError = String(options.loadError || "");
  const transcriptDisabled = transcriptLoading || transcriptUnavailable;
  const jobs = data.jobs || [];
  const actions = data.actionItems || [];
  const exports = data.exports || [];
  const qualityReport = data.qualityReport || (transcriptLoading
    ? { status: "review_recommended", metrics: {}, issues: [], recommendations: [] }
    : buildClientQualityReport(transcriptSegments, actions));
  const knowledgeReadiness = data.knowledgeReadiness || null;
  const audioSegments = data.audioSegments || [];
  const uploadedAudio = audioSegments.filter((segment) => segment.upload_status === "uploaded").length;
  const recordingSources = data.recordingSources || [];
  const statusHint = meetingStatusHint(meeting.status, audioSegments, transcriptSegments);
  const speakerSamples = buildSpeakerSamples(transcriptSegments, audioSegments, meeting.id);
  const speakerStats = (transcriptLoading || transcriptUnavailable) && !transcriptSegments.length
    ? buildSpeakerStatsFromSpeakers(data.speakers || [], actions)
    : buildSpeakerStats(transcriptSegments, actions, speakerSamples);
  const segmentInsights = buildSegmentInsights(transcriptSegments, actions, audioSegments);
  const actionRiskMap = buildActionRiskMap(qualityReport);
  const speakerEvidenceMap = buildSpeakerEvidenceMap(qualityReport);
  const actionRows = actions.length ? actions : [{ owner: "", task: "", due: "", status: "open" }];
  const filteredSegments = filteredTranscriptSegments(transcriptSegments);
  const availableFilters = buildTranscriptFilters(transcriptSegments);
  const transcriptMeta = data.transcriptMeta || {};
  const transcriptCount = transcriptLoading
    ? Number(transcriptMeta.segment_count || 0)
    : transcriptSegments.length;
  const visibleTranscriptSegments = transcriptLoading
    ? []
    : filteredSegments.slice(0, state.transcriptRenderLimit);
  const hiddenTranscriptCount = Math.max(0, filteredSegments.length - visibleTranscriptSegments.length);
  const transcriptResultLabel = transcriptLoading
    ? `预计 ${transcriptCount} 段`
    : `${filteredSegments.length} 段${hiddenTranscriptCount ? `，先显示 ${visibleTranscriptSegments.length} 段` : ""}`;
  $("#meetingDetail").innerHTML = `
    <div class="meeting-detail-shell ${isLoadingMore ? "is-loading-more" : ""}">
      <div class="detail-head">
        <div class="detail-title-row">
          <input id="detailTitle" class="input detail-title" value="${escapeAttr(meeting.title)}">
          <span class="status-pill">${statusLabel(meeting.status)}</span>
        </div>
        <div class="detail-actions">
          <button id="saveMeeting" class="button primary">保存标题/纪要</button>
          <button id="processMeeting" class="button secondary">重新转写整理</button>
        </div>
      </div>
      <div class="status-banner ${meeting.status === "failed" ? "danger" : ""}">
        <b>${isLoadingMore ? "会议已打开，正在补齐内容" : statusLabel(meeting.status)}</b>
        <span>${escapeHtml(loadError || statusHint)}</span>
      </div>
      <div class="progress-strip">
        <span>录音分段：${audioSegments.length}</span>
        <span>录音源：${recordingSources.length || 1}</span>
        <span>已上传：${uploadedAudio}</span>
        <span>转写段落：${transcriptCount}</span>
        <span>总时长：${formatTime(meeting.duration_ms || 0)}</span>
      </div>
      ${isLoadingMore ? `
        <div class="inline-loading" role="status" aria-live="polite">
          <span class="loading-spinner small" aria-hidden="true"></span>
          <div>
            <b>已打开会议，正在补全转写和证据检查</b>
            <span>${detailLoading && transcriptLoading ? "先显示概要，完整证据和时间线会分批出现。" : detailLoading ? "转写时间线已就绪，正在补全质量证据。" : "会议信息已就绪，正在读取转写时间线。"}</span>
          </div>
        </div>
      ` : ""}
      <div class="meeting-detail-scroll">
        <section class="meeting-priority-grid" aria-label="会议复核主工作区">
          <div class="summary-box priority-card priority-people">
            <div class="section-row">
              <h3>人物校对</h3>
              <span class="hint">先确认发言人，后续纪要和待办才可信</span>
            </div>
            <div class="people-grid">
              ${speakerStats.map(renderPersonCard).join("") || (transcriptLoading ? renderDeferredPanel("正在加载人物校对", "人物声音样本会在转写时间线加载后显示。") : "<p class='hint'>暂无人物信息。转写完成后可在这里统一校对人名。</p>")}
            </div>
          </div>
          <div class="summary-box priority-card priority-summary">
            <h3>会议纪要</h3>
            <textarea id="detailSummary" class="input" rows="7">${escapeHtml(meeting.summary || "")}</textarea>
            <h3 class="subsection-title">分角色整理</h3>
            <textarea id="detailRoleNotes" class="input" rows="5">${escapeHtml(meeting.role_notes || "")}</textarea>
          </div>
          <div class="actions-box priority-card priority-actions">
            <div class="section-row">
              <h3>待办</h3>
              <div class="detail-actions">
                <button id="copyActions" class="button secondary">复制待办</button>
                <button id="applyAllSuggestedOwners" class="button secondary">应用全部建议负责人</button>
                <button id="addActionItem" class="button secondary">新增待办</button>
              </div>
            </div>
            <div id="actionList" class="action-list">
              ${actionRows.map((item) => renderActionRow(item, actionRiskMap)).join("")}
            </div>
            <button id="saveActions" class="button primary">保存待办</button>
          </div>
        </section>
        <section class="evidence-workspace" aria-label="证据与回听工作区">
          <div class="summary-box">
            <div class="section-row">
              <h3>整理质量</h3>
              <span class="quality-score ${escapeAttr(qualityReport.status || "review_recommended")}">${qualityScoreLabel(qualityReport)}</span>
            </div>
            ${detailLoading || transcriptLoading ? renderDeferredPanel("正在加载质量证据", "转写时间线到达后会显示发言人证据、待办证据和可入库检查。") : renderQualityReport(qualityReport, knowledgeReadiness)}
          </div>
          <div class="summary-box">
            <div class="section-row">
              <h3>分段洞察</h3>
              <span class="hint">按时间查看发言人、讨论内容、待办和负责人</span>
            </div>
            ${transcriptUnavailable ? renderUnavailablePanel("转写时间线暂未加载", "请稍后重新打开会议，已显示的纪要和待办不会丢失。") : (transcriptLoading ? renderDeferredPanel("正在加载分段洞察", "分段列表到达后会按时间聚合发言人、主题和待办。") : renderSegmentInsights(segmentInsights))}
          </div>
          <div class="summary-box">
            <div class="section-row">
              <h3>导出文件</h3>
              <div class="detail-actions">
                <button data-export="markdown" class="button secondary">Markdown</button>
                <button data-export="docx" class="button secondary">Word</button>
                <button data-export="pdf" class="button secondary">PDF</button>
                <button data-export="json" class="button secondary">JSON</button>
                <button data-export="srt" class="button secondary">SRT</button>
              </div>
            </div>
            <div id="exportList" class="export-list">
              ${renderExports(exports)}
            </div>
          </div>
          <div class="summary-box">
            <div class="section-row">
              <h3>录音分段</h3>
              <span class="hint">需要核对时再加载播放</span>
            </div>
            ${renderRecordingSources(recordingSources)}
            <div class="audio-list">
              ${audioSegments.map(renderAudioSegment).join("") || "<p class='hint'>暂无音频</p>"}
            </div>
          </div>
          <section id="transcriptWorkspace" class="transcript-workspace">
            <div class="section-row">
              <div>
                <h3>转写时间线</h3>
                <p class="hint">${transcriptLoading ? "正在读取转写时间线，大会议可能需要多等几秒。" : `当前筛选 ${transcriptResultLabel}。长段可直接上下滚动；如果一段里有多人说话，先拆分，再把拆出的段落设为新发言人。`}</p>
              </div>
              <div class="detail-actions">
                <select id="transcriptFilter" class="input compact-input" ${transcriptDisabled ? "disabled" : ""}>
                  ${availableFilters.map((filter) => `
                    <option value="${escapeAttr(filter.value)}" ${filter.value === state.selectedTranscriptFilter ? "selected" : ""}>
                      ${escapeHtml(filter.label)}
                    </option>
                  `).join("")}
                </select>
                <button id="expandTranscript" class="button secondary" ${transcriptDisabled ? "disabled" : ""}>展开阅读</button>
                <button id="copyTranscript" class="button secondary" ${transcriptDisabled ? "disabled" : ""}>复制转写</button>
              </div>
            </div>
            <div id="transcriptList" class="transcript-list">
              ${transcriptUnavailable ? renderUnavailablePanel("转写未加载成功", "为避免误删服务端转写，当前禁止保存空时间线。请重新打开会议或刷新页面。") : (transcriptLoading ? renderTranscriptSkeleton(transcriptCount) : (visibleTranscriptSegments.map((segment) => renderTranscriptRow(segment, speakerEvidenceMap)).join("") || "<p class='hint'>当前筛选下暂无转写</p>"))}
            </div>
            ${hiddenTranscriptCount ? `<button id="loadMoreTranscript" class="button secondary transcript-more">继续显示 ${Math.min(TRANSCRIPT_LOAD_MORE_ROWS, hiddenTranscriptCount)} 段</button>` : ""}
            <button id="saveTranscript" class="button primary" ${transcriptDisabled ? "disabled" : ""}>保存转写修改</button>
          </section>
          <div class="summary-box">
            <h3>最近任务</h3>
            <div class="job-list">
              ${jobs.map((job) => `<div class="job-item"><b>${job.current_stage}</b><span>${job.status} · ${job.progress}%</span><span class="hint">${escapeHtml(job.error_message || "")}</span></div>`).join("") || "<p class='hint'>暂无任务</p>"}
            </div>
          </div>
        </section>
      </div>
    </div>
  `;
  $("#saveMeeting").addEventListener("click", saveMeeting);
  $("#processMeeting").addEventListener("click", processSelectedMeeting);
  $("#saveTranscript")?.addEventListener("click", saveTranscript);
  $("#saveActions").addEventListener("click", saveActions);
  $("#addActionItem").addEventListener("click", addActionRow);
  $("#copyActions").addEventListener("click", copyActionsToClipboard);
  $("#applyAllSuggestedOwners").addEventListener("click", applyAllSuggestedActionOwners);
  $("#expandTranscript")?.addEventListener("click", toggleTranscriptExpanded);
  $("#loadMoreTranscript")?.addEventListener("click", () => {
    const mergedSegments = mergeRenderedTranscriptEdits(transcriptSegments);
    state.currentTranscriptSegments = mergedSegments;
    state.transcriptRenderLimit += TRANSCRIPT_LOAD_MORE_ROWS;
    renderMeetingDetail(data, mergedSegments);
  });
  $("#copyTranscript")?.addEventListener("click", copyTranscriptToClipboard);
  $("#transcriptFilter")?.addEventListener("change", (event) => {
    const mergedSegments = mergeRenderedTranscriptEdits(transcriptSegments);
    state.currentTranscriptSegments = mergedSegments;
    state.selectedTranscriptFilter = event.target.value;
    state.transcriptRenderLimit = TRANSCRIPT_INITIAL_ROWS;
    renderMeetingDetail(data, mergedSegments);
  });
  $$(".quality-shortcut").forEach((button) => {
    button.addEventListener("click", () => {
      applyTranscriptFilter(button.dataset.transcriptFilter || "all", data, transcriptSegments);
    });
  });
  $$("[data-export]").forEach((button) => {
    button.addEventListener("click", () => exportMeeting(button.dataset.export));
  });
  $$("[data-audio-load]").forEach((button) => {
    button.addEventListener("click", () => loadAuthorizedAudio(button));
  });
  $$(".person-save").forEach((button) => {
    button.addEventListener("click", () => savePersonAlias(button.closest(".person-card")));
  });
  $$(".speaker-sample-play").forEach((button) => {
    button.addEventListener("click", () => playSpeakerSample(button));
  });
  $$(".transcript-row").forEach(bindTranscriptRowEvents);
  $$(".export-download").forEach((button) => {
    button.addEventListener("click", () => downloadExport(button.dataset.url || "", button.dataset.name || ""));
  });
  $$(".export-copy").forEach((button) => {
    button.addEventListener("click", () => copyExportLink(button.dataset.url || ""));
  });
  $$(".remove-action").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest(".action-row-wrap")?.remove();
      if (!$$("#actionList .action-row-wrap").length) addActionRow();
    });
  });
  $$(".apply-suggested-owner").forEach((button) => {
    button.addEventListener("click", () => applySuggestedActionOwner(button));
  });
  $$(".jump-transcript").forEach((button) => {
    button.addEventListener("click", () => jumpToTranscriptEvidence(button));
  });
}

function applyTranscriptFilter(filter, data, transcriptSegments) {
  if (filter === "summary:evidence_weak") {
    $("#detailSummary")?.scrollIntoView({ behavior: "smooth", block: "center" });
    $("#detailSummary")?.focus();
    return;
  }
  state.selectedTranscriptFilter = filter || "all";
  renderMeetingDetail(data, transcriptSegments);
  $("#transcriptWorkspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderAudioSegment(segment) {
  const sourceLabel = segment.source_label || segment.source_id || "primary";
  const sourceSegment = segment.source_segment_no || segment.segment_no;
  return `
    <div class="audio-segment">
      <div>
        <b>${escapeHtml(sourceLabel)} · 分段 ${sourceSegment}</b>
        <span>${formatTime(segment.start_ms || 0)} - ${formatTime(segment.end_ms || 0)}</span>
      </div>
      <div class="audio-controls">
        <button type="button" class="button secondary" data-audio-load="${escapeAttr(segment.download_url || "")}">加载播放</button>
        <span class="status-pill">${segment.upload_status === "uploaded" ? "已上传" : "待上传"}</span>
      </div>
    </div>
  `;
}

function renderRecordingSources(sources) {
  if (!Array.isArray(sources) || !sources.length) return "";
  return `
    <div class="source-strip">
      ${sources.map((source) => `
        <span class="source-chip">
          ${escapeHtml(source.label || source.source_id || "录音源")}
          <small>${escapeHtml(source.device_name || source.source_id || "")}</small>
        </span>
      `).join("")}
    </div>
  `;
}

function renderActionRow(item, riskMap = new Map()) {
  const risk = actionRiskForItem(item, riskMap);
  const reviewOnly = isReviewOnlyAction(item) || risk?.reviewOnly;
  return `
    <div class="action-row-wrap ${risk ? "has-risk" : ""} ${reviewOnly ? "review-only" : ""}"
      data-action-id="${escapeAttr(item.id || "")}"
      data-review-only="${reviewOnly ? "true" : "false"}">
      ${reviewOnly ? `<div class="system-review-banner">系统复核提醒，不会复制为督办待办</div>` : ""}
      <div class="action-row">
        <input class="input action-owner" placeholder="负责人" value="${escapeAttr(item.owner || "")}">
        <input class="input action-task" placeholder="待办事项" value="${escapeAttr(item.task || "")}">
        <input class="input action-due" placeholder="截止时间" value="${escapeAttr(item.due || "")}">
        <select class="input action-status">
          ${["open", "doing", "done", "blocked"].map((status) => `
            <option value="${status}" ${status === (item.status || "open") ? "selected" : ""}>${actionStatusLabel(status)}</option>
          `).join("")}
        </select>
        <button type="button" class="button secondary remove-action">删除</button>
      </div>
      ${risk ? renderActionRisk(risk) : ""}
    </div>
  `;
}

function buildActionRiskMap(report) {
  const map = new Map();
  (report.actionEvidence || []).forEach((item) => {
    const key = actionRiskKey(item);
    if (!key) return;
    const labels = {
      supported: ["有转写依据"],
      majority: ["多数源确认"],
      system_review: ["系统复核提醒"],
      weak_owner: ["负责人证据弱"],
      conflict: ["多源冲突待核对"],
      contradiction: ["待办与原文相反"],
      unsupported: ["缺转写证据"],
    }[item.status] || ["待核对"];
    map.set(key, {
      labels,
      details: [item.reason || ""].filter(Boolean),
      evidence: Array.isArray(item.evidence) ? dedupeActionEvidence(item.evidence) : [],
      suggestedOwner: item.suggested_owner || "",
      suggestedReason: item.suggested_owner_reason || "",
      suggestedEvidence: Array.isArray(item.suggested_owner_evidence)
        ? dedupeActionEvidence(item.suggested_owner_evidence)
        : [],
      type: item.status || "supported",
      actionKind: item.action_kind || "meeting_action",
      reviewOnly: Boolean(item.review_only || item.action_kind === "system_review" || item.status === "system_review"),
      autoActionable: item.auto_actionable !== false,
      reminderSafe: item.reminder_safe === true,
    });
  });
  const add = (item, type, label, detail) => {
    const key = actionRiskKey(item);
    if (!key) return;
    const current = map.get(key) || { labels: [], details: [], evidence: [] };
    if (!current.labels.includes(label)) current.labels.push(label);
    if (detail && !current.details.includes(detail)) current.details.push(detail);
    if (!current.suggestedOwner && item.suggested_owner) {
      current.suggestedOwner = item.suggested_owner;
      current.suggestedReason = item.suggested_owner_reason || "";
      current.suggestedEvidence = Array.isArray(item.suggested_owner_evidence)
        ? dedupeActionEvidence(item.suggested_owner_evidence)
        : [];
    }
    (item.evidence || []).forEach((evidence) => {
      const evidenceKey = `${evidence.start_ms || 0}|${evidence.speaker || ""}|${evidence.text || ""}`;
      if (!current.evidence.some((existing) => existing.key === evidenceKey)) {
        current.evidence.push({ ...evidence, key: evidenceKey });
      }
    });
    current.type = current.type || type;
    current.reviewOnly = Boolean(
      current.reviewOnly
      || item.review_only
      || item.action_kind === "system_review"
      || item.status === "system_review"
    );
    current.autoActionable = item.auto_actionable !== false && current.autoActionable !== false;
    current.reminderSafe = item.reminder_safe === true || current.reminderSafe === true;
    map.set(key, current);
  };
  (report.unsupportedActions || []).forEach((item) => {
    add(item, "unsupported", "缺转写证据", "待办事项和转写原文关联较弱，请回看转写或录音。");
  });
  (report.weakActionOwners || []).forEach((item) => {
    add(item, "weak-owner", "负责人证据弱", "负责人和该任务缺少明确上下文关联，请确认后再督办。");
  });
  return map;
}

function dedupeActionEvidence(items) {
  const result = [];
  items.forEach((evidence) => {
    const key = `${evidence.start_ms || 0}|${evidence.speaker || ""}|${evidence.text || ""}`;
    if (!result.some((existing) => existing.key === key)) {
      result.push({ ...evidence, key });
    }
  });
  return result;
}

function actionRiskForItem(item, riskMap) {
  const risk = riskMap.get(actionRiskKey(item)) || null;
  if (risk || !isReviewOnlyAction(item)) return risk;
  return {
    labels: ["系统复核提醒"],
    details: [reviewOnlyActionReason(item)],
    evidence: Array.isArray(item.evidence) ? dedupeActionEvidence(item.evidence) : [],
    suggestedEvidence: [],
    type: "system_review",
    actionKind: "system_review",
    reviewOnly: true,
    autoActionable: false,
    reminderSafe: false,
  };
}

function actionRiskKey(item) {
  if (!item) return "";
  if (item.id) return `id:${item.id}`;
  const owner = String(item.owner || "").trim();
  const task = String(item.task || "").trim();
  return task ? `text:${owner}|${task}` : "";
}

function renderActionRisk(risk) {
  const evidence = Array.isArray(risk.evidence) ? risk.evidence : [];
  const suggestedEvidence = Array.isArray(risk.suggestedEvidence) ? risk.suggestedEvidence : [];
  const missingEvidence = risk.labels.includes("缺转写证据") && !evidence.length;
  return `
    <div class="action-risk-line ${escapeAttr(risk.type || "supported")}">
      ${risk.labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("")}
      <small>${escapeHtml(risk.details.join(" "))}</small>
      ${risk.suggestedOwner ? `
        <div class="action-suggestion">
          <b>建议负责人：${escapeHtml(risk.suggestedOwner)}</b>
          <small>${escapeHtml(risk.suggestedReason || "请结合转写证据确认后应用。")}</small>
          <button type="button" class="button secondary apply-suggested-owner" data-owner="${escapeAttr(risk.suggestedOwner)}">应用建议</button>
        </div>
      ` : ""}
      ${suggestedEvidence.length ? `
        <div class="action-risk-evidence suggested">
          ${suggestedEvidence.slice(0, 2).map((item) => `
            <em>${formatTime(item.start_ms || 0)} · ${escapeHtml(item.speaker || "转写")}</em>
            <q>${escapeHtml(item.text || "")}</q>
            ${renderEvidenceJumpButton(item)}
          `).join("")}
        </div>
      ` : ""}
      ${evidence.length ? `
        <div class="action-risk-evidence">
          ${evidence.slice(0, 3).map((item) => `
            <em>${formatTime(item.start_ms || 0)} · ${escapeHtml(item.speaker || "转写")}</em>
            <q>${escapeHtml(item.text || "")}</q>
            ${renderEvidenceJumpButton(item)}
          `).join("")}
        </div>
      ` : ""}
      ${missingEvidence ? `
        <div class="action-risk-evidence">
          <q>未找到相关转写片段</q>
        </div>
      ` : ""}
    </div>
  `;
}

function isReviewOnlyAction(item) {
  const task = String(item?.task || "").trim();
  return Boolean(
    item?.reviewOnly
    || item?.actionKind === "system_review"
    || item?.action_kind === "system_review"
    || item?.evidenceStatus === "system_review"
    || task.startsWith("检查转写结果并补充真实会议纪要")
    || task.startsWith("按转写原文复核待办")
  );
}

function reviewOnlyActionReason(item) {
  const task = String(item?.task || "").trim();
  if (task.startsWith("检查转写结果并补充真实会议纪要")) {
    return "这是占位转写、空语音或缺音频触发的复核入口，不是会议中产生的可督办待办。";
  }
  return "这是模型待办被证据检查拦截后保留的人工复核入口，不会自动复制为督办事项。";
}

function renderEvidenceJumpButton(item) {
  const segmentId = item?.segment_id || "";
  const sourceId = item?.source_id || "";
  const sourceSegmentNo = item?.source_segment_no || item?.segment_no || "";
  if (!segmentId && !sourceSegmentNo) return "";
  return `
    <button type="button" class="evidence-jump jump-transcript"
      data-segment-id="${escapeAttr(segmentId)}"
      data-source-id="${escapeAttr(sourceId)}"
      data-source-segment="${escapeAttr(sourceSegmentNo)}">定位转写</button>
  `;
}

function renderPersonCard(person) {
  const sample = person.sample;
  const speakerIds = Array.isArray(person.speakerIds) && person.speakerIds.length
    ? person.speakerIds
    : [person.id];
  const sampleHint = sample
    ? `${sample.sourceLabel} · ${formatTime(sample.absoluteStartMs)}-${formatTime(sample.absoluteEndMs)}`
    : "暂无可试听样本";
  return `
    <article class="person-card"
      data-speaker="${escapeAttr(person.id)}"
      data-speakers="${escapeAttr(speakerIds.join("|"))}"
      data-original-name="${escapeAttr(person.name)}">
      <div>
        <b>${escapeHtml(person.name)}</b>
        <span>${person.count} 段发言 · ${formatTime(person.durationMs)} · ${person.actionCount} 个待办${speakerIds.length > 1 ? ` · 已归并 ${speakerIds.length} 个标签` : ""}</span>
      </div>
      <div class="speaker-sample">
        <div>
          <b>声音样本</b>
          <span>${escapeHtml(sampleHint)}</span>
        </div>
        ${sample ? `
          <button type="button" class="button secondary speaker-sample-play"
            data-sample-audio="${escapeAttr(sample.audioUrl)}"
            data-sample-start="${escapeAttr(sample.startSec)}"
            data-sample-end="${escapeAttr(sample.endSec)}">
            试听 ${escapeHtml(formatSampleSeconds(sample))}
          </button>
          <audio class="speaker-sample-audio" controls preload="none"></audio>
          <small>${escapeHtml(sample.text)}</small>
        ` : "<small>转写段落还没有对应的可播放音频。</small>"}
      </div>
      <label>正确姓名</label>
      <input class="input person-name" value="${escapeAttr(person.name)}">
      <label>文本别名/音译名</label>
      <input class="input person-aliases" placeholder="多个用逗号分隔，例如 Renxu, 任旭" value="${escapeAttr(person.aliases.join(", "))}">
      <label class="checkbox-row"><input class="person-replace-text" type="checkbox" checked> 同时替换转写、纪要和待办正文</label>
      <button type="button" class="button secondary person-save">统一替换</button>
    </article>
  `;
}

function renderSegmentInsights(items) {
  if (!items.length) return "<p class='hint'>暂无分段洞察。</p>";
  return `
    <div class="segment-insight-list">
      ${items.map((item) => `
        <article class="segment-insight">
          <div class="segment-insight-head">
            <b>${escapeHtml(item.label)}</b>
            <span>${formatTime(item.startMs)} - ${formatTime(item.endMs)}</span>
          </div>
          <div class="segment-insight-grid">
            <div><span>发言人</span><b>${escapeHtml(item.speakers.join("、") || "待识别")}</b>${item.speakerHint ? `<small>${escapeHtml(item.speakerHint)}</small>` : ""}</div>
            <div><span>讨论内容</span><p>${escapeHtml(item.topic || "暂无内容")}</p></div>
            <div><span>相关待办</span><p>${escapeHtml(item.actions.join("；") || "暂无")}</p></div>
            <div><span>负责人</span><b>${escapeHtml(item.owners.join("、") || "待确认")}</b></div>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function renderExports(exports) {
  if (!exports.length) return "<p class='hint'>尚未生成导出文件。点击上方导出按钮后会出现在这里。</p>";
  return exports.map((item) => `
    <div class="export-row">
      <div>
        <b>${escapeHtml(item.file_name || `${item.format}.${item.id}`)}</b>
        <span>${escapeHtml(item.format.toUpperCase())} · ${formatBytes(Number(item.size_bytes || 0))} · ${escapeHtml(formatDate(item.created_at))}</span>
      </div>
      <div class="detail-actions">
        <button type="button" class="button secondary export-download" data-url="${escapeAttr(item.download_url || "")}" data-name="${escapeAttr(item.file_name || "")}">下载</button>
        <button type="button" class="button secondary export-copy" data-url="${escapeAttr(item.download_url || "")}">复制链接</button>
      </div>
    </div>
  `).join("");
}

function renderDeferredPanel(title, detail) {
  return `
    <div class="deferred-panel">
      <span class="loading-spinner small" aria-hidden="true"></span>
      <div>
        <b>${escapeHtml(title)}</b>
        <span>${escapeHtml(detail)}</span>
      </div>
    </div>
  `;
}

function renderUnavailablePanel(title, detail) {
  return `
    <div class="deferred-panel warning-panel">
      <div>
        <b>${escapeHtml(title)}</b>
        <span>${escapeHtml(detail)}</span>
      </div>
    </div>
  `;
}

function renderTranscriptSkeleton(count) {
  const rows = Math.max(3, Math.min(Number(count || 0) || 4, 8));
  return `
    <div class="transcript-skeleton" aria-hidden="true">
      ${Array.from({ length: rows }).map(() => `
        <div class="transcript-skeleton-row">
          <span></span>
          <span></span>
          <span></span>
        </div>
      `).join("")}
    </div>
  `;
}

function renderQualityReport(report, knowledgeReadiness = null) {
  const metrics = report.metrics || {};
  const issues = Array.isArray(report.issues) ? report.issues : [];
  const recommendations = Array.isArray(report.recommendations) ? report.recommendations : [];
  const people = Array.isArray(report.candidatePeople) ? report.candidatePeople : [];
  const unsupportedCount = Number(metrics.unsupported_action_count || 0);
  const weakSpeakerEvidenceCount = Number(metrics.speaker_evidence_weak_count || 0);
  const weakActionOwnerCount = Number(metrics.weak_action_owner_count || 0);
  const actionContradictionCount = Number(metrics.action_contradiction_count || 0);
  const summaryUnsupportedCount = Number(metrics.summary_unsupported_count || 0);
  const summaryContradictionCount = Number(metrics.summary_contradiction_count || 0);
  const summaryConflictCount = Number(metrics.summary_conflict_count || 0);
  const speakerReviewCount = Number(metrics.speaker_review_count || 0);
  const speakerAliasConflictCount = Number(metrics.speaker_alias_conflict_count || 0);
  const longSegmentCount = Number(metrics.long_segment_count || 0);
  const llmSegmentCount = Number(metrics.llm_segment_count || 0);
  const sourceWeakCount = Number(metrics.source_segment_weak_count || 0);
  const placeholderTranscriptCount = Number(metrics.placeholder_transcript_count || 0);
  const systemReviewActionCount = Number(metrics.system_review_action_count || 0);
  const multiSourceMerged = Number(metrics.multi_source_merged_count || 0);
  const multiSourceMajority = Number(metrics.multi_source_majority_count || 0);
  const multiSourceComplemented = Number(metrics.multi_source_complemented_count || 0);
  const multiSourceConflict = Number(metrics.multi_source_conflict_count || 0);
  const ownerRisk =
    Number(metrics.generic_owner_count || 0) +
    unsupportedCount +
    weakActionOwnerCount +
    actionContradictionCount +
    Number(metrics.duplicate_action_count || 0) +
    Number(metrics.top_owner_ratio >= 0.7 ? 1 : 0);
  return `
    <div class="quality-grid">
      <div><span>发言人</span><b>${Number(metrics.speaker_count || 0)}</b></div>
      <div><span>候选人名</span><b>${Number(metrics.candidate_people_count || people.length || 0)}</b></div>
      <div><span>需校对段落</span><b>${Number(metrics.speaker_review_count || 0)}</b></div>
      <div><span>发言人证据风险</span><b>${weakSpeakerEvidenceCount}</b></div>
      <div><span>同名多标签</span><b>${speakerAliasConflictCount}</b></div>
      <div><span>纪要证据率</span><b>${formatPercent(metrics.summary_evidence_coverage)}</b></div>
      <div><span>待办证据率</span><b>${formatPercent(metrics.action_evidence_coverage)}</b></div>
      <div><span>分段覆盖率</span><b>${formatPercent(metrics.source_segment_coverage)}</b></div>
      <div><span>多源合并</span><b>${multiSourceMerged}</b></div>
      <div><span>多数源确认</span><b>${multiSourceMajority}</b></div>
      <div><span>多源互补</span><b>${multiSourceComplemented}</b></div>
      <div><span>多源冲突</span><b>${multiSourceConflict}</b></div>
      <div><span>待办归属风险</span><b>${ownerRisk}</b></div>
      <div><span>系统复核提醒</span><b>${systemReviewActionCount}</b></div>
    </div>
    ${renderKnowledgeReadiness(knowledgeReadiness)}
    ${renderSummaryEvidence(report.summaryEvidence)}
    ${renderMultiSourceConflicts(report.multiSourceConflicts)}
    ${renderSourceCoverage(report.sourceCoverage)}
    ${renderSpeakerAliasConflicts(report.speakerAliasConflicts)}
    ${people.length ? `<p class="quality-people">候选人名：${escapeHtml(people.slice(0, 12).join("、"))}${people.length > 12 ? "..." : ""}</p>` : ""}
    ${renderQualityShortcuts([
      { label: "查看需确认段落", filter: "flag:speaker_review", count: speakerReviewCount },
      { label: "查看证据弱段落", filter: "flag:speaker_evidence_weak", count: weakSpeakerEvidenceCount },
      { label: "查看长段落", filter: "risk:long_segment", count: longSegmentCount },
      { label: "查看覆盖不足分段", filter: "risk:source_coverage", count: sourceWeakCount },
      { label: "查看复核占位", filter: "risk:placeholder_transcript", count: placeholderTranscriptCount },
      { label: "查看多源冲突", filter: "risk:multi_source_conflict", count: multiSourceConflict },
      { label: "查看大模型分段", filter: "flag:semantic_llm", count: llmSegmentCount },
      { label: "查看纪要风险", filter: "summary:evidence_weak", count: summaryUnsupportedCount + summaryContradictionCount + summaryConflictCount },
    ])}
    <div class="quality-issues">
      ${issues.map(renderQualityIssue).join("") || "<span class='quality-ok'>暂无明显质量风险。</span>"}
    </div>
    ${recommendations.length ? `
      <div class="quality-recommendations">
        ${recommendations.slice(0, 4).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
      </div>
    ` : ""}
  `;
}

function renderKnowledgeReadiness(readiness) {
  if (!readiness) return "";
  const blockers = Array.isArray(readiness.blockers) ? readiness.blockers : [];
  const warnings = Array.isArray(readiness.reviewWarnings) ? readiness.reviewWarnings : [];
  const notes = Array.isArray(readiness.notes) ? readiness.notes : [];
  const evidence = readiness.reviewEvidence || {};
  const evidenceItems = knowledgeReviewEvidenceItems(evidence);
  const hasReview = blockers.length || warnings.length || notes.length || evidenceItems.length;
  const status = readiness.status || (readiness.canIndex ? "ready" : "hold");
  return `
    <div class="knowledge-readiness ${escapeAttr(status)}">
      <div class="knowledge-readiness-head">
        <div>
          <b>知识入库复核</b>
          <span>${escapeHtml(knowledgeReadinessStatusLabel(status))}</span>
        </div>
        <small>${escapeHtml(readiness.canIndex === false ? "暂缓自动入库" : "可按风险标记入库")}</small>
      </div>
      ${!hasReview ? "<p class='hint'>当前没有明显入库阻塞或人工复核项。</p>" : ""}
      ${blockers.length || warnings.length ? `
        <div class="knowledge-readiness-tags">
          ${blockers.map((item) => `<span class="blocker">${escapeHtml(knowledgeIssueLabel(item))}</span>`).join("")}
          ${warnings.map((item) => `<span>${escapeHtml(knowledgeIssueLabel(item))}</span>`).join("")}
        </div>
      ` : ""}
      ${notes.length ? `
        <div class="knowledge-readiness-notes">
          ${notes.slice(0, 3).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
        </div>
      ` : ""}
      ${evidenceItems.length ? `
        <div class="knowledge-review-list">
          ${evidenceItems.slice(0, 10).map(renderKnowledgeReviewEvidenceItem).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

function knowledgeReviewEvidenceItems(evidence) {
  const items = [];
  const addItems = (type, list) => {
    (Array.isArray(list) ? list : []).forEach((item) => items.push({ type, item }));
  };
  addItems("multi_source_conflict", evidence.multiSourceConflicts);
  addItems("source_coverage", evidence.sourceCoverageWeakSegments);
  addItems("speaker", evidence.speakerEvidence);
  addItems("speaker_alias", evidence.speakerAliasConflicts);
  addItems("summary", evidence.summaryClaims);
  addItems("action", evidence.actionEvidence);
  return items;
}

function renderKnowledgeReviewEvidenceItem(entry) {
  const item = entry.item || {};
  const type = entry.type || "";
  const { title, detail, className } = knowledgeReviewEvidenceText(type, item);
  return `
    <article class="knowledge-review-item ${escapeAttr(className)}">
      <b>${escapeHtml(title)}</b>
      ${detail ? `<p>${escapeHtml(detail)}</p>` : ""}
      ${renderKnowledgeReviewEvidenceRefs(type, item)}
    </article>
  `;
}

function renderKnowledgeReviewEvidenceRefs(type, item) {
  if (type === "source_coverage") {
    return `
      <div class="summary-evidence-refs">
        <span>${escapeHtml(sourceConflictLabel(item))} · ${escapeHtml(formatTime(item.start_ms || 0))} - ${escapeHtml(formatTime(item.end_ms || 0))} · 转写 ${Number(item.transcript_segment_count || 0)} 段</span>
        ${renderEvidenceJumpButton(item)}
      </div>
    `;
  }
  if (type === "speaker_alias") {
    return `<div class="summary-evidence-refs"><span>${escapeHtml((item.speaker_ids || []).join(" / ") || "多个 speaker_id")}</span></div>`;
  }
  if (type === "summary" && Array.isArray(item.evidence)) {
    return renderSummaryEvidenceRefs(item.evidence);
  }
  if (type === "action") {
    const evidence = Array.isArray(item.evidence) && item.evidence.length
      ? item.evidence
      : item.suggested_owner_evidence;
    return renderSummaryEvidenceRefs(evidence || []);
  }
  return renderSummaryEvidenceRefs([item]);
}

function knowledgeReviewEvidenceText(type, item) {
  if (type === "multi_source_conflict") {
    return {
      title: `多源冲突：${sourceConflictLabel(item)}`,
      detail: `${formatTime(item.start_ms || 0)} ${item.speaker || "发言人"}：${item.text || ""}`,
      className: "conflict",
    };
  }
  if (type === "source_coverage") {
    return {
      title: `音频覆盖不足：${sourceConflictLabel(item)}`,
      detail: item.sample || "该录音分段当前缺少足够转写文本。若有系统复核行，它只是可定位入口，不是有效转写。",
      className: "blocker",
    };
  }
  if (type === "speaker") {
    return {
      title: `发言人待复核：${item.speaker || item.display_name || item.speaker_id || "待识别"}`,
      detail: item.reason || item.text || "该发言人由模型或上下文推断，建议人工确认。",
      className: "warning",
    };
  }
  if (type === "speaker_alias") {
    return {
      title: `同名多标签：${item.display_name || "同名发言人"}`,
      detail: "同一显示名对应多个原始说话人标签，入库前建议合并口径。",
      className: "warning",
    };
  }
  if (type === "summary") {
    return {
      title: `纪要复核：${item.claim || "待核对要点"}`,
      detail: summaryEvidenceStatusLabel(item.status),
      className: summaryEvidenceStatusClass(item.status),
    };
  }
  if (type === "action") {
    return {
      title: `${item.status === "system_review" || item.action_kind === "system_review" ? "系统复核提醒" : "待办复核"}：${item.task || "待办事项"}`,
      detail: `${actionEvidenceStatusLabel(item.status)}${item.owner ? ` · 负责人：${item.owner}` : ""}${item.reason ? ` · ${item.reason}` : ""}`,
      className: item.status === "conflict" || item.status === "contradiction" ? "conflict" : item.status === "system_review" ? "system-review" : "warning",
    };
  }
  return {
    title: "复核项",
    detail: "",
    className: "warning",
  };
}

function knowledgeReadinessStatusLabel(status) {
  return {
    ready: "可入库",
    review_first: "先复核再入库",
    hold: "暂缓入库",
  }[status] || "先复核再入库";
}

function knowledgeIssueLabel(type) {
  return {
    empty_transcript: "转写为空",
    placeholder_transcript: "占位转写",
    generic_owner: "泛化负责人",
    system_review_action: "系统复核提醒",
    unsupported_action_evidence: "待办缺证据",
    action_evidence_contradiction: "待办与原文相反",
    summary_evidence_weak: "纪要证据弱",
    summary_evidence_contradiction: "纪要与原文相反",
    source_segment_coverage_weak: "音频覆盖不足",
    speaker_review: "发言人需确认",
    speaker_evidence_weak: "发言人证据弱",
    speaker_alias_conflict: "同名多标签",
    weak_action_owner_evidence: "负责人证据弱",
    multi_source_conflict: "多源冲突",
    summary_multisource_conflict: "纪要含冲突",
    owner_over_concentrated: "负责人过集中",
    candidate_people_not_speakers: "候选人未成发言人",
    long_segment: "长段落",
    mixed_speaker_markers: "混合发言",
    single_speaker: "单一发言人",
  }[type] || type || "复核项";
}

function renderMultiSourceConflicts(conflicts) {
  const items = Array.isArray(conflicts) ? conflicts : [];
  if (!items.length) return "";
  return `
    <div class="summary-risk-list multi-source-conflict-list">
      ${items.slice(0, 6).map((item) => {
        const nearby = Array.isArray(item.nearby) ? item.nearby : [];
        return `
          <div class="summary-evidence-item conflict">
            <b>多源冲突：${escapeHtml(sourceConflictLabel(item))}</b>
            <p>${escapeHtml(formatTime(item.start_ms || 0))} ${escapeHtml(item.speaker || "发言人")}：${escapeHtml(item.text || "")}</p>
            ${renderEvidenceJumpButton(item)}
            ${nearby.length ? `
              <div class="summary-evidence-refs">
                ${nearby.slice(0, 3).map((nearbyItem) => `
                  <span>
                    对照 ${escapeHtml(sourceConflictLabel(nearbyItem))} · ${escapeHtml(nearbyItem.speaker || "发言人")}：${escapeHtml(nearbyItem.text || "")}
                    ${renderEvidenceJumpButton(nearbyItem)}
                  </span>
                `).join("")}
              </div>
            ` : ""}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function sourceConflictLabel(item) {
  const sourceId = item?.source_id || "primary";
  const sourceSegment = item?.source_segment_no || "";
  const label = sourceDisplayLabel(item);
  return sourceSegment ? `${label} · 分段 ${sourceSegment}` : label || sourceId;
}

function renderSourceCoverage(sourceCoverage) {
  const weak = Array.isArray(sourceCoverage?.weakSegments) ? sourceCoverage.weakSegments : [];
  if (!weak.length) return "";
  return `
    <div class="summary-risk-list">
      ${weak.slice(0, 6).map((item) => `
        <div class="summary-evidence-item unsupported">
          <b>音频分段待核对：分段 ${escapeHtml(item.segment_no || "")}</b>
          <p>${escapeHtml(item.sample || "该音频分段当前缺少足够转写文本。若有系统复核行，它只是可定位入口，不是有效转写。")}</p>
          <div class="summary-evidence-refs">
            <span>${escapeHtml(formatTime(item.start_ms || 0))} - ${escapeHtml(formatTime(item.end_ms || 0))} · 有效转写 ${Number(item.substantive_transcript_segment_count || 0)} 段 / 可定位复核行 ${Number(item.transcript_segment_count || 0)}</span>
            ${renderEvidenceJumpButton(item)}
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderSpeakerAliasConflicts(items) {
  const conflicts = Array.isArray(items) ? items : [];
  if (!conflicts.length) return "";
  return `
    <div class="speaker-alias-conflicts">
      ${conflicts.slice(0, 4).map((item) => `
        <div class="speaker-alias-conflict">
          <b>${escapeHtml(item.display_name || "同名发言人")}</b>
          <span>${escapeHtml((item.speaker_ids || []).join(" / "))}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function renderSummaryEvidence(summaryEvidence) {
  const unsupported = Array.isArray(summaryEvidence?.unsupportedClaims)
    ? summaryEvidence.unsupportedClaims
    : [];
  const supported = Array.isArray(summaryEvidence?.supportedClaims)
    ? summaryEvidence.supportedClaims
    : [];
  if (!unsupported.length && !supported.length) return "";
  return `
    <div class="summary-risk-list">
      ${supported.slice(0, 4).map((item) => `
        <div class="summary-evidence-item ${escapeAttr(summaryEvidenceStatusClass(item.status))}">
          <b>${escapeHtml(summaryEvidenceStatusLabel(item.status))}：${escapeHtml(item.claim || "")}</b>
          ${item.reason ? `<small>${escapeHtml(item.reason)}</small>` : ""}
          ${renderSummaryEvidenceRefs(item.evidence)}
        </div>
      `).join("")}
      ${unsupported.slice(0, 4).map((item) => `
        <div class="summary-evidence-item unsupported">
          <b>纪要待核对：${escapeHtml(item.claim || "")}</b>
        </div>
      `).join("")}
    </div>
  `;
}

function summaryEvidenceStatusClass(status) {
  if (status === "conflict") return "conflict";
  if (status === "contradiction") return "contradiction";
  if (status === "majority") return "majority";
  if (status === "unsupported") return "unsupported";
  return "supported";
}

function summaryEvidenceStatusLabel(status) {
  if (status === "conflict") return "纪要多源冲突待核对";
  if (status === "contradiction") return "纪要与原文相反";
  if (status === "majority") return "纪要多数源确认";
  if (status === "unsupported") return "纪要缺少转写依据";
  return "纪要有依据";
}

function actionEvidenceStatusLabel(status) {
  return {
    supported: "有转写依据",
    majority: "多数源确认",
    system_review: "系统复核提醒",
    conflict: "多源冲突待核对",
    contradiction: "待办与原文相反",
    weak_owner: "负责人证据弱",
    unsupported: "缺转写证据",
  }[status] || "待核对";
}

function renderSummaryEvidenceRefs(evidence) {
  const items = Array.isArray(evidence) ? evidence : [];
  if (!items.length) return "<span>未找到相关转写片段</span>";
  return `
    <div class="summary-evidence-refs">
      ${items.slice(0, 2).map((item) => `
        <span>
          ${escapeHtml(formatTime(item.start_ms))} ${escapeHtml(item.speaker || "发言人")}：${escapeHtml(item.text || "")}
          ${renderEvidenceJumpButton(item)}
        </span>
      `).join("")}
    </div>
  `;
}

function renderQualityShortcuts(items) {
  const activeItems = items.filter((item) => Number(item.count || 0) > 0);
  if (!activeItems.length) return "";
  return `
    <div class="quality-shortcuts">
      ${activeItems.map((item) => `
        <button type="button" class="quality-shortcut" data-transcript-filter="${escapeAttr(item.filter)}">
          <span>${escapeHtml(item.label)}</span>
          <b>${Number(item.count || 0)}</b>
        </button>
      `).join("")}
    </div>
  `;
}

function renderQualityIssue(issue) {
  const severity = issue.severity || "low";
  return `
    <article class="quality-issue ${escapeAttr(severity)}">
      <b>${escapeHtml(issue.title || qualitySeverityLabel(severity))}</b>
      <span>${escapeHtml(issue.detail || "")}</span>
    </article>
  `;
}

function qualityScoreLabel(report) {
  const score = Number(report.score || 0);
  const status = report.status || "review_recommended";
  const label = {
    good: "可用",
    review_recommended: "建议复核",
    needs_review: "需要复核",
  }[status] || "建议复核";
  return `${label} · ${score}`;
}

function qualitySeverityLabel(severity) {
  return {
    high: "高风险",
    medium: "需关注",
    low: "提示",
  }[severity] || "提示";
}

function renderTranscriptRow(segment, speakerEvidenceMap = new Map()) {
  const source = segment.source_segment_no
    ? `${sourceDisplayLabel(segment)} · 分段 ${segment.source_segment_no}`
    : "最终整理";
  const flags = parseFlags(segment.flags);
  const reviewPlaceholder = isPlaceholderTranscriptFlags(flags);
  const needsReview = flags.includes("speaker_review") && !reviewPlaceholder;
  const weakSpeakerEvidence = flags.includes("speaker_evidence_weak") && !reviewPlaceholder;
  const refinedByModel = flags.includes("llm_refined") || flags.includes("semantic_llm");
  const refinedByRule = flags.includes("semantic_rule");
  const scenario = transcriptScenarioLabel(flags);
  const evidence = speakerEvidenceMap.get(segment.id || "") || null;
  const badges = [
    needsReview ? "需确认" : "",
    weakSpeakerEvidence ? "发言人证据弱" : "",
    refinedByModel ? "大模型分段" : "",
    refinedByRule ? "规则分段" : "",
    scenario,
  ].filter(Boolean);
  return `
    <div class="transcript-row"
      data-id="${escapeAttr(segment.id || "")}"
      data-source-id="${escapeAttr(segment.source_id || "")}"
      data-source-segment="${escapeAttr(segment.source_segment_no || "")}"
      data-review-placeholder="${reviewPlaceholder ? "true" : "false"}">
      <div>
        <b>${formatTime(segment.start_ms)}</b>
        <span class="hint">${source}</span>
        ${badges.length ? `<div class="badge-line">${badges.map((badge) => `<span class="mini-badge ${reviewBadgeClass(badge)}">${escapeHtml(badge)}</span>`).join("")}</div>` : ""}
      </div>
      <div>
        <input class="speaker-name" data-speaker="${escapeAttr(segment.speaker_id)}" value="${escapeAttr(segment.display_name || segment.speaker_id)}">
        <input class="speaker-id" type="hidden" value="${escapeAttr(segment.speaker_id)}">
      </div>
      <textarea class="input segment-text" rows="4">${escapeHtml(segment.text || "")}</textarea>
      <input class="start-ms" type="hidden" value="${segment.start_ms || 0}">
      <input class="end-ms" type="hidden" value="${segment.end_ms || 0}">
      ${renderSpeakerEvidenceHint(evidence)}
      <div class="transcript-tools">
        <button type="button" class="button secondary split-segment">拆分段落</button>
        <button type="button" class="button secondary auto-split-speakers">按人名拆分</button>
        <button type="button" class="button secondary new-speaker">设为新发言人</button>
      </div>
    </div>
  `;
}

function buildSpeakerEvidenceMap(report) {
  const items = Array.isArray(report?.speakerEvidence) ? report.speakerEvidence : [];
  return new Map(items.filter((item) => item.segment_id).map((item) => [item.segment_id, item]));
}

function renderSpeakerEvidenceHint(evidence) {
  if (!evidence) return "";
  const context = Array.isArray(evidence.context) ? evidence.context : [];
  const contextLines = context.slice(0, 3).map((item) => `
    <span class="${item.current ? "current" : ""}">
      ${escapeHtml(formatTime(item.start_ms))} ${escapeHtml(item.speaker || "发言人")}：${escapeHtml(item.text || "")}
    </span>
  `).join("");
  return `
    <div class="speaker-evidence ${escapeAttr(evidence.risk || "review")}">
      <b>${escapeHtml(evidence.scenario_label || "推断依据")}</b>
      <span>${escapeHtml(evidence.reason || "该发言人由模型推断，建议人工确认。")}</span>
      ${contextLines ? `<div class="speaker-evidence-context">${contextLines}</div>` : ""}
    </div>
  `;
}

function reviewBadgeClass(badge) {
  if (badge === "需确认" || badge === "发言人证据弱") return "warning";
  return "";
}

function transcriptScenarioLabel(flags) {
  const scenario = flags.find((flag) => String(flag).startsWith("scenario:"));
  const value = scenario ? scenario.slice("scenario:".length) : "";
  return {
    explicit_name: "明确人名",
    context_bridge: "上下文衔接",
    dialogue_logic: "对话逻辑",
    task_ownership: "任务归属",
    native_speaker: "ASR说话人",
    unknown: "推断未知",
  }[value] || "";
}

function bindTranscriptRowEvents(row) {
  row.querySelector(".split-segment")?.addEventListener("click", () => splitTranscriptRow(row));
  row.querySelector(".auto-split-speakers")?.addEventListener("click", () => autoSplitSpeakers(row));
  row.querySelector(".new-speaker")?.addEventListener("click", () => assignNewSpeaker(row));
}

async function saveMeeting() {
  const id = state.selectedMeetingId;
  await api(`/api/web/meetings/${id}`, {
    method: "PATCH",
    body: JSON.stringify({
      title: $("#detailTitle").value,
      summary: $("#detailSummary").value,
      role_notes: $("#detailRoleNotes").value,
    }),
  });
  toast("会议已保存");
  await loadMeetings($("#searchInput").value.trim());
  await selectMeeting(id);
}

async function processSelectedMeeting() {
  await api(`/api/web/meetings/${state.selectedMeetingId}/process`, { method: "POST", body: "{}" });
  toast("已提交处理任务");
  await selectMeeting(state.selectedMeetingId);
}

async function saveTranscript() {
  const renderedRows = $$("#transcriptList .transcript-row");
  const filteredRows = filteredTranscriptSegments(state.currentTranscriptSegments);
  if (state.selectedTranscriptFilter === "all" && filteredRows.length > renderedRows.length) {
    state.transcriptRenderLimit = Math.max(
      state.transcriptRenderLimit,
      filteredRows.length,
    );
    renderMeetingDetail(state.currentMeetingDetail, state.currentTranscriptSegments);
    toast("已展开全部转写段落，请确认后再次保存");
    return;
  }
  const editedRows = renderedRows.map(readTranscriptRow);
  const editedById = new Map(editedRows.filter((segment) => segment.id).map((segment) => [segment.id, segment]));
  const newRows = editedRows.filter((segment) => !segment.id);
  const base = state.currentTranscriptSegments.map((segment) => ({
    id: segment.id || null,
    source_id: segment.source_id || "",
    speaker_id: segment.speaker_id || "SPEAKER_01",
    display_name: segment.display_name || segment.speaker_id || "发言人",
    source_segment_no: segment.source_segment_no || null,
    start_ms: Number(segment.start_ms || 0),
    end_ms: Number(segment.end_ms || 0),
    text: segment.text || "",
    confidence: segment.confidence ?? null,
    flags: parseFlags(segment.flags),
  }));
  const segments = state.selectedTranscriptFilter === "all"
    ? editedRows
    : [
      ...base.map((segment) => editedById.get(segment.id || "") || segment),
      ...newRows,
    ];
  segments.sort((left, right) => (left.start_ms - right.start_ms) || (left.end_ms - right.end_ms));
  await api(`/api/web/meetings/${state.selectedMeetingId}/transcript`, {
    method: "PUT",
    body: JSON.stringify({ version: state.selectedTranscriptVersion, segments }),
  });
  toast("转写已保存");
  await selectMeeting(state.selectedMeetingId);
}

function readTranscriptRow(row) {
  return {
    id: row.dataset.id || null,
    source_id: row.dataset.sourceId || "",
    speaker_id: row.querySelector(".speaker-id").value,
    display_name: row.querySelector(".speaker-name").value,
    source_segment_no: Number(row.dataset.sourceSegment || 0) || null,
    start_ms: Number(row.querySelector(".start-ms").value),
    end_ms: Number(row.querySelector(".end-ms").value),
    text: row.querySelector(".segment-text").value,
    flags: [],
  };
}

function mergeRenderedTranscriptEdits(segments) {
  const renderedRows = $$("#transcriptList .transcript-row");
  if (!renderedRows.length) return segments;
  const editedRows = renderedRows.map(readTranscriptRow);
  const editedById = new Map(editedRows.filter((segment) => segment.id).map((segment) => [segment.id, segment]));
  const editedBySource = new Map(
    editedRows
      .filter((segment) => !segment.id && segment.source_segment_no)
      .map((segment) => [sourceKey(segment.source_id, segment.source_segment_no), segment]),
  );
  const newRows = editedRows.filter((segment) => !segment.id && !segment.source_segment_no);
  const merged = (segments || []).map((segment) => {
    if (segment.id && editedById.has(segment.id)) return editedById.get(segment.id);
    const key = sourceKey(segment.source_id, segment.source_segment_no);
    if (!segment.id && editedBySource.has(key)) return editedBySource.get(key);
    return segment;
  });
  return [...merged, ...newRows].sort((left, right) => (left.start_ms - right.start_ms) || (left.end_ms - right.end_ms));
}

function addActionRow() {
  $("#actionList").insertAdjacentHTML("beforeend", renderActionRow({ owner: "", task: "", due: "", status: "open" }));
  const button = $$("#actionList .action-row-wrap:last-child .remove-action")[0];
  if (button) {
    button.addEventListener("click", () => {
      button.closest(".action-row-wrap")?.remove();
      if (!$$("#actionList .action-row-wrap").length) addActionRow();
    });
  }
}

async function saveActions() {
  const items = $$("#actionList .action-row-wrap").map((row) => ({
    owner: row.querySelector(".action-owner").value,
    task: row.querySelector(".action-task").value,
    due: row.querySelector(".action-due").value,
    status: row.querySelector(".action-status").value,
  })).filter((item) => item.task.trim());
  await api(`/api/web/meetings/${state.selectedMeetingId}/actions`, {
    method: "PUT",
    body: JSON.stringify({ items }),
  });
  toast("待办已保存");
  await selectMeeting(state.selectedMeetingId);
}

function applySuggestedActionOwner(button) {
  const owner = button?.dataset?.owner || "";
  const row = button?.closest(".action-row-wrap");
  const input = row?.querySelector(".action-owner");
  if (!owner || !input) return;
  input.value = owner;
  toast("已填入建议负责人，保存待办后生效");
}

function applyAllSuggestedActionOwners() {
  const buttons = $$(".apply-suggested-owner");
  let changed = 0;
  buttons.forEach((button) => {
    const owner = button?.dataset?.owner || "";
    const row = button?.closest(".action-row-wrap");
    const input = row?.querySelector(".action-owner");
    if (!owner || !input || input.value.trim() === owner) return;
    input.value = owner;
    changed += 1;
  });
  toast(changed ? `已填入 ${changed} 个建议负责人，保存待办后生效` : "暂无可应用的建议负责人");
}

function jumpToTranscriptEvidence(button) {
  const segmentId = button?.dataset?.segmentId || "";
  const sourceId = button?.dataset?.sourceId || "";
  const sourceSegment = button?.dataset?.sourceSegment || "";
  let filterChanged = false;
  if (sourceSegment) {
    const nextFilter = sourceId
      ? `segment:${sourceKey(sourceId, sourceSegment)}`
      : `segment:${sourceSegment}`;
    filterChanged = state.selectedTranscriptFilter !== nextFilter;
    state.selectedTranscriptFilter = nextFilter;
    if (filterChanged && state.currentMeetingDetail && state.currentTranscriptSegments) {
      renderMeetingDetail(state.currentMeetingDetail, state.currentTranscriptSegments);
      requestAnimationFrame(() => jumpToTranscriptEvidence(button));
      return;
    }
  }
  const target = segmentId
    ? $(`#transcriptList .transcript-row[data-id="${cssEscape(segmentId)}"]`)
    : sourceId
      ? $(`#transcriptList .transcript-row[data-source-id="${cssEscape(sourceId)}"][data-source-segment="${cssEscape(sourceSegment)}"]`)
      : $(`#transcriptList .transcript-row[data-source-segment="${cssEscape(sourceSegment)}"]`);
  if (!target) {
    const matchingIndex = findTranscriptEvidenceIndex(segmentId, sourceId, sourceSegment);
    if (
      matchingIndex >= state.transcriptRenderLimit
      && state.currentMeetingDetail
      && state.currentTranscriptSegments
    ) {
      state.transcriptRenderLimit = matchingIndex + TRANSCRIPT_LOAD_MORE_ROWS;
      renderMeetingDetail(state.currentMeetingDetail, state.currentTranscriptSegments);
      requestAnimationFrame(() => jumpToTranscriptEvidence(button));
      return;
    }
    $("#transcriptWorkspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
    toast(sourceSegment ? "该音频分段暂缺可定位转写，请回听录音或重新转写" : "未找到对应转写段落");
    return;
  }
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("highlight");
  window.setTimeout(() => target.classList.remove("highlight"), 1800);
}

function findTranscriptEvidenceIndex(segmentId, sourceId, sourceSegment) {
  const rows = filteredTranscriptSegments(state.currentTranscriptSegments || []);
  return rows.findIndex((segment) => {
    if (segmentId && String(segment.id || "") === String(segmentId)) return true;
    if (sourceSegment && sourceId) {
      return String(segment.source_id || "") === String(sourceId)
        && String(segment.source_segment_no || "") === String(sourceSegment);
    }
    if (sourceSegment) return String(segment.source_segment_no || "") === String(sourceSegment);
    return false;
  });
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(String(value || ""));
  }
  return String(value || "").replace(/["\\]/g, "\\$&");
}

async function copyActionsToClipboard() {
  const items = $$("#actionList .action-row-wrap").map((row) => ({
    owner: row.querySelector(".action-owner").value.trim() || "待确认",
    task: row.querySelector(".action-task").value.trim(),
    due: row.querySelector(".action-due").value.trim(),
    status: row.querySelector(".action-status").value,
    reviewOnly: row.dataset.reviewOnly === "true",
  })).filter((item) => item.task && !item.reviewOnly);
  if (!items.length) {
    toast("暂无可复制的督办待办，系统复核提醒已跳过");
    return;
  }
  const text = buildActionCopyText(items);
  const copied = await copyText(text);
  if (copied) {
    toast("待办已复制，可直接粘贴到 IM");
  } else {
    window.prompt("浏览器未开放剪贴板权限，请手动复制待办：", text);
  }
}

function buildActionCopyText(items) {
  return items.map((item, index) => {
    const due = item.due ? `｜截止：${item.due}` : "";
    return `${index + 1}. ${item.task}｜负责人：${item.owner}${due}｜状态：${actionStatusLabel(item.status)}`;
  }).join("\n");
}

async function copyTranscriptToClipboard() {
  const renderedRows = $$("#transcriptList .transcript-row");
  const renderedById = new Map(renderedRows.map((row) => [row.dataset.id || "", row]));
  const filteredRows = filteredTranscriptSegments(state.currentTranscriptSegments || []);
  const text = filteredRows.map((segment) => {
    const row = renderedById.get(segment.id || "");
    if (row) {
      const time = row.querySelector("b")?.textContent?.trim() || "";
      const speaker = row.querySelector(".speaker-name")?.value?.trim() || "发言人";
      const body = row.querySelector(".segment-text")?.value?.trim() || "";
      return `[${time}] ${speaker}：${body}`;
    }
    return `[${formatTime(segment.start_ms)}] ${segment.display_name || segment.speaker_id || "发言人"}：${segment.text || ""}`;
  }).filter(Boolean).join("\n");
  if (!text) {
    toast("暂无可复制的转写");
    return;
  }
  const copied = await copyText(text);
  if (copied) toast("转写已复制");
  else window.prompt("浏览器未开放剪贴板权限，请手动复制转写：", text);
}

function toggleTranscriptExpanded() {
  const list = $("#transcriptList");
  const button = $("#expandTranscript");
  if (!list || !button) return;
  const expanded = list.classList.toggle("expanded");
  button.textContent = expanded ? "收起阅读" : "展开阅读";
}

function splitTranscriptRow(row) {
  if (!row) return;
  const textarea = row.querySelector(".segment-text");
  const text = textarea?.value || "";
  if (!text.trim()) {
    toast("当前段落没有可拆分文本");
    return;
  }
  const cursor = textarea.selectionStart || Math.floor(text.length / 2);
  const splitAt = bestSplitPosition(text, cursor);
  if (splitAt <= 0 || splitAt >= text.length) {
    toast("请把光标放到要拆分的位置");
    return;
  }
  const first = text.slice(0, splitAt).trim();
  const second = text.slice(splitAt).trim();
  textarea.value = first;
  const startMs = Number(row.querySelector(".start-ms").value || 0);
  const endMs = Number(row.querySelector(".end-ms").value || startMs);
  const midMs = Math.max(startMs + 1, Math.min(endMs - 1, Math.round((startMs + endMs) / 2)));
  row.querySelector(".end-ms").value = midMs;
  const clone = row.cloneNode(true);
  clone.dataset.id = "";
  clone.querySelector(".segment-text").value = second;
  clone.querySelector(".start-ms").value = midMs;
  clone.querySelector(".end-ms").value = endMs;
  clone.querySelector("b").textContent = formatTime(midMs);
  row.insertAdjacentElement("afterend", clone);
  bindTranscriptRowEvents(clone);
  toast("已拆分段落，记得保存转写修改");
}

function autoSplitSpeakers(row) {
  if (!row) return;
  const current = readTranscriptRow(row);
  const blocks = parseSpeakerBlocks(current.text);
  if (blocks.length < 2) {
    toast("没有识别到可拆分的人名标记，例如“张三：”");
    return;
  }
  const speakerIds = new Map();
  const duration = Math.max(blocks.length, current.end_ms - current.start_ms);
  const segments = blocks.map((block, index) => {
    const name = block.speaker;
    if (!speakerIds.has(name)) {
      speakerIds.set(
        name,
        name === current.display_name ? current.speaker_id : `MANUAL_${stableToken(name)}_${Date.now().toString(36)}`,
      );
    }
    const start = current.start_ms + Math.round((duration * index) / blocks.length);
    const end = index === blocks.length - 1
      ? current.end_ms
      : current.start_ms + Math.round((duration * (index + 1)) / blocks.length);
    return {
      id: null,
      source_id: current.source_id,
      speaker_id: speakerIds.get(name),
      display_name: name,
      source_segment_no: current.source_segment_no,
      start_ms: start,
      end_ms: Math.max(start + 1, end),
      text: block.text,
      flags: [],
    };
  });
  const wrapper = document.createElement("template");
  wrapper.innerHTML = segments.map((segment) => renderTranscriptRow(segment)).join("");
  const rows = Array.from(wrapper.content.querySelectorAll(".transcript-row"));
  rows.forEach(bindTranscriptRowEvents);
  row.replaceWith(wrapper.content);
  toast(`已按人名拆成 ${segments.length} 段，检查后保存转写修改`);
}

function parseSpeakerBlocks(text) {
  const value = String(text || "").trim();
  const pattern = /(^|[\n\r。！？!?；;])\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,12})\s*[:：]/g;
  const matches = [];
  let match;
  while ((match = pattern.exec(value))) {
    const boundaryLength = match[1] ? match[1].length : 0;
    matches.push({
      markerStart: match.index + boundaryLength,
      contentStart: pattern.lastIndex,
      speaker: match[2].trim(),
    });
  }
  if (matches.length < 2) return [];
  const prefix = value.slice(0, matches[0].markerStart).trim();
  return matches.map((item, index) => {
    const next = matches[index + 1];
    const rawText = value.slice(item.contentStart, next ? next.markerStart : value.length).trim();
    return {
      speaker: item.speaker,
      text: index === 0 && prefix ? `${prefix}\n${rawText}` : rawText,
    };
  }).filter((item) => item.text);
}

function stableToken(value) {
  let hash = 0;
  for (const char of String(value || "")) {
    hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function assignNewSpeaker(row) {
  if (!row) return;
  const existingNames = new Set($$("#transcriptList .speaker-name").map((input) => input.value.trim()).filter(Boolean));
  let index = existingNames.size + 1;
  let name = `发言人 ${index}`;
  while (existingNames.has(name)) {
    index += 1;
    name = `发言人 ${index}`;
  }
  const speakerId = `MANUAL_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
  row.querySelector(".speaker-id").value = speakerId;
  const input = row.querySelector(".speaker-name");
  input.dataset.speaker = speakerId;
  input.value = name;
  input.focus();
  input.select();
  toast("已设为新发言人，可直接输入正确姓名后保存");
}

function bestSplitPosition(text, cursor) {
  const marks = ["。", "！", "？", ".", "!", "?", "\n", "；", ";", "，", ","];
  for (const mark of marks) {
    const before = text.lastIndexOf(mark, cursor);
    if (before > 0 && cursor - before < 80) return before + mark.length;
    const after = text.indexOf(mark, cursor);
    if (after > 0 && after - cursor < 80) return after + mark.length;
  }
  return cursor;
}

async function savePersonAlias(card) {
  if (!card) return;
  const speakerId = card.dataset.speaker || "";
  const speakerIds = (card.dataset.speakers || speakerId)
    .split("|")
    .map((item) => item.trim())
    .filter(Boolean);
  const displayName = card.querySelector(".person-name").value.trim();
  const aliases = card.querySelector(".person-aliases").value
    .split(/[,，、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  const originalName = (card.dataset.originalName || "").trim();
  const ownerName = (speakerId.startsWith("owner:") ? speakerId.slice("owner:".length) : "").trim();
  [originalName, ownerName].forEach((name) => {
    if (name && name !== displayName && !aliases.includes(name)) aliases.push(name);
  });
  const replaceText = card.querySelector(".person-replace-text").checked;
  if (!speakerId || !displayName) {
    toast("请填写正确姓名");
    return;
  }
  for (const id of speakerIds) {
    await api(`/api/web/meetings/${state.selectedMeetingId}/speakers/rename`, {
      method: "POST",
      body: JSON.stringify({
        speaker_id: id,
        display_name: displayName,
        aliases,
        replace_text: replaceText,
      }),
    });
  }
  toast("人物名称和正文已统一处理");
  await selectMeeting(state.selectedMeetingId);
}

async function copyExportLink(url) {
  if (!url) {
    toast("暂无导出链接");
    return;
  }
  const absolute = new URL(url, location.origin).toString();
  const copied = await copyText(absolute);
  if (copied) toast("导出链接已复制");
  else window.prompt("浏览器未开放剪贴板权限，请手动复制链接：", absolute);
}

async function downloadExport(url, fileName) {
  if (!url) {
    toast("暂无导出文件");
    return;
  }
  try {
    const response = await fetch(url, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = fileName || "solorecord-export";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    toast("导出文件已开始下载");
  } catch (error) {
    toast(`下载失败：${friendlyError(error)}`);
  }
}

async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (error) {
    // Fall through to the legacy copy path.
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const ok = document.execCommand("copy");
  textarea.remove();
  return ok;
}

async function renameSpeaker(speakerId, displayName) {
  if (!displayName.trim()) return;
  await api(`/api/web/meetings/${state.selectedMeetingId}/speakers/rename`, {
    method: "POST",
    body: JSON.stringify({ speaker_id: speakerId, display_name: displayName, aliases: [], replace_text: false }),
  });
  $$(".speaker-name").forEach((input) => {
    if (input.dataset.speaker === speakerId) input.value = displayName;
  });
  toast("同一角色名称已全部替换");
}

async function exportMeeting(format) {
  const data = await api(`/api/web/meetings/${state.selectedMeetingId}/exports?export_format=${format}`, {
    method: "POST",
    body: "{}",
  });
  toast(`已生成 ${format}：${data.file_name}`);
  await selectMeeting(state.selectedMeetingId);
}

async function loadAuthorizedAudio(button) {
  const url = button.dataset.audioLoad || "";
  if (!url) return;
  try {
    button.disabled = true;
    button.textContent = "加载中";
    const response = await fetch(url, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = URL.createObjectURL(blob);
    button.replaceWith(audio);
  } catch (error) {
    button.replaceWith(Object.assign(document.createElement("span"), {
      className: "hint",
      textContent: "音频加载失败，请确认权限或稍后重试",
    }));
  }
}

async function playSpeakerSample(button) {
  const url = button.dataset.sampleAudio || "";
  const start = Number(button.dataset.sampleStart || 0);
  const end = Number(button.dataset.sampleEnd || 0);
  const sampleBox = button.closest(".speaker-sample");
  const audio = sampleBox?.querySelector(".speaker-sample-audio");
  if (!url || !audio) return;
  try {
    button.disabled = true;
    button.textContent = "加载中";
    if (audio.dataset.objectUrl) {
      URL.revokeObjectURL(audio.dataset.objectUrl);
      audio.dataset.objectUrl = "";
    }
    const response = await fetch(url, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const objectUrl = URL.createObjectURL(await response.blob());
    audio.dataset.objectUrl = objectUrl;
    audio.dataset.sampleEnd = String(end);
    audio.src = objectUrl;
    audio.classList.add("ready");
    await seekAndPlayAudio(audio, start, end);
    button.textContent = "重新试听";
  } catch (error) {
    button.textContent = "试听失败";
    toast("声音样本加载失败，请确认权限或稍后重试");
  } finally {
    button.disabled = false;
  }
}

function seekAndPlayAudio(audio, start, end) {
  const safeStart = Math.max(0, Number(start || 0));
  const safeEnd = Math.max(safeStart + 1, Number(end || safeStart + 10));
  audio.ontimeupdate = () => {
    if (audio.currentTime >= safeEnd) {
      audio.pause();
      audio.currentTime = safeStart;
    }
  };
  return new Promise((resolve) => {
    const play = () => {
      try {
        audio.currentTime = safeStart;
      } catch (error) {
        // Some mobile browsers reject seeking before metadata is complete.
      }
      audio.play().catch(() => {});
      resolve();
    };
    if (audio.readyState >= 1) {
      play();
      return;
    }
    audio.addEventListener("loadedmetadata", play, { once: true });
    audio.load();
  });
}

async function createAndUpload() {
  const file = $("#audioFile").files[0];
  if (!file) {
    toast("请选择音频文件");
    setUploadStatus("请选择要补传的音频文件。支持 m4a、mp3、wav、webm 等常见音频，实际识别取决于服务器 ASR 能力。", "warning");
    return;
  }
  if (!requireLoginForAction("请先登录后再上传音频")) {
    setUploadStatus("请先登录后再上传音频，登录后文件仍可继续选择并重试。", "warning");
    return;
  }
  const button = $("#createUploadButton");
  let meetingId = "";
  try {
    button.disabled = true;
    button.textContent = "正在创建会议...";
    setUploadStatus(`正在创建会议：${file.name}（${formatBytes(file.size)}）`, "running");
    toast("正在创建会议");
    const joinCode = $("#uploadJoinCode")?.value?.trim() || "";
    const sourceLabel = $("#uploadSourceLabel")?.value || "";
    const title = $("#newMeetingTitle").value || file.name;
    const meeting = joinCode
      ? await api("/api/web/meetings/join", {
          method: "POST",
          body: JSON.stringify({
            title,
            join_code: joinCode,
            source_label: sourceLabel,
            device_name: navigator.platform || "",
          }),
        })
      : await api("/api/web/meetings", {
          method: "POST",
          body: JSON.stringify({
            title,
            recording_mode: "single",
            max_sources: 1,
            source_label: sourceLabel,
          }),
        });
    meetingId = meeting.meeting.id;
    const sourceId = meeting.joinedSource?.source_id || meeting.recordingSources?.[0]?.source_id || "primary";
    const form = new FormData();
    form.append("segment_no", "1");
    form.append("source_id", sourceId);
    form.append("source_label", sourceLabel);
    form.append("source_segment_no", "1");
    form.append("start_ms", "0");
    form.append("end_ms", "180000");
    form.append("duration_ms", "180000");
    form.append("file", file);
    button.textContent = "正在上传音频...";
    const upload = await uploadWithProgress(
      `/api/mobile/meetings/${meetingId}/segments`,
      form,
      (percent) => {
        button.textContent = `正在上传 ${percent}%`;
        setUploadStatus(`正在上传音频 ${percent}%，上传完成后服务器会立即保存原始文件并启动阶段转写。`, "running");
      },
      () => {
        button.textContent = "服务器正在识别...";
        setUploadStatus("音频已上传到服务器，正在等待服务器保存并调用 ASR。大文件或 m4a 转写可能需要更久。", "running");
      },
    );
    setUploadStatus("音频已到服务器，正在等待 ASR 返回阶段转写。这个步骤可能比上传更久，请不要重复点击。", "running");
    if (upload.partial?.status === "failed") {
      setUploadStatus(`音频已保存，阶段转写失败：${upload.partial.error || "请稍后重试转写"}`, "warning");
      toast(`音频已保存，阶段转写失败：${upload.partial.error || "请稍后重试转写"}`);
    } else {
      setUploadStatus("阶段转写已返回，正在提交整场会议整理。", "running");
      toast("音频已上传，正在提交整理");
    }
    button.textContent = "正在提交整理...";
    await api(`/api/mobile/meetings/${meetingId}/finish`, { method: "POST", body: "{}" });
    setUploadStatus("已提交整理。会议会出现在记录页，稍后刷新可查看纪要、待办和转写。", "done");
    toast("已上传并提交处理");
    setView("meetings");
    await loadMeetings();
    await selectMeeting(meetingId);
  } catch (error) {
    if (isAuthError(error)) {
      setUploadStatus("登录状态已过期，请重新登录后再次上传。", "warning");
      promptLogin("登录状态已过期，请重新登录后再次上传");
      return;
    }
    const message = friendlyError(error);
    setUploadStatus(
      meetingId
        ? `上传流程中断：${message}。如果音频已经到服务器，记录页可能仍能看到该会议；也可以稍后重新补传。`
        : `创建或上传失败：${message}`,
      "error",
    );
    toast(`上传失败：${friendlyError(error)}`);
  } finally {
    button.disabled = false;
    button.textContent = "创建会议并上传";
  }
}

async function loadRecorderConfig() {
  try {
    const data = await api("/api/mobile/config");
    state.recorder.segmentMs = Math.max(1, Number(data.segmentMinutes || 5)) * 60 * 1000;
  } catch (error) {
    state.recorder.segmentMs = 5 * 60 * 1000;
  }
  renderRecorderSegments();
  await loadJoinableMeetings();
}

async function startWebRecording() {
  if (!requireLoginForAction("请先登录后再开始录音")) {
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    toast(recordingSupportMessage());
    return;
  }
  await loadRecorderConfig();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    toast(`无法打开麦克风：${friendlyError(error)}`);
    return;
  }
  const title = $("#recordMeetingTitle").value.trim() || `会议录音 ${new Date().toLocaleString()}`;
  const joinCode = $("#recordJoinCode")?.value?.trim() || "";
  const sourceLabel = $("#recordSourceLabel")?.value?.trim() || state.user?.display_name || "";
  const meeting = joinCode
    ? await api("/api/web/meetings/join", {
        method: "POST",
        body: JSON.stringify({
          title,
          join_code: joinCode,
          source_label: sourceLabel,
          device_name: navigator.platform || "",
        }),
      })
    : await api("/api/web/meetings", {
        method: "POST",
        body: JSON.stringify({
          title,
          started_at: new Date().toISOString(),
          source_label: sourceLabel,
        }),
      });
  const joinedSource = meeting.joinedSource || meeting.recordingSources?.[0] || {};
  const mimeType = pickRecorderMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  Object.assign(state.recorder, {
    mediaRecorder: recorder,
    stream,
    meetingId: meeting.meeting.id,
    sourceId: joinedSource.source_id || "primary",
    sourceLabel,
    startedAt: Date.now(),
    segmentStartedAt: Date.now(),
    segmentNo: 0,
    chunks: [],
    uploads: [],
    mimeType: recorder.mimeType || mimeType || "audio/webm",
    pendingBlobs: [],
    continueAfterStop: false,
  });
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) state.recorder.chunks.push(event.data);
  });
  recorder.addEventListener("stop", () => {
    const shouldContinue = state.recorder.continueAfterStop;
    state.recorder.continueAfterStop = false;
    void finalizeRecorderSegment(shouldContinue);
  });
  recorder.start();
  state.recorder.timer = setInterval(updateRecordTimer, 1000);
  $("#startRecordButton").disabled = true;
  $("#stopRecordButton").disabled = false;
  $("#recordStatus").textContent = "录音中";
  $("#recordDot").classList.add("active");
  toast("已开始录音");
}

async function stopWebRecording() {
  const recorder = state.recorder.mediaRecorder;
  if (!recorder) return;
  $("#stopRecordButton").disabled = true;
  $("#recordStatus").textContent = "正在保存最后分段";
  if (recorder.state === "recording") {
    state.recorder.continueAfterStop = false;
    recorder.stop();
  }
}

async function rotateRecorderSegment() {
  const recorder = state.recorder.mediaRecorder;
  if (!recorder || recorder.state !== "recording") return;
  state.recorder.continueAfterStop = true;
  recorder.stop();
}

async function finalizeRecorderSegment(continueRecording) {
  const recorderState = state.recorder;
  const blob = new Blob(recorderState.chunks, { type: recorderState.mimeType || "audio/webm" });
  const startedAt = recorderState.segmentStartedAt;
  const now = Date.now();
  recorderState.chunks = [];
  if (blob.size > 0 && recorderState.meetingId) {
    recorderState.segmentNo += 1;
    const segmentNo = recorderState.segmentNo;
    const startMs = Math.max(0, startedAt - recorderState.startedAt);
    const endMs = Math.max(startMs, now - recorderState.startedAt);
    recorderState.uploads.push({ segmentNo, status: "上传中", size: blob.size });
    renderRecorderSegments();
    await uploadRecorderSegment(blob, segmentNo, startMs, endMs);
  }
  if (continueRecording && recorderState.stream) {
    const mimeType = pickRecorderMimeType();
    const nextRecorder = new MediaRecorder(recorderState.stream, mimeType ? { mimeType } : undefined);
    recorderState.chunks = [];
    recorderState.mediaRecorder = nextRecorder;
    recorderState.segmentStartedAt = Date.now();
    recorderState.mimeType = nextRecorder.mimeType || mimeType || "audio/webm";
    nextRecorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size > 0) recorderState.chunks.push(event.data);
    });
    nextRecorder.addEventListener("stop", () => {
      const shouldContinue = recorderState.continueAfterStop;
      recorderState.continueAfterStop = false;
      void finalizeRecorderSegment(shouldContinue);
    });
    nextRecorder.start();
    return;
  }
  await finishWebRecording();
}

async function uploadRecorderSegment(blob, segmentNo, startMs, endMs) {
  const extension = recorderExtension(state.recorder.mimeType);
  const form = new FormData();
  form.append("segment_no", String(segmentNo));
  form.append("source_id", state.recorder.sourceId || "primary");
  form.append("source_label", state.recorder.sourceLabel || "");
  form.append("source_segment_no", String(segmentNo));
  form.append("start_ms", String(startMs));
  form.append("end_ms", String(endMs));
  form.append("duration_ms", String(endMs - startMs));
  form.append("file", blob, `web_part_${String(segmentNo).padStart(4, "0")}.${extension}`);
  try {
    await api(`/api/mobile/meetings/${state.recorder.meetingId}/segments`, { method: "POST", body: form, headers: {} });
    updateRecorderUpload(segmentNo, "已上传");
    state.recorder.pendingBlobs = state.recorder.pendingBlobs.filter((item) => item.segmentNo !== segmentNo);
  } catch (error) {
    updateRecorderUpload(segmentNo, "待重试");
    state.recorder.pendingBlobs.push({ blob, segmentNo, startMs, endMs });
    toast("分段上传失败，录音仍在当前页面缓存，可点击重试上传");
  }
}

async function finishWebRecording() {
  if (state.recorder.timer) clearInterval(state.recorder.timer);
  if (state.recorder.stream) {
    state.recorder.stream.getTracks().forEach((track) => track.stop());
  }
  const meetingId = state.recorder.meetingId;
  const pending = state.recorder.uploads.filter((item) => item.status !== "已上传");
  if (meetingId && !pending.length) {
    await api(`/api/mobile/meetings/${meetingId}/finish`, { method: "POST", body: "{}" });
    toast("录音已结束，已提交完整整理");
    Object.assign(state.recorder, {
      mediaRecorder: null,
      stream: null,
      meetingId: "",
      sourceId: "primary",
      sourceLabel: "",
      startedAt: 0,
      segmentStartedAt: 0,
      chunks: [],
      uploads: [],
      pendingBlobs: [],
      timer: null,
      continueAfterStop: false,
    });
    $("#startRecordButton").disabled = false;
    $("#stopRecordButton").disabled = true;
    $("#recordStatus").textContent = "未开始";
    $("#recordDot").classList.remove("active");
    updateRecordTimer();
    setView("meetings");
    await loadMeetings();
    await selectMeeting(meetingId);
    return;
  } else if (pending.length) {
    renderRecorderSegments();
    toast("仍有分段未上传，请保持页面打开并点击重试上传");
    $("#startRecordButton").disabled = true;
    $("#stopRecordButton").disabled = true;
    $("#recordStatus").textContent = "有分段待上传";
    $("#recordDot").classList.remove("active");
    updateRecordTimer();
    return;
  }
}

async function retryPendingRecorderUploads() {
  if (!state.recorder.meetingId || !state.recorder.pendingBlobs.length) {
    toast("暂无待重试分段");
    return;
  }
  const pending = [...state.recorder.pendingBlobs];
  state.recorder.pendingBlobs = [];
  for (const item of pending) {
    updateRecorderUpload(item.segmentNo, "上传中");
    await uploadRecorderSegment(item.blob, item.segmentNo, item.startMs, item.endMs);
  }
  const stillPending = state.recorder.uploads.filter((item) => item.status !== "已上传");
  if (!stillPending.length) {
    await finishWebRecording();
  } else {
    renderRecorderSegments();
  }
}

function updateRecorderUpload(segmentNo, status) {
  const item = state.recorder.uploads.find((entry) => entry.segmentNo === segmentNo);
  if (item) item.status = status;
  renderRecorderSegments();
}

function renderRecorderSegments() {
  const box = $("#recordSegmentList");
  if (!box) return;
  if (!state.recorder.uploads.length) {
    box.innerHTML = `<p class="hint">暂无录音分段</p>`;
    return;
  }
  box.innerHTML = state.recorder.uploads.map((item) => `
    <div class="audio-segment">
      <div><b>分段 ${item.segmentNo}</b><span>${formatBytes(item.size || 0)}</span></div>
      <span class="status-pill">${escapeHtml(item.status)}</span>
    </div>
  `).join("") + (state.recorder.pendingBlobs.length ? `
    <button id="retryRecorderUploads" class="button secondary">重试上传待处理分段</button>
  ` : "");
  const retry = $("#retryRecorderUploads");
  if (retry) retry.addEventListener("click", () => retryPendingRecorderUploads().catch(() => toast("重试上传失败")));
}

function setUploadStatus(message, level = "info") {
  const box = $("#uploadStatus");
  if (!box) return;
  box.className = `upload-status ${level}`;
  box.textContent = message || "";
}

function uploadWithProgress(path, form, onProgress, onUploaded) {
  return new Promise((resolve, reject) => {
    if (!state.token) {
      reject(httpError(401, JSON.stringify({ detail: "Missing access token" })));
      return;
    }
    const request = new XMLHttpRequest();
    request.open("POST", path);
    if (state.token) request.setRequestHeader("Authorization", `Bearer ${state.token}`);
    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) {
        onProgress?.(0);
        return;
      }
      const percent = Math.max(1, Math.min(99, Math.round((event.loaded / event.total) * 100)));
      onProgress?.(percent);
    });
    request.upload.addEventListener("load", () => {
      onUploaded?.();
    });
    request.addEventListener("load", () => {
      if (request.status < 200 || request.status >= 300) {
        reject(httpError(request.status, request.responseText));
        return;
      }
      try {
        resolve(JSON.parse(request.responseText || "{}"));
      } catch (error) {
        reject(new Error("服务器返回内容无法解析"));
      }
    });
    request.addEventListener("error", () => reject(new Error("网络连接失败")));
    request.addEventListener("timeout", () => reject(new Error("上传或识别等待超时")));
    request.timeout = 90 * 60 * 1000;
    onProgress?.(1);
    request.send(form);
  });
}

function updateRecordTimer() {
  const elapsed = state.recorder.startedAt ? Date.now() - state.recorder.startedAt : 0;
  $("#recordTimer").textContent = formatTime(elapsed);
  if (
    state.recorder.mediaRecorder
    && state.recorder.mediaRecorder.state === "recording"
    && elapsed > 0
    && Date.now() - state.recorder.segmentStartedAt >= state.recorder.segmentMs
  ) {
    void rotateRecorderSegment();
  }
}

function pickRecorderMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/aac"];
  return candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) || "";
}

function recorderExtension(mimeType) {
  if (String(mimeType).includes("mp4")) return "m4a";
  if (String(mimeType).includes("aac")) return "aac";
  if (String(mimeType).includes("ogg")) return "ogg";
  return "webm";
}

function friendlyError(error) {
  const text = String(error?.message || error || "未知错误");
  if (isAuthError(error)) return "请先登录后再继续";
  if (text.includes("NotAllowedError")) return "麦克风权限被拒绝，请允许 SoloRecord 使用麦克风";
  if (text.includes("NotFoundError")) return "没有找到可用麦克风";
  if (text.includes("NotReadableError")) return "麦克风被其他程序占用";
  if (text.includes("ASR HTTP request failed")) return "音频已到服务器，但识别服务暂时失败";
  return text.length > 160 ? `${text.slice(0, 160)}...` : text;
}

function recordingSupportMessage() {
  if (!window.isSecureContext && location.protocol !== "https:" && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    return "当前网页是 HTTP 内网地址，浏览器会禁用麦克风录音。请使用 Windows 客户端，或让运维配置 HTTPS。";
  }
  return "当前客户端不支持浏览器录音，请使用文件补传、Windows 客户端或 Android App";
}

function renderRecordCapabilityHint() {
  const hint = $("#recordCapabilityHint");
  if (!hint) return;
  const startButton = $("#startRecordButton");
  const unsupported = !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined";
  const insecureBrowser = !window.isSecureContext && !IS_DESKTOP_CLIENT && !["localhost", "127.0.0.1"].includes(location.hostname);
  if (unsupported || insecureBrowser) {
    hint.textContent = recordingSupportMessage();
    hint.classList.add("warning-text");
    if (startButton) {
      startButton.disabled = true;
      startButton.textContent = "需客户端或 HTTPS";
    }
    return;
  }
  if (startButton && !state.recorder.mediaRecorder) {
    startButton.disabled = false;
    startButton.textContent = "开始录音";
  }
  hint.textContent = IS_DESKTOP_CLIENT
    ? "Windows 客户端支持麦克风录音；首次使用时请允许系统麦克风权限。"
    : "当前浏览器支持录音；首次使用时请允许麦克风权限。";
  hint.classList.remove("warning-text");
}

async function loadRelease() {
  try {
    const platform = state.selectedDownloadPlatform || "android";
    const data = await api(`/api/web/releases/latest?platform=${encodeURIComponent(platform)}`);
    const box = $("#releaseBox");
    if (!data.release) {
      box.innerHTML = `<p>尚未发布 ${PLATFORM_LABELS[platform]}。管理员可在管理页上传。</p>`;
      return;
    }
    const rel = data.release;
    box.innerHTML = `
      <h3>${escapeHtml(PLATFORM_LABELS[rel.platform] || rel.platform)} · ${escapeHtml(rel.version_name)} (${rel.version_code})</h3>
      <p>SHA-256：<code>${escapeHtml(rel.sha256)}</code></p>
      <p>${escapeHtml(rel.release_notes || "")}</p>
      <a class="button primary" href="${rel.downloadUrl}">下载 ${escapeHtml(PLATFORM_LABELS[rel.platform] || "应用")}</a>
    `;
  } catch (error) {
    $("#releaseBox").textContent = "请先登录后查看发布包。";
  }
}

async function loadAdmin() {
  try {
    const providers = await api("/api/admin/providers");
    const config = providers.config;
    $("#asrProvider").value = config.asr_provider || "mock";
    $("#asrCommand").value = config.asr_command || "";
    $("#asrEndpoint").value = config.asr_endpoint || "";
    $("#asrApiKey").value = "";
    $("#asrApiKey").placeholder = config.asr_api_key_set ? "已保存，留空保持不变" : "可选";
    $("#asrModel").value = config.asr_model || "";
    $("#llmProvider").value = config.llm_provider || "mock";
    $("#llmEndpoint").value = config.llm_endpoint || "";
    $("#llmApiKey").value = "";
    $("#llmApiKey").placeholder = config.llm_api_key_set ? "已保存，留空保持不变" : "可选";
    $("#llmModel").value = config.llm_model || "";
    $("#hermesWebhookUrl").value = config.hermes_webhook_url || "";
    $("#hermesWebhookToken").value = "";
    $("#hermesWebhookToken").placeholder = config.hermes_webhook_token_set ? "已保存，留空保持不变" : "可选";
    $("#esEnabled").checked = Boolean(config.es_enabled);
    $("#esUrl").value = config.es_url || "";
    $("#esIndex").value = config.es_index || "solorecord_meetings";
    $("#externalApiTokens").value = "";
    $("#externalApiTokens").placeholder = config.external_api_tokens_set ? "已保存，留空保持不变" : "client:token";
    $("#segmentMinutes").value = config.audio_segment_minutes || 5;
    $("#targetSampleRate").value = config.target_sample_rate || 16000;
    $("#enableDiarization").checked = Boolean(config.enable_diarization);
    $("#enableSemanticSegmentation").checked = config.enable_semantic_segmentation !== false;
    $("#enableDenoise").checked = Boolean(config.enable_denoise);
    const jobs = await api("/api/admin/jobs");
    $("#jobList").innerHTML = (jobs.items || []).map((job) => `
      <div class="job-item">
        <b>${job.status} · ${job.current_stage}</b>
        <span>${job.progress}% · ${job.asr_provider}</span>
        <button class="button secondary retry-job" data-id="${job.id}">重试</button>
        <span class="hint">${escapeHtml(job.error_message || "")}</span>
      </div>
    `).join("") || "暂无任务";
    $$(".retry-job").forEach((button) => button.addEventListener("click", () => retryJob(button.dataset.id)));
  } catch (error) {
    toast("管理页需要管理员账号");
  }
}

async function saveProviders() {
  await api("/api/admin/providers", {
    method: "PUT",
    body: JSON.stringify({
      asr_provider: $("#asrProvider").value,
      asr_command: $("#asrCommand").value,
      asr_endpoint: $("#asrEndpoint").value,
      asr_api_key: $("#asrApiKey").value,
      asr_model: $("#asrModel").value,
      llm_provider: $("#llmProvider").value,
      llm_endpoint: $("#llmEndpoint").value,
      llm_api_key: $("#llmApiKey").value,
      llm_model: $("#llmModel").value,
      hermes_webhook_url: $("#hermesWebhookUrl").value,
      hermes_webhook_token: $("#hermesWebhookToken").value,
      es_enabled: $("#esEnabled").checked,
      es_url: $("#esUrl").value,
      es_index: $("#esIndex").value,
      external_api_tokens: $("#externalApiTokens").value,
      audio_segment_minutes: Number($("#segmentMinutes").value),
      enable_diarization: $("#enableDiarization").checked,
      enable_semantic_segmentation: $("#enableSemanticSegmentation").checked,
      enable_denoise: $("#enableDenoise").checked,
      target_sample_rate: Number($("#targetSampleRate").value),
    }),
  });
  toast("配置已保存");
}

async function retryJob(jobId) {
  await api(`/api/admin/jobs/${jobId}/retry`, { method: "POST", body: "{}" });
  toast("已重新提交任务");
  await loadAdmin();
}

async function uploadRelease() {
  const file = $("#releaseFile").files[0];
  if (!file) {
    toast("请选择发布包文件");
    return;
  }
  const form = new FormData();
  form.append("platform", $("#releasePlatform").value);
  form.append("version_name", $("#releaseVersionName").value || "0.7.0");
  form.append("version_code", $("#releaseVersionCode").value || "7");
  form.append("release_notes", $("#releaseNotes").value || "");
  form.append("force_update", $("#forceUpdate").checked ? "true" : "false");
  form.append("file", file);
  await api("/api/admin/releases", { method: "POST", body: form, headers: {} });
  state.selectedDownloadPlatform = $("#releasePlatform").value;
  toast("发布包已上传");
  await loadRelease();
}

function statusLabel(status) {
  const labels = {
    local_recording: "录音中",
    local_recorded: "待上传",
    uploading: "上传中",
    uploaded: "已上传",
    partial_ready: "分段转写中",
    queued: "排队中",
    preprocessing: "预处理",
    diarizing: "分离说话人",
    transcribing: "转写中",
    postprocessing: "后处理",
    summarizing: "整理纪要",
    ready: "已完成",
    failed: "失败",
  };
  return labels[status] || status || "未知";
}

function meetingStatusHint(status, audioSegments, transcriptSegments) {
  const pending = audioSegments.filter((segment) => segment.upload_status !== "uploaded").length;
  if (status === "failed") return "处理失败。管理员可以在任务队列里查看错误并重试，已上传音频和转写不会丢失。";
  if (pending > 0) return `还有 ${pending} 个音频分段未到服务器，网络恢复后继续同步即可。`;
  if (status === "partial_ready") return "分段转写正在持续补充，结束会议后会生成完整纪要和待办。";
  if (status === "ready") return "会议已完成，可以校对说话人、待办和转写后导出或交给知识平台读取。";
  if (["queued", "preprocessing", "transcribing", "summarizing"].includes(status)) return "服务器正在处理，稍后刷新可看到最新结果。";
  if (transcriptSegments.length) return "已有转写内容，可以先校对关键段落。";
  return "音频已保存后会进入转写和整理流程。";
}

function buildSpeakerStats(segments, actions = [], speakerSamples = new Map()) {
  const stats = new Map();
  const substantiveSegments = segments.filter((segment) => !isPlaceholderTranscriptFlags(parseFlags(segment.flags)));
  substantiveSegments.forEach((segment) => {
    const id = segment.speaker_id || segment.display_name || "speaker";
    const name = segment.display_name || segment.speaker_id || "发言人";
    const key = speakerStatsKey(id, name);
    const item = stats.get(key) || {
      id,
      name,
      count: 0,
      durationMs: 0,
      actionCount: 0,
      aliases: [],
      speakerIds: [],
      sample: null,
    };
    item.name = name || item.name;
    if (id && !item.speakerIds.includes(id)) item.speakerIds.push(id);
    item.count += 1;
    item.durationMs += Math.max(0, Number(segment.end_ms || 0) - Number(segment.start_ms || 0));
    if (segment.display_name && segment.display_name !== id) item.aliases.push(id);
    item.sample = item.sample || speakerSamples.get(id) || speakerSamples.get(name) || null;
    stats.set(key, item);
  });
  actions.forEach((action) => {
    const owner = String(action.owner || "").trim();
    if (!owner) return;
    const match = Array.from(stats.values()).find((item) => item.name === owner || item.id === owner);
    if (match) {
      match.actionCount += 1;
    } else if (owner !== "待确认") {
      stats.set(`owner:${owner}`, {
        id: `owner:${owner}`,
        name: owner,
        count: 0,
        durationMs: 0,
        actionCount: 1,
        aliases: [],
        speakerIds: [`owner:${owner}`],
        sample: null,
      });
    }
  });
  return Array.from(stats.values())
    .map((item) => ({ ...item, aliases: Array.from(new Set(item.aliases.filter(Boolean))) }))
    .sort((left, right) => right.durationMs - left.durationMs);
}

function buildSpeakerStatsFromSpeakers(speakers = [], actions = []) {
  const stats = new Map();
  speakers.forEach((speaker) => {
    const id = speaker.speaker_id || speaker.id || speaker.display_name || "speaker";
    const name = speaker.display_name || speaker.speaker_id || "发言人";
    stats.set(speakerStatsKey(id, name), {
      id,
      name,
      count: 0,
      durationMs: 0,
      actionCount: 0,
      aliases: id && id !== name ? [id] : [],
      speakerIds: [id].filter(Boolean),
      sample: null,
    });
  });
  actions.forEach((action) => {
    const owner = String(action.owner || "").trim();
    if (!owner || owner === "待确认") return;
    const match = Array.from(stats.values()).find((item) => item.name === owner || item.id === owner);
    if (match) {
      match.actionCount += 1;
    } else {
      stats.set(`owner:${owner}`, {
        id: `owner:${owner}`,
        name: owner,
        count: 0,
        durationMs: 0,
        actionCount: 1,
        aliases: [],
        speakerIds: [`owner:${owner}`],
        sample: null,
      });
    }
  });
  return Array.from(stats.values()).sort((left, right) => right.actionCount - left.actionCount);
}

function speakerStatsKey(id, name) {
  const displayName = String(name || "").trim();
  const speakerId = String(id || "").trim();
  if (displayName && !isGenericSpeakerLabel(displayName)) return `name:${displayName}`;
  return `id:${speakerId || displayName || "speaker"}`;
}

function isGenericSpeakerLabel(name) {
  const value = String(name || "").trim();
  return !value || value.startsWith("发言人") || value.toLowerCase().startsWith("speaker");
}

function buildSpeakerSamples(segments, audioSegments, meetingId) {
  const samples = new Map();
  const substantiveSegments = segments.filter((segment) => {
    const flags = parseFlags(segment.flags);
    return !isPlaceholderTranscriptFlags(flags) && (segment.speaker_id || segment.display_name);
  });
  substantiveSegments.forEach((segment) => {
    const audio = findAudioForTranscriptSegment(segment, audioSegments);
    if (!audio) return;
    const sample = buildSpeakerSample(segment, audio, meetingId);
    if (!sample) return;
    [segment.speaker_id, segment.display_name].filter(Boolean).forEach((key) => {
      const current = samples.get(key);
      if (!current || sample.rank > current.rank) samples.set(key, sample);
    });
  });
  return samples;
}

function findAudioForTranscriptSegment(segment, audioSegments) {
  if (!Array.isArray(audioSegments) || !audioSegments.length) return null;
  const sourceId = String(segment.source_id || "primary").trim() || "primary";
  const sourceSegmentNo = Number(segment.source_segment_no || 0);
  if (sourceSegmentNo) {
    const exact = audioSegments.find((audio) => (
      String(audio.source_id || "primary") === sourceId
      && Number(audio.source_segment_no || audio.segment_no || 0) === sourceSegmentNo
    ));
    if (exact) return exact;
  }
  const start = Number(segment.start_ms || 0);
  const end = Number(segment.end_ms || start);
  return audioSegments.find((audio) => {
    const audioStart = Number(audio.start_ms || 0);
    const audioEnd = Number(audio.end_ms || audioStart + Number(audio.duration_ms || 0));
    return start < audioEnd && end > audioStart;
  }) || null;
}

function buildSpeakerSample(segment, audio, meetingId) {
  const audioStartMs = Number(audio.start_ms || 0);
  const audioDurationMs = Number(audio.duration_ms || Math.max(0, Number(audio.end_ms || 0) - audioStartMs));
  const audioEndMs = audioDurationMs ? audioStartMs + audioDurationMs : Number(audio.end_ms || 0);
  const segmentStartMs = Math.max(audioStartMs, Number(segment.start_ms || audioStartMs));
  const segmentEndMs = Math.max(segmentStartMs + 1000, Number(segment.end_ms || segmentStartMs + 10000));
  const availableEndMs = audioEndMs > audioStartMs ? Math.min(segmentEndMs, audioEndMs) : segmentEndMs;
  const availableMs = Math.max(1000, availableEndMs - segmentStartMs);
  const targetMs = Math.min(20000, Math.max(5000, availableMs));
  const sampleEndMs = audioEndMs > audioStartMs
    ? Math.min(audioEndMs, segmentStartMs + targetMs)
    : segmentStartMs + targetMs;
  if (sampleEndMs <= segmentStartMs) return null;
  const relativeStartSec = Math.max(0, (segmentStartMs - audioStartMs) / 1000);
  const relativeEndSec = Math.max(relativeStartSec + 1, (sampleEndMs - audioStartMs) / 1000);
  const absoluteDurationMs = sampleEndMs - segmentStartMs;
  const downloadUrl = audio.download_url || `/api/web/meetings/${meetingId}/segments/${audio.segment_no}/audio`;
  return {
    audioUrl: webAudioUrl(downloadUrl),
    startSec: relativeStartSec.toFixed(2),
    endSec: relativeEndSec.toFixed(2),
    absoluteStartMs: segmentStartMs,
    absoluteEndMs: sampleEndMs,
    durationMs: absoluteDurationMs,
    sourceLabel: `${audio.source_label || sourceDisplayLabel(audio)} · 分段 ${audio.source_segment_no || audio.segment_no}`,
    text: summarizeSegmentText(segment.text || ""),
    rank: speakerSampleRank(segment, absoluteDurationMs),
  };
}

function webAudioUrl(url) {
  return String(url || "").replace("/api/mobile/", "/api/web/");
}

function speakerSampleRank(segment, durationMs) {
  const textLength = String(segment.text || "").trim().length;
  const durationScore = durationMs >= 5000 && durationMs <= 20000 ? 100 : Math.min(80, durationMs / 200);
  return durationScore + Math.min(60, textLength);
}

function formatSampleSeconds(sample) {
  const seconds = Math.max(1, Math.round(Number(sample?.durationMs || 0) / 1000));
  return `${seconds} 秒`;
}

function buildSegmentInsights(segments, actions, audioSegments) {
  const groups = new Map();
  const substantiveSegments = segments.filter((segment) => !isPlaceholderTranscriptFlags(parseFlags(segment.flags)));
  const speakerTotals = buildSpeakerStats(substantiveSegments);
  segments.forEach((segment) => {
    const isPlaceholder = isPlaceholderTranscriptFlags(parseFlags(segment.flags));
    const key = segment.source_segment_no
      ? sourceKey(segment.source_id, segment.source_segment_no)
      : inferAudioSegmentNo(segment, audioSegments) || "final";
    const item = groups.get(key) || {
      key,
      label: key === "final" ? "最终整理" : segment.source_segment_no
        ? `${sourceDisplayLabel(segment)} · 分段 ${segment.source_segment_no}`
        : `音频分段 ${key}`,
      startMs: Number(segment.start_ms || 0),
      endMs: Number(segment.end_ms || 0),
      speakers: new Set(),
      speakerCounts: new Map(),
      texts: [],
      actions: [],
      owners: new Set(),
    };
    item.startMs = Math.min(item.startMs, Number(segment.start_ms || 0));
    item.endMs = Math.max(item.endMs, Number(segment.end_ms || item.startMs));
    const speakerName = segment.display_name || segment.speaker_id || "发言人";
    if (!isPlaceholder) {
      item.speakers.add(speakerName);
      item.speakerCounts.set(speakerName, (item.speakerCounts.get(speakerName) || 0) + 1);
    }
    if (segment.text) item.texts.push(segment.text);
    groups.set(key, item);
  });
  const items = Array.from(groups.values()).sort((left, right) => left.startMs - right.startMs);
  actions.forEach((action) => {
    const text = `${action.task || ""} ${action.owner || ""}`;
    const matched = items.find((item) => item.texts.some((line) => action.task && line.includes(action.task)))
      || items.find((item) => item.texts.some((line) => text && text.split(/\s+/).some((word) => word && line.includes(word))))
      || items[items.length - 1];
    if (matched) {
      matched.actions.push(action.task || "待办");
      if (action.owner) matched.owners.add(action.owner);
    }
  });
  return items.map((item) => ({
    ...item,
    speakers: Array.from(item.speakers),
    speakerHint: buildSpeakerHint(Array.from(item.speakers), speakerTotals, substantiveSegments.length),
    owners: Array.from(item.owners),
    topic: summarizeSegmentText(item.texts.join("")),
  }));
}

function buildSpeakerHint(speakers, speakerTotals, totalSegments) {
  if (speakers.length > 1) return "";
  if (!speakers.length || totalSegments < 2) return "";
  const onlySpeaker = speakers[0];
  const matched = speakerTotals.find((speaker) => speaker.name === onlySpeaker);
  if (matched && matched.count === totalSegments) {
    return "整场暂只有一个发言人标签，如本段包含多人，请在时间线拆分并设为新发言人。";
  }
  return "";
}

function buildClientQualityReport(segments, actions) {
  const substantiveSegments = segments.filter((segment) => !isPlaceholderTranscriptFlags(parseFlags(segment.flags)));
  const speakerReviewCount = segments.filter((segment) => {
    const flags = parseFlags(segment.flags);
    return flags.includes("speaker_review") && !isPlaceholderTranscriptFlags(flags);
  }).length;
  const speakerCount = new Set(substantiveSegments.map((segment) => segment.display_name || segment.speaker_id).filter(Boolean)).size;
  const placeholderTranscriptCount = segments.filter((segment) => {
    const flags = parseFlags(segment.flags);
    return isPlaceholderTranscriptFlags(flags);
  }).length;
  const actionableActions = actions.filter((action) => !isReviewOnlyAction(action));
  const systemReviewActionCount = actions.length - actionableActions.length;
  const genericOwnerCount = actionableActions.filter((action) => isGenericOwner(action.owner)).length;
  const issues = [];
  if (!segments.length) {
    issues.push({ severity: "high", title: "暂无转写", detail: "会议还没有可检查的转写文本。" });
  }
  if (placeholderTranscriptCount) {
    issues.push({ severity: "high", title: "存在占位转写", detail: `${placeholderTranscriptCount} 个段落需要重新转写或人工复核。` });
  }
  if (speakerCount <= 1 && substantiveSegments.length >= 2) {
    issues.push({ severity: "medium", title: "整场只有一个发言人标签", detail: "多人会议建议检查长段并拆分发言人。" });
  }
  if (speakerCount >= 16) {
    issues.push({ severity: "high", title: "发言人标签异常偏多", detail: `${speakerCount} 个发言人标签可能是同一人被拆成多个 speaker。` });
  } else if (speakerCount >= 10) {
    issues.push({ severity: "medium", title: "发言人标签偏多", detail: "建议在人物校对区试听声音样本并合并同一人标签。" });
  }
  if (speakerReviewCount) {
    issues.push({ severity: "medium", title: "存在需要校对的发言人", detail: `${speakerReviewCount} 个段落建议人工抽查。` });
  }
  if (genericOwnerCount) {
    issues.push({ severity: "high", title: "待办负责人仍需确认", detail: `${genericOwnerCount} 个待办负责人偏泛。` });
  }
  if (systemReviewActionCount) {
    issues.push({ severity: "medium", title: "存在系统复核提醒", detail: "系统复核提醒不是可自动督办的会议待办。" });
  }
  const score = Math.max(0, Math.min(100, 92 - issues.reduce((sum, issue) => sum + (issue.severity === "high" ? 22 : 12), 0)));
  return {
    score,
    status: issues.some((issue) => issue.severity === "high") ? "needs_review" : score >= 86 ? "good" : "review_recommended",
    metrics: {
      speaker_count: speakerCount,
      candidate_people_count: 0,
      speaker_review_count: speakerReviewCount,
      speaker_evidence_weak_count: 0,
      speaker_over_split_count: speakerCount >= 10 ? speakerCount : 0,
      action_count: actions.length,
      actionable_action_count: actionableActions.length,
      system_review_action_count: systemReviewActionCount,
      generic_owner_count: genericOwnerCount,
      unsupported_action_count: 0,
      weak_action_owner_count: 0,
      action_evidence_coverage: actionableActions.length ? 1 : 1,
      summary_evidence_coverage: 1,
      summary_unsupported_count: 0,
      placeholder_transcript_count: placeholderTranscriptCount,
    },
    candidatePeople: [],
    summaryEvidence: { coverage: 1, claim_count: 0, unsupported_count: 0, unsupportedClaims: [] },
    issues,
    recommendations: issues.map((issue) => issue.detail).filter(Boolean),
  };
}

function isGenericOwner(owner) {
  const value = String(owner || "").trim();
  return !value || ["待确认", "负责人", "相关负责人", "前端开发", "UI讨论者", "主持人"].includes(value) || value.endsWith("负责人");
}

function inferAudioSegmentNo(segment, audioSegments) {
  const start = Number(segment.start_ms || 0);
  const row = audioSegments.find((audio) => start >= Number(audio.start_ms || 0) && start <= Number(audio.end_ms || 0));
  return row?.segment_no || null;
}

function sourceKey(sourceId, sourceSegmentNo) {
  const normalizedSourceId = String(sourceId || "primary").trim() || "primary";
  return `${normalizedSourceId}::${String(sourceSegmentNo || "").trim()}`;
}

function parseSourceKey(value) {
  const raw = String(value || "");
  if (!raw.includes("::")) {
    return { sourceId: "", sourceSegmentNo: Number(raw || 0) || 0 };
  }
  const [sourceId, sourceSegmentNo] = raw.split("::");
  return {
    sourceId: sourceId || "primary",
    sourceSegmentNo: Number(sourceSegmentNo || 0) || 0,
  };
}

function sourceDisplayLabel(segment) {
  const detail = state.currentMeetingDetail || {};
  const sourceId = String(segment?.source_id || "primary").trim() || "primary";
  const source = (detail.recordingSources || []).find((item) => item.source_id === sourceId);
  return source?.label || segment?.source_label || (sourceId === "primary" ? "主录音源" : sourceId);
}

function summarizeSegmentText(text) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  if (value.length <= 120) return value;
  return `${value.slice(0, 120)}...`;
}

function buildTranscriptFilters(segments) {
  const filters = [{ value: "all", label: "全部段落" }];
  const riskFilters = [
    { value: "flag:speaker_review", label: "需确认段落" },
    { value: "flag:speaker_evidence_weak", label: "发言人证据弱" },
    { value: "risk:placeholder_transcript", label: "复核占位" },
    { value: "risk:long_segment", label: "长段落" },
    { value: "risk:multi_source_conflict", label: "多源冲突" },
    { value: "flag:multi_source_majority", label: "多数源确认" },
    { value: "flag:multi_source_complemented", label: "多源互补" },
    { value: "flag:semantic_llm", label: "大模型分段" },
    { value: "flag:semantic_rule", label: "规则分段" },
  ].filter((filter) => segments.some((segment) => matchesTranscriptFilter(segment, filter.value)));
  filters.push(...riskFilters);
  const seenSegments = new Set();
  segments.forEach((segment) => {
    if (segment.source_segment_no) {
      const key = sourceKey(segment.source_id, segment.source_segment_no);
      if (seenSegments.has(key)) return;
      seenSegments.add(key);
      filters.push({
        value: `segment:${key}`,
        label: `${sourceDisplayLabel(segment)} · 分段 ${segment.source_segment_no}`,
      });
    }
  });
  buildSpeakerStats(segments).forEach((speaker) => {
    const speakerIds = Array.isArray(speaker.speakerIds) && speaker.speakerIds.length
      ? speaker.speakerIds
      : [speaker.id];
    filters.push({ value: `speaker:${speakerIds.join("|")}`, label: speaker.name });
  });
  return filters;
}

function filteredTranscriptSegments(segments) {
  const filter = state.selectedTranscriptFilter || "all";
  if (filter === "all") return segments;
  return segments.filter((segment) => matchesTranscriptFilter(segment, filter));
}

function matchesTranscriptFilter(segment, filter) {
  if (!filter || filter === "all") return true;
  if (filter.startsWith("segment:")) {
    const parsed = parseSourceKey(filter.slice("segment:".length));
    if (parsed.sourceId) {
      return String(segment.source_id || "primary") === parsed.sourceId
        && Number(segment.source_segment_no || 0) === parsed.sourceSegmentNo;
    }
    return Number(segment.source_segment_no || 0) === parsed.sourceSegmentNo;
  }
  if (filter.startsWith("speaker:")) {
    const speakerIds = filter.slice("speaker:".length).split("|").filter(Boolean);
    return speakerIds.includes(String(segment.speaker_id || ""));
  }
  if (filter.startsWith("flag:")) {
    const wanted = filter.slice("flag:".length);
    const flags = parseFlags(segment.flags);
    if (wanted === "speaker_review" && isPlaceholderTranscriptFlags(flags)) {
      return false;
    }
    if (wanted === "semantic_llm") {
      return flags.includes("semantic_llm") || flags.includes("llm_refined");
    }
    return flags.includes(wanted);
  }
  if (filter === "risk:placeholder_transcript") {
    return isPlaceholderTranscriptFlags(parseFlags(segment.flags));
  }
  if (filter === "risk:long_segment") {
    return (
      Number(segment.end_ms || 0) - Number(segment.start_ms || 0) >= 180000 ||
      String(segment.text || "").length >= 900
    );
  }
  if (filter === "risk:source_coverage") {
    const weak = state.currentMeetingDetail?.qualityReport?.sourceCoverage?.weakSegments || [];
    const weakKeys = new Set(weak.map((item) => sourceKey(item.source_id, item.source_segment_no || item.segment_no)));
    return weakKeys.has(sourceKey(segment.source_id, segment.source_segment_no));
  }
  if (filter === "risk:multi_source_conflict") {
    return parseFlags(segment.flags).includes("multi_source_conflict");
  }
  return true;
}

function isPlaceholderTranscriptFlags(flags) {
  return ["mock_asr", "empty_asr", "missing_audio", "source_coverage_gap"].some((flag) => flags.includes(flag));
}

function actionStatusLabel(status) {
  return {
    open: "待处理",
    doing: "进行中",
    done: "已完成",
    blocked: "受阻",
  }[status] || status || "待处理";
}

function parseFlags(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [String(value)];
  }
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "";
}

function formatTime(ms) {
  const seconds = Math.floor((ms || 0) / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${Math.round(Math.max(0, Math.min(1, number)) * 100)}%`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

function bindEvents() {
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => setView(item.dataset.view)));
  $("#loginButton").addEventListener("click", (event) => {
    if (event && event.altKey) {
      demoLogin();
      return;
    }
    showLogin();
  });
  $("#desktopLoginButton")?.addEventListener("click", showLogin);
  $("#desktopLogoutButton")?.addEventListener("click", logout);
  $("#loginForm").addEventListener("submit", ldapLogin);
  $("#cancelLogin").addEventListener("click", hideLogin);
  $("#loginModal").addEventListener("click", (event) => {
    if (event.target === $("#loginModal")) hideLogin();
  });
  $("#refreshMeetings").addEventListener("click", () => loadMeetings($("#searchInput").value.trim()));
  $("#searchInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadMeetings($("#searchInput").value.trim());
  });
  $("#createUploadButton").addEventListener("click", createAndUpload);
  ["recordJoinCode", "uploadJoinCode"].forEach((id) => {
    const input = $(`#${id}`);
    if (!input) return;
    input.addEventListener("focus", () => loadJoinableMeetings(input.value.trim()));
    input.addEventListener("input", () => {
      renderJoinableMeetingLists();
      scheduleJoinableMeetingLoad(input);
    });
  });
  $("#startRecordButton").addEventListener("click", () => {
    startWebRecording().catch(() => toast("无法开始录音，请检查麦克风权限"));
  });
  $("#stopRecordButton").addEventListener("click", () => {
    stopWebRecording().catch(() => toast("结束录音失败，请稍后重试"));
  });
  $$("#downloadTabs .chip").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedDownloadPlatform = button.dataset.platform;
      $$("#downloadTabs .chip").forEach((item) => item.classList.toggle("active", item === button));
      loadRelease();
    });
  });
  $("#refreshAdmin").addEventListener("click", loadAdmin);
  $("#saveProviders").addEventListener("click", saveProviders);
  $("#uploadRelease").addEventListener("click", uploadRelease);
  window.addEventListener("beforeunload", (event) => {
    if (state.recorder.mediaRecorder) {
      event.preventDefault();
      event.returnValue = "录音仍在进行中，请先结束录音。";
    }
  });
}

async function init() {
  configureClientMode();
  bindEvents();
  renderAccount();
  if (state.token) {
    try {
      const data = await api("/api/web/me");
      state.user = data.user;
      renderAccount();
      await loadMeetings();
      await loadJoinableMeetings();
    } catch (error) {
      localStorage.removeItem("solo_token");
      localStorage.removeItem("solo_user");
      state.token = "";
      state.user = null;
      renderAccount();
    }
  }
}

init();
