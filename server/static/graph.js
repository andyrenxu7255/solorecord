const graphState = {
  token: localStorage.getItem("solo_token") || "",
  meetingId: new URLSearchParams(window.location.search).get("meetingId") || "",
  graph: { nodes: [], edges: [] },
  simulation: null,
  transform: { x: 0, y: 0, scale: 1 },
  draggingNode: null,
  panning: null,
};

const $ = (selector) => document.querySelector(selector);

function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.add("show");
  setTimeout(() => box.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (graphState.token) headers.Authorization = `Bearer ${graphState.token}`;
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`);
  return response.json();
}

async function loadGraph() {
  if (!graphState.meetingId) {
    toast("缺少会议 ID");
    return;
  }
  const detail = await api(`/api/web/meetings/${encodeURIComponent(graphState.meetingId)}`);
  const graph = detail.ontologyGraph || { nodes: [], edges: [] };
  graphState.graph = {
    nodes: (graph.nodes || []).map((node) => ({ ...node })),
    edges: (graph.edges || []).map((edge) => ({ ...edge })),
  };
  $("#graphTitle").textContent = `${detail.meeting?.title || "会议"} · 本体图谱`;
  renderGraph();
}

async function rebuildGraph() {
  await api(`/api/web/meetings/${encodeURIComponent(graphState.meetingId)}/ontology/extract`, {
    method: "POST",
    body: "{}",
  });
  toast("已提交抽槽任务，稍后刷新查看");
}

function renderGraph() {
  const svg = $("#graphStage");
  const { width, height } = stageSize(svg);
  svg.innerHTML = "";
  const nodes = graphState.graph.nodes;
  const edges = graphState.graph.edges;
  if (!nodes.length) {
    svg.innerHTML = `<text x="32" y="48" class="graph-empty">暂无图谱节点，请先生成转写和待办，或点击重建图谱。</text>`;
    $("#graphInspector").innerHTML = "<h2>节点详情</h2><p class='hint'>暂无图谱数据。</p>";
    return;
  }
  nodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(1, nodes.length);
    node.x = node.x ?? width / 2 + Math.cos(angle) * Math.min(width, height) * 0.25;
    node.y = node.y ?? height / 2 + Math.sin(angle) * Math.min(width, height) * 0.25;
    node.vx = 0;
    node.vy = 0;
  });
  const viewport = svgEl("g", { class: "ontology-viewport" });
  const edgeLayer = svgEl("g", { class: "ontology-edges" });
  const nodeLayer = svgEl("g", { class: "ontology-nodes" });
  viewport.append(edgeLayer, nodeLayer);
  svg.append(viewport);
  bindStagePan(svg, viewport);
  edges.forEach((edge) => {
    const line = svgEl("line", { class: "ontology-edge" });
    const label = svgEl("text", { class: "ontology-edge-label" });
    label.textContent = edge.label || "关联";
    line.addEventListener("click", () => inspectEdge(edge));
    label.addEventListener("click", () => inspectEdge(edge));
    edge._line = line;
    edge._label = label;
    edgeLayer.append(line, label);
  });
  nodes.forEach((node) => {
    const group = svgEl("g", { class: `ontology-node node-${node.type || "item"}` });
    const circle = svgEl("circle", { r: nodeRadius(node), tabindex: "0" });
    const text = svgEl("text", { y: -4 });
    nodeLabelLines(node.label || node.id).forEach((line, index, lines) => {
      const tspan = svgEl("tspan", {
        x: 0,
        dy: index === 0 ? 0 : 14,
      });
      tspan.textContent = line;
      if (lines.length === 1) text.setAttribute("y", "4");
      text.append(tspan);
    });
    group.append(circle, text);
    group.addEventListener("pointerdown", (event) => startNodeDrag(event, node));
    group.addEventListener("click", () => inspectNode(node));
    node._group = group;
    nodeLayer.append(group);
  });
  startSimulation();
  fitGraph();
}

function startSimulation() {
  if (graphState.simulation) cancelAnimationFrame(graphState.simulation);
  const nodes = graphState.graph.nodes;
  const edges = graphState.graph.edges;
  let tick = 0;
  const run = () => {
    tick += 1;
    simulate(nodes, edges, tick);
    updateSvgPositions();
    if (tick < 260) graphState.simulation = requestAnimationFrame(run);
  };
  run();
}

function simulate(nodes, edges, tick) {
  const svg = $("#graphStage");
  const { width, height } = stageSize(svg);
  const alpha = Math.max(0.02, 0.22 * (1 - tick / 280));
  nodes.forEach((left, index) => {
    for (let i = index + 1; i < nodes.length; i += 1) {
      const right = nodes[i];
      const dx = (left.x - right.x) || 0.01;
      const dy = (left.y - right.y) || 0.01;
      const dist2 = Math.max(100, dx * dx + dy * dy);
      const force = 2600 / dist2;
      left.vx += (dx / Math.sqrt(dist2)) * force * alpha;
      left.vy += (dy / Math.sqrt(dist2)) * force * alpha;
      right.vx -= (dx / Math.sqrt(dist2)) * force * alpha;
      right.vy -= (dy / Math.sqrt(dist2)) * force * alpha;
    }
    left.vx += (width / 2 - left.x) * 0.002 * alpha;
    left.vy += (height / 2 - left.y) * 0.002 * alpha;
  });
  edges.forEach((edge) => {
    const source = nodeById(edge.source);
    const target = nodeById(edge.target);
    if (!source || !target) return;
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
    const desired = edge.type === "responsible_for" ? 150 : 185;
    const force = (distance - desired) * 0.012 * alpha;
    const fx = (dx / distance) * force;
    const fy = (dy / distance) * force;
    source.vx += fx;
    source.vy += fy;
    target.vx -= fx;
    target.vy -= fy;
  });
  nodes.forEach((node) => {
    if (node.fx != null && node.fy != null) {
      node.x = node.fx;
      node.y = node.fy;
      node.vx = 0;
      node.vy = 0;
      return;
    }
    node.vx *= 0.82;
    node.vy *= 0.82;
    node.x = Math.max(40, Math.min(width - 40, node.x + node.vx));
    node.y = Math.max(40, Math.min(height - 40, node.y + node.vy));
  });
}

function updateSvgPositions() {
  graphState.graph.edges.forEach((edge) => {
    const source = nodeById(edge.source);
    const target = nodeById(edge.target);
    if (!source || !target) return;
    edge._line?.setAttribute("x1", source.x);
    edge._line?.setAttribute("y1", source.y);
    edge._line?.setAttribute("x2", target.x);
    edge._line?.setAttribute("y2", target.y);
    edge._label?.setAttribute("x", (source.x + target.x) / 2);
    edge._label?.setAttribute("y", (source.y + target.y) / 2 - 5);
  });
  graphState.graph.nodes.forEach((node) => {
    node._group?.setAttribute("transform", `translate(${node.x},${node.y})`);
  });
}

function startNodeDrag(event, node) {
  event.preventDefault();
  const svg = $("#graphStage");
  graphState.draggingNode = node;
  const move = (moveEvent) => {
    const point = svgPoint(svg, moveEvent);
    node.fx = point.x;
    node.fy = point.y;
    node.x = point.x;
    node.y = point.y;
    updateSvgPositions();
  };
  const up = () => {
    node.fx = null;
    node.fy = null;
    graphState.draggingNode = null;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    startSimulation();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function bindStagePan(svg, viewport) {
  applyTransform(viewport);
  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    const delta = event.deltaY > 0 ? 0.9 : 1.1;
    graphState.transform.scale = Math.max(0.35, Math.min(2.6, graphState.transform.scale * delta));
    applyTransform(viewport);
  }, { passive: false });
  svg.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".ontology-node")) return;
    graphState.panning = { x: event.clientX, y: event.clientY, tx: graphState.transform.x, ty: graphState.transform.y };
  });
  window.addEventListener("pointermove", (event) => {
    if (!graphState.panning) return;
    graphState.transform.x = graphState.panning.tx + event.clientX - graphState.panning.x;
    graphState.transform.y = graphState.panning.ty + event.clientY - graphState.panning.y;
    applyTransform(viewport);
  });
  window.addEventListener("pointerup", () => {
    graphState.panning = null;
  });
}

function fitGraph() {
  graphState.transform = { x: 0, y: 0, scale: 1 };
  const viewport = $("#graphStage .ontology-viewport");
  if (viewport) applyTransform(viewport);
}

function applyTransform(viewport) {
  const transform = graphState.transform;
  viewport.setAttribute("transform", `translate(${transform.x},${transform.y}) scale(${transform.scale})`);
}

function inspectNode(node) {
  $("#graphInspector").innerHTML = `
    <h2>${escapeHtml(node.label || node.id)}</h2>
    <div class="inspector-tags">
      <span>${escapeHtml(typeLabel(node.type))}</span>
      <span>置信度 ${formatConfidence(node.confidence)}</span>
      <span>${escapeHtml(node.source || "rule")}</span>
    </div>
    ${node.description ? `<p>${escapeHtml(node.description)}</p>` : ""}
    ${renderEvidence(node.evidence)}
  `;
}

function inspectEdge(edge) {
  $("#graphInspector").innerHTML = `
    <h2>${escapeHtml(edge.label || "关系")}</h2>
    <p><b>${escapeHtml(edge.source_label || edge.source)}</b> → <b>${escapeHtml(edge.target_label || edge.target)}</b></p>
    <div class="inspector-tags">
      <span>${escapeHtml(edge.type || "related_to")}</span>
      <span>置信度 ${formatConfidence(edge.confidence)}</span>
      <span>${escapeHtml(edge.source_kind || "rule")}</span>
    </div>
    ${renderEvidence(edge.evidence)}
  `;
}

function renderEvidence(evidence) {
  const items = Array.isArray(evidence) ? evidence : [];
  if (!items.length) return "<p class='hint'>暂无可定位证据。</p>";
  return `
    <div class="inspector-evidence">
      ${items.slice(0, 6).map((item) => `
        <article>
          <b>${escapeHtml(evidenceTitle(item))}</b>
          <p>${escapeHtml(item.text || item.task || `${item.owner || ""} ${item.due || ""}`.trim() || "证据")}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function evidenceTitle(item) {
  if (item.kind === "action_item") return `待办 ${item.action_id || ""}`.trim();
  const source = item.source_id ? `${item.source_id}#${item.source_segment_no || ""}` : "转写";
  return `${source} ${formatTime(item.start_ms || 0)} ${item.speaker || ""}`.trim();
}

function nodeById(id) {
  return graphState.graph.nodes.find((node) => node.id === id);
}

function nodeRadius(node) {
  const labelLength = String(node.label || node.id || "").length;
  const base = { person: 30, action: 40, matter: 34, time: 25, place: 27 }[node.type] || 28;
  return Math.min(52, base + Math.max(0, labelLength - 6) * 1.4);
}

function nodeLabelLines(label) {
  const value = String(label || "").trim();
  if (value.length <= 7) return [value];
  if (value.length <= 14) return [value.slice(0, Math.ceil(value.length / 2)), value.slice(Math.ceil(value.length / 2))];
  return [value.slice(0, 7), `${value.slice(7, 13)}...`];
}

function stageSize(svg) {
  const rect = svg.getBoundingClientRect();
  return { width: Math.max(320, rect.width || 960), height: Math.max(320, rect.height || 640) };
}

function svgPoint(svg, event) {
  const point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const matrix = svg.getScreenCTM()?.inverse();
  const raw = matrix ? point.matrixTransform(matrix) : point;
  const transform = graphState.transform;
  return {
    x: (raw.x - transform.x) / transform.scale,
    y: (raw.y - transform.y) / transform.scale,
  };
}

function svgEl(tag, attrs = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function typeLabel(type) {
  return { person: "人员", place: "地点", time: "时间", matter: "事项", action: "待办" }[type] || "对象";
}

function formatConfidence(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${Math.round(number * 100)}%`;
}

function formatTime(ms) {
  const seconds = Math.max(0, Math.floor(Number(ms || 0) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

$("#refreshGraph").addEventListener("click", () => loadGraph().catch(() => toast("刷新失败")));
$("#rebuildGraph").addEventListener("click", () => rebuildGraph().catch(() => toast("提交失败")));
$("#fitGraph").addEventListener("click", fitGraph);
window.addEventListener("resize", () => renderGraph());
loadGraph().catch(() => toast("读取图谱失败，请确认已登录并有会议权限"));
