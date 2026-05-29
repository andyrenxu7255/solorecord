const state = {
  token: localStorage.getItem("solo_token") || "",
  user: JSON.parse(localStorage.getItem("solo_user") || "null"),
  meetings: [],
  selectedMeetingId: "",
  selectedTranscriptVersion: 1,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.add("show");
  setTimeout(() => box.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function setView(name) {
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  if (name === "downloads") loadRelease();
  if (name === "admin") loadAdmin();
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
  toast("已登录");
}

function renderAccount() {
  $("#accountName").textContent = state.user ? `${state.user.display_name} (${state.user.role})` : "未登录";
  $("#loginButton").textContent = state.user ? "切换账号" : "统一登录";
}

function ssoLogin() {
  window.location.href = `/api/auth/sso/start?redirect_after=${encodeURIComponent("/")}`;
}

async function loadMeetings(query = "") {
  if (!state.token) return;
  const data = query ? await api(`/api/web/search?q=${encodeURIComponent(query)}`) : await api("/api/web/meetings");
  state.meetings = data.items || [];
  renderMeetingList();
}

function renderMeetingList() {
  const list = $("#meetingList");
  if (!state.meetings.length) {
    list.innerHTML = `<div class="empty-state">暂无会议</div>`;
    return;
  }
  list.innerHTML = state.meetings.map((meeting) => `
    <article class="meeting-card ${meeting.id === state.selectedMeetingId ? "active" : ""}" data-id="${meeting.id}">
      <h3>${escapeHtml(meeting.title)}</h3>
      <div class="meta-row">
        <span>${formatDate(meeting.created_at)}</span>
        <span class="status-pill">${statusLabel(meeting.status)}</span>
      </div>
    </article>
  `).join("");
  $$(".meeting-card").forEach((card) => {
    card.addEventListener("click", () => selectMeeting(card.dataset.id));
  });
}

async function selectMeeting(id) {
  state.selectedMeetingId = id;
  renderMeetingList();
  const data = await api(`/api/web/meetings/${id}`);
  const transcript = await api(`/api/web/meetings/${id}/transcript`);
  state.selectedTranscriptVersion = transcript.version;
  renderMeetingDetail(data, transcript.segments || []);
}

function renderMeetingDetail(data, transcriptSegments) {
  const meeting = data.meeting;
  const jobs = data.jobs || [];
  const actions = data.actionItems || [];
  const audioSegments = data.audioSegments || [];
  const uploadedAudio = audioSegments.filter((segment) => segment.upload_status === "uploaded").length;
  $("#meetingDetail").innerHTML = `
    <div>
      <input id="detailTitle" class="input" value="${escapeAttr(meeting.title)}">
      <div class="detail-actions">
        <button id="saveMeeting" class="button primary">保存标题/纪要</button>
        <button id="processMeeting" class="button secondary">重新转写整理</button>
        <button data-export="markdown" class="button secondary">导出 Markdown</button>
        <button data-export="docx" class="button secondary">导出 Word</button>
        <button data-export="pdf" class="button secondary">导出 PDF</button>
        <button data-export="srt" class="button secondary">导出 SRT</button>
      </div>
      <div class="meta-row">
        <span>状态：${statusLabel(meeting.status)}</span>
        <span>版本：${meeting.version}</span>
      </div>
      <div class="progress-strip">
        <span>录音分段：${audioSegments.length}</span>
        <span>已上传：${uploadedAudio}</span>
        <span>转写段落：${transcriptSegments.length}</span>
        <span>总时长：${formatTime(meeting.duration_ms || 0)}</span>
      </div>
      <div class="summary-box">
        <h3>会议纪要</h3>
        <textarea id="detailSummary" class="input" rows="5">${escapeHtml(meeting.summary || "")}</textarea>
      </div>
      <div class="actions-box">
        <h3>待办</h3>
        ${actions.length ? actions.map((item) => `<p>${escapeHtml(item.owner)}：${escapeHtml(item.task)} <span class="status-pill">${escapeHtml(item.status)}</span></p>`).join("") : "<p class='hint'>暂无待办</p>"}
      </div>
      <h3>录音分段</h3>
      <div class="audio-list">
        ${audioSegments.map(renderAudioSegment).join("") || "<p class='hint'>暂无音频</p>"}
      </div>
      <h3>转写时间线</h3>
      <div id="transcriptList" class="transcript-list">
        ${transcriptSegments.map(renderTranscriptRow).join("") || "<p class='hint'>暂无转写</p>"}
      </div>
      <button id="saveTranscript" class="button primary">保存转写修改</button>
      <h3>最近任务</h3>
      ${jobs.map((job) => `<div class="job-item"><b>${job.current_stage}</b><span>${job.status} · ${job.progress}%</span><span class="hint">${escapeHtml(job.error_message || "")}</span></div>`).join("") || "<p class='hint'>暂无任务</p>"}
    </div>
  `;
  $("#saveMeeting").addEventListener("click", saveMeeting);
  $("#processMeeting").addEventListener("click", processSelectedMeeting);
  $("#saveTranscript").addEventListener("click", saveTranscript);
  $$("[data-export]").forEach((button) => {
    button.addEventListener("click", () => exportMeeting(button.dataset.export));
  });
  $$(".speaker-name").forEach((input) => {
    input.addEventListener("change", () => renameSpeaker(input.dataset.speaker, input.value));
  });
}

function renderAudioSegment(segment) {
  return `
    <div class="audio-segment">
      <div>
        <b>分段 ${segment.segment_no}</b>
        <span>${formatTime(segment.start_ms || 0)} - ${formatTime(segment.end_ms || 0)}</span>
      </div>
      <span class="status-pill">${segment.upload_status === "uploaded" ? "已上传" : "待上传"}</span>
    </div>
  `;
}

function renderTranscriptRow(segment) {
  const source = segment.source_segment_no ? `分段 ${segment.source_segment_no}` : "最终整理";
  return `
    <div class="transcript-row" data-id="${segment.id || ""}">
      <div>
        <b>${formatTime(segment.start_ms)}</b>
        <span class="hint">${source}</span>
      </div>
      <div>
        <input class="speaker-name" data-speaker="${escapeAttr(segment.speaker_id)}" value="${escapeAttr(segment.display_name || segment.speaker_id)}">
        <input class="speaker-id" type="hidden" value="${escapeAttr(segment.speaker_id)}">
      </div>
      <textarea class="input segment-text" rows="2">${escapeHtml(segment.text || "")}</textarea>
      <input class="start-ms" type="hidden" value="${segment.start_ms || 0}">
      <input class="end-ms" type="hidden" value="${segment.end_ms || 0}">
    </div>
  `;
}

async function saveMeeting() {
  const id = state.selectedMeetingId;
  await api(`/api/web/meetings/${id}`, {
    method: "PATCH",
    body: JSON.stringify({
      title: $("#detailTitle").value,
      summary: $("#detailSummary").value,
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
  const segments = $$("#transcriptList .transcript-row").map((row) => ({
    id: row.dataset.id || null,
    speaker_id: row.querySelector(".speaker-id").value,
    display_name: row.querySelector(".speaker-name").value,
    start_ms: Number(row.querySelector(".start-ms").value),
    end_ms: Number(row.querySelector(".end-ms").value),
    text: row.querySelector(".segment-text").value,
    flags: [],
  }));
  await api(`/api/web/meetings/${state.selectedMeetingId}/transcript`, {
    method: "PUT",
    body: JSON.stringify({ version: state.selectedTranscriptVersion, segments }),
  });
  toast("转写已保存");
  await selectMeeting(state.selectedMeetingId);
}

async function renameSpeaker(speakerId, displayName) {
  if (!displayName.trim()) return;
  await api(`/api/web/meetings/${state.selectedMeetingId}/speakers/rename`, {
    method: "POST",
    body: JSON.stringify({ speaker_id: speakerId, display_name: displayName }),
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
}

async function createAndUpload() {
  const file = $("#audioFile").files[0];
  if (!file) {
    toast("请选择音频文件");
    return;
  }
  const meeting = await api("/api/web/meetings", {
    method: "POST",
    body: JSON.stringify({ title: $("#newMeetingTitle").value || file.name }),
  });
  const meetingId = meeting.meeting.id;
  const form = new FormData();
  form.append("segment_no", "1");
  form.append("start_ms", "0");
  form.append("end_ms", "180000");
  form.append("duration_ms", "180000");
  form.append("file", file);
  await api(`/api/mobile/meetings/${meetingId}/segments`, { method: "POST", body: form, headers: {} });
  await api(`/api/mobile/meetings/${meetingId}/finish`, { method: "POST", body: "{}" });
  toast("已上传并提交处理");
  setView("meetings");
  await loadMeetings();
  await selectMeeting(meetingId);
}

async function loadRelease() {
  try {
    const data = await api("/api/web/releases/latest");
    const box = $("#releaseBox");
    if (!data.release) {
      box.innerHTML = `<p>尚未发布 APK。管理员可在管理页上传。</p>`;
      return;
    }
    const rel = data.release;
    box.innerHTML = `
      <h3>${escapeHtml(rel.version_name)} (${rel.version_code})</h3>
      <p>SHA-256：<code>${escapeHtml(rel.sha256)}</code></p>
      <p>${escapeHtml(rel.release_notes || "")}</p>
      <a class="button primary" href="${rel.downloadUrl}">下载 APK</a>
    `;
  } catch (error) {
    $("#releaseBox").textContent = "请先登录后查看 APK。";
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
  const file = $("#apkFile").files[0];
  if (!file) {
    toast("请选择 APK 文件");
    return;
  }
  const form = new FormData();
  form.append("version_name", $("#releaseVersionName").value || "0.7.0");
  form.append("version_code", $("#releaseVersionCode").value || "7");
  form.append("release_notes", $("#releaseNotes").value || "");
  form.append("force_update", $("#forceUpdate").checked ? "true" : "false");
  form.append("file", file);
  await api("/api/admin/releases", { method: "POST", body: form, headers: {} });
  toast("APK 已发布");
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

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "";
}

function formatTime(ms) {
  const seconds = Math.floor((ms || 0) / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
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
  $("#refreshAdmin").addEventListener("click", loadAdmin);
  $("#saveProviders").addEventListener("click", saveProviders);
  $("#uploadRelease").addEventListener("click", uploadRelease);
}

async function init() {
  bindEvents();
  renderAccount();
  if (state.token) {
    try {
      const data = await api("/api/web/me");
      state.user = data.user;
      renderAccount();
      await loadMeetings();
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
