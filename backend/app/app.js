"use strict";
const appPath = window.assistantPaths.path;
const appFetch = window.assistantPaths.fetch;
const el = id => document.getElementById(id);
const state = { loaded:false, configured:false, busy:false, view:"chat", sessions:[], active:null, detail:null, pending:null, pendingSteps:[], pendingText:"", failure:null, m5stackEnabled:true, useKnowledge:false, pendingKnowledge:false };
const configIds = ["provider", "base_url", "model", "models_protocol"];
const realtimeAdvancedDefaults = {
  rt_silence_gate_enabled:true, rt_silence_gate_rms:120, rt_defer_response_until_transcript:false,
  rt_max_continuous_turns:6, rt_max_continuous_seconds:600, rt_ack_enabled:true,
};
const MANUAL = "__manual__";
const SESSION_PAGE = 25;
let sessionHasMore = false, sessionLoading = false, sessionError = "", sessionOffset = 0;
let sessionLoadId = 0, sessionController = null, sessionSearchTimer = null, activeTurn = null;
const STOP_INTENT_RE = /^(?:停|停下|停下来|停止|停止操作|别动|别动了|别操作了|取消|取消操作|住手|stop|cancel)[！!。.？?]*$/i;
const capabilityState = { tools:[], documents:[], total:0, offset:0, loading:false, busy:false, queryId:0, supportedFileTypes:[".txt",".md",".markdown",".docx"], selectedCapability:null, libraries:[], selectionSupported:false, selectedTools:[], selectedKbs:[], activeLibraryId:null, toolsLoaded:false, librariesLoaded:false, librariesError:false, selectionFetched:false, selectionError:false, selectionSaving:false };
const INSIGHT_PAGE = 25;
const insightState = {kb:{offset:0,total:0,loading:false,requestId:0,controller:null,filters:{},items:[],searchTimer:null},tools:{offset:0,total:0,loading:false,requestId:0,controller:null,filters:{},items:[],searchTimer:null},traces:{offset:0,total:0,loading:false,requestId:0,controller:null,filters:{},items:[],searchTimer:null},errors:{offset:0,total:0,loading:false,requestId:0,controller:null,filters:{},items:[],searchTimer:null}};
let insightDeleteState = null;
let savedFingerprint = "";
let lastStepPreview = null;
let ackGenerationBusy = false;
let savedConfig = null, savedTtsConfig = null, modelsFetched = false, speechModels = [];
let savedWeather = {enabled:true, city:""};
let qwenVoices = [], realtimeSampleUrl = null, realtimePreviewController = null;
// Cloned voices come from the server; the model selects which family is shown.
const CLONE_MODEL = "mimo-v2.5-tts-voiceclone";
const VOICEDESIGN_MODEL = "mimo-v2.5-tts-voicedesign";
const PRESET_VOICES = ["mimo_default","冰糖","茉莉","苏打","白桦","Mia","Chloe","Milo","Dean"];
const OPENAI_TTS_MODELS = ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"];
const OPENAI_TTS_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"];
const BAILIAN_TTS_MODELS = ["qwen3-tts-flash-realtime", "qwen3-tts-vc-realtime"];
const BAILIAN_TTS_VOICES = ["Cherry", "Serena", "Ethan", "Chelsie", "Momo", "Vivian", "Moon", "Maia", "Kai", "Nofish", "Bella", "Jennifer", "Ryan", "Katerina", "Elias"];
const MIMO_TTS_MODELS = ["mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"];
let clonedVoices = [], bailianTtsVoices = [], voiceProfiles = {};
// Fixed speaking-style hint for the TTS provider; deliberately not the role text.
const SPEAKING_STYLE = "用活泼轻快、带点主播感的语气说，语速正常，咬字清楚，不要含糊。";
let ttsLoaded = false, ttsBusy = false, ttsController = null, ttsAudioUrl = null;
const ttsIds = ["tts_provider", "tts_model", "tts_voice"];
function node(tag, className = "", text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`); svg.append(use); svg.setAttribute("aria-hidden", "true");
  return svg;
}
function remember(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch {} }
function recalled(key) { try { return localStorage.getItem(key); } catch { return null; } }
function notice(message = "", kind = "") {
  const target = el(state.view === "chat" ? "notice" : "settings-notice");
  target.textContent = message; target.dataset.kind = kind; target.hidden = !message;
}
async function request(path, method = "GET", body, signal) {
  let response;
  try {
    response = await appFetch(path, { method, signal, headers:{ "Content-Type":"application/json", "X-Local-Settings":"1" }, body:body === undefined ? undefined : JSON.stringify(body) });
  } catch (error) { if (error.name === "AbortError") throw error; throw new Error("无法连接本机服务，请确认服务正在运行后重试。"); }
  if (response.status === 204) return null;
  if (response.ok && response.headers.get("Content-Type")?.startsWith("audio/")) return response.blob();
  let data;
  try { data = await response.json(); } catch { throw new Error(`服务返回了无法读取的响应（HTTP ${response.status}）。`); }
  if (!response.ok) {
    const detail = data.detail;
    let message = typeof detail === "string" ? detail : detail?.message;
    if (Array.isArray(detail)) message = detail.map(item => `${item.loc.slice(1).join(".")}：${item.msg}`).join("；");
    const error = new Error(message || `请求失败（HTTP ${response.status}）`); error.code = detail?.code; error.status = response.status; throw error;
  }
  return data;
}
function refreshControls() {
  el("config-fields").disabled = state.busy || ttsBusy || !state.loaded;
  for (const id of ["save", "test", "fetch-models"]) el(id).disabled = state.busy || ttsBusy || !state.loaded;
  el("new-session").disabled = state.busy;
  el("send").hidden = state.busy;
  el("send").disabled = state.busy || !state.configured || !el("message").value.trim();
  el("stop-turn").hidden = !state.busy;
  el("stop-turn").disabled = !state.busy || Boolean(activeTurn?.stopping);
  el("message").disabled = false;
  el("message").placeholder = state.busy ? "运行中，可点右侧停止或输入“停止”…" : "发消息…";
  el("voice-toggle").disabled = state.busy;
  el("use-knowledge").disabled = state.busy || !state.m5stackEnabled;
  el("use-knowledge").setAttribute("aria-pressed", String(state.useKnowledge));
  for (const id of ["rename-session", "delete-session", "export-session"]) {
    el(id).hidden = state.view !== "chat"; el(id).disabled = state.busy || !state.active;
  }
  document.querySelectorAll(".session-item").forEach(button => { button.disabled = state.busy; });
  document.querySelectorAll(".session-row-check input").forEach(input => { input.disabled = state.busy; });
  if (el("session-manage-toggle")) el("session-manage-toggle").disabled = state.busy;
  if (el("session-select-all")) el("session-select-all").disabled = state.busy || !state.sessions.length;
  if (el("session-bulk-delete")) el("session-bulk-delete").disabled = state.busy || selectedSessionIds.size === 0;
  if (el("session-manage-done")) el("session-manage-done").disabled = state.busy;
  const label = state.busy ? "正在处理请求…" : state.configured ? "已配置，随时提问" : state.loaded ? "尚未配置模型" : "正在连接本机服务";
  el("composer-state").replaceChildren(node("span", "state-dot"), document.createTextNode(label));
  el("composer-state").classList.toggle("sr-only", !state.busy);
  el("configure-link").hidden = state.configured;
  el("context-note").hidden = !state.configured;
  el("role-fields").disabled = state.busy || ttsBusy || !state.loaded || !ttsLoaded;
  el("tts-save").disabled = state.busy || ttsBusy || !state.loaded || !ttsLoaded;
  el("tts-preview").disabled = state.busy || ttsBusy || !ttsLoaded;
  el("fetch-speech-models").disabled = state.busy || ttsBusy || !state.loaded;
  el("tts-text").disabled = ttsBusy;
  el("assistant-reset").disabled = state.busy || ttsBusy || !state.loaded || !ttsLoaded;
}
function busy(value) { state.busy = value; refreshControls(); }
function closeSidebar() { document.body.classList.remove("sidebar-open"); el("sidebar-overlay").hidden = true; }
function openSidebar() {
  document.body.classList.remove("sidebar-collapsed");
  if (matchMedia("(max-width:700px)").matches) { document.body.classList.add("sidebar-open"); el("sidebar-overlay").hidden = false; }
}
function navigate(view, push = true, deviceTab = "desktop") {
  if (view === "settings") view = recalled("atoms3r.settingsSection") || "role";
  if (state.view !== view) { stopTtsPreview(); stopRealtimeSample(); }
  state.view = view;
  if (view !== "chat") remember("atoms3r.settingsSection", view);
  for (const name of ["settings", "connections", "devices", "capabilities", "insights"]) el(`${name}-view`).hidden = name === "settings" ? view !== "role" : name !== view;
  el("chat-view").hidden = false;
  el("test-panel").hidden = true;
  el("settings-page").hidden = view === "chat";
  el("settings-nav").hidden = false;
  if (view !== "chat") el("api-workbench").hidden = true;
  document.querySelectorAll("[data-view]").forEach(link => { const active = (link.dataset.view === view) && view !== "chat"; link.classList.toggle("active", active); link.setAttribute("aria-current", active ? "page" : "false"); });
  el("settings-button").classList.toggle("active", view !== "chat");
  const title = view === "chat" ? state.detail?.title || "新对话" : {settings:"Agent 与档案", connections:"模型与连接", role:"Agent 与档案", devices:"终端节点", capabilities:"技能与知识", insights:"执行洞察"}[view];
  el("view-title").textContent = title;
  el("rename-form").hidden = true; el("view-title").hidden = false;
  const path = appPath({settings:"/settings", connections:"/settings#api", role:"/settings#role", devices:"/devices", capabilities:"/settings#capabilities", insights:"/settings#insights", chat:"/"}[view]);
  if (push && location.pathname + location.hash !== path) history.pushState({view}, "", path);
  document.title = `${title} · 小圆`;
  closeSidebar(); notice(); refreshControls(); renderSessions();
  if (view === "connections" && state.loaded && savedConfig?.voice_mode === "pipeline" && savedConfig?.api_key_configured && !modelsFetched && !state.busy) queueMicrotask(refreshModelChoices);
  if (view === "role" && state.loaded && !deviceData) loadDevices(true).catch(error => notice(error.message,"error"));
  if (view === "devices") showDeviceTab(deviceTab);
  if (view === "capabilities") loadCapabilities().catch(error => capabilityNotice(error.message,true));
  if (view === "insights") loadInsights().catch(error => insightNotice(error.message,true));
}
let sessionManageMode = false;
const selectedSessionIds = new Set();
function syncBulkSessionControls() {
  const toggleBtn = el("session-manage-toggle"), bar = el("session-bulk-bar");
  const selectAll = el("session-select-all"), delBtn = el("session-bulk-delete");
  if (!toggleBtn || !bar || !selectAll || !delBtn) return;
  toggleBtn.hidden = sessionManageMode || !state.sessions.length;
  bar.hidden = !sessionManageMode;
  const visibleIds = state.sessions.map(session => session.session_id);
  const selectedVisible = visibleIds.filter(id => selectedSessionIds.has(id)).length;
  selectAll.checked = visibleIds.length > 0 && selectedVisible === visibleIds.length;
  selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visibleIds.length;
  delBtn.textContent = selectedSessionIds.size ? `删除 (${selectedSessionIds.size})` : "删除";
  delBtn.disabled = state.busy || selectedSessionIds.size === 0;
}
function renderSessions() {
  const list = el("session-list"), scrollTop = list.scrollTop; list.replaceChildren();
  const query = el("session-search").value.trim();
  if (!state.sessions.length && !sessionError) list.append(node("p", "sidebar-empty", sessionLoading ? "正在加载…" : query ? "没有匹配的对话" : "开始对话后，记录会出现在这里。"));
  for (const session of state.sessions) {
    if (sessionManageMode) {
      const row = node("label", "session-row-check");
      const box = node("input"); box.type = "checkbox"; box.checked = selectedSessionIds.has(session.session_id);
      box.disabled = state.busy;
      box.addEventListener("change", () => {
        if (box.checked) selectedSessionIds.add(session.session_id);
        else selectedSessionIds.delete(session.session_id);
        syncBulkSessionControls();
      });
      row.title = session.title;
      row.append(box, node("span", "", session.title));
      list.append(row);
    } else {
      const button = node("button", "session-item" + (session.session_id === state.active && state.view === "chat" ? " active" : ""));
      button.title = session.title; button.append(node("span", "", session.title));
      button.setAttribute("aria-current", session.session_id === state.active && state.view === "chat" ? "page" : "false");
      button.addEventListener("click", () => selectSession(session.session_id)); list.append(button);
    }
  }
  if (sessionError) list.append(node("p", "sidebar-empty", sessionError));
  if (sessionHasMore || sessionError) {
    const more = node("button", "session-more", sessionLoading ? "正在加载…" : sessionError ? "重试加载" : "加载更多");
    more.type = "button"; more.disabled = sessionLoading;
    more.addEventListener("click", () => loadSessions(state.sessions.length > 0).catch(() => {})); list.append(more);
  }
  list.scrollTop = scrollTop; syncBulkSessionControls(); refreshControls();
}
el("session-manage-toggle")?.addEventListener("click", () => {
  if (state.busy) return;
  sessionManageMode = true; selectedSessionIds.clear(); renderSessions();
});
el("session-manage-done")?.addEventListener("click", () => {
  sessionManageMode = false; selectedSessionIds.clear(); renderSessions();
});
el("session-select-all")?.addEventListener("change", () => {
  const checked = el("session-select-all").checked;
  for (const session of state.sessions) {
    if (checked) selectedSessionIds.add(session.session_id);
    else selectedSessionIds.delete(session.session_id);
  }
  renderSessions();
});
el("session-bulk-delete")?.addEventListener("click", async () => {
  const ids = Array.from(selectedSessionIds);
  if (!ids.length || state.busy) return;
  if (!confirm(`确定删除选中的 ${ids.length} 段对话？删除后无法恢复。`)) return;
  busy(true);
  try {
    const results = await Promise.allSettled(ids.map(id => request(`/sessions/${encodeURIComponent(id)}`, "DELETE")));
    const deleted = ids.filter((_, idx) => results[idx].status === "fulfilled");
    const failed = ids.filter((_, idx) => results[idx].status === "rejected");
    for (const id of deleted) selectedSessionIds.delete(id);
    if (state.active && deleted.includes(state.active)) {
      state.active = null; state.detail = null; state.pending = null; state.pendingSteps = []; state.pendingText = ""; state.failure = null;
      remember("atoms3r.active", null); renderMessages();
    }
    if (!failed.length) sessionManageMode = false;
    busy(false);
    await loadSessions();
    if (failed.length) notice(`已删除 ${deleted.length} 段，${failed.length} 段删除失败。`, "error");
    else notice(`已删除 ${deleted.length} 段对话。`, "success");
  } catch (error) { notice(error.message, "error"); } finally { busy(false); }
});
async function loadSessions(append = false) {
  clearTimeout(sessionSearchTimer);
  sessionController?.abort(); const controller = new AbortController(); sessionController = controller;
  const id = ++sessionLoadId, offset = append ? sessionOffset : 0;
  sessionLoading = true; sessionError = "";
  if (!append) {state.sessions = []; sessionOffset = 0; sessionHasMore = false;}
  renderSessions();
  const params = new URLSearchParams({limit:String(SESSION_PAGE + 1), offset:String(offset), q:el("session-search").value.trim()});
  try {
    const rows = await request(`/sessions?${params}`, "GET", undefined, controller.signal);
    if (id !== sessionLoadId) return;
    const page = rows.slice(0, SESSION_PAGE);
    state.sessions = append ? [...state.sessions, ...page].filter((item,index,all) => all.findIndex(other => other.session_id === item.session_id) === index) : page;
    sessionOffset = offset + page.length; sessionHasMore = rows.length > SESSION_PAGE;
  } catch (error) {
    if (error.name === "AbortError" || id !== sessionLoadId) return;
    sessionError = error.message; throw error;
  } finally {
    if (id === sessionLoadId) { sessionLoading = false; renderSessions(); }
  }
}
async function selectSession(id) {
  if (state.busy) return;
  busy(true);
  try {
    const detail = await request(`/sessions/${id}`);
    state.active = id; state.detail = detail; state.pending = null; state.pendingSteps = []; state.pendingText = ""; state.failure = null;
    remember("atoms3r.active", id); el("message").value = ""; fitComposer();
    navigate("chat"); renderMessages();
  } catch (error) { notice(error.message, "error"); } finally { busy(false); }
}
function newConversation() {
  if (state.busy) return;
  state.active = null; state.detail = null; state.pending = null; state.pendingSteps = []; state.pendingText = ""; state.failure = null;
  remember("atoms3r.active", null); el("message").value = ""; fitComposer();
  navigate("chat"); renderMessages(); el("message").focus();
}
function inline(parent, text) {
  const regex = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\))/g;
  let offset = 0;
  for (const match of text.matchAll(regex)) {
    parent.append(document.createTextNode(text.slice(offset, match.index)));
    const value = match[0];
    if (value.startsWith("`")) parent.append(node("code", "", value.slice(1,-1)));
    else if (value.startsWith("**")) parent.append(node("strong", "", value.slice(2,-2)));
    else {
      const parts = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(value);
      try {
        const url = new URL(parts[2]);
        if (!["https:", "http:"].includes(url.protocol)) throw new Error();
        const link = node("a", "", parts[1]); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; parent.append(link);
      } catch { parent.append(document.createTextNode(value)); }
    }
    offset = match.index + value.length;
  }
  parent.append(document.createTextNode(text.slice(offset)));
}
function markdown(text) {
  const result = node("div", "message-body"); const lines = text.split("\n");
  let paragraph = [], list = null;
  const flush = () => { if (paragraph.length) { const p = node("p"); inline(p, paragraph.join("\n")); result.append(p); paragraph = []; } list = null; };
  for (let i=0; i<lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("```")) {
      flush(); const language = line.slice(3).trim(); const codeLines = [];
      while (++i < lines.length && !lines[i].startsWith("```")) codeLines.push(lines[i]);
      const block = node("div", "code-block"); block.append(node("div", "code-header", language || "代码"));
      const pre = node("pre"); pre.append(node("code", "", codeLines.join("\n"))); block.append(pre); result.append(block); continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) { flush(); const h = node(`h${heading[1].length + 1}`); inline(h, heading[2]); result.append(h); continue; }
    const cells = value => value.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(cell => cell.trim());
    const headerCells = cells(line), divider = cells(lines[i+1] || "");
    if (line.includes("|") && headerCells.length > 1 && headerCells.length === divider.length && divider.every(cell => /^:?-{3,}:?$/.test(cell))) {
      flush(); const wrap = node("div", "table-wrap"), table = node("table"), head = node("thead"), headRow = node("tr");
      for (const text of headerCells) { const cell = node("th"); inline(cell,text); headRow.append(cell); }
      head.append(headRow); table.append(head); const body = node("tbody");
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        const values = cells(lines[i]), row = node("tr");
        for (let index=0; index<headerCells.length; index++) { const cell = node("td"); inline(cell,values[index] || ""); row.append(cell); }
        body.append(row); i++;
      }
      i--; table.append(body); wrap.append(table); result.append(wrap); continue;
    }
    const bullet = /^(?:([-*])|\d+[.)])\s+(.+)$/.exec(line);
    if (bullet) {
      if (paragraph.length) flush();
      const type = bullet[1] ? "UL" : "OL";
      if (!list || list.tagName !== type) { list = node(type.toLowerCase()); result.append(list); }
      const item = node("li"); inline(item, bullet[2]); list.append(item); continue;
    }
    if (!line.trim()) { flush(); continue; }
    list = null; paragraph.push(line);
  }
  flush(); return result;
}
function messageNode(message) {
  const article = node("article", `message ${message.role}`);
  if (message.role === "user") { article.append(node("div", "user-text", message.content)); return article; }
  const label = node("div", "assistant-label"); label.append(icon("chat"), document.createTextNode("小圆 助理"));
  article.append(label, markdown(message.content));
  const footer = node("div", "message-footer"); const copy = node("button", "icon-button");
  copy.setAttribute("aria-label", "复制回答"); copy.title = "复制回答"; copy.append(icon("copy"));
  copy.addEventListener("click", async () => {
    const current = article.querySelector(".message-body")?.innerText || message.content;
    try { await navigator.clipboard.writeText(current); notice("回答已复制。", "success"); }
    catch { notice("无法写入剪贴板，请选择回答文字后手动复制。", "error"); }
  });
  footer.append(copy);
  const metadata = node("span", "", assistantInfo(message));
  footer.append(metadata); article.append(footer);
  if (message.knowledge) {
    const sources = node("details", "message-sources");
    sources.append(node("summary", "", message.knowledge.status === "empty" ? "未检索到匹配的官方资料" : `检索了 ${message.knowledge.documents.length} 个资料片段 · 查看来源`));
    sources.append(sourceList(message.knowledge.sources)); article.append(sources);
  }
  renderMessageReferences(article,message);
  return article;
}
const TOOL_DISPLAY_NAMES = {
  get_weather: "天气查询",
  web_search: "联网搜索",
  search_m5stack: "M5 官方资料",
  search_personal_knowledge: "个人知识库",
  search_conversation_history: "会话历史",
  get_device_status: "硬件状态",
  set_device_volume: "硬件音量",
  set_speech_rate: "语音语速",
  set_speech_pitch: "语音音调",
  desktop_list_nodes: "列出电脑节点",
  desktop_inspect_screen: "观察电脑屏幕",
  desktop_clipboard: "读取剪贴板",
  desktop_list_dir: "浏览电脑目录",
  desktop_read_file: "读取电脑文件",
  desktop_set_clipboard: "写入剪贴板",
  desktop_open: "打开电脑应用/链接",
  desktop_gui_action: "电脑键鼠操控",
  desktop_run_command: "电脑终端命令",
};
function toolDisplayName(name) { return TOOL_DISPLAY_NAMES[name] || name || "工具调用"; }
const APPROVAL_STATUS_TEXT = {
  pending: "等待确认",
  approved: "已确认执行",
  consumed: "已确认执行",
  denied: "已取消",
  expired: "已超时",
  superseded: "已被后续操作取代",
};
const DESKTOP_LEASE_TOOLS = new Set(["desktop_open", "desktop_gui_action", "desktop_set_clipboard"]);
function renderApprovalCard(article, message) {
  article.querySelector(".approval-card")?.remove();
  const pa = message.pending_approval;
  if (!pa || !pa.tool_name) return;
  const status = pa.status || "pending";
  const card = node("div", `approval-card approval-${status}`);
  const head = node("div", "approval-card-head");
  head.append(node("strong", "", `待确认操作 · ${toolDisplayName(pa.tool_name)}`));
  head.append(node("span", "approval-status-badge", APPROVAL_STATUS_TEXT[status] || status));
  card.append(head);
  if (pa.summary) card.append(node("div", "approval-summary", pa.summary));
  if (status === "pending" && pa.approval_id) {
    const actions = node("div", "approval-actions");
    const approveBtn = node("button", "primary-button", "确认执行"); approveBtn.type = "button";
    const leaseBtn = DESKTOP_LEASE_TOOLS.has(pa.tool_name) ? node("button", "secondary-button", "确认并免问电脑操控 (3 分钟)") : null;
    if (leaseBtn) leaseBtn.type = "button";
    const denyBtn = node("button", "secondary-button", "取消执行"); denyBtn.type = "button";
    const setBusy = flag => {
      approveBtn.disabled = flag; denyBtn.disabled = flag;
      if (leaseBtn) leaseBtn.disabled = flag;
    };
    const submitDecision = async decision => {
      setBusy(true);
      try {
        const res = await request(`/api/approvals/${encodeURIComponent(pa.approval_id)}`, "POST", {
          decision,
          session_id: state.active || pa.session_id || null,
        });
        pa.status = res.status;
        renderApprovalCard(article, message);
        if (decision === "approve" || decision === "approve_desktop_lease") await sendMessage("确认执行");
        else notice("已取消该操作。");
      } catch (error) {
        notice(error.message, "error");
        if (error.code === "approval_expired" || error.code === "approval_closed") {
          pa.status = error.code === "approval_expired" ? "expired" : "denied";
          renderApprovalCard(article, message);
        } else {
          setBusy(false);
        }
      }
    };
    approveBtn.addEventListener("click", () => submitDecision("approve"));
    if (leaseBtn) leaseBtn.addEventListener("click", () => submitDecision("approve_desktop_lease"));
    denyBtn.addEventListener("click", () => submitDecision("deny"));
    actions.append(approveBtn);
    if (leaseBtn) actions.append(leaseBtn);
    actions.append(denyBtn);
    card.append(actions);
  }
  article.append(card);
}
function renderStepPreview(calls) {
  const preview = lastStepPreview;
  if (!preview || !calls?.some(call => call.call_id === preview.callId)) return null;
  const details = node("details", "step-preview-details");
  details.open = preview.open;
  details.addEventListener("toggle", () => { preview.open = details.open; });
  const img = node("img");
  img.alt = "带编号框的电脑截图";
  img.loading = "lazy";
  img.src = preview.url;
  details.append(node("summary", "", "查看刚截取的带框画面"), img);
  return details;
}
function renderMessageReferences(article,message) {
  if (!article) return;
  article.querySelector(".tool-pills")?.remove();
  article.querySelector(".step-preview-details")?.remove();
  article.querySelector(".approval-card")?.remove();
  article.querySelector(".message-personal-sources")?.remove();
  article.querySelector(".message-tool-calls")?.remove();
  article.querySelector(".message-token-usage")?.remove();
  if (Array.isArray(message.tool_calls) && message.tool_calls.length) {
    const visibleCalls = message.tool_calls.filter(call => (call.tool_name || call.name) !== "_load_task_tools");
    if (visibleCalls.length) {
      const strip = node("div", "tool-pills");
      for (const call of visibleCalls) {
        const st = call.status || "ok";
        const pill = node("span", `tool-pill tool-pill-${st}`);
        pill.append(node("i", "tool-pill-dot"));
        const label = toolDisplayName(call.tool_name || call.name);
        const titled = call.detail ? `${label} · ${call.detail}` : label;
        pill.append(document.createTextNode(call.elapsed_ms != null ? `${titled} · ${call.elapsed_ms}ms` : titled));
        strip.append(pill);
      }
      const footer = article.querySelector(".message-footer");
      if (footer) footer.before(strip); else article.append(strip);
    }
  }
  const stepPreview = renderStepPreview(message.tool_calls);
  if (stepPreview) {
    const footer = article.querySelector(".message-footer");
    if (footer) footer.before(stepPreview); else article.append(stepPreview);
  }
  renderApprovalCard(article, message);
  const usageDetails = tokenUsageDetails(message.usage);
  article.append(usageDetails);
  if (Array.isArray(message.sources) && message.sources.length) {
    const details = node("details","message-sources message-personal-sources");
    details.append(node("summary","",`已向模型提供 ${message.sources.length} 个资料片段 · 查看出处；实际引用以正文 [资料N] 为准`));
    const list = node("ul","message-reference-list");
    for (const source of message.sources) {
      const entry = node("li"), citation = source.citation || "资料";
      const parts = [source.title || source.filename || "未命名资料"];
      if (source.filename && source.title && source.filename !== source.title) parts.push(source.filename);
      if (source.page != null) parts.push(`第 ${source.page} 页`);
      if (source.ordinal != null) parts.push(`片段 ${source.ordinal}`);
      const label = `${citation} ${parts.join(" · ")}`;
      let original = null;
      if (source.original_url) {try {const url = window.assistantPaths.localLink(source.original_url); if (url?.pathname.startsWith(appPath("/api/knowledge/personal/"))) original = url;} catch {}}
      if (original) {const link = node("a","",label); link.href = original.href; link.download = source.filename || ""; entry.append(link);}
      else entry.append(node("span","",label));
      if (source.document_version != null) entry.append(node("span","metadata",`资料版本 ${source.document_version}`));
      list.append(entry);
    }
    details.append(list); article.append(details);
  }
  if (Array.isArray(message.tool_calls) && message.tool_calls.length) {
    const details = node("details","message-sources message-tool-calls");
    details.append(node("summary","",`调用了 ${message.tool_calls.length} 次工具 · 查看`));
    const list = node("ul","message-reference-list");
    for (const call of message.tool_calls) {
      const entry = node("li");
      entry.append(node("span","",`${toolDisplayName(call.tool_name || call.name)} (${call.tool_name || call.name || "tool"})`));
      const bits = [call.detail || "", call.status || (call.http_status != null ? `HTTP ${call.http_status}` : ""), call.elapsed_ms != null ? `${call.elapsed_ms} ms` : "", call.error_code || ""].filter(Boolean);
      if (bits.length) entry.append(node("span","metadata",bits.join(" · ")));
      const resp = call.response || {};
      const extra = [];
      if (call.request?.arguments && (call.tool_name || "").startsWith("desktop_")) extra.push(`参数：${JSON.stringify(call.request.arguments)}`);
      if (resp.screen_coords) extra.push(`点击坐标：(${resp.screen_coords.x}, ${resp.screen_coords.y})`);
      if (resp.vision_analysis) extra.push(`看图：${resp.vision_analysis}`);
      if (resp.vision_error || resp.message) extra.push(`返回：${resp.vision_error || resp.message}`);
      if (extra.length) entry.append(node("div", "metadata", extra.join(" ｜ ")));
      list.append(entry);
    }
    details.append(list); article.append(details);
  }
}
const SOURCE_LABELS = { text: "文字", web_voice: "网页语音", device_voice: "设备语音" };
function tokenUsageDetails(usage) {
  const details = node("details", "message-sources message-token-usage");
  details.append(node("summary", "", "Token 明细与统计口径"));
  const list = node("ul", "message-reference-list");
  const count = value => Number.isInteger(value) ? value.toLocaleString("zh-CN") : "未报告";
  const row = (label, value) => {
    const entry = node("li");
    entry.append(node("span", "", label), node("span", "metadata", count(value)));
    list.append(entry);
  };
  row("本轮模型响应次数（含工具续答）", usage?.response_count);
  row("已报告用量的响应次数", usage?.reported_response_count);
  const labels = {text_tokens:"文字", audio_tokens:"音频", image_tokens:"图片", video_tokens:"视频",
    cached_tokens:"缓存命中（输入子集）", cached_tokens_details:"缓存命中细分",
    reasoning_tokens:"思考（输出子集）"};
  const breakdown = (prefix, values) => {
    for (const [key, value] of Object.entries(values || {})) {
      const label = `${prefix} · ${labels[key] || key}`;
      if (value && typeof value === "object") breakdown(label, value);
      else row(label, value);
    }
  };
  for (const [label, field] of [["输入", "input_tokens_details"], ["输出", "output_tokens_details"]]) {
    const values = usage?.[field];
    const expected = field === "input_tokens_details" ? ["text_tokens", "audio_tokens", "cached_tokens"] : ["text_tokens", "audio_tokens"];
    for (const key of expected) row(`${label} · ${labels[key]}`, values?.[key]);
    breakdown(label, Object.fromEntries(Object.entries(values || {}).filter(([key]) => !expected.includes(key))));
  }
  for (const [index, response] of (usage?.responses || []).entries()) {
    const entry = node("li", "", `第 ${index + 1} 次模型响应：输入 ${count(response.prompt_tokens)} / 输出 ${count(response.completion_tokens)} / 合计 ${count(response.total_tokens)}`);
    list.append(entry);
  }
  details.append(list, node("p", "", "输入包含指令、工具定义、有效历史和当前消息，语音还可能含音频。供应商未逐项报告系统指令/工具/历史各占多少；这里不估造。缓存是输入的一部分，不重复相加。一次回答可能经过多次模型响应，各次输入会分别计量；Token 数不等于费用。缺项表示未报告，旧历史无法补算。"));
  if (usage?.response_count > usage?.reported_response_count) {
    details.append(node("p", "", "本轮部分响应未报告用量，合计不完整；明细只在所有响应均报告同一项时累计。"));
  }
  return details;
}
function assistantInfo(message) {
  const info = [];
  if (message.source && message.source !== "text" && SOURCE_LABELS[message.source]) info.push(SOURCE_LABELS[message.source]);
  if (message.model) info.push(message.model);
  const usage = message.usage;
  if (usage && ["prompt_tokens", "completion_tokens", "total_tokens"].some(key => usage[key] !== null && usage[key] !== undefined)) {
    const count = value => value === null || value === undefined ? "未报告" : value.toLocaleString("zh-CN");
    info.push(`本轮 Token：输入 ${count(usage.prompt_tokens)} / 输出 ${count(usage.completion_tokens)} / 合计 ${count(usage.total_tokens)}`);
  } else {
    info.push("本轮 Token：供应商未报告");
  }
  if (message.estimated_cost !== null && message.estimated_cost !== undefined) info.push(`${message.estimated_cost} ${message.currency}`);
  if (message.knowledge) info.push(message.knowledge.status === "empty" ? "资料未命中" : `资料检索 ${message.knowledge.documents?.length ?? 0} 段`);
  if (message.finish_reason === "length") info.push("回复达到长度上限");
  if (message.status === "interrupted") info.push("生成已停止");
  if (message.status === "failed") info.push("回答未完成");
  if (message.audio_status === "failed") info.push("语音未完成");
  else if (message.audio_status === "interrupted") info.push("语音已停止");
  else if (message.audio_status === "played") info.push("已播放");
  else if (message.audio_status) info.push("语音未确认播完");
  return info.join(" · ");
}
window.atoms3rVoiceMessages = {
  realtime() {return savedConfig?.voice_mode === "realtime";},
  sessionId() { return state.active; },
  bindSession(data) {
    state.active = data.session_id;
    remember("atoms3r.active", data.session_id);
    if (state.detail) {
      state.detail.session_id = data.session_id;
      for (const message of state.detail.messages.slice(-2)) message.turn_id = data.turn_id;
    }
  },
  async syncHistory(id) {
    const detail = await request(`/sessions/${id}`);
    if (state.active === id) state.detail = detail;
    await loadSessions();
  },
  completed(data, article) {
    const latest = state.detail?.messages.findLast(message => message.turn_id === data.turn_id && message.role === "assistant");
    if (latest) Object.assign(latest, {
      content:data.reply, model:data.model, provider:data.provider, usage:data.usage,
      estimated_cost:data.estimated_cost, currency:data.currency, finish_reason:data.finish_reason,
      status:"complete", audio_status:data.audio_status,
      sources:data.sources ?? latest.sources, tool_calls:data.tool_calls ?? latest.tool_calls,
      pending_approval:data.pending_approval ?? latest.pending_approval,
    });
    const footer = article?.querySelector(".message-footer > span");
    if (footer && latest) footer.textContent = assistantInfo(latest);
    if (article && latest) renderMessageReferences(article, latest);
    article?.removeAttribute("aria-busy");
    if (data.history_persisted === false) notice("回答已收到，但历史未能写入本机。", "error");
    loadSessions().catch(() => notice("回答已保存，会话列表暂时无法刷新。", "error"));
  },
  appendExchange(text, status) {
    const area = el("messages");
    const user = messageNode({role:"user", content:text, voiceExchange:true});
    const assistant = messageNode({role:"assistant", content:status});
    assistant.classList.add("voice-assistant");
    state.detail ||= {session_id:null, title:text.slice(0,40), messages:[]};
    state.detail.messages.push(
      {role:"user", content:text, created_at:new Date().toISOString(), voiceExchange:true},
      {role:"assistant", content:status, created_at:new Date().toISOString(), voiceExchange:true},
    );
    if (state.view === "chat") {
      el("view-title").textContent = state.detail.title;
      document.title = `${state.detail.title} · 小圆`;
    }
    user.dataset.voiceExchange = ""; assistant.dataset.voiceExchange = "";
    area.append(user, assistant); el("empty-state").hidden = true;
    el("chat-scroll").scrollTop = el("chat-scroll").scrollHeight;
    return assistant;
  },
  updateAssistant(article, text) {
    if (!article) return;
    const current = article.querySelector(".message-body");
    if (current) current.replaceWith(markdown(text));
    article.querySelector(".message-footer")?.classList.toggle("pending", text === "正在思考…");
    const latest = state.detail?.messages.findLast(message => message.voiceExchange && message.role === "assistant");
    if (latest) latest.content = text;
    el("chat-scroll").scrollTop = el("chat-scroll").scrollHeight;
  },
};
function renderMessages() {
  const messages = state.detail?.messages || []; const area = el("messages"); area.replaceChildren();
  document.dispatchEvent(new Event("atoms3r:chat-rendered"));
  window.dispatchEvent(new Event("atoms3r:chat-rendered"));
  el("empty-state").hidden = messages.length > 0 || Boolean(state.pending) || Boolean(state.failure);
  for (const message of messages) area.append(messageNode(message));
  if (state.pending || state.failure) {
    area.append(messageNode({role:"user", content:state.pending || state.failure.message}));
    if (state.pending) {
      const box = node("div", "pending-live-box");
      const activeStep = [...state.pendingSteps].reverse().find(step => step.status === "running");
      const statusText = activeStep
        ? `正在${toolDisplayName(activeStep.tool_name)}${activeStep.detail ? `：${activeStep.detail}` : ""}…`
        : (state.pendingKnowledge ? "正在查询官方资料并生成回答…" : "正在思考…");
      const pending = node("div", "pending-text");
      pending.append(node("span", "pending-dot"), document.createTextNode(statusText));
      const inlineStop = node("button", "pending-stop-button", activeTurn?.stopping ? "正在停止…" : "停止");
      inlineStop.type = "button";
      inlineStop.disabled = Boolean(activeTurn?.stopping);
      inlineStop.addEventListener("click", () => stopActiveTurn());
      pending.append(inlineStop);
      box.append(pending);
      if (state.pendingSteps.length) {
        const strip = node("div", "tool-pills");
        for (const step of state.pendingSteps) {
          const pill = node("span", `tool-pill tool-pill-${step.status || "running"}`);
          pill.append(node("i", "tool-pill-dot"));
          const label = toolDisplayName(step.tool_name);
          const titled = step.detail ? `${label} · ${step.detail}` : label;
          const suffix = step.status === "running" ? " · 进行中…" : (step.elapsed_ms != null ? ` · ${step.elapsed_ms}ms` : "");
          pill.append(document.createTextNode(`${titled}${suffix}`));
          strip.append(pill);
        }
        box.append(strip);
      }
      const stepPreview = renderStepPreview(state.pendingSteps);
      if (stepPreview) box.append(stepPreview);
      if (state.pendingText) box.append(markdown(state.pendingText));
      area.append(box);
    } else {
      const failure = node("div", "request-error", state.failure.error);
      const retry = node("button", "secondary-button", "重新发送"); retry.addEventListener("click", () => sendMessage(state.failure.message, state.failure.useKnowledge)); failure.append(retry); area.append(failure);
    }
  }
  el("chat-scroll").scrollTop = el("chat-scroll").scrollHeight;
}
function fitComposer() {
  const input = el("message"); input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight,180)}px`;
  el("character-count").textContent = input.value.length > 3200 ? `${input.value.length} / 4000` : ""; refreshControls();
}
async function streamChatTurn(body, onEvent, signal) {
  let response;
  try {
    response = await appFetch("/chat/stream", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json", "X-Local-Settings": "1" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new Error("无法连接本机服务，请确认服务正在运行后重试。");
  }
  if (!response.ok) {
    const errPayload = await response.json().catch(() => ({}));
    const detail = errPayload?.detail;
    const msg = (typeof detail === "object" && detail?.message) ? detail.message : (typeof detail === "string" ? detail : `请求失败 (${response.status})`);
    const err = new Error(msg);
    if (typeof detail === "object" && detail?.code) err.code = detail.code;
    throw err;
  }
  if (!response.body) return request("/chat", "POST", body);
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let doneData = null;
  const dispatchBlock = block => {
    const lines = block.split(/\r?\n/);
    let eventName = "message";
    const dataLines = [];
    for (const line of lines) {
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return;
    let payload = {};
    try { payload = JSON.parse(dataLines.join("\n")); } catch { return; }
    if (eventName === "error") {
      const err = new Error(payload.message || "请求失败");
      if (payload.code) err.code = payload.code;
      throw err;
    }
    if (eventName === "done") doneData = payload;
    onEvent(eventName, payload);
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const match = /\r?\n\r?\n/.exec(buffer);
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + (match ? match[0].length : 2));
      if (block.trim()) dispatchBlock(block);
    }
  }
  if (buffer.trim()) dispatchBlock(buffer);
  if (!doneData) throw new Error("回答流提前结束，请重试或刷新会话查看是否已保存。");
  return doneData;
}
async function stopActiveTurn() {
  if (!state.busy || !activeTurn || activeTurn.stopping) return;
  activeTurn.stopping = true;
  refreshControls();
  renderMessages();
  const sid = activeTurn.sessionId || state.active;
  const tid = activeTurn.turnId || null;
  if (sid) {
    appFetch("/chat/cancel", {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json", "X-Local-Settings": "1" },
      body: JSON.stringify(tid ? { session_id: sid, turn_id: tid } : { session_id: sid }),
    }).catch(() => {});
  }
  activeTurn.controller.abort();
}
async function sendMessage(value, useKnowledge = state.useKnowledge) {
  const message = value.trim();
  if (!message) return;
  if (state.busy) {
    if (STOP_INTENT_RE.test(message)) {
      el("message").value = ""; fitComposer();
      await stopActiveTurn();
    }
    return;
  }
  if (!state.configured) return;
  const controller = new AbortController();
  activeTurn = { controller, sessionId: state.active, turnId: null, stopping: false };
  state.pending = message; state.pendingSteps = []; state.pendingText = ""; state.pendingKnowledge = useKnowledge; state.failure = null; el("message").value = ""; fitComposer(); busy(true); notice(); renderMessages();
  const body = {message}; if (state.active) body.session_id = state.active;
  if (useKnowledge) body.use_m5stack = true;
  try {
    const data = await streamChatTurn(body, (kind, payload) => {
      if (kind === "session") {
        if (payload.session_id) {
          state.active = payload.session_id; remember("atoms3r.active", payload.session_id);
          if (activeTurn) activeTurn.sessionId = payload.session_id;
        }
        if (payload.turn_id && activeTurn) activeTurn.turnId = payload.turn_id;
      } else if (kind === "tool") {
        if (payload.phase === "start") {
          state.pendingSteps.push({ call_id: payload.call_id, tool_name: payload.tool_name, detail: payload.detail || "", status: "running", elapsed_ms: null });
        } else if (payload.phase === "end") {
          const preview = payload.preview_image_url;
          if (payload.tool_name === "desktop_inspect_screen" && typeof preview === "string" &&
              preview.length <= 350 * 1024 && /^data:image\/(jpeg|png|webp);base64,/.test(preview)) {
            lastStepPreview = {callId:payload.call_id, url:preview, open:false};
          }
          const hit = state.pendingSteps.find(s => s.call_id === payload.call_id);
          if (hit) {
            hit.status = payload.status || "ok";
            hit.elapsed_ms = payload.elapsed_ms;
            if (payload.detail) hit.detail = payload.detail;
          } else {
            state.pendingSteps.push({ call_id: payload.call_id, tool_name: payload.tool_name, detail: payload.detail || "", status: payload.status || "ok", elapsed_ms: payload.elapsed_ms });
          }
        }
        renderMessages();
      } else if (kind === "text") {
        state.pendingText = payload.full || "";
        renderMessages();
      }
    }, controller.signal);
    state.active = data.session_id; remember("atoms3r.active", data.session_id);
    if (!state.detail) state.detail = {session_id:data.session_id, title:message.slice(0,40), messages:[]};
    const now = new Date().toISOString();
    state.detail.messages.push({role:"user",content:message,created_at:now}, {role:"assistant",content:data.reply,created_at:now,model:data.model,provider:data.provider,usage:data.usage,estimated_cost:data.estimated_cost,currency:data.currency,finish_reason:data.finish_reason,knowledge:data.knowledge,sources:data.sources,tool_calls:data.tool_calls,pending_approval:data.pending_approval || null});
    state.pending = null; state.pendingSteps = []; state.pendingText = ""; state.failure = null; renderMessages();
    if (state.view === "chat") { el("view-title").textContent = state.detail.title; document.title = `${state.detail.title} · 小圆`; }
    if (data.history_persisted === false) notice("已收到回答，但历史记录未能写入本机；当前对话仅保留在内存。", "error");
    // A sidebar refresh failure must never turn a successful paid call into a retry.
    try { await loadSessions(); } catch { notice("回答已收到；会话列表暂时无法刷新，请刷新页面重试。", "error"); }
  } catch (error) {
    const userStopped = Boolean(activeTurn?.stopping) || error?.name === "AbortError" || error?.code === "turn_cancelled";
    state.pending = null; state.pendingSteps = []; state.pendingText = "";
    if (userStopped) {
      state.failure = null;
      if (state.active) { try { state.detail = await request(`/sessions/${state.active}`); } catch {} }
      renderMessages(); fitComposer(); notice("已停止当前操作。");
    } else {
      state.failure = {message,error:error.message,useKnowledge}; el("message").value = message;
      if (error.code === "session_not_found") notice("这段会话已不存在，请点击“新对话”再发送。", "error");
      renderMessages(); fitComposer();
    }
  } finally { activeTurn = null; busy(false); el("message").focus(); }
}
function configPayload() {
  const draft = connectionPayload();
  for (const id of ["tts_base_url", "tts_api_key", "tts_use_text_connection"]) delete draft[id];
  return {...draft, model:el("model").value.trim(),
    timeout_seconds:savedConfig?.timeout_seconds ?? 30, max_tokens:savedConfig?.max_tokens ?? null,
    currency:savedConfig?.currency ?? "CNY",
    input_price_per_million:savedConfig?.input_price_per_million ?? null,
    output_price_per_million:savedConfig?.output_price_per_million ?? null};
}
function connectionPayload() {
  const result = {};
  for (const id of configIds.filter(id => id !== "model")) result[id] = el(id).value.trim();
  result.m5stack_enabled = el("m5stack_enabled").checked;
  result.tts_provider = el("tts_provider").value;
  result.tts_use_text_connection = !el("tts-separate-service").checked;
  result.asr_provider = el("asr_provider").value;
  result.asr_model = el("asr_model").value.trim() || (result.asr_provider === "bailian" ? "qwen3-asr-flash-realtime" : "whisper-1");
  result.asr_language = el("asr_language").value.trim();
  result.asr_use_text_connection = !el("asr-separate-service").checked;
  if (el("api_key").value.trim()) result.api_key = el("api_key").value.trim();
  if (el("conn_web_search_api_key")?.value.trim()) result.web_search_api_key = el("conn_web_search_api_key").value.trim();
  if (!result.tts_use_text_connection) {
    result.tts_base_url = el("tts_base_url").value.trim();
    if (el("tts_api_key").value.trim()) result.tts_api_key = el("tts_api_key").value.trim();
  }
  if (!result.asr_use_text_connection && result.asr_provider !== "local") {
    result.asr_base_url = el("asr_base_url").value.trim();
    if (el("asr_api_key").value.trim()) result.asr_api_key = el("asr_api_key").value.trim();
  }
  return result;
}
function realtimePayload() {
  const data = Object.fromEntries(["voice_mode","rt_provider","rt_endpoint","rt_workspace","rt_model","rt_voice","rt_asr_model"].map(id => [id,el(id).value.trim()]));
  for (const [id, defaultValue] of Object.entries(realtimeAdvancedDefaults)) {
    const input = el(id);
    data[id] = typeof defaultValue === "boolean" ? input.checked : input.valueAsNumber;
  }
  if (el("rt_api_key").value.trim()) data.rt_api_key = el("rt_api_key").value.trim();
  return data;
}
const DESKTOP_PLANNER_PRESETS = ["", "qwen3.5-plus", "qwen3.5-flash", "qwen3-vl-plus"];
function isNativeVisionModel(modelName) {
  const lowered = (modelName || "").trim().toLowerCase();
  if (!lowered) return false;
  return ["qwen3.5","qwen3-vl","qwen2.5-vl","qwen-vl","qvq","gpt-4o","gpt-4.1","gpt-5","o1","o3","o4","gemini","claude-3","claude-4","kimi-latest"].some(p => lowered.startsWith(p));
}
function desktopModelsPayload() {
  return {
    desktop_planner_model: el("desktop_planner_model").value.trim(),
    desktop_vision_model: el("desktop_vision_model").value.trim(),
  };
}
function syncDesktopPlannerPreset(value) {
  const clean = (value || "").trim();
  el("desktop_planner_model").value = clean;
  const preset = el("desktop-planner-preset");
  if (DESKTOP_PLANNER_PRESETS.includes(clean)) {
    preset.value = clean;
    el("desktop_planner_model").hidden = true;
  } else {
    preset.value = "__manual__";
    el("desktop_planner_model").hidden = false;
  }
}
function resolveDesktopModelState() {
  const rtMode = el("voice_mode").value === "realtime";
  const hasBailianKey = el("rt_provider").value === "bailian" && (Boolean(savedConfig?.rt_key_configured) || Boolean(el("rt_api_key").value.trim()));
  const textModel = el("model").value.trim();
  const hasText = Boolean(textModel && el("base_url").value.trim() && (Boolean(savedConfig?.api_key_configured) || Boolean(el("api_key").value.trim())));
  const planner = el("desktop_planner_model").value.trim();
  const vision = el("desktop_vision_model").value.trim() || "qwen3-vl-plus";
  let effectiveModel = "";
  let routeNote = "";
  if (hasBailianKey && planner && /^(?:qwen|qvq)/i.test(planner) && (!el("base_url").value.toLowerCase().includes("aliyuncs.com") || !hasText || rtMode)) {
    effectiveModel = planner;
    routeNote = "复用百炼 Key";
  } else if (hasBailianKey && !planner && rtMode && (!hasText || !isNativeVisionModel(textModel))) {
    effectiveModel = "qwen3.5-plus";
    routeNote = "自动推荐 · 复用百炼 Key";
  } else if (!rtMode) {
    effectiveModel = planner || textModel || (hasBailianKey ? "qwen3.5-plus" : "");
    routeNote = (!planner && !textModel && hasBailianKey) ? "复用百炼 Key" : (el("provider").value.trim() || "文字服务");
  } else if (hasText) {
    effectiveModel = planner || textModel;
    routeNote = el("provider").value.trim() || "文字服务";
  }
  const direct = Boolean(effectiveModel) && isNativeVisionModel(effectiveModel);
  return {effectiveModel, direct, routeNote, vision, rtMode, hasBailianKey, textModel};
}
function updateModelOverview() {
  const st = resolveDesktopModelState();
  const chatModel = st.rtMode ? (el("rt_model").value.trim() || "qwen3.8-omni-flash-realtime") : (st.textModel || "未配置");
  const chatProvider = st.rtMode ? (el("rt_provider").value === "bailian" ? "阿里云百炼" : "自定义实时") : (el("provider").value.trim() || "文字服务");
  el("overview-chat-model").textContent = chatModel;
  el("overview-chat-meta").textContent = chatProvider;
  el("overview-desktop-model").textContent = st.effectiveModel || "未配置";
  el("overview-desktop-meta").textContent = st.effectiveModel ? st.routeNote.replace("自动推荐 · ", "") : "请先配置服务密钥";
}
function selectedSpeechModel() {
  const picked = el("tts_model").value;
  if (picked === MANUAL) return el("tts_model_custom").value.trim();
  return picked;
}
function selectedSpeechVoice() {
  const picked = el("tts_voice").value;
  if (picked === MANUAL) return el("tts_voice_custom").value.trim();
  return picked;
}
function realtimeScopeKey() {
  return `realtime:${el("rt_provider").value}:${el("rt_model").value.trim()}`;
}
function ttsScopeKey() {
  return `tts:${el("tts_provider").value}:${selectedSpeechModel()}`;
}
function restoreSavedProfileForCurrentTarget(targetKind) {
  if (targetKind === "realtime") {
    const profile = voiceProfiles[realtimeScopeKey()];
    if (profile) {
      if (profile.voice) el("rt_voice").value = profile.voice;
      if (el("voice_mode").value === "realtime") resetTuning({rate: profile.rate, pitch: profile.pitch});
    } else if (el("rt_provider").value === "compatible" && (!el("rt_voice").value || el("rt_voice").value.startsWith("qwen-"))) {
      el("rt_voice").value = "alloy";
    } else if (el("rt_provider").value === "bailian" && !el("rt_voice").value) {
      el("rt_voice").value = "Tina";
    }
    syncRealtimeVoices();
    return;
  }
  const provider = el("tts_provider").value;
  const profile = voiceProfiles[ttsScopeKey()];
  if (profile) {
    setSpeechVoice(profile.voice);
    if (el("voice_mode").value === "pipeline") resetTuning({rate: profile.rate, pitch: profile.pitch});
  } else if (provider === "openai") {
    setSpeechVoice("alloy");
  } else if (provider === "bailian") {
    setSpeechVoice(selectedSpeechModel().startsWith("qwen3-tts-vc-") ? (bailianTtsVoices[0]?.voice || "") : "Cherry");
  } else if (selectedSpeechModel() === CLONE_MODEL) {
    setSpeechVoice(clonedVoices[0]?.id || "");
  } else {
    setSpeechVoice("mimo_default");
  }
  renderVoiceOptions();
}
function confirmVoiceSchemeChange(nextMode, nextRtProvider, nextRtModel, nextTtsProvider, nextTtsModel) {
  if (!savedConfig || !savedTtsConfig) return true;
  const modeChanged = nextMode !== savedConfig.voice_mode;
  const rtChanged = nextMode === "realtime" && (nextRtProvider !== savedConfig.rt_provider || nextRtModel !== savedConfig.rt_model);
  const ttsChanged = nextMode === "pipeline" && (
    nextTtsProvider !== (savedTtsConfig.tts_provider || "mimo")
    || (nextTtsModel !== savedTtsConfig.tts_model
        && (nextTtsModel === CLONE_MODEL || savedTtsConfig.tts_model === CLONE_MODEL
            || nextTtsModel.startsWith("qwen3-tts-vc-") || savedTtsConfig.tts_model.startsWith("qwen3-tts-vc-")))
  );
  if (!modeChanged && !rtChanged && !ttsChanged) return true;
  return confirm(
    "切换语音模式或服务商/模型后，原方案的复刻音色不会自动迁移到新方案（若新方案尚无对应音色，需重新选择或复刻）。\n\n"
    + "原方案已绑定的音色与语速音调均已保留，以后切回可直接恢复。\n\n确认切换并保存吗？"
  );
}
document.querySelectorAll('input[name="voice-route"]').forEach(radio => radio.addEventListener("change", () => {
  stopRealtimeSample();
  el("voice_mode").value = radio.value === "pipeline" ? "pipeline" : "realtime";
  restoreSavedProfileForCurrentTarget(el("voice_mode").value === "realtime" ? "realtime" : "tts");
  updateConnectionMode(); dirty();
}));
el("rt_provider").addEventListener("change", () => {
  stopRealtimeSample(); el("rt_api_key").value = "";
  if (el("rt_provider").value === "compatible" && el("rt_model").value === "qwen3.8-omni-flash-realtime") {
    el("rt_model").value = "gpt-realtime";
  } else if (el("rt_provider").value === "bailian" && ["gpt-realtime", "gpt-4o-realtime-preview"].includes(el("rt_model").value)) {
    el("rt_model").value = "qwen3.8-omni-flash-realtime";
  }
  restoreSavedProfileForCurrentTarget("realtime");
  updateConnectionMode(); dirty();
});
el("rt_model").addEventListener("change", () => { restoreSavedProfileForCurrentTarget("realtime"); dirty(); });
el("asr_provider").addEventListener("change", () => {
  if (el("asr_provider").value === "bailian" && (!el("asr_model").value || el("asr_model").value === "whisper-1")) {
    el("asr_model").value = "qwen3-asr-flash-realtime";
  } else if (el("asr_provider").value === "openai" && el("asr_model").value === "qwen3-asr-flash-realtime") {
    el("asr_model").value = "whisper-1";
  }
  updateConnectionMode(); dirty();
});
el("tts_provider").addEventListener("change", () => {
  const provider = el("tts_provider").value;
  populateSpeechModels(provider);
  if (provider === "openai") setSpeechModel("tts-1");
  else if (provider === "bailian") setSpeechModel("qwen3-tts-flash-realtime");
  else setSpeechModel("mimo-v2.5-tts");
  restoreSavedProfileForCurrentTarget("tts");
  if (provider === "bailian") loadBailianTtsVoices();
  updateConnectionMode(); updateTtsMode(); assistantDirty(); dirty();
});
function fingerprint() { const payload = {...connectionPayload(), ...desktopModelsPayload(), model:el("model").value.trim(),
  tts_provider:el("tts_provider").value, tts_model:selectedSpeechModel(), tts_voice:selectedSpeechVoice()}; Object.assign(payload,realtimePayload()); delete payload.rt_api_key; delete payload.api_key; delete payload.tts_api_key; delete payload.asr_api_key; delete payload.web_search_api_key; return JSON.stringify(payload); }
function dirty() { el("dirty-state").textContent = fingerprint() !== savedFingerprint || el("rt_api_key").value || el("api_key").value || el("tts_api_key").value || el("asr_api_key").value || el("conn_web_search_api_key")?.value ? "有未保存的修改" : ""; }
function voiceChoice() {
  // Only the voice id travels from the page; the server resolves the sample path so a
  // request can never point the clone model at an arbitrary file.
  const provider = el("tts_provider").value;
  const pick = selectedSpeechVoice();
  if (pick) return {tts_voice: pick};
  if (provider === "openai") return {tts_voice: "alloy"};
  if (provider === "bailian") return {tts_voice: "Cherry"};
  return {tts_voice: "mimo_default"};
}
function assistantPayload() {
  const prompt = el("system_prompt").value.trim();
  const profile = el("agent_profile")?.value?.trim() || "";
  const choice = voiceChoice();
  // The role description drives the model's words; the speaking style is a separate,
  // short instruction. Reusing the whole role text here overflowed its length limit and
  // made a long persona break voice preview.
  return {system_prompt:prompt, agent_profile:profile, tts_provider:el("tts_provider").value, tts_model:selectedSpeechModel(), tts_voice:choice.tts_voice,
    tts_rate:Number(el("tts_rate").value), tts_pitch:Number(el("tts_pitch").value),
    tts_instruction:SPEAKING_STYLE, tts_timeout_seconds:savedTtsConfig?.tts_timeout_seconds ?? 60};
}
function assistantDirty() {
  const changed = el("system_prompt").value.trim() !== (savedConfig?.system_prompt || "")
    || (el("agent_profile")?.value?.trim() || "") !== (savedConfig?.agent_profile || "")
    || el("tts_provider").value !== (savedTtsConfig?.tts_provider || "mimo")
    || selectedSpeechModel() !== savedTtsConfig?.tts_model
    || voiceChoice().tts_voice !== savedTtsConfig?.tts_voice
    || Number(el("tts_rate").value) !== Number(savedTtsConfig?.tts_rate ?? 1)
    || Number(el("tts_pitch").value) !== Number(savedTtsConfig?.tts_pitch ?? 0)
    || deviceData && Number(el("device-volume").value) !== deviceData.preferences.volume;
  el("role-dirty-state").textContent = changed ? "有未保存的修改" : "设置已同步";
}
function modelOptionList(models) {
  return [new Option("请选择模型", ""), ...models.map(model => new Option(model, model)), new Option("手动填写模型 ID…", MANUAL)];
}
function resetModelList(message = "") {
  modelsFetched = false; el("model-options").replaceChildren(...modelOptionList([]));
  syncModelOption(); el("models-status").textContent = message; el("models-status").dataset.kind = "";
}
function syncModelOption() {
  const select = el("model-options"), model = el("model").value.trim();
  if (model && !Array.from(select.options).some(option => option.value === model)) select.append(new Option(model, model));
  select.value = model;
  el("model").hidden = true;
}
function populateSpeechModels(provider) {
  const select = el("tts_model");
  const base = provider === "openai" ? OPENAI_TTS_MODELS : provider === "bailian" ? BAILIAN_TTS_MODELS : MIMO_TTS_MODELS;
  const options = [...base, ...speechModels.filter(m => !base.includes(m))];
  select.replaceChildren(...options.map(m => new Option(m, m)), new Option("手动填写模型 ID…", MANUAL));
}
function setSpeechModel(value) {
  const select = el("tts_model");
  const custom = el("tts_model_custom");
  if (!value) return;
  if (Array.from(select.options).some(option => option.value === value && option.value !== MANUAL)) {
    select.value = value;
    custom.hidden = true;
    custom.value = "";
  } else {
    select.value = MANUAL;
    custom.hidden = false;
    custom.value = value;
  }
}
function setSpeechVoice(value) {
  const select = el("tts_voice");
  const custom = el("tts_voice_custom");
  if (!value) return;
  if (Array.from(select.options).some(option => option.value === value && option.value !== MANUAL)) {
    select.value = value;
    custom.hidden = true;
    custom.value = "";
  } else {
    custom.dataset.pendingValue = value;
  }
}
async function loadBailianTtsVoices() {
  try {
    const model = selectedSpeechModel();
    const data = await request(`/api/voices/qwen?target_model=${encodeURIComponent(model || "qwen3-tts-vc-realtime")}`);
    bailianTtsVoices = Array.isArray(data.voices) ? data.voices : [];
  } catch {
    bailianTtsVoices = [];
  }
  renderVoiceOptions();
}
function renderVoiceOptions() {
  // Presets and cloned voices live in the same control but never mix: the provider & model decide.
  const select = el("tts_voice");
  const custom = el("tts_voice_custom");
  const provider = el("tts_provider").value;
  const model = selectedSpeechModel();
  const previous = custom.dataset.pendingValue || (select.value === MANUAL ? custom.value : select.value);
  delete custom.dataset.pendingValue;
  if (provider === "mimo" && model === CLONE_MODEL) {
    if (!clonedVoices.length) {
      select.replaceChildren(new Option("还没有克隆的声音", ""));
      el("delete-clone").hidden = true;
    } else {
      select.replaceChildren(...clonedVoices.map(v => new Option(`${v.name}（${v.kb}KB）`, v.id)));
      if (clonedVoices.some(v => v.id === previous)) select.value = previous;
      el("delete-clone").hidden = !select.value;
    }
    custom.hidden = true;
    el("clone-new").hidden = false;
  } else if (provider === "openai") {
    select.replaceChildren(...OPENAI_TTS_VOICES.map(v => new Option(v, v)), new Option("自定义音色 ID…", MANUAL));
    if (previous && !OPENAI_TTS_VOICES.includes(previous)) {
      select.value = MANUAL; custom.hidden = false; custom.value = previous;
    } else {
      if (previous) select.value = previous;
      custom.hidden = true;
    }
    el("clone-new").hidden = true;
    el("delete-clone").hidden = true;
  } else if (provider === "bailian") {
    if (model.startsWith("qwen3-tts-vc-")) {
      const opts = bailianTtsVoices.map(v => new Option(`${v.name}（百炼复刻）`, v.voice));
      select.replaceChildren(...(opts.length ? opts : [new Option("填入或复刻音色 ID", "")]), new Option("自定义音色 ID…", MANUAL));
      if (previous && bailianTtsVoices.some(v => v.voice === previous)) {
        select.value = previous; custom.hidden = true;
      } else if (previous) {
        select.value = MANUAL; custom.hidden = false; custom.value = previous;
      } else {
        custom.hidden = select.value !== MANUAL;
      }
      el("clone-new").hidden = true;
      el("delete-clone").hidden = true;
    } else {
      select.replaceChildren(...BAILIAN_TTS_VOICES.map(v => new Option(v, v)), new Option("自定义音色 ID…", MANUAL));
      if (previous && !BAILIAN_TTS_VOICES.includes(previous)) {
        select.value = MANUAL; custom.hidden = false; custom.value = previous;
      } else {
        if (previous) select.value = previous;
        custom.hidden = true;
      }
      el("clone-new").hidden = true;
      el("delete-clone").hidden = true;
    }
  } else {
    select.replaceChildren(...PRESET_VOICES.map(v => new Option(v === "mimo_default" ? "默认" : v, v)));
    if (PRESET_VOICES.includes(previous)) select.value = previous;
    custom.hidden = true;
    el("clone-new").hidden = true;
    el("delete-clone").hidden = true;
  }
  el("tts_voice").hidden = provider === "mimo" && model === VOICEDESIGN_MODEL;
  if (el("tts_voice").hidden) custom.hidden = true;
}
async function loadVoices() {
  try {
    const response = await appFetch("/api/voices", {headers:{"X-Local-Settings":"1"}});
    if (!response.ok) return;
    const data = await response.json();
    clonedVoices = Array.isArray(data.cloned) ? data.cloned : [];
    renderVoiceOptions();
  } catch (error) { /* keeping the current list is better than clearing it */ }
}
function applyTuning() {
  const rate = Number(el("tts_rate").value);
  const pitch = Number(el("tts_pitch").value);
  el("tts_rate-value").textContent = `${rate.toFixed(2)}x`;
  el("tts_pitch-value").textContent = pitch > 0 ? `+${pitch}` : `${pitch}`;
  const volume = el("device-volume");
  if (volume) el("device-volume-value").textContent = `${volume.value}`;
}
function resetTuning(values = {}) {
  el("tts_rate").value = values.rate ?? 1;
  el("tts_pitch").value = values.pitch ?? 0;
  applyTuning();
}
function renderConnectionStatus() {
  const connected = savedConfig?.api_key_configured;
  el("connection-summary").textContent = connected ? "已接入" : "未配置";
  el("speech-api-state").textContent = savedTtsConfig?.api_key_configured ? "已接入" : "未配置";
  el("asr-api-state").textContent = savedConfig?.asr_provider === "local" ? "本地识别" : (savedConfig?.asr_key_configured ? "已接入" : "未配置");
  const missing = [];
  if (savedConfig?.voice_mode !== "realtime" && !savedConfig?.api_key_configured) missing.push("文字");
  if (savedConfig?.voice_mode === "realtime" ? !savedConfig.rt_key_configured : !savedTtsConfig?.api_key_configured) missing.push("语音");
  if (savedConfig?.voice_mode !== "realtime" && savedConfig?.asr_provider !== "local" && !savedConfig?.asr_key_configured) missing.push("识别");
  let hint;
  if (missing.length) hint = `${missing.join("、")}服务尚未接入，请到「API接入」填写`;
  else hint = savedConfig.voice_mode === "realtime" ? savedConfig.rt_model : `${savedConfig.model || "未选择"} · ${savedTtsConfig.tts_model}`;
  document.querySelectorAll(".model-hint").forEach(node => { node.textContent = hint; });
}
function renderAckCache() {
  const count = savedConfig?.rt_ack_cached_count || 0;
  el("rt-ack-status").textContent = count
    ? (savedConfig.rt_ack_cached_voice + " · 已缓存 " + count + " 条") : "当前音色暂无首响缓存";
  el("rt-ack-generate").disabled = ackGenerationBusy ||
    savedConfig?.rt_provider !== "bailian" || !savedConfig?.rt_key_configured;
}
el("rt-ack-generate").addEventListener("click", async () => {
  if (ackGenerationBusy || !confirm("用已保存的百炼音色生成首响？费用以百炼账单为准。")) return;
  ackGenerationBusy = true;
  renderAckCache();
  notice("正在生成首响语音…");
  try {
    const result = await request("/api/voice/ack/generate", "POST", {});
    if (savedConfig?.rt_provider === "bailian" && savedConfig.rt_voice === result.voice) {
      savedConfig.rt_ack_cached_voice = result.voice;
      savedConfig.rt_ack_cached_count = result.count;
    }
    notice("已生成 " + result.count + " 条首响语音。", "success");
  } catch (error) { notice(error.message, "error"); }
  finally { ackGenerationBusy = false; renderAckCache(); }
});
function applyConfig(data, preserve = false) {
  if (data.voice_profiles) voiceProfiles = data.voice_profiles;
  for (const id of ["voice_mode","rt_provider","rt_endpoint","rt_workspace","rt_model","rt_voice","rt_asr_model","asr_provider","asr_model","asr_language"]) el(id).value = data[id] ?? "";
  for (const [id, defaultValue] of Object.entries(realtimeAdvancedDefaults)) {
    if (typeof defaultValue === "boolean") el(id).checked = data[id] ?? defaultValue;
    else el(id).value = data[id] ?? defaultValue;
  }
  el("asr_base_url").value = data.asr_base_url || "";
  el("asr_api_key").value = ""; el("asr_api_key").type = "password";
  el("asr-show-key").textContent = "显示"; el("asr-show-key").setAttribute("aria-pressed", "false");
  el("asr_api_key").placeholder = data.asr_separate_key_configured ? "已保存，留空保留" : "输入识别服务密钥";
  el("asr-separate-service").checked = !data.asr_use_text_connection;
  el("rt-fields").hidden = data.voice_mode !== "realtime";
  el("rt_api_key").value = ""; el("rt_api_key").placeholder = data.rt_key_configured ? "已保存，留空保留" : "输入百炼 API Key";
  const model = el("model").value;
  if (!preserve) {
    el("system_prompt").value = data.system_prompt;
    if (el("agent_profile")) el("agent_profile").value = data.agent_profile || "";
  }
  savedConfig = data; state.configured = data.configured;
  renderAckCache();
  renderWebSearchConnectionState();
  applyWeatherSettings(data);
  syncDesktopPlannerPreset(data.desktop_planner_model || "");
  el("desktop_vision_model").value = data.desktop_vision_model || "";
  capabilityState.selectionSupported = Array.isArray(data.selected_tool_ids) || Array.isArray(data.selected_kb_ids);
  capabilityState.selectedTools = Array.isArray(data.selected_tool_ids) ? data.selected_tool_ids.slice() : [];
  capabilityState.selectedKbs = Array.isArray(data.selected_kb_ids) ? data.selected_kb_ids.slice() : [];
  updateConnectionMode();
  state.m5stackEnabled = data.m5stack_enabled !== false; el("m5stack_enabled").checked = state.m5stackEnabled;
  if (!state.m5stackEnabled) state.useKnowledge = false;
  for (const id of configIds) el(id).value = data[id] ?? "";
  if (preserve) el("model").value = model;
  el("api_key").value = ""; el("api_key").type = "password"; el("show-key").textContent = "显示"; el("show-key").setAttribute("aria-pressed", "false");
  el("api_key").placeholder = data.api_key_configured ? "已保存，留空保留" : "输入文字服务密钥";
  if (el("conn_web_search_api_key")) el("conn_web_search_api_key").value = "";
  el("model-label").textContent = data.active_model || data.model || "未选择模型";
  syncModelOption(); renderConnectionStatus(); refreshControls();
}
function usageText(data) {
  const usage = data.usage;
  return `输入 ${usage?.prompt_tokens ?? "未知"} · 输出 ${usage?.completion_tokens ?? "未知"} · 合计 ${usage?.total_tokens ?? "未知"} Token\n估算费用：${data.estimated_cost === null ? "未知（未配置价格或用量缺失）" : `${data.estimated_cost} ${data.currency}`}`;
}
function ttsPayload() {
  const {tts_provider, tts_model, tts_voice, tts_instruction, tts_rate, tts_pitch} = assistantPayload();
  return {tts_provider, tts_base_url: savedTtsConfig?.tts_base_url || savedConfig?.base_url || "",
    tts_model, tts_voice, tts_instruction, tts_rate, tts_pitch,
    tts_timeout_seconds:savedTtsConfig?.tts_timeout_seconds ?? 60};
}
function updateTtsMode() {
  const design = el("tts_provider").value === "mimo" && selectedSpeechModel() === "mimo-v2.5-tts-voicedesign";
  el("tts_voice").hidden = design;
  if (design) el("tts_voice_custom").hidden = true;
}
function clearTtsAudio() {
  el("tts-audio").pause(); el("tts-audio").removeAttribute("src"); el("tts-audio").load(); el("tts-audio").hidden = true;
  if (ttsAudioUrl) URL.revokeObjectURL(ttsAudioUrl);
  ttsAudioUrl = null;
}
function stopTtsPreview() { ttsController?.abort(); clearTtsAudio(); }
function applyTtsConfig(data, preserve = false) {
  savedTtsConfig = data;
  if (data.voice_profiles) voiceProfiles = data.voice_profiles;
  const provider = data.tts_provider || "mimo";
  if (!preserve) {
    el("tts_provider").value = provider;
    populateSpeechModels(provider);
    setSpeechModel(data.tts_model);
    setSpeechVoice(data.tts_voice);
  }
  renderVoiceOptions();
  if (!preserve && provider === "mimo" && data.tts_model === CLONE_MODEL) {
    const saved = data.tts_voice || "";
    if (clonedVoices.some(v => v.id === saved)) el("tts_voice").value = saved;
  }
  if (!preserve) resetTuning({rate:data.tts_rate, pitch:data.tts_pitch});
  el("tts_base_url").value = data.tts_base_url || "";
  el("tts_api_key").value = ""; el("tts_api_key").type = "password";
  el("tts_api_key").placeholder = data.separate_api_key_configured ? "已保存，留空保留" : "输入语音服务密钥";
  el("tts-separate-service").checked = !data.use_text_connection;
  updateConnectionMode();
  el("tts-show-key").textContent = "显示"; el("tts-show-key").setAttribute("aria-pressed", "false");
  updateTtsMode(); assistantDirty(); renderConnectionStatus(); savedFingerprint = fingerprint(); dirty();
  if (!preserve && provider === "bailian") loadBailianTtsVoices();
}
function stopRealtimeSample() {
  realtimePreviewController?.abort();
  realtimePreviewController = null;
  if (realtimeSampleUrl) URL.revokeObjectURL(realtimeSampleUrl);
  realtimeSampleUrl = null;
  const audio = el("rt-sample");
  audio.pause(); audio.removeAttribute("src"); audio.load();
  el("rt-sample-button").textContent = "试听";
  el("rt-sample-error").hidden = true;
}
async function loadQwenVoices() {
  try {
    const data = await request("/api/voices/qwen");
    qwenVoices = Array.isArray(data.voices) ? data.voices : [];
  } catch (error) {
    qwenVoices = [];
  }
  syncRealtimeVoices();
}
function syncRealtimeVoices() {
  const picker = el("rt-voice-picker"), field = el("rt_voice");
  const system = el("rt_provider").value === "bailian" && el("rt_model").value.trim() === "qwen3.8-omni-flash-realtime";
  picker.hidden = !system; field.hidden = system;
  el("rt-voice-label").htmlFor = system ? picker.id : field.id;
  el("rt-sample-button").hidden = !system;
  el("rt-clone-button").hidden = !system;
  el("rt-delete-clone").hidden = !system;
  if (!system) return;
  picker.querySelectorAll("[data-qwen-clone]").forEach(option => option.remove());
  for (const voice of qwenVoices) {
    const option = new Option(`${voice.name}（复刻）`, voice.voice);
    option.dataset.qwenClone = "1";
    picker.add(option);
  }
  const previous = picker.querySelector("[data-unlisted]");
  if (previous && previous.value !== field.value) previous.remove();
  picker.value = field.value;
  if (field.value && !picker.value) {
    const current = new Option(field.value === "longanlingxin" ? "龙安灵心" : "当前自定义音色",field.value);
    current.dataset.unlisted = "1"; picker.add(current); picker.value = field.value;
  }
  const selected = picker.selectedOptions[0];
  el("rt-sample-button").disabled = !selected?.dataset.sample && !selected?.dataset.qwenClone;
  el("rt-delete-clone").hidden = !selected?.dataset.qwenClone;
}
el("rt-voice-picker").addEventListener("input", () => {
  stopRealtimeSample(); el("rt_voice").value = el("rt-voice-picker").value;
  const selected = el("rt-voice-picker").selectedOptions[0];
  el("rt-delete-clone").hidden = !selected?.dataset.qwenClone;
  dirty();
});
for (const id of ["rt_model","rt_provider"]) el(id).addEventListener("input",stopRealtimeSample);
el("rt-sample-button").addEventListener("click", async () => {
  const audio = el("rt-sample"), button = el("rt-sample-button");
  if (audio.hasAttribute("src")) { stopRealtimeSample(); return; }
  const option = el("rt-voice-picker").selectedOptions[0];
  if (!option) return;
  button.disabled = true; button.textContent = "加载中…"; el("rt-sample-error").hidden = true;
  try {
    if (option.dataset.sample) {
      audio.src = option.dataset.sample;
    } else {
      realtimePreviewController = new AbortController();
      const response = await appFetch("/api/voices/qwen/preview", {
        method:"POST", signal:realtimePreviewController.signal,
        headers:{"Content-Type":"application/json","X-Local-Settings":"1"},
        body:JSON.stringify({voice:option.value}),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail?.message || "试听生成失败。");
      }
      realtimeSampleUrl = URL.createObjectURL(await response.blob());
      audio.src = realtimeSampleUrl;
    }
    realtimePreviewController = null; button.disabled = false; button.textContent = "停止";
    await audio.play();
  } catch (error) {
    if (error.name === "AbortError") return;
    stopRealtimeSample();
    el("rt-sample-error").textContent = error.message || "样音未能播放，请重试。";
    el("rt-sample-error").hidden = false;
  } finally {
    if (!audio.hasAttribute("src")) button.disabled = false;
  }
});
el("rt-sample").addEventListener("ended",stopRealtimeSample);
el("rt-clone-button").addEventListener("click", () => {
  el("qwen-clone-status").textContent = "";
  el("qwen-clone-name").value = "";
  el("qwen-clone-file").value = "";
  el("qwen-clone-dialog").showModal();
  el("qwen-clone-name").focus();
});
el("qwen-clone-cancel").addEventListener("click", () => el("qwen-clone-dialog").close());
el("qwen-clone-form").addEventListener("submit", async event => {
  event.preventDefault();
  const file = el("qwen-clone-file").files[0];
  const name = el("qwen-clone-name").value.trim();
  if (!file || !name) return;
  if (file.size > 10 * 1024 * 1024) {
    el("qwen-clone-status").textContent = "音频不能超过 10MB。";
    return;
  }
  const submit = el("qwen-clone-submit");
  submit.disabled = true;
  el("qwen-clone-status").textContent = "正在上传并复刻，通常需要几秒…";
  try {
    const response = await appFetch("/api/voices/qwen", {
      method:"POST",
      headers:{"Content-Type":"application/octet-stream","X-Local-Settings":"1",
        "X-Voice-Name":encodeURIComponent(name),"X-Voice-Filename":encodeURIComponent(file.name)},
      body:await file.arrayBuffer(),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.detail?.message || "音色复刻失败。");
    await loadQwenVoices();
    el("rt_voice").value = data.voice;
    syncRealtimeVoices();
    el("rt-voice-picker").value = data.voice;
    el("qwen-clone-dialog").close();
    dirty();
    notice(`已生成「${data.name}」，点试听确认后保存。`, "success");
  } catch (error) {
    el("qwen-clone-status").textContent = error.message;
    el("qwen-clone-status").dataset.kind = "error";
  } finally {
    submit.disabled = false;
  }
});
el("rt-delete-clone").addEventListener("click", async () => {
  const option = el("rt-voice-picker").selectedOptions[0];
  if (!option?.dataset.qwenClone || !confirm(`删除复刻音色「${option.textContent}」？`)) return;
  try {
    await request(`/api/voices/qwen/${encodeURIComponent(option.value)}`, "DELETE");
    el("rt_voice").value = "Tina";
    await loadQwenVoices();
    syncRealtimeVoices();
    dirty();
    notice("已删除复刻音色。", "success");
  } catch (error) {
    el("rt-sample-error").textContent = error.message;
    el("rt-sample-error").hidden = false;
  }
});
function updateConnectionMode() {
  syncRealtimeVoices();
  const rt = el("voice_mode").value === "realtime";
  const custom = el("rt_provider").value === "compatible";
  const route = rt ? "realtime" : "pipeline";
  document.querySelectorAll('input[name="voice-route"]').forEach(radio => { radio.checked = radio.value === route; });
  el("rt-service-name").textContent = custom ? "Omni 兼容接口" : "阿里云百炼";
  el("rt-region").hidden = custom;
  const saved = savedConfig?.rt_key_configured && savedConfig.rt_provider === el("rt_provider").value &&
    (custom ? savedConfig.rt_endpoint === el("rt_endpoint").value.trim() : savedConfig.rt_workspace === el("rt_workspace").value.trim());
  el("rt-key-state").textContent = el("rt_api_key").value ? "待保存" : saved ? "已保存" : "";
  el("rt_api_key").placeholder = saved ? "••••••••" : "输入 API Key";
  el("text-services").hidden = rt;
  for (const control of el("text-services").querySelectorAll("input,select")) control.disabled = rt;
  el("rt-fields").hidden = !rt;
  el("rt-custom-row").hidden = el("rt_provider").value !== "compatible";
  el("rt-workspace-row").hidden = !el("rt-custom-row").hidden;
  const asrLocal = el("asr_provider").value === "local";
  el("asr-model-row").hidden = asrLocal;
  el("asr-lang-row").hidden = asrLocal;
  el("asr-separate-choice").hidden = asrLocal;
  const asrSeparate = !rt && !asrLocal && el("asr-separate-service").checked;
  el("asr-separate-fields").hidden = !asrSeparate;
  el("asr-shared-note").hidden = asrSeparate || asrLocal;
  for (const id of ["asr_base_url", "asr_api_key", "asr-show-key"]) el(id).disabled = !asrSeparate;
  const ttsBailian = el("tts_provider").value === "bailian";
  el("tts-separate-service").closest(".api-service-choice").hidden = rt || ttsBailian;
  const separate = !rt && !ttsBailian && el("tts-separate-service").checked;
  el("tts-separate-fields").hidden = !separate; el("shared-service-note").hidden = separate;
  for (const id of ["tts_base_url", "tts_api_key", "tts-show-key"]) el(id).disabled = !separate;
  updateModelOverview();
}
el("asr-show-key").addEventListener("click", () => {
  const show = el("asr_api_key").type === "password"; el("asr_api_key").type = show ? "text" : "password";
  el("asr-show-key").textContent = show ? "隐藏" : "显示"; el("asr-show-key").setAttribute("aria-pressed", String(show));
});
el("tts-show-key").addEventListener("click", () => {
  const show = el("tts_api_key").type === "password"; el("tts_api_key").type = show ? "text" : "password";
  el("tts-show-key").textContent = show ? "隐藏" : "显示"; el("tts-show-key").setAttribute("aria-pressed", String(show));
});
el("assistant-form").addEventListener("input", event => {
  updateTtsMode(); clearTtsAudio(); notice(); el("tts-result").textContent = ""; el("test-panel").hidden = true;
  assistantDirty();
});
el("tts-text").addEventListener("input", () => { clearTtsAudio(); el("tts-result").textContent = ""; });
function closeSettings() {
  stopTtsPreview();
  if (savedConfig) applyConfig(savedConfig);
  if (savedTtsConfig) applyTtsConfig(savedTtsConfig);
  el("tts-result").textContent = ""; el("test-panel").hidden = true;
  el("api-workbench").hidden = true; el("tool-key").value = ""; el("tool-editor").hidden = true; notice();
  navigate("chat");
  el(matchMedia("(max-width:700px)").matches ? "model-button" : "settings-button").focus();
}
el("assistant-reset").addEventListener("click", closeSettings);
el("settings-close").addEventListener("click", closeSettings);
el("settings-api-cancel").addEventListener("click", closeSettings);
el("assistant-form").addEventListener("invalid", event => {
  if (event.target.id === "system_prompt" && state.view !== "role") navigate("role");
}, true);
el("assistant-form").addEventListener("submit", async event => {
  event.preventDefault(); if (ttsBusy || state.busy) return;
  if (!confirmVoiceSchemeChange(el("voice_mode").value, el("rt_provider").value, el("rt_model").value.trim(), el("tts_provider").value, selectedSpeechModel())) return;
  ttsBusy = true; refreshControls();
  try {
    const data = await request("/api/settings/assistant", "PUT", {...assistantPayload(), model:savedConfig.model});
    savedConfig = data.text; savedTtsConfig = data.tts; state.configured = data.text.configured;
    if (data.text.voice_profiles) voiceProfiles = data.text.voice_profiles;
    // Volume belongs to the device record, so it is saved separately from the voice config.
    const volume = Number(el("device-volume").value);
    if (!deviceData) await loadDevices();
    if (volume !== deviceData.preferences.volume) {
      const saved = await request("/api/devices/preferences", "PUT",
        {...deviceData.preferences, volume});
      deviceData = saved;
    }
    el("model-label").textContent = data.text.active_model || data.text.model || "未选择模型"; assistantDirty(); clearTtsAudio(); el("tts-result").textContent = "";
    closeSettings(); notice("角色与声音已保存，下次回答生效。", "success");
  } catch (error) { notice(error.message, "error"); }
  finally { ttsBusy = false; refreshControls(); }
});
el("tts-preview").addEventListener("click", async () => {
  if (ttsBusy || state.busy || !el("assistant-form").reportValidity()) return;
  if (!el("tts-text").value.trim()) { el("tts-result").textContent = "请输入试听文字。"; return; }
  clearTtsAudio(); const controller = new AbortController(); ttsController = controller; ttsBusy = true;
  el("tts-cancel").hidden = false; el("tts-preview").textContent = "正在合成…";
  el("tts-result").textContent = "正在使用草稿合成，未保存配置…"; el("tts-result").dataset.kind = ""; refreshControls();
  try {
    const realtime = savedConfig.voice_mode === "realtime";
    const blob = await request(realtime ? "/api/voices/qwen/preview" : "/api/settings/tts/preview", "POST",
      realtime ? {voice:savedConfig.rt_voice, text:el("tts-text").value.trim().slice(0,80),
        rate:Number(el("tts_rate").value), pitch:Number(el("tts_pitch").value)}
      : {config:ttsPayload(), text:el("tts-text").value.trim()}, controller.signal);
    if (controller.signal.aborted || state.view !== "role") return;
    ttsAudioUrl = URL.createObjectURL(blob); el("tts-audio").src = ttsAudioUrl; el("tts-audio").hidden = false;
    el("tts-result").textContent = "合成成功，点击播放试听。草稿未保存。";
  } catch (error) {
    el("tts-result").textContent = error.name === "AbortError" ? "已取消试听；供应商可能仍处理或计费，不会自动重试。" : error.message;
    el("tts-result").dataset.kind = error.name === "AbortError" ? "" : "error";
  } finally {
    ttsController = null; ttsBusy = false; el("tts-cancel").hidden = true; el("tts-preview").textContent = "试听"; refreshControls();
  }
});
el("tts-cancel").addEventListener("click", stopTtsPreview);
// Model selection swaps the voice list between presets and cloned voices.
el("tts_model").addEventListener("change", () => {
  el("tts_model_custom").hidden = el("tts_model").value !== MANUAL;
  if (el("tts_model").value === MANUAL) el("tts_model_custom").focus();
  restoreSavedProfileForCurrentTarget("tts");
  assistantDirty(); dirty();
});
el("tts_model_custom").addEventListener("input", () => {
  renderVoiceOptions(); assistantDirty(); dirty();
});
el("tts_voice").addEventListener("change", () => {
  el("tts_voice_custom").hidden = el("tts_voice").value !== MANUAL;
  if (el("tts_voice").value === MANUAL) el("tts_voice_custom").focus();
  el("delete-clone").hidden = el("tts_provider").value !== "mimo" || selectedSpeechModel() !== CLONE_MODEL || !el("tts_voice").value;
  assistantDirty(); dirty();
});
el("tts_voice_custom").addEventListener("input", () => { assistantDirty(); dirty(); });
["tts_rate", "tts_pitch"].forEach(id => el(id).addEventListener("input", () => { applyTuning(); assistantDirty(); }));
el("device-volume").addEventListener("input", () => {applyTuning(); assistantDirty(); el("volume-status").textContent = "";});
el("tuning-reset").addEventListener("click", () => {resetTuning(); assistantDirty();});
el("volume-apply").addEventListener("click", async () => {
  const button = el("volume-apply"), status = el("volume-status");
  button.disabled = true; status.textContent = "正在应用…";
  const volume = Number(el("device-volume").value);
  try {
    await loadDevices();
    deviceData = await request("/api/devices/preferences", "PUT", {...deviceData.preferences, volume});
    const result = await request("/api/devices/volume/apply", "POST");
    status.textContent = result.verified ? "设备已生效" : "设备已确认";
  } catch (error) {status.textContent = error.message;}
  finally {button.disabled = false; assistantDirty();}
});
el("clone-new").addEventListener("click", () => {
  el("clone-status").textContent = ""; el("clone-status").dataset.kind = "";
  el("clone-name").value = ""; el("clone-file").value = "";
  el("clone-dialog").showModal(); el("clone-name").focus();
});
el("clone-cancel").addEventListener("click", () => el("clone-dialog").close());
el("clone-form").addEventListener("submit", async event => {
  event.preventDefault();
  const file = el("clone-file").files[0];
  const name = el("clone-name").value.trim();
  if (!file || !name) { el("clone-status").textContent = "请填写名字并选择音频文件。"; return; }
  if (file.size > 10 * 1024 * 1024) { el("clone-status").textContent = "音频不能超过 10MB。"; return; }
  const submit = el("clone-submit");
  submit.disabled = true; el("clone-status").textContent = "正在处理音频…"; el("clone-status").dataset.kind = "";
  try {
    const response = await appFetch("/api/voices", {
      method: "POST",
      headers: {"X-Local-Settings":"1", "X-Voice-Name":encodeURIComponent(name), "X-Voice-Filename":encodeURIComponent(file.name), "Content-Type":"application/octet-stream"},
      body: await file.arrayBuffer(),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.detail?.message || "克隆失败。");
    el("clone-status").textContent = `已生成「${data.name}」，样本 ${data.kb}KB。可以在音色里选中并试听。`;
    await loadVoices();
    el("tts_provider").value = "mimo";
    populateSpeechModels("mimo");
    setSpeechModel(CLONE_MODEL);
    renderVoiceOptions();
    el("tts_voice").value = data.id;
    el("delete-clone").hidden = false;
    assistantDirty();
    setTimeout(() => { if (el("clone-dialog").open) el("clone-dialog").close(); }, 1200);
  } catch (error) {
    el("clone-status").textContent = error.message; el("clone-status").dataset.kind = "error";
  } finally { submit.disabled = false; }
});
el("delete-clone").addEventListener("click", async () => {
  const id = selectedSpeechVoice();
  if (el("tts_provider").value !== "mimo" || selectedSpeechModel() !== CLONE_MODEL || !id) return;
  if (!confirm("删除这个克隆的声音？已保存的参考音频也会被移除。")) return;
  try {
    await request(`/api/voices/${encodeURIComponent(id)}`, "DELETE");
    await loadVoices(); assistantDirty(); notice("已删除该声音。", "success");
  } catch (error) { notice(error.message, "error"); }
});
el("tts-audio").addEventListener("error", () => {
  if (ttsAudioUrl) { el("tts-result").textContent = "浏览器无法播放返回的音频；请核对语音服务格式。"; el("tts-result").dataset.kind = "error"; }
});
window.addEventListener("pagehide", stopTtsPreview);
document.querySelectorAll("[data-view]").forEach(link => link.addEventListener("click", event => { event.preventDefault(); navigate(link.dataset.view); }));
el("new-session").addEventListener("click", newConversation);
el("session-search").addEventListener("input", () => {
  clearTimeout(sessionSearchTimer); sessionController?.abort(); ++sessionLoadId;
  state.sessions = []; sessionOffset = 0; sessionHasMore = false; sessionLoading = true; sessionError = ""; renderSessions();
  sessionSearchTimer = setTimeout(() => loadSessions().catch(() => {}),250);
});
el("open-sidebar").addEventListener("click", openSidebar);
el("collapse-sidebar").addEventListener("click", () => { closeSidebar(); document.body.classList.add("sidebar-collapsed"); el("open-sidebar").focus(); });
el("sidebar-overlay").addEventListener("click", closeSidebar);
el("message").addEventListener("input", fitComposer);
el("message").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendMessage(el("message").value); } });
el("chat-form").addEventListener("submit", event => { event.preventDefault(); sendMessage(el("message").value); });
el("stop-turn").addEventListener("click", () => { stopActiveTurn(); });
document.querySelectorAll("#empty-state [data-prompt]").forEach(button => button.addEventListener("click", () => {
  if (state.busy) return;
  el("message").value = button.dataset.prompt;
  fitComposer();
  el("message").focus();
  if (state.configured) sendMessage(el("message").value);
  else notice("请先在「模型与连接」完成配置，再发送消息。");
}));
for (const id of ["model-button", "configure-link"]) el(id).addEventListener("click", () => navigate("connections"));
el("desktop-planner-preset").addEventListener("change", () => {
  const picked = el("desktop-planner-preset").value;
  if (picked === "__manual__") {
    el("desktop_planner_model").hidden = false;
    if (DESKTOP_PLANNER_PRESETS.includes(el("desktop_planner_model").value.trim())) el("desktop_planner_model").value = "";
    el("desktop_planner_model").focus();
  } else {
    el("desktop_planner_model").value = picked;
    el("desktop_planner_model").hidden = true;
  }
  updateModelOverview(); dirty(); notice();
});
el("show-key").addEventListener("click", () => { const show = el("api_key").type === "password"; el("api_key").type = show ? "text" : "password"; el("show-key").textContent = show ? "隐藏" : "显示"; el("show-key").setAttribute("aria-pressed", String(show)); });
el("config-form").addEventListener("input", event => { updateConnectionMode(); updateTtsMode(); stopTtsPreview(); el("test-panel").hidden = true; if (["base_url", "api_key", "models_protocol"].includes(event.target.id)) { resetModelList(); } dirty(); notice(); });
el("model-options").addEventListener("change", () => {
  const value = el("model-options").value;
  if (value === MANUAL) { el("model").value = ""; el("model").hidden = false; el("model").focus(); }
  else { el("model").value = value; el("model").hidden = true; }
  updateModelOverview(); dirty(); notice(); el("test-panel").hidden = true;
});
async function refreshModelChoices() {
  if (state.busy || !state.loaded || !savedConfig) return;
  modelsFetched = true; busy(true); el("models-status").textContent = "正在获取模型…";
  try {
    const data = await request("/api/settings/models", "POST", {...configPayload(), model:""});
    speechModels = data.speech_models || [];
    el("model-options").replaceChildren(...modelOptionList(data.models || []));
    syncModelOption();
    if (speechModels.length) renderSpeechOptions(speechModels);
    el("models-status").textContent = ""; el("models-status").dataset.kind = "";
  } catch (error) { syncModelOption(); el("models-status").textContent = error.message; el("models-status").dataset.kind = "error"; }
  finally { busy(false); }
}
function renderSpeechOptions(models) {
  const current = selectedSpeechModel();
  populateSpeechModels(el("tts_provider").value);
  setSpeechModel(current);
}
async function refreshSpeechModels(silent = false) {
  if (state.busy || !state.loaded || !savedConfig) return;
  busy(true); if (!silent) { el("tts-result").textContent = "正在获取声音模型…"; el("tts-result").dataset.kind = ""; }
  try {
    const data = await request("/api/settings/models", "POST", {...configPayload(), model:""});
    speechModels = data.speech_models || [];
    renderSpeechOptions(speechModels);
    el("tts-result").textContent = speechModels.length || silent ? "" : "该服务没有返回可用的声音模型，可继续使用当前值。";
    el("tts-result").dataset.kind = "";
    assistantDirty();
  } catch (error) {
    if (!silent) { el("tts-result").textContent = error.message; el("tts-result").dataset.kind = "error"; }
  }
  finally { busy(false); }
}
el("fetch-models").addEventListener("click", refreshModelChoices);
el("fetch-speech-models").addEventListener("click", () => refreshSpeechModels());
el("config-form").addEventListener("submit", async event => {
  event.preventDefault(); if (state.busy || ttsBusy) return;
  const rt = realtimePayload();
  const speechModel = selectedSpeechModel();
  if (!confirmVoiceSchemeChange(rt.voice_mode, rt.rt_provider, rt.rt_model, el("tts_provider").value, speechModel)) return;
  for (const [id, defaultValue] of Object.entries(realtimeAdvancedDefaults)) {
    if (rt[id] === (savedConfig?.[id] ?? defaultValue)) delete rt[id];
  }
  busy(true);
  try {
    const data = await request("/api/settings/api", "PUT", {...connectionPayload(), ...rt, ...desktopModelsPayload(),
      model:el("model").value.trim(), tts_model:speechModel, tts_voice:voiceChoice().tts_voice});
    applyConfig(data.text, true); applyTtsConfig(data.tts, true); stopTtsPreview(); el("test-panel").hidden = true;
    closeSettings(); notice("配置已保存。", "success");
  } catch (error) { notice(error.message, "error"); } finally { busy(false); }
});
el("test").addEventListener("click", async () => {
  if (state.busy || ttsBusy || !el("base_url").reportValidity()) return;
  if (!el("model").value.trim()) { if (!state.busy) notice("请先选择对话模型。", "error"); return; }
  busy(true); el("test-panel").hidden = false; el("test-result").textContent = "正在测试所选模型…"; el("test-usage").textContent = "";
  try {
    const data = await request("/api/settings/test", "POST", configPayload());
    el("test-result").textContent = data.reply; el("test-usage").textContent = usageText(data); notice("模型调用成功；本次测试不会保存设置。", "success");
  } catch (error) { el("test-result").textContent = error.message; notice(error.message, "error"); } finally { busy(false); }
});
el("rename-session").addEventListener("click", () => { el("rename-title").value = state.detail.title; el("rename-form").hidden = false; el("view-title").hidden = true; el("rename-title").focus(); el("rename-title").select(); });
el("cancel-rename").addEventListener("click", () => { el("rename-form").hidden = true; el("view-title").hidden = false; });
el("rename-form").addEventListener("submit", async event => {
  event.preventDefault(); if (state.busy) return; busy(true);
  try {
    const result = await request(`/sessions/${state.active}`, "PATCH", {title:el("rename-title").value.trim()});
    state.detail.title = result.title; navigate("chat"); await loadSessions();
    if (result.history_persisted === false) notice("名称已更新，但尚未写入本机历史记录。", "error");
  } catch (error) { notice(error.message, "error"); } finally { busy(false); }
});
el("delete-session").addEventListener("click", () => { el("delete-dialog").returnValue = "cancel"; el("delete-dialog").showModal(); });
el("delete-dialog").addEventListener("close", async () => {
  if (el("delete-dialog").returnValue !== "delete" || !state.active || state.busy) return;
  busy(true);
  try { await request(`/sessions/${state.active}`, "DELETE"); busy(false); newConversation(); await loadSessions(); notice("对话已删除。", "success"); }
  catch (error) { notice(error.message, "error"); } finally { busy(false); }
});
el("export-session").addEventListener("click", () => {
  if (!state.detail) return;
  const text = `# ${state.detail.title}\n\n` + state.detail.messages.map(message => `## ${message.role === "user" ? "你" : "助理"}\n\n${message.content}\n`).join("\n");
  const url = URL.createObjectURL(new Blob([text], {type:"text/markdown;charset=utf-8"}));
  const link = node("a"); link.href = url; link.download = state.detail.title.replace(/[\\/:*?"<>|]/g,"_").slice(0,60) + ".md"; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
});
function sourceList(sources) {
  const list = node("div", "source-list");
  for (const source of sources) {
    try {
      const url = new URL(source.url);
      if (url.protocol !== "https:" || url.username || url.password) continue;
      const link = node("a", "", source.title); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; list.append(link);
    } catch {}
  }
  if (!list.childElementCount) list.append(node("span", "metadata", "官方服务未提供可跳转的来源链接。"));
  return list;
}
el("use-knowledge").addEventListener("click", () => { state.useKnowledge = !state.useKnowledge; refreshControls(); if (state.useKnowledge) notice("本条问题会先发送至 M5Stack 官方资料服务检索，再交给模型回答。"); else notice(); });
function setTheme(theme) { document.documentElement.dataset.theme = theme; remember("atoms3r.theme",theme); el("theme-toggle").setAttribute("aria-label", theme === "dark" ? "切换浅色模式" : "切换深色模式"); }
setTheme(recalled("atoms3r.theme") || (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light"));
el("theme-toggle").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    if (document.querySelector("dialog[open]")) return;
    if (!el("api-workbench").hidden) { event.preventDefault(); closeApiWorkbench(); return; }
    if (!el("settings-page").hidden) { event.preventDefault(); closeSettings(); return; }
    closeSidebar();
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); openSidebar(); el("session-search").focus(); }
  if ((event.ctrlKey || event.metaKey) && event.altKey && event.key.toLowerCase() === "n") { event.preventDefault(); newConversation(); }
});
function capabilityNotice(text = "", error = false) {
  el("capability-notice").textContent = text; el("capability-notice").dataset.kind = error ? "error" : "";
}
function capabilityControls() {
  const disabled = capabilityState.busy || capabilityState.loading;
  el("capability-refresh").disabled = disabled;
  for (const area of ["capabilities-view", "kb-rename-dialog"]) el(area).querySelectorAll("button,input,select,textarea").forEach(control => { if (control.id === "kb-new-library") return; control.disabled = disabled || control.dataset.requiresEnabled === "false"; });
  el("tool-name").readOnly = Boolean(el("tool-editor").dataset.editing);
}
function capabilityButton(text, action) {
  const button = node("button", "text-button", text); button.type = "button"; button.addEventListener("click", action); return button;
}
async function capabilityAction(action) {
  if (capabilityState.busy || capabilityState.loading) return;
  capabilityState.busy = true; capabilityNotice(); capabilityControls();
  try { await action(); }
  catch (error) { capabilityNotice(error.message,true); }
  finally { capabilityState.busy = false; capabilityControls(); }
}
function updateCapabilityCatalog(data) {
  capabilityState.tools = data.tools;
  if (Array.isArray(data.supported_file_types)) capabilityState.supportedFileTypes = data.supported_file_types.map(type => `.${type.replace(/^\./,"")}`);
  for (const id of ["kb-file","kb-replacement"]) el(id).accept = capabilityState.supportedFileTypes.join(",");
  const pdf = capabilityState.supportedFileTypes.includes(".pdf");
  el("kb-file-types").textContent = `支持 TXT、Markdown、DOCX${pdf ? "、文字版 PDF" : ""}，单份不超过 10MB。${pdf ? "扫描件与图片识别尚未接入。" : "PDF 暂不可用。"}检索结果显示来源文件与片段位置。`;
  if (el("capability-integration")) el("capability-integration").textContent = data.conversation_integration ? "能力已接入对话" : "外部工具与个人知识库尚未接入对话";
  const official = data.tools.find(tool => tool.name === "search_m5stack");
  if (official) {
    state.m5stackEnabled = official.enabled; el("m5stack_enabled").checked = official.enabled;
    if (savedConfig) savedConfig.m5stack_enabled = official.enabled;
    if (savedFingerprint) {const value = JSON.parse(savedFingerprint); value.m5stack_enabled = official.enabled; savedFingerprint = JSON.stringify(value);}
    if (!official.enabled) state.useKnowledge = false;
    refreshControls();
  }
  capabilityState.toolsLoaded = true;
  renderCapabilityTools();
}
async function loadAssistantSelection() {
  try {
    const data = await request("/api/assistant/selection");
    capabilityState.selectedTools = Array.isArray(data.selected_tool_ids) ? data.selected_tool_ids.slice() : [];
    capabilityState.selectedKbs = Array.isArray(data.selected_kb_ids) ? data.selected_kb_ids.slice() : [];
    capabilityState.selectionSupported = true; capabilityState.selectionError = false;
  } catch { capabilityState.selectionSupported = false; capabilityState.selectionError = true; capabilityState.selectedTools = []; capabilityState.selectedKbs = []; }
  capabilityState.selectionFetched = true;
}
async function loadKbLibraries() {
  try {
    const data = await request("/api/knowledge/libraries");
    capabilityState.libraries = Array.isArray(data.libraries) ? data.libraries : [];
    capabilityState.librariesLoaded = true; capabilityState.librariesError = false;
    if (!capabilityState.activeLibraryId || !capabilityState.libraries.some(lib => lib.id === capabilityState.activeLibraryId)) {
      const def = capabilityState.libraries.find(lib => lib.is_default) || capabilityState.libraries[0];
      capabilityState.activeLibraryId = def ? def.id : null;
    }
  } catch {
    capabilityState.libraries = []; capabilityState.librariesLoaded = false; capabilityState.librariesError = true;
  }
  renderKbLibraries();
}
async function loadCapabilities() {
  if (capabilityState.loading || capabilityState.busy) return;
  capabilityState.loading = true; capabilityControls(); capabilityNotice("正在加载技能与资料…");
  try {
    const results = await Promise.allSettled([
      request("/api/tools"),
      request("/api/knowledge/personal?limit=50&offset=0"),
      loadAssistantSelection(),
      loadKbLibraries(),
    ]);
    const failures = [];
    if (results[0].status === "fulfilled") updateCapabilityCatalog(results[0].value);
    else {capabilityState.toolsLoaded = false; if (el("capability-integration")) el("capability-integration").textContent = "技能目录加载失败"; failures.push(results[0].reason.message);}
    if (results[1].status === "fulfilled") {
      capabilityState.documents = results[1].value.documents; capabilityState.total = results[1].value.total;
      capabilityState.offset = capabilityState.documents.length; renderKnowledgeDocuments();
    } else {el("kb-documents").replaceChildren(node("p","small-note","资料加载失败，请刷新重试。")); failures.push(results[1].reason.message);}
    renderCapabilityTools();
    renderKbLibraries();
    if (capabilityState.activeLibraryId) await reloadKnowledgeDocuments().catch(() => {});
    capabilityNotice(failures.join("；"),failures.length > 0);
  } finally { capabilityState.loading = false; capabilityControls(); }
}
async function syncAssistantSelection(nextTools, nextKbs) {
  if (!capabilityState.selectionSupported) return {selected_tool_ids: nextTools, selected_kb_ids: nextKbs};
  const saved = await request("/api/assistant/selection", "PUT", {
    selected_tool_ids: Array.from(new Set(nextTools)),
    selected_kb_ids: Array.from(new Set(nextKbs)),
  });
  capabilityState.selectedTools = Array.isArray(saved.selected_tool_ids) ? saved.selected_tool_ids.slice() : nextTools.slice();
  capabilityState.selectedKbs = Array.isArray(saved.selected_kb_ids) ? saved.selected_kb_ids.slice() : nextKbs.slice();
  if (savedConfig) {
    savedConfig.selected_tool_ids = capabilityState.selectedTools.slice();
    savedConfig.selected_kb_ids = capabilityState.selectedKbs.slice();
  }
  return saved;
}
function isSkillActive(tool) {
  if (!tool || !tool.enabled) return false;
  return !capabilityState.selectionSupported || capabilityState.selectedTools.includes(tool.name);
}
async function setSkillEnabled(tool, enabled) {
  await request(`/api/tools/${encodeURIComponent(tool.name)}/enabled`, "PUT", {enabled});
  if (capabilityState.selectionSupported) {
    const nextTools = enabled
      ? [...capabilityState.selectedTools, tool.name]
      : capabilityState.selectedTools.filter(id => id !== tool.name);
    await syncAssistantSelection(nextTools, capabilityState.selectedKbs);
  }
  const catalog = await request("/api/tools");
  updateCapabilityCatalog(catalog);
}
function syncWeatherCard() {
  const city = el("weather_default_city");
  if (city && document.activeElement !== city) city.value = savedWeather.city || "";
}
function applyWeatherSettings(data) {
  savedWeather.city = typeof data.weather_default_city === "string" ? data.weather_default_city : "";
  if (typeof data.weather_enabled === "boolean") savedWeather.enabled = data.weather_enabled;
  syncWeatherCard();
}
function weatherHeading() {
  const titleWrap = node("div","capability-item-title"); titleWrap.append(node("h3","","天气查询")); return titleWrap;
}
function weatherToolCard(tool) {
  const active = isSkillActive(tool);
  const card = node("div","capability-item"), header = node("div","capability-item-header");
  header.append(weatherHeading());
  const toggleLabel = node("label","checkbox-control"), toggle = node("input");
  toggle.type = "checkbox"; toggle.id = "weather_enabled"; toggle.checked = active;
  toggle.setAttribute("aria-label","开启天气查询技能");
  const toggleText = document.createTextNode(active ? "已开启" : "已停用");
  toggle.addEventListener("change", async () => {
    const enabled = toggle.checked, previous = active;
    toggle.disabled = true;
    try {
      await setSkillEnabled(tool, enabled);
      savedWeather.enabled = enabled;
      if (savedConfig) savedConfig.weather_enabled = enabled;
      capabilityNotice(enabled ? "已为 Agent 开启天气查询。" : "已停用天气查询。");
    } catch (error) {
      toggle.checked = previous;
      capabilityNotice(error.message, true);
    } finally { toggle.disabled = false; }
  });
  toggleLabel.append(toggle,toggleText); header.append(toggleLabel);
  const details = node("details","weather-city-config"), summary = node("summary","","常用城市 · 可选");
  const row = node("label","weather-city-row"), city = node("input");
  city.id = "weather_default_city"; city.maxLength = 80; city.value = savedWeather.city || ""; city.placeholder = "例如：上海；留空则每次先问你在哪";
  const saveCity = async () => {
    const value = city.value.trim();
    if (value === (savedWeather.city || "")) return;
    city.disabled = true;
    try {
      const data = await request("/api/settings/assistant","PUT",{weather_default_city: value});
      if (data && data.text) { savedConfig = data.text; savedTtsConfig = data.tts; }
      savedWeather.city = (data && data.text && typeof data.text.weather_default_city === "string") ? data.text.weather_default_city : value;
      capabilityNotice(value ? `常用城市已保存：${value}` : "常用城市已清空，问天气时会先问你。");
    } catch (error) {
      city.value = savedWeather.city || "";
      capabilityNotice(error.message, true);
    } finally { city.disabled = false; }
  };
  city.addEventListener("change", saveCity);
  city.addEventListener("keydown", event => {if (event.key === "Enter") {event.preventDefault(); saveCity();}});
  row.append(city); details.append(summary,row);
  card.append(header,node("p","small-note",tool.description || "允许 Agent 查询实时与未来天气（Open-Meteo，无需密钥）。"),details);
  return card;
}
function weatherHeadingPair(toggleLabel) {
  const header = node("div","capability-item-header"); header.append(weatherHeading(),toggleLabel); return header;
}
function weatherUnavailableCard(message) {
  const card = node("div","capability-item capability-item-muted"), header = weatherHeadingPair(node("span","capability-state-tag","不可用"));
  card.append(header,node("p","small-note",message));
  return card;
}
function desktopToolCard(tool) {
  const active = isSkillActive(tool);
  const card = node("div", "capability-item"), header = node("div", "capability-item-header");
  const titleWrap = node("div", "capability-item-title");
  titleWrap.append(node("h3", "", "个人电脑操控（Windows / Mac）"));
  header.append(titleWrap);
  const toggleLabel = node("label", "checkbox-control"), toggle = node("input");
  toggle.type = "checkbox"; toggle.checked = active;
  const toggleText = document.createTextNode(active ? "已开启" : "已停用");
  toggle.addEventListener("change", () => {
    const enabled = toggle.checked; toggle.checked = active;
    capabilityAction(async () => {
      await setSkillEnabled(tool, enabled);
      if (savedConfig) savedConfig.desktop_enabled = enabled;
      capabilityNotice(enabled ? "已开启个人电脑操控；请在「终端节点」连接电脑。" : "已停用个人电脑操控。");
    });
  });
  toggleLabel.append(toggle, toggleText); header.append(toggleLabel);
  const st = resolveDesktopModelState();
  card.append(
    header,
    node("p", "small-note", `当前主控模型：${st.effectiveModel || "未配置"}`),
  );
  const actions = node("div", "capability-item-actions");
  const goModels = capabilityButton("模型配置 →", () => {
    navigate("connections");
    requestAnimationFrame(() => el("desktop-planner-preset")?.focus());
  });
  const goDevices = capabilityButton("管理终端节点 →", () => navigate("devices"));
  actions.append(goModels, goDevices);
  card.append(actions);
  return card;
}
const CAPABILITY_LABELS = {
  get_weather: "天气查询",
  web_search: "联网搜索",
  search_m5stack: "M5 官方资料",
  desktop_control: "个人电脑操控 (Win/Mac)",
};
function capabilityItems() {
  const items = [];
  const weather = capabilityState.tools.find(tool => tool.name === "get_weather");
  items.push({key:"get_weather", title:CAPABILITY_LABELS.get_weather, type:"weather", available:Boolean(weather), enabled:isSkillActive(weather), tool:weather || null});
  const desktop = capabilityState.tools.find(tool => tool.name === "desktop_control");
  if (desktop) {
    items.push({key:desktop.name, title:CAPABILITY_LABELS.desktop_control, type:"desktop", available:true, enabled:isSkillActive(desktop), tool:desktop});
  }
  for (const tool of capabilityState.tools) {
    if (tool.name === "get_weather" || tool.name === "desktop_control") continue;
    if (tool.kind === "personal") continue; // 个人知识库检索在「个人知识库」页签按库直接开关
    items.push({key:tool.name, title:CAPABILITY_LABELS[tool.name] || tool.name, type:tool.kind, available:true, enabled:isSkillActive(tool), tool});
  }
  return items;
}
function renderCapabilityTools() {
  const list = el("capability-tools"); list.replaceChildren();
  const items = capabilityItems();
  if (!capabilityState.selectedCapability || !items.some(item => item.key === capabilityState.selectedCapability)) {
    capabilityState.selectedCapability = items.length ? items[0].key : null;
  }
  for (const item of items) {
    const row = node("button","cap-list-item"); row.type = "button"; row.dataset.key = item.key;
    if (item.key === capabilityState.selectedCapability) row.classList.add("active");
    const state = node("span","cap-list-state", !item.available ? "不可用" : item.enabled ? "已开启" : "已停用");
    state.dataset.state = !item.available ? "unavailable" : item.enabled ? "on" : "off";
    row.append(node("span","cap-list-title", item.title), state);
    row.addEventListener("click", () => { capabilityState.selectedCapability = item.key; renderCapabilityTools(); });
    list.append(row);
  }
  renderCapabilityDetail(items.find(item => item.key === capabilityState.selectedCapability));
}
function renderCapabilityDetail(item) {
  const detail = el("capability-detail"); detail.replaceChildren();
  if (!item) { detail.append(node("p","small-note","暂无技能。")); return; }
  if (item.type === "weather") {
    if (!item.available) { detail.append(weatherUnavailableCard("天气工具当前不可用（后端未提供 get_weather）。")); return; }
    detail.append(weatherToolCard(item.tool)); return;
  }
  if (item.type === "desktop") {
    detail.append(desktopToolCard(item.tool)); return;
  }
  if (item.key === "web_search") {
    detail.append(webSearchToolCard(item.tool)); return;
  }
  detail.append(toolDetailCard(item.tool));
}
function webSearchKeyStateText(cfg) {
  if (cfg?.web_search_separate_key_configured) return "已配置独立 Key";
  if (cfg?.web_search_configured) return "自动复用 DeepSeek 主模型 Key";
  return "尚未配置密钥";
}
function renderWebSearchConnectionState() {
  const stateEl = el("conn-web-search-key-state"), clearBtn = el("conn-web-search-clear");
  if (!stateEl) return;
  stateEl.textContent = webSearchKeyStateText(savedConfig);
  if (clearBtn) clearBtn.hidden = !savedConfig?.web_search_separate_key_configured;
}
async function runQuickWebSearchTest(query, resultEl, triggerBtn) {
  const clean = (query || "").trim() || "今日新闻";
  if (triggerBtn) triggerBtn.disabled = true;
  if (resultEl) { resultEl.hidden = false; resultEl.dataset.kind = ""; resultEl.textContent = `正在测试搜索「${clean}」…`; }
  const started = performance.now();
  try {
    const res = await request("/api/tools/web_search/call", "POST", {arguments: {query: clean, count: 1}, confirmed: false});
    const ms = Math.round(performance.now() - started);
    const items = Array.isArray(res?.results) ? res.results : [];
    const summary = items.length ? `搜索正常（${ms}ms，返回 ${items.length} 条）：${items[0].title || items[0].url || ""}` : `接口连通（${ms}ms），但本次未返回结果。`;
    if (resultEl) resultEl.textContent = summary;
    return {ok: true, summary};
  } catch (error) {
    const msg = error.code === "tool_not_found" ? "联网搜索尚未启用，请先到「技能与知识 → 技能中心」勾选“启用资源”。" : error.message;
    if (resultEl) { resultEl.textContent = msg; resultEl.dataset.kind = "error"; }
    return {ok: false, message: msg};
  } finally {
    if (triggerBtn) triggerBtn.disabled = false;
  }
}
el("conn-web-search-clear")?.addEventListener("click", async () => {
  if (state.busy) return;
  busy(true);
  try {
    const {text} = await request("/api/settings/connections", "PUT", {web_search_api_key: ""});
    if (savedConfig) {
      savedConfig.web_search_configured = text.web_search_configured;
      savedConfig.web_search_separate_key_configured = text.web_search_separate_key_configured;
    }
    renderWebSearchConnectionState();
    if (capabilityState.tools.length) renderCapabilityTools();
    notice("独立联网搜索密钥已清除。", "success");
  } catch (error) { notice(error.message, "error"); }
  finally { busy(false); }
});
el("conn-web-search-test")?.addEventListener("click", async () => {
  if (state.busy) return;
  const resultEl = el("conn-web-search-test-result"), btn = el("conn-web-search-test");
  const draftKey = el("conn_web_search_api_key")?.value.trim();
  if (draftKey) {
    btn.disabled = true;
    resultEl.hidden = false; resultEl.dataset.kind = ""; resultEl.textContent = "正在保存搜索密钥并测试…";
    try {
      const {text} = await request("/api/settings/connections", "PUT", {web_search_api_key: draftKey});
      el("conn_web_search_api_key").value = "";
      if (savedConfig) {
        savedConfig.web_search_configured = text.web_search_configured;
        savedConfig.web_search_separate_key_configured = text.web_search_separate_key_configured;
      }
      renderWebSearchConnectionState();
      if (capabilityState.tools.length) renderCapabilityTools();
      dirty();
    } catch (error) {
      resultEl.textContent = error.message; resultEl.dataset.kind = "error";
      btn.disabled = false;
      return;
    }
  }
  await runQuickWebSearchTest("今日新闻", resultEl, btn);
});
function webSearchToolCard(tool) {
  const active = isSkillActive(tool);
  const card = node("div", "capability-item");
  const header = node("div", "capability-item-header");
  const title = node("div", "capability-item-title");
  title.append(node("h3", "", "联网搜索"), node("p", "small-note", "DeepSeek Search"));
  header.append(title);

  const toggleLabel = node("label", "checkbox-control"), toggle = node("input");
  toggle.type = "checkbox"; toggle.checked = active;
  toggle.addEventListener("change", () => {
    const enabled = toggle.checked; toggle.checked = active;
    capabilityAction(async () => {
      await setSkillEnabled(tool, enabled);
      capabilityNotice(enabled ? "已为 Agent 开启「联网搜索」。" : "已停用。");
    });
  });
  toggleLabel.append(toggle, document.createTextNode(active ? "已开启" : "已停用"));
  header.append(toggleLabel);

  const keySection = node("div", "search-key-config");
  const keyHead = node("div", "search-key-head");
  const label = node("label", "", "DeepSeek API Key");
  label.htmlFor = "web_search_api_key";
  const status = node("p", "small-note", webSearchKeyStateText(savedConfig));
  status.id = "web-search-key-status";
  keyHead.append(label, status);

  const keyRow = node("div", "search-key-row");
  const field = node("input");
  field.id = "web_search_api_key"; field.type = "password"; field.autocomplete = "off"; field.spellcheck = false;
  field.placeholder = "填 DeepSeek API Key；主模型已是 DeepSeek 可留空";
  field.setAttribute("aria-describedby", status.id);
  const separate = Boolean(savedConfig?.web_search_separate_key_configured);

  const saveKey = clear => capabilityAction(async () => {
    const value = clear ? "" : field.value.trim();
    if (!clear && !value) {
      capabilityNotice("请输入 DeepSeek API Key。", true);
      return;
    }
    field.value = "";
    const {text} = await request("/api/settings/connections", "PUT", {web_search_api_key:value});
    if (savedConfig) {
      savedConfig.web_search_configured = text.web_search_configured;
      savedConfig.web_search_separate_key_configured = text.web_search_separate_key_configured;
    }
    renderWebSearchConnectionState();
    renderCapabilityTools();
    capabilityNotice(clear ? "独立密钥已清除。" : "密钥已保存。");
  });
  const saveBtn = node("button", "secondary-button", "保存密钥");
  saveBtn.type = "button"; saveBtn.addEventListener("click", () => saveKey(false));
  keyRow.append(field, saveBtn);
  if (separate) {
    const clearBtn = node("button", "text-button", "清除");
    clearBtn.type = "button"; clearBtn.addEventListener("click", () => saveKey(true));
    keyRow.append(clearBtn);
  }
  field.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      saveKey(false);
    }
  });
  keySection.append(keyHead, keyRow);

  const quickTest = node("div", "search-quick-test");
  const testRow = node("div", "search-quick-test-row");
  const testInput = node("input");
  testInput.type = "text"; testInput.maxLength = 128; testInput.value = "今日新闻";
  testInput.placeholder = "输入测试关键词，例如：今天金价";
  testInput.setAttribute("aria-label", "测试搜索关键词");
  const quickBtn = node("button", "secondary-button", "测试搜索");
  quickBtn.type = "button";
  quickBtn.disabled = !tool.enabled; quickBtn.dataset.requiresEnabled = String(tool.enabled);
  const debugBtn = capabilityButton("JSON 调试", () => openToolCall(tool));
  debugBtn.disabled = !tool.enabled; debugBtn.dataset.requiresEnabled = String(tool.enabled);
  const quickResult = node("p", "small-note");
  quickResult.hidden = true;
  const runQuick = () => runQuickWebSearchTest(testInput.value, quickResult, quickBtn).then(res => {
    capabilityNotice(res.ok ? res.summary : res.message, !res.ok);
  });
  quickBtn.addEventListener("click", runQuick);
  testInput.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      if (!quickBtn.disabled) runQuick();
    }
  });
  testRow.append(testInput, quickBtn, debugBtn);
  quickTest.append(node("label", "", "快速提问测试"), testRow, quickResult);

  card.append(header, keySection, quickTest);
  return card;
}
function toolDetailCard(tool) {
  const active = isSkillActive(tool);
  const card = node("div","capability-item");
  const header = node("div","capability-item-header");
  header.append(node("h3","", CAPABILITY_LABELS[tool.name] || tool.name));
  const toggleLabel = node("label","checkbox-control"), toggle = node("input");
  toggle.type = "checkbox"; toggle.checked = active;
  const toggleText = document.createTextNode(active ? "已开启" : "已停用");
  toggle.addEventListener("change", () => {
    const enabled = toggle.checked; toggle.checked = active;
    capabilityAction(async () => {
      await setSkillEnabled(tool, enabled);
      capabilityNotice(enabled ? `已为 Agent 开启「${CAPABILITY_LABELS[tool.name] || tool.name}」。` : "已停用。");
    });
  });
  toggleLabel.append(toggle,toggleText); header.append(toggleLabel);
  card.append(header,node("p","small-note",tool.description || ""));
  if (tool.kind === "http") card.append(node("p","small-note",`${tool.request?.method || tool.method} ${tool.request?.url || tool.url}`));
  const actions = node("div","capability-item-actions");
  const call = capabilityButton("手动测试", () => openToolCall(tool)); call.disabled = !tool.enabled; call.dataset.requiresEnabled = String(tool.enabled); actions.append(call);
  if (tool.kind === "http") {
    actions.append(capabilityButton("编辑", () => editExternalTool(tool)), capabilityButton("删除", () => {
      if (!confirm(`删除自定义工具「${tool.name}」及其配置？`)) return;
      capabilityAction(async () => {
        if (capabilityState.selectionSupported && capabilityState.selectedTools.includes(tool.name)) {
          await syncAssistantSelection(capabilityState.selectedTools.filter(id => id !== tool.name), capabilityState.selectedKbs);
        }
        await request(`/api/tools/${encodeURIComponent(tool.name)}`,"DELETE");
        updateCapabilityCatalog(await request("/api/tools"));
        capabilityNotice("工具已删除。");
      });
    }));
  }
  card.append(actions);
  return card;
}
function renderKbLibraries() {
  const box = el("kb-library-list"); if (!box) return;
  box.replaceChildren();
  const newBtn = el("kb-new-library");
  if (newBtn) newBtn.disabled = !capabilityState.librariesLoaded;
  if (!capabilityState.librariesLoaded) {
    box.append(node("p","small-note", capabilityState.librariesError ? "知识库加载失败，请刷新重试。" : "知识库加载中…"));
    return;
  }
  if (!capabilityState.libraries.length) {
    box.append(node("p","small-note","还没有知识库，点「新建库」添加。"));
    return;
  }
  for (const lib of capabilityState.libraries) {
    const row = node("div","kb-lib-item" + (lib.id === capabilityState.activeLibraryId ? " active" : ""));
    const name = node("button","kb-lib-name","" + lib.name); name.type = "button"; name.title = "切换到此知识库";
    name.addEventListener("click", () => { capabilityState.activeLibraryId = lib.id; renderKbLibraries(); reloadKnowledgeDocuments().catch(error => capabilityNotice(error.message,true)); });
    row.append(name);
    row.append(node("span","kb-lib-count", `${lib.document_count != null ? lib.document_count : "?"} 份`));
    if (capabilityState.selectionSupported) {
      const useWrap = node("label", "kb-lib-use"), cb = node("input");
      cb.type = "checkbox"; cb.checked = capabilityState.selectedKbs.includes(lib.id);
      cb.setAttribute("aria-label", `允许 Agent 检索知识库 ${lib.name}`);
      const badge = node("span", "", cb.checked ? "已挂载" : "未挂载");
      cb.addEventListener("click", event => event.stopPropagation());
      cb.addEventListener("change", () => {
        const nextChecked = cb.checked; cb.checked = !nextChecked;
        capabilityAction(async () => {
          const nextKbs = nextChecked
            ? [...capabilityState.selectedKbs, lib.id]
            : capabilityState.selectedKbs.filter(id => id !== lib.id);
          await syncAssistantSelection(capabilityState.selectedTools, nextKbs);
          renderKbLibraries();
          capabilityNotice(nextChecked ? `已将「${lib.name}」挂载给 Agent 检索。` : `已取消挂载「${lib.name}」。`);
        });
      });
      useWrap.append(cb, badge);
      row.append(useWrap);
    }
    if (!lib.is_default) {
      const acts = node("span","kb-lib-actions");
      const rename = capabilityButton("改名", () => openKbLibraryDialog(lib));
      const del = capabilityButton("删除", () => {
        if (!confirm(`删除知识库「${lib.name}」？空库才能删，默认库不能删。`)) return;
        capabilityAction(async () => {
          if (capabilityState.selectionSupported && capabilityState.selectedKbs.includes(lib.id)) {
            await syncAssistantSelection(
              capabilityState.selectedTools,
              capabilityState.selectedKbs.filter(id => id !== lib.id),
            );
          }
          await request(`/api/knowledge/libraries/${encodeURIComponent(lib.id)}`,"DELETE");
          if (capabilityState.activeLibraryId === lib.id) capabilityState.activeLibraryId = null;
          await loadKbLibraries();
          await reloadKnowledgeDocuments().catch(() => {});
          renderKbLibraries();
          capabilityNotice("知识库已删除。");
        });
      });
      acts.append(rename, del); row.append(acts);
    }
    box.append(row);
  }
}
let kbLibraryEditing = null;
function openKbLibraryDialog(lib = null) {
  kbLibraryEditing = lib;
  el("kb-library-dialog-title").textContent = lib ? "重命名知识库" : "新建知识库";
  el("kb-library-name").value = lib ? lib.name : "";
  el("kb-library-status").textContent = ""; el("kb-library-status").dataset.kind = "";
  el("kb-library-dialog").showModal(); el("kb-library-name").focus();
}
el("kb-new-library").addEventListener("click", () => { if (!capabilityState.librariesLoaded) return; openKbLibraryDialog(); });
el("kb-library-cancel").addEventListener("click", () => el("kb-library-dialog").close());
el("kb-library-form").addEventListener("submit", event => {
  event.preventDefault();
  const name = el("kb-library-name").value.trim(); if (!name) return;
  const status = el("kb-library-status"); status.textContent = "正在保存…"; status.dataset.kind = "";
  capabilityAction(async () => {
    let created = null;
    try {
      if (kbLibraryEditing) await request(`/api/knowledge/libraries/${encodeURIComponent(kbLibraryEditing.id)}`,"PATCH",{name});
      else created = await request("/api/knowledge/libraries","POST",{name});
    } catch (error) { status.textContent = error.message; status.dataset.kind = "error"; return; }
    el("kb-library-dialog").close();
    if (created && created.id) {
      capabilityState.activeLibraryId = created.id;
      if (capabilityState.selectionSupported) {
        await syncAssistantSelection(capabilityState.selectedTools, [...capabilityState.selectedKbs, created.id]).catch(() => {});
      }
    }
    await loadKbLibraries();
    await reloadKnowledgeDocuments().catch(() => {});
    renderKbLibraries();
    capabilityNotice(kbLibraryEditing ? "知识库已重命名。" : "知识库已新建并默认挂载给 Agent。");
  });
});
const apiWorkbench = { tool:null, baseline:"", loading:false, saving:false, debug:null, pending:null, response:null, generation:0, mode:"visual" };
const apiSchemaRoots = {input:{},output:{}};
const API_SENSITIVE_KEY = /authorization|cookie|password|passwd|token|secret|api[-_]?key|credential/i;
function apiSavedAuth() {const auth = apiWorkbench.tool?.request?.auth; return el("api-auth-type").value === "basic" ? Boolean(auth?.password_configured) : Boolean(auth?.token_configured);}
function apiNotice(text = "", error = false) {el("api-workbench-notice").textContent = text; el("api-workbench-notice").dataset.kind = error ? "error" : "";}
function apiControls() {
  const disabled = apiWorkbench.loading || apiWorkbench.saving || Boolean(apiWorkbench.debug);
  el("api-request-fields").disabled = disabled; el("tool-editor-fields").disabled = disabled;
  el("api-new-request").disabled = disabled; el("api-show-save").disabled = disabled;
  el("api-request-list").querySelectorAll("button").forEach(button => {button.disabled = disabled;});
  el("api-inflight").hidden = !apiWorkbench.debug;
  el("tool-name").readOnly = Boolean(apiWorkbench.tool);
}
function apiTab(name) {
  for (const tab of ["params","headers","auth","body"]) {
    el(`api-pane-${tab}`).hidden = tab !== name;
    el(`api-tab-${tab}`).setAttribute("aria-selected",String(tab === name));
    el(`api-tab-${tab}`).tabIndex = tab === name ? 0 : -1;
  }
}
document.querySelectorAll("[data-api-tab]").forEach(button => {
  button.addEventListener("click",() => apiTab(button.dataset.apiTab));
  button.addEventListener("keydown",event => {
    if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    const tabs = ["params","headers","auth","body"], index = tabs.indexOf(button.dataset.apiTab);
    const next = event.key === "Home" ? 0 : event.key === "End" ? 3 : (index + (event.key === "ArrowRight" ? 1 : 3)) % 4;
    event.preventDefault(); apiTab(tabs[next]); el(`api-tab-${tabs[next]}`).focus();
  });
});
function addApiRow(areaId, data = {}) {
  const row = node("div","api-keyvalue-row"); row.dataset.configured = String(Boolean(data.value_configured));
  const enabled = node("input"); enabled.type = "checkbox"; enabled.checked = data.enabled !== false; enabled.dataset.field = "enabled"; enabled.setAttribute("aria-label","启用此字段");
  const key = node("input"); key.placeholder = "Key"; key.value = data.key || ""; key.dataset.field = "key"; key.setAttribute("aria-label","字段名称");
  const value = node("input"); value.placeholder = data.value_configured ? "已保存，保留时不回传" : "Value"; value.value = data.value || ""; value.dataset.field = "value"; value.setAttribute("aria-label","字段值"); value.autocomplete = "off";
  const secretLabel = node("label","checkbox-control api-row-secret"), secret = node("input"); secret.type = "checkbox"; secret.checked = Boolean(data.secret || data.value_configured); secret.dataset.field = "secret"; secretLabel.append(secret,document.createTextNode("敏感"));
  const action = node("select"); action.dataset.field = "action"; action.setAttribute("aria-label","敏感值处理"); action.append(new Option("保留","keep"),new Option("替换","replace"),new Option("清除","clear")); action.value = data.value_configured ? "keep" : "replace";
  const sync = () => {action.hidden = row.dataset.configured !== "true"; value.type = secret.checked ? "password" : "text"; value.readOnly = row.dataset.configured === "true" && action.value !== "replace";};
  key.addEventListener("input",() => {if (API_SENSITIVE_KEY.test(key.value)) secret.checked = true; sync();});
  secret.addEventListener("change",sync); action.addEventListener("change",() => {if (action.value !== "replace") value.value = ""; sync();}); sync();
  const remove = capabilityButton("×",() => {row.remove(); apiDirty();}); remove.setAttribute("aria-label","移除此字段");
  row.append(enabled,key,value,secretLabel,action,remove); el(areaId).append(row);
}
function apiRows(areaId) {
  return Array.from(el(areaId).children).map(row => {
    const field = name => row.querySelector(`[data-field="${name}"]`);
    const key = field("key").value.trim(), action = field("action").value;
    return {key,value:row.dataset.configured === "true" && action === "keep" ? null : action === "clear" ? "" : field("value").value,enabled:field("enabled").checked,secret:field("secret").checked || API_SENSITIVE_KEY.test(key) || row.dataset.configured === "true" && action === "keep"};
  }).filter(item => item.key);
}
for (const [button,area] of [["api-add-param","api-params"],["api-add-header","api-headers"],["api-add-form","api-form-fields"]]) el(button).addEventListener("click",() => {addApiRow(area); apiDirty();});
function syncApiAuth() {
  const type = el("api-auth-type").value, action = el("api-secret-action").value;
  const hasSaved = apiSavedAuth();
  el("api-secret-action-row").hidden = type === "none" || !hasSaved;
  el("api-auth-header-row").hidden = type !== "header"; el("api-auth-scheme-row").hidden = type !== "header";
  el("api-auth-username-row").hidden = type !== "basic";
  el("api-auth-token-row").hidden = !["bearer","header"].includes(type) || action === "clear" || hasSaved && action === "keep";
  el("api-auth-password-row").hidden = type !== "basic" || action === "clear" || hasSaved && action === "keep";
  el("tool-key-state").textContent = hasSaved ? "已保存凭据只由服务端复用，保留时不回传。更换地址或鉴权方式必须替换或清除。" : "密钥仅保存于服务端，不写入浏览器存储。";
}
function syncApiBody() {
  const mode = el("api-body-mode").value, configured = Boolean(apiWorkbench.tool?.request?.body?.text_configured);
  const preserve = configured && el("api-body-secret-action").value !== "replace";
  el("api-body-text-row").hidden = !["json","text"].includes(mode); el("api-body-form-row").hidden = mode !== "form";
  el("api-body-secret-controls").hidden = !["json","text"].includes(mode);
  el("api-body-secret-action-row").hidden = !configured;
  el("api-body-text").readOnly = preserve;
  el("api-body-text").placeholder = preserve ? "敏感正文已存于服务端；选择替换后可编辑。" : "请求正文";
}
function apiRequestDraft() {
  const type = el("api-auth-type").value, action = el("api-secret-action").value;
  const keep = apiSavedAuth() && action === "keep";
  const auth = {type,header:el("tool-auth-header").value.trim(),scheme:el("tool-auth-scheme").value,username:el("api-auth-username").value};
  if (["bearer","header"].includes(type)) auth.token = keep ? null : action === "clear" ? "" : el("tool-key").value;
  if (type === "basic") auth.password = keep ? null : action === "clear" ? "" : el("api-auth-password").value;
  const mode = el("api-body-mode").value, bodyAction = el("api-body-secret-action").value;
  let bodyText = ["json","text"].includes(mode) ? el("api-body-text").value : "";
  if (apiWorkbench.tool?.request?.body?.text_configured && ["json","text"].includes(mode)) bodyText = bodyAction === "keep" ? null : bodyAction === "clear" ? "" : bodyText;
  let secret = el("api-body-secret").checked || Boolean(apiWorkbench.tool?.request?.body?.text_configured && bodyAction === "keep");
  if (mode === "json" && bodyText) {try {const scan = value => value && typeof value === "object" && (Array.isArray(value) ? value.some(scan) : Object.entries(value).some(([key,item]) => API_SENSITIVE_KEY.test(key) || scan(item))); secret ||= Boolean(scan(JSON.parse(bodyText)));} catch {}}
  return {method:el("tool-method").value,url:el("tool-url").value.trim(),params:apiRows("api-params"),headers:apiRows("api-headers"),auth,body:{mode,text:bodyText,fields:mode === "form" ? apiRows("api-form-fields") : [],secret:["json","text"].includes(mode) && secret},timeout_seconds:Number(el("api-timeout").value)};
}
function apiSchemaArea(kind) {return el(`api-${kind}-table`);}
function renderApiSchema(kind, schema = {}) {
  apiSchemaRoots[kind] = structuredClone(schema);
  const table = node("table","schema-table"), head = node("thead"), row = node("tr"), body = node("tbody");
  const labels = kind === "input" ? ["名称","描述","类型","必填","默认值","启用","操作"] : ["名称","描述","类型","启用","操作"];
  for (const label of labels) {const cell = node("th","",label); cell.scope = "col"; row.append(cell);}
  head.append(row); table.append(head,body); apiSchemaArea(kind).replaceChildren(table);
  for (const [name,definition] of Object.entries(schema.properties || {})) addApiSchemaRow(kind,name,definition,(schema.required || []).includes(name));
  syncApiSchema(kind);
}
function addApiSchemaRow(kind, name = "", definition = {type:"string"}, required = false) {
  const row = node("tr","api-schema-row"); row._definition = structuredClone(definition);
  const fields = {};
  const add = (label, field, control) => {const cell = node("td"); cell.dataset.label = label; control.dataset.schemaField = field; control.setAttribute("aria-label",`${kind === "input" ? "参数" : "输出"}${label}`); fields[field] = control; cell.append(control); row.append(cell);};
  const nameInput = node("input"); nameInput.value = name; nameInput.placeholder = "字段名"; add("名称","name",nameInput);
  const description = node("input"); description.value = definition.description || ""; description.placeholder = "字段用途"; add("描述","description",description);
  const type = node("select"); for (const value of ["string","integer","number","boolean","object","array","null"]) type.append(new Option(value,value));
  if (typeof definition.type !== "string" || ![...type.options].some(option => option.value === definition.type)) type.append(new Option("复杂规则（JSON）","custom"));
  type.value = typeof definition.type === "string" && [...type.options].some(option => option.value === definition.type) ? definition.type : "custom"; add("类型","type",type);
  if (kind === "input") {
    const must = node("input"); must.type = "checkbox"; must.checked = required; add("必填","required",must);
    const value = node("input"); value.value = Object.hasOwn(definition,"default") ? typeof definition.default === "string" ? definition.default : JSON.stringify(definition.default) : ""; value.placeholder = "未指定"; value.dataset.edited = "false"; value.addEventListener("input",() => {value.dataset.edited = "true";}); add("默认值","default",value);
  }
  const enabled = node("input"); enabled.type = "checkbox"; enabled.checked = definition["x-enabled"] !== false; add("启用","enabled",enabled);
  const remove = capabilityButton("删除",() => {row.remove(); syncApiSchema(kind); apiDirty();}); add("操作","remove",remove);
  const sync = () => {row.dataset.disabled = String(!enabled.checked); try {syncApiSchema(kind); el("tool-editor-status").textContent = "";} catch (error) {el("tool-editor-status").textContent = error.message;} };
  row.addEventListener("input",sync); row.addEventListener("change",sync);
  apiSchemaArea(kind).querySelector("tbody").append(row); return fields;
}
function syncApiSchema(kind) {
  const root = structuredClone(apiSchemaRoots[kind]), properties = {}, required = [];
  for (const row of apiSchemaArea(kind).querySelectorAll(".api-schema-row")) {
    const field = name => row.querySelector(`[data-schema-field="${name}"]`);
    const name = field("name").value.trim(); if (!name) continue;
    if (Object.hasOwn(properties,name)) throw new Error(`字段名「${name}」重复。`);
    const definition = structuredClone(row._definition);
    if (field("type").value !== "custom") definition.type = field("type").value;
    definition.description = field("description").value;
    if (!field("enabled").checked) definition["x-enabled"] = false; else delete definition["x-enabled"];
    if (kind === "input") {
      if (field("required").checked) required.push(name);
      const value = field("default").value;
      if (value || field("default").dataset.edited === "false" && Object.hasOwn(definition,"default")) {
        if (definition.type === "string") definition.default = value;
        else if (field("default").dataset.edited === "true" || !Object.hasOwn(definition,"default")) {
          try {definition.default = JSON.parse(value);} catch {throw new Error(`「${name}」默认值需符合 ${definition.type || "JSON"} 类型。`);}
        }
      } else delete definition.default;
    }
    Object.defineProperty(properties,name,{value:definition,enumerable:true,writable:true,configurable:true});
  }
  root.type = "object"; root.properties = properties;
  if (kind === "input") {if (required.length) root.required = required; else delete root.required;}
  el(kind === "input" ? "tool-schema" : "tool-output-schema").value = JSON.stringify(root,null,2); return root;
}
for (const kind of ["input","output"]) el(`api-${kind}-add`).addEventListener("click",() => {addApiSchemaRow(kind); apiSchemaArea(kind).lastElementChild?.scrollIntoView({block:"nearest"});});
function apiDefinition() {
  return {name:el("tool-name").value.trim(),description:el("tool-description").value,group:el("tool-group").value,permission:el("tool-permission").value,enabled:el("tool-enabled").checked,argument_target:el("api-argument-target").value,parameters:syncApiSchema("input"),output_schema:syncApiSchema("output"),request:apiRequestDraft()};
}
// 外部 JSON 定义（用户平台格式：apiName/apiPath/body/output/authorization…）兼容
function externalTypeToSchema(type) {
  const map = {string:"string",boolean:"boolean",integer:"integer",number:"number",object:"object",array:"array",null:"null"};
  return map[String(type == null ? "String" : type).toLowerCase()] || "string";
}
function schemaTypeToExternal(type) {
  const map = {string:"String",boolean:"Boolean",integer:"Integer",number:"Number",object:"Object",array:"Array",null:"String"};
  return map[type] || "String";
}
function isExternalFormat(obj) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if ("apiName" in obj || "apiPath" in obj || "authorization" in obj) return true;
  const looksFieldArray = value => Array.isArray(value) && value.some(item => item && typeof item === "object" && "key" in item);
  return looksFieldArray(obj.body) || looksFieldArray(obj.output) || looksFieldArray(obj.header);
}
function externalFieldToSchema(item) {
  const def = {type:externalTypeToSchema(item && item.type)};
  if (item && item.description) def.description = item.description;
  if (item && item.enable === false) def["x-enabled"] = false;
  if (item && Array.isArray(item.children) && item.children.length) {
    if (def.type === "array") {
      def.items = externalFieldToSchema(item.children[0] || {});
    } else {
      const properties = {}, required = [];
      for (const child of item.children) {
        const name = String((child && (child.key || child.name)) || "").trim(); if (!name) continue;
        properties[name] = externalFieldToSchema(child);
        if (child.required) required.push(name);
      }
      def.type = "object"; def.properties = properties; if (required.length) def.required = required;
    }
  }
  return def;
}
function externalListToSchema(list) {
  const properties = {}, required = [];
  for (const item of list || []) {
    const name = String((item && (item.key || item.name)) || "").trim(); if (!name) continue;
    properties[name] = externalFieldToSchema(item);
    if (item.required) required.push(name);
  }
  const schema = {type:"object",properties}; if (required.length) schema.required = required; return schema;
}
function externalToDefinition(obj) {
  const body = Array.isArray(obj.body) ? obj.body : [];
  const output = Array.isArray(obj.output) ? obj.output : [];
  const params = (Array.isArray(obj.params) ? obj.params : []).map(item => ({key:item.key || "", value:item.value == null ? "" : String(item.value), description:item.description || "", enabled:item.enable !== false, secret:false}));
  const headers = (Array.isArray(obj.header) ? obj.header : []).map(item => ({key:item.key || "", value:item.value == null ? "" : String(item.value), description:item.description || "", enabled:true, secret:false}));
  const method = String(obj.apiMethod || "GET").toUpperCase();
  const hasBody = body.length > 0;
  const bodyMode = (obj.bodyType === 2 || hasBody) ? "json" : "none";
  const argumentTarget = (hasBody && !["GET","HEAD","OPTIONS"].includes(method)) ? "body" : "auto";
  const authorization = obj.authorization || {};
  let auth = {type:"none"};
  if (authorization.isAuthenticated) auth = {type:"header", header:authorization.header || "Authorization", scheme:"Bearer", token:authorization.apiKey || ""};
  return {
    name:obj.apiName || "", description:obj.apiDescription || "", group:"", permission:"read", enabled:false, argument_target:argumentTarget,
    parameters:externalListToSchema(body), output_schema:externalListToSchema(output),
    request:{method, url:obj.apiPath || "", params, headers, auth, body:{mode:bodyMode, text:hasBody ? "{}" : "", fields:[], secret:false}, timeout_seconds:20}
  };
}
function schemaToExternalField(name, schema, required) {
  const field = {key:name, description:(schema && schema.description) || "", type:schemaTypeToExternal(schema && schema.type), required:Boolean(required), value:"", enable:!(schema && schema["x-enabled"] === false), children:[]};
  if (schema && schema.type === "array" && schema.items) field.children.push(schemaToExternalField("item", schema.items, false));
  if (schema && schema.properties) {
    for (const [childName, childSchema] of Object.entries(schema.properties)) field.children.push(schemaToExternalField(childName, childSchema, (schema.required || []).includes(childName)));
  }
  return field;
}
function definitionToExternal(def) {
  const req = (def && def.request) || {};
  const params = (req.params || []).map(item => ({key:item.key, value:item.value == null ? "" : item.value, description:item.description || ""}));
  const header = (req.headers || []).map(item => ({key:item.key, value:item.value == null ? "" : item.value, description:item.description || ""}));
  const body = Object.entries((def && def.parameters && def.parameters.properties) || {}).map(([name, schema]) => schemaToExternalField(name, schema, ((def.parameters.required) || []).includes(name)));
  const output = Object.entries((def && def.output_schema && def.output_schema.properties) || {}).map(([name, schema]) => schemaToExternalField(name, schema, false));
  const auth = req.auth || {};
  const authorization = (auth.type && auth.type !== "none") ? {isAuthenticated:true, authType:"1", apiKey:auth.token || "", header:auth.header || "Authorization"} : {isAuthenticated:false, authType:"1", apiKey:"", header:""};
  return {version:1, apiName:(def && def.name) || "", apiMethod:req.method || "GET", apiPath:req.url || "", apiDescription:(def && def.description) || "", bodyType:((req.body && req.body.mode === "json") ? 2 : 0), params, header, body, output, authorization};
}
function applyApiDefinition() {
  const raw = JSON.parse(el("api-definition").value);
  const value = isExternalFormat(raw) ? externalToDefinition(raw) : raw;
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("JSON 需为对象。");
  const missing = [];
  if (!value.request) missing.push("request");
  if (value.parameters?.type !== "object") missing.push("parameters（object 类型）");
  if (value.output_schema && ![undefined,"object"].includes(value.output_schema.type)) missing.push("output_schema（object 类型）");
  if (missing.length) throw new Error(`定义缺少或类型不对：${missing.join("、")}。`);
  if (apiWorkbench.tool && value.name !== apiWorkbench.tool.name) throw new Error("已保存接口的名称不可在这里修改，请新建接口。");
  const draft = value.request, auth = draft.auth || {}, body = draft.body || {};
  if (!["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"].includes(draft.method) || !["read","write","paid"].includes(value.permission) || !["auto","query","body"].includes(value.argument_target)) throw new Error("请检查 method、permission 和 argument_target。");
  if (!["none","bearer","header","basic"].includes(auth.type || "none") || !["none","json","text","form"].includes(body.mode || "none")) throw new Error("鉴权类型或正文类型无效。");
  for (const [id,text] of [["tool-name",value.name || ""],["tool-description",value.description || ""],["tool-group",value.group || ""],["tool-method",draft.method],["tool-url",draft.url || ""],["tool-permission",value.permission],["api-argument-target",value.argument_target],["api-timeout",draft.timeout_seconds ?? 20],["api-auth-type",auth.type || "none"],["tool-auth-header",auth.header || "Authorization"],["tool-auth-scheme",auth.scheme || "Bearer"],["api-auth-username",auth.username || ""],["api-body-mode",body.mode || "none"],["api-body-text",body.text || ""]]) el(id).value = text;
  const credential = auth.type === "basic" ? auth.password : auth.token;
  if (credential === null && !apiSavedAuth()) throw new Error("此接口没有可保留的已存凭据，请填写或清除。");
  el("api-secret-action").value = credential === null ? "keep" : credential === "" ? "clear" : "replace";
  el("tool-key").value = auth.token || ""; el("api-auth-password").value = auth.password || "";
  el("api-body-secret").checked = Boolean(body.secret); el("api-body-secret-action").value = body.text === null ? "keep" : body.text === "" ? "clear" : "replace";
  el("tool-enabled").checked = Boolean(value.enabled);
  for (const [area,rows] of [["api-params",draft.params],["api-headers",draft.headers],["api-form-fields",body.fields]]) {el(area).replaceChildren(); for (const item of rows || []) addApiRow(area,{...item,value_configured:item.value === null});}
  renderApiSchema("input",value.parameters); renderApiSchema("output",value.output_schema || {}); syncApiAuth(); syncApiBody();
}
function apiConfigMode(mode) {
  let ok = true;
  if (mode === "json" && apiWorkbench.mode !== "json") {
    try {
      el("api-definition").value = JSON.stringify(definitionToExternal(apiDefinition()), null, 2);
      apiWorkbench.jsonBaseline = el("api-definition").value;
    } catch (error) {el("api-definition-status").textContent = error.message; apiNotice(error.message,true); return false;}
  }
  if (mode === "visual" && apiWorkbench.mode === "json") {
    try { applyApiDefinition(); }
    catch (error) {
      // 不把用户锁在 JSON 页：允许切回可视化，保留原表单，只提示 JSON 未生效。
      ok = false;
      el("api-definition-status").textContent = `JSON 未生效，已忽略：${error.message}`;
      apiNotice("JSON 未生效，已忽略；表单保留原值。可修正后再切回。", true);
    }
  }
  apiWorkbench.mode = mode; el("api-json-panel").hidden = mode !== "json"; el("api-json-test").hidden = mode !== "json";
  el("api-request-fields").hidden = mode !== "visual"; el("tool-editor").hidden = mode !== "visual";
  for (const name of ["visual","json"]) el(`api-mode-${name}`).setAttribute("aria-pressed",String(name === mode));
  if (ok) el("api-definition-status").textContent = "";
  apiDirty(); return ok;
}
el("api-mode-json").addEventListener("click",() => apiConfigMode("json"));
el("api-mode-visual").addEventListener("click",() => apiConfigMode("visual"));
el("api-json-test").addEventListener("click",() => {if (apiConfigMode("visual")) el("api-send").click();});
function apiHasChanges() {return Boolean(apiWorkbench.baseline && apiFingerprint() !== apiWorkbench.baseline || apiWorkbench.mode === "json" && el("api-definition").value !== apiWorkbench.jsonBaseline);}
function apiFingerprint() {return JSON.stringify({request:apiRequestDraft(),permission:el("tool-permission").value,name:el("tool-name").value,description:el("tool-description").value,group:el("tool-group").value,target:el("api-argument-target").value,parameters:el("tool-schema").value,output_schema:el("tool-output-schema").value,enabled:el("tool-enabled").checked});}
function apiDirty() {
  const changed = apiHasChanges();
  el("api-draft-state").textContent = changed ? "有未保存草稿" : apiWorkbench.tool ? "已保存" : "未保存";
  if (changed && !apiWorkbench.debug && !apiWorkbench.saving) {
    apiNotice();
    if (apiWorkbench.response) {const data = apiWorkbench.response; el("api-response-meta").textContent = `上次响应：${data.status} · ${data.elapsed_ms} ms${data.truncated ? " · 已截断" : ""}`;}
  }
  el("api-send-confirm").checked = false;
}
el("api-workbench").addEventListener("input",apiDirty);
el("api-workbench").addEventListener("change",apiDirty);
el("api-auth-type").addEventListener("change",syncApiAuth);
el("api-secret-action").addEventListener("change",() => {el("tool-key").value = ""; el("api-auth-password").value = ""; syncApiAuth();});
el("api-body-mode").addEventListener("change",syncApiBody);
el("api-body-secret-action").addEventListener("change",() => {if (el("api-body-secret-action").value !== "replace") el("api-body-text").value = ""; syncApiBody();});
function renderApiList() {
  const list = el("api-request-list"), query = el("api-request-search").value.trim().toLowerCase(); list.replaceChildren();
  const tools = capabilityState.tools.filter(tool => tool.kind === "http" && `${tool.name} ${tool.group || ""} ${tool.request?.url || tool.url || ""}`.toLowerCase().includes(query));
  const groups = [...new Set(tools.map(tool => tool.group || "未分组"))];
  for (const group of groups) {
    list.append(node("p","api-list-group",group));
    for (const tool of tools.filter(item => (item.group || "未分组") === group)) {
      const button = node("button","api-list-request" + (tool.name === apiWorkbench.tool?.name ? " active" : "")); button.type = "button";
      button.append(node("span","api-method",tool.request?.method || tool.method),node("span","",tool.name));
      button.title = tool.name; button.addEventListener("click",() => editExternalTool(tool)); list.append(button);
    }
  }
  if (!tools.length) list.append(node("p","small-note",query ? "没有匹配的接口" : "尚无已保存接口。新建请求可先调试，调通后再保存。"));
  apiControls();
}
function populateApiRequest(tool) {
  apiWorkbench.tool = tool; ++apiWorkbench.generation;
  const draft = tool?.request || {method:tool?.method || "GET",url:tool?.url || "",auth:{type:tool?.key_configured ? "header" : "none",header:tool?.auth_header || "Authorization",scheme:tool?.auth_scheme || "Bearer"}};
  const auth = draft.auth || {}, body = draft.body || {};
  el("tool-editor").dataset.editing = tool?.name || "";
  el("api-current-name").textContent = tool?.name || "未保存的请求";
  el("tool-editor-title").textContent = tool ? "更新助手工具" : "保存为助手工具";
  for (const [id,value] of [["tool-name",tool?.name || ""],["tool-group",tool?.group || ""],["tool-description",tool?.description || ""],["tool-method",draft.method || "GET"],["tool-url",draft.url || ""],["tool-permission",tool?.permission || "read"],["api-timeout",draft.timeout_seconds || 20],["api-auth-type",auth.type || "none"],["tool-auth-header",auth.header || "Authorization"],["tool-auth-scheme",auth.scheme || "Bearer"],["api-auth-username",auth.username || ""],["api-body-mode",body.mode || "none"],["api-body-text",body.text || ""],["api-argument-target",tool?.argument_target || "auto"]]) el(id).value = value;
  el("api-secret-action").value = apiSavedAuth() ? "keep" : "replace";
  el("tool-key").value = ""; el("api-auth-password").value = "";
  el("api-body-secret").checked = Boolean(body.secret); el("api-body-secret-action").value = body.text_configured ? "keep" : "replace";
  renderApiSchema("input",tool?.parameters || {type:"object",properties:{},additionalProperties:false});
  renderApiSchema("output",tool?.output_schema || {});
  el("tool-enabled").checked = tool?.enabled || false;
  for (const [area,rows] of [["api-params",draft.params],["api-headers",draft.headers],["api-form-fields",body.fields]]) {el(area).replaceChildren(); for (const row of rows || []) addApiRow(area,row); if (!rows?.length) addApiRow(area);}
  apiWorkbench.response = null; el("api-response").hidden = true; el("api-response-meta").textContent = "尚未发送"; el("api-response-body").textContent = "发送后在这里显示实际响应。"; el("api-response-headers").replaceChildren(); el("api-pretty-response").hidden = true;
  apiWorkbench.mode = "visual"; el("api-definition").value = ""; el("tool-editor-status").textContent = "";
  syncApiAuth(); syncApiBody(); apiTab("params"); apiConfigMode("visual"); apiNotice(); apiWorkbench.baseline = apiFingerprint(); apiDirty(); renderApiList();
}
async function editExternalTool(tool = null) {
  if (capabilityState.busy || capabilityState.loading || apiWorkbench.loading || apiWorkbench.saving || apiWorkbench.debug) return;
  if (!el("api-workbench").hidden && apiHasChanges() && !confirm("切换接口会丢弃当前未保存草稿，继续？")) return;
  openApiWorkbenchPage();
  apiWorkbench.loading = true; apiControls(); apiNotice("正在读取接口…");
  try {
    const data = tool ? await request(`/api/tools/${encodeURIComponent(tool.name)}`) : null;
    populateApiRequest(data);
  } catch (error) {apiNotice(error.message,true);}
  finally {apiWorkbench.loading = false; apiControls(); el("tool-url").focus();}
}
el("tool-new").addEventListener("click",() => editExternalTool());
el("api-new-request").addEventListener("click",() => editExternalTool());
el("api-request-search").addEventListener("input",renderApiList);
el("api-show-save").addEventListener("click",() => {if (apiConfigMode("visual")) el("tool-editor").requestSubmit();});
el("api-url-clear").addEventListener("click",() => {el("tool-url").value = ""; apiDirty();});
function autoApiName(url) {
  try {
    const segment = new URL(url).pathname.split("/").filter(Boolean).pop() || "";
    let name = segment.toLowerCase().replace(/[^a-z0-9_]/g,"_").replace(/^[^a-z]+/,"");
    if (!name) name = "api_tool";
    if (!/^[a-z]/.test(name)) name = "t_" + name;
    return name.slice(0,48);
  } catch { return ""; }
}
function syncMethodDefaults() {
  const isRead = ["GET","HEAD","OPTIONS"].includes(el("tool-method").value);
  el("tool-permission").value = isRead ? "read" : "write";
  el("api-argument-target").value = isRead ? "query" : "body";
}
el("tool-method").addEventListener("change",syncMethodDefaults);
el("tool-url").addEventListener("input",() => {
  if (apiWorkbench.tool) return; // 编辑已保存接口时不覆盖名称/权限
  if (!el("tool-name").value.trim()) {const name = autoApiName(el("tool-url").value); if (name) el("tool-name").value = name;}
  syncMethodDefaults();
});
function validateApiRequest() {
  if (!el("tool-url").reportValidity() || !el("api-timeout").reportValidity()) return false;
  const draft = apiRequestDraft();
  if (["PUT","PATCH","DELETE"].includes(draft.method) && el("tool-permission").value === "read") {apiNotice("修改或删除请求请选择对应操作权限。",true); return false;}
  if (draft.url.includes("?")) {apiTab("params"); apiNotice("请把 URL 中的查询参数移到「参数」页签，接口地址仅填路径。",true); return false;}
  if (draft.body.mode === "json" && draft.body.text !== null && draft.body.text !== "") {
    try {JSON.parse(draft.body.text);}
    catch {apiTab("body"); apiNotice("JSON 正文格式无效。",true); return false;}
  }
  return true;
}
function apiPreview(draft) {
  const result = structuredClone(draft);
  const rows = items => items.map(item => ({...item,value:item.secret || item.value === null ? "[敏感值已隐藏]" : item.value}));
  result.params = rows(result.params); result.headers = rows(result.headers); result.body.fields = rows(result.body.fields);
  if (result.body.secret) result.body.text = "[敏感正文已隐藏]";
  for (const key of ["token","password"]) if (key in result.auth) result.auth[key] = result.auth[key] === null ? "[使用服务端已存凭据]" : "[已隐藏]";
  return result;
}
function collectTestValues(schema) {
  const values = {};
  for (const [name, def] of Object.entries(schema.properties || {})) {
    if (def && def["x-enabled"] === false) continue;
    if (def && Object.hasOwn(def, "default") && String(def.default) !== "") values[name] = def.default;
  }
  return values;
}
function buildTestRequest() {
  const draft = apiRequestDraft();
  const schema = syncApiSchema("input");
  const properties = schema.properties || {};
  const target = el("api-argument-target").value;
  const inject = Object.keys(properties).length > 0 && (target === "body" || (target === "auto" && !["GET","HEAD","OPTIONS"].includes(draft.method)));
  if (inject) {
    for (const name of (schema.required || [])) {
      const def = properties[name] || {};
      const enabled = def["x-enabled"] !== false;
      const value = Object.hasOwn(def, "default") ? def.default : "";
      if (enabled && String(value == null ? "" : value) === "") {
        apiTab("body"); apiNotice(`请填写「${name}」（必填）。`, true); return null;
      }
    }
    let object = {};
    if (draft.body.mode === "json" && draft.body.text) { try { object = JSON.parse(draft.body.text) || {}; } catch { object = {}; } }
    for (const [name, value] of Object.entries(collectTestValues(schema))) object[name] = value;
    draft.body.mode = "json"; draft.body.text = JSON.stringify(object);
  }
  return {request:draft, permission:el("tool-permission").value};
}
async function sendApiDraft(draft, confirmed) {
  const operation = {id:crypto.randomUUID(),controller:new AbortController(),generation:++apiWorkbench.generation};
  apiWorkbench.debug = operation; apiControls(); apiNotice("正在发送草稿请求…");
  apiWorkbench.response = null; el("api-response").hidden = false; el("api-response-meta").textContent = "正在发送"; el("api-response-body").textContent = "正在等待本次响应…"; el("api-response-headers").replaceChildren(); el("api-pretty-response").hidden = true;
  const body = {request_id:operation.id,request:draft.request,permission:draft.permission,confirmed};
  if (apiWorkbench.tool) body.reuse_tool = apiWorkbench.tool.name;
  try {
    const result = await request("/api/tools/debug","POST",body,operation.controller.signal);
    if (operation.generation !== apiWorkbench.generation || operation.controller.signal.aborted) return;
    apiWorkbench.response = result; renderApiResponse(); apiNotice("已收到实际响应；本次发送未修改工具配置。");
  } catch (error) {
    if (operation.generation !== apiWorkbench.generation || operation.controller.signal.aborted) return;
    el("api-response").hidden = false; el("api-response-meta").textContent = "请求未完成"; apiNotice(error.message,true);
  } finally {if (apiWorkbench.debug === operation) {apiWorkbench.debug = null; apiControls();}}
}
el("api-send").addEventListener("click",() => {
  if (!validateApiRequest() || apiWorkbench.debug || apiWorkbench.saving || apiWorkbench.loading) return;
  let draft;
  try {draft = buildTestRequest();} catch (error) {apiNotice(error.message,true); return;}
  if (!draft) return;
  // 查询类直接发送；修改/付费类才弹确认
  if (draft.permission === "read") { sendApiDraft(draft, false); return; }
  apiWorkbench.pending = draft;
  el("api-send-preview").textContent = JSON.stringify({permission:draft.permission,request:apiPreview(draft.request)},null,2);
  el("api-send-confirm-row").hidden = false; el("api-send-confirm").required = true; el("api-send-confirm").checked = false; el("api-send-dialog").showModal();
});
el("api-send-back").addEventListener("click",() => {apiWorkbench.pending = null; el("api-send-dialog").close();});
el("api-send-dialog").addEventListener("cancel",() => {apiWorkbench.pending = null;});
el("api-send-form").addEventListener("submit",async event => {
  event.preventDefault(); if (!apiWorkbench.pending || apiWorkbench.debug) return;
  const draft = apiWorkbench.pending; apiWorkbench.pending = null;
  const confirmed = el("api-send-confirm").checked; el("api-send-dialog").close();
  await sendApiDraft(draft, confirmed);
});
async function cancelApiRequest() {
  const operation = apiWorkbench.debug; if (!operation) return;
  operation.controller.abort(); apiWorkbench.debug = null; apiControls();
  const text = "已停止等待并请求服务端取消；外部操作或费用可能已生效，结果需核实。未自动重试。";
  apiNotice(text,true); el("api-response-meta").textContent = "等待已取消，结果未知";
  try {
    const result = await request(`/api/tools/debug/${operation.id}/cancel`,"POST");
    if (operation.generation === apiWorkbench.generation && !result.cancelled) apiNotice("等待已停止；服务端当前无可取消请求，外部执行结果需核实。未自动重试。",true);
  } catch {if (operation.generation === apiWorkbench.generation) apiNotice("已停止本地等待，但未能确认服务端取消；外部执行结果需核实。未自动重试。",true);}
}
el("api-cancel-request").addEventListener("click",cancelApiRequest);
function renderApiResponse() {
  const data = apiWorkbench.response; if (!data) return;
  el("api-response").hidden = false;
  el("api-response-meta").textContent = `${data.status} · ${data.elapsed_ms} ms · ${data.content_type || "未提供类型"}${data.truncated ? " · 正文已截断" : ""}`;
  el("api-response-body").textContent = data.body || "（空响应正文）";
  const area = el("api-response-headers"); area.replaceChildren();
  for (const header of data.headers || []) {const row = node("div","api-response-header"); row.append(node("strong","",header.name),node("span","",header.value)); area.append(row);}
  if (!area.childElementCount) area.append(node("p","small-note","服务端未返回响应头。"));
  el("api-pretty-response").hidden = false; apiResponseTab("body");
}
function apiResponseTab(tab) {el("api-response-body").hidden = tab !== "body"; el("api-response-headers").hidden = tab !== "headers"; el("api-response-body-tab").setAttribute("aria-pressed",String(tab === "body")); el("api-response-headers-tab").setAttribute("aria-pressed",String(tab === "headers"));}
el("api-response-body-tab").addEventListener("click",() => apiResponseTab("body"));
el("api-response-headers-tab").addEventListener("click",() => apiResponseTab("headers"));
el("api-pretty-response").addEventListener("click",() => {
  try {el("api-response-body").textContent = JSON.stringify(JSON.parse(apiWorkbench.response.body),null,2); apiResponseTab("body");}
  catch {apiNotice("响应不是 JSON，保留原始正文。");}
});
el("tool-editor").addEventListener("submit",async event => {
  event.preventDefault(); if (apiWorkbench.saving || apiWorkbench.loading || apiWorkbench.debug || !validateApiRequest()) return;
  let parameters, outputSchema;
  try {parameters = syncApiSchema("input"); outputSchema = syncApiSchema("output");}
  catch (error) {el("tool-editor-status").textContent = error.message; el("tool-editor-status").dataset.kind = "error"; return;}
  const draft = apiRequestDraft(), target = el("api-argument-target").value;
  if (Object.keys(parameters.properties || {}).length && (target === "body" || target === "auto" && !["GET","HEAD","OPTIONS"].includes(draft.method))) {
    let object;
    try {object = draft.body.mode === "none" ? {} : draft.body.mode === "json" ? JSON.parse(draft.body.text) : null;}
    catch {object = null;}
    if (!object || typeof object !== "object" || Array.isArray(object) || draft.body.secret) {el("tool-editor-status").textContent = "模型参数注入 Body 时，仅支持不含隐藏敏感字段的 JSON 对象。"; return;}
  }
  const payload = {name:el("tool-name").value.trim(),description:el("tool-description").value.trim(),group:el("tool-group").value.trim(),permission:el("tool-permission").value,enabled:el("tool-enabled").checked,parameters,output_schema:outputSchema,argument_target:target,request:draft};
  apiWorkbench.saving = true; apiControls(); el("tool-editor-status").textContent = "正在保存工具，不发送外部请求…"; el("tool-editor-status").dataset.kind = "";
  try {
    await request(`/api/tools/${encodeURIComponent(payload.name)}`,"PUT",payload);
    updateCapabilityCatalog(await request("/api/tools"));
    populateApiRequest(await request(`/api/tools/${encodeURIComponent(payload.name)}`));
    apiNotice("已保存为助手工具，未发送外部请求。自动对话接入状态见能力页。");
  } catch (error) {el("tool-editor-status").textContent = error.message; el("tool-editor-status").dataset.kind = "error";}
  finally {apiWorkbench.saving = false; apiControls();}
});
function openApiWorkbenchPage() {
  el("api-workbench").hidden = false;
  document.body.classList.add("workbench-open");
}
function closeApiWorkbench() {
  if (apiWorkbench.saving) {apiNotice("正在保存，请等待服务端返回。"); return;}
  cancelApiRequest(); ++apiWorkbench.generation; apiWorkbench.pending = null; el("tool-key").value = ""; el("api-auth-password").value = "";
  el("api-params").replaceChildren(); el("api-headers").replaceChildren(); el("api-form-fields").replaceChildren(); el("api-body-text").value = "";
  el("api-definition").value = ""; apiWorkbench.mode = "visual"; el("api-definition-status").textContent = "";
  el("api-workbench").hidden = true; document.body.classList.remove("workbench-open");
  el("tool-new").focus();
}
el("api-workbench-close").addEventListener("click",closeApiWorkbench);
el("api-workbench").addEventListener("click", event => {
  if (event.target === el("api-workbench")) closeApiWorkbench();
});
let toolCallSelection = null, toolCallController = null;
function openToolCall(tool) {
  if (!tool.enabled || capabilityState.busy || toolCallController) return;
  toolCallSelection = tool;
  el("tool-call-title").textContent = `手动调用：${tool.name}`;
  el("tool-call-description").textContent = tool.kind === "http" ? `${tool.request?.method || tool.method} ${tool.request?.url || tool.url}\n${tool.description}` : tool.description;
  el("tool-call-arguments").value = tool.name === "web_search" ? '{\n  "query": "今日新闻",\n  "count": 3\n}' : "{}"; el("tool-call-confirm").checked = false;
  el("tool-call-confirm-row").hidden = tool.permission === "read"; el("tool-call-confirm").required = tool.permission !== "read";
  el("tool-call-warning").textContent = tool.permission === "read" ? "会发送真实查询请求，不自动重试。" : "会执行真实修改或付费操作；核对参数并勾选确认后才执行，不自动重试。";
  el("tool-call-status").textContent = ""; el("tool-call-result").hidden = true; el("tool-call-submit").disabled = false;
  el("tool-call-dialog").showModal(); el("tool-call-arguments").focus();
}
function closeToolCall() {toolCallController?.abort(); el("tool-call-dialog").close();}
el("tool-call-close").addEventListener("click",closeToolCall);
el("tool-call-dialog").addEventListener("cancel",event => {event.preventDefault(); closeToolCall();});
el("tool-call-arguments").addEventListener("input", () => {el("tool-call-confirm").checked = false; el("tool-call-result").hidden = true;});
el("tool-call-form").addEventListener("submit", async event => {
  event.preventDefault(); if (toolCallController || !toolCallSelection) return;
  let args;
  try {args = JSON.parse(el("tool-call-arguments").value); if (!args || Array.isArray(args) || typeof args !== "object") throw new Error();}
  catch {el("tool-call-status").textContent = "参数必须是 JSON 对象。"; return;}
  const tool = toolCallSelection, controller = new AbortController(); toolCallController = controller;
  el("tool-call-submit").disabled = true; el("tool-call-arguments").disabled = true; el("tool-call-confirm").disabled = true;
  el("tool-call-status").textContent = "正在执行一次请求…"; el("tool-call-status").dataset.kind = ""; el("tool-call-result").hidden = true;
  try {
    const result = await request(`/api/tools/${encodeURIComponent(tool.name)}/call`,"POST",{arguments:args,confirmed:el("tool-call-confirm").checked},controller.signal);
    el("tool-call-result").textContent = JSON.stringify(result,null,2); el("tool-call-result").hidden = false;
    el("tool-call-status").textContent = "已收到服务端结果，内容如下。";
  } catch (error) {
    const text = error.name === "AbortError" ? "已停止等待，服务可能仍在执行或计费，结果未知；未自动重试。" : error.message;
    el("tool-call-status").textContent = text; el("tool-call-status").dataset.kind = "error";
    if (!el("tool-call-dialog").open) capabilityNotice(text,true);
  } finally {
    toolCallController = null; el("tool-call-submit").disabled = false; el("tool-call-arguments").disabled = false; el("tool-call-confirm").disabled = false; el("tool-call-confirm").checked = false;
  }
});
const KB_PAGE = 50;
async function reloadKnowledgeDocuments(append = false) {
  const offset = append ? capabilityState.offset : 0;
  const lib = capabilityState.activeLibraryId ? `&library_id=${encodeURIComponent(capabilityState.activeLibraryId)}` : "";
  const data = await request(`/api/knowledge/personal?limit=${KB_PAGE}&offset=${offset}${lib}`);
  capabilityState.documents = append ? [...capabilityState.documents,...data.documents].filter((item,index,all) => all.findIndex(other => other.id === item.id) === index) : data.documents;
  capabilityState.offset = offset + data.documents.length; capabilityState.total = data.total; renderKnowledgeDocuments();
}
function kbStatusMeta(status) {
  return ({ready:{label:"可用",state:"ready"},processing:{label:"建立索引中",state:"processing"},failed:{label:"处理失败",state:"failed"}})[status] || {label:status || "未知",state:status || "unknown"};
}
function kbSizeText(size) {return typeof size === "number" && Number.isFinite(size) ? `${(size/1024).toFixed(1)} KB` : "—";}
function renderKnowledgeDocuments() {
  const area = el("kb-documents"); area.replaceChildren();
  el("kb-total").textContent = capabilityState.total ? `共 ${capabilityState.total} 份` : "";
  if (!capabilityState.documents.length) {
    area.append(node("p","kb-empty","还没有资料，先在上面的「上传资料」里传一份。"));
    el("kb-more").hidden = true; return;
  }
  const table = node("table","kb-doc-table"), thead = node("thead"), hr = node("tr"), tbody = node("tbody");
  for (const label of ["名称","分组","状态","片段","大小","更新时间","操作"]) hr.append(node("th","",label));
  thead.append(hr);
  for (const doc of capabilityState.documents) {
    const tr = node("tr");
    const nameTd = node("td","kb-doc-name"), wrap = node("div","kb-doc-namewrap");
    const titleSpan = node("span","kb-doc-title",doc.title || doc.filename || "未命名");
    titleSpan.title = doc.title || doc.filename || "";
    wrap.append(titleSpan);
    if (doc.filename && doc.filename !== doc.title) wrap.append(node("span","kb-doc-file",doc.filename));
    nameTd.append(wrap); tr.append(nameTd);
    tr.append(node("td","",doc.group_name || "未分组"));
    const stMeta = kbStatusMeta(doc.status), stTd = node("td"), tag = node("span","kb-status",stMeta.label);
    tag.dataset.state = stMeta.state; stTd.append(tag); tr.append(stTd);
    tr.append(node("td","kb-num",doc.chunks != null ? `${doc.chunks} 段` : "—"));
    tr.append(node("td","kb-num",kbSizeText(doc.size)));
    tr.append(node("td","kb-time",doc.updated_at ? insightTime(doc.updated_at) : "—"));
    const actTd = node("td","kb-doc-actions");
    actTd.append(capabilityButton("查看内容", () => openKbContent(doc)));
    const more = node("details","kb-row-more"), moreSummary = node("summary","","更多");
    const menu = node("div","kb-row-menu");
    menu.append(capabilityButton("改名 / 分组", () => {
      el("kb-rename-dialog").dataset.documentId = doc.id; el("kb-rename-title").value = doc.title; el("kb-rename-group").value = doc.group_name; el("kb-rename-status").textContent = ""; el("kb-rename-dialog").showModal(); el("kb-rename-title").focus();
    }));
    menu.append(capabilityButton("替换", () => {el("kb-replacement").dataset.documentId = doc.id; el("kb-replacement").value = ""; el("kb-replacement").click();}));
    menu.append(capabilityButton("删除", () => {
      if (!confirm(`删除资料「${doc.title}」及其索引？此操作无法撤销。`)) return;
      capabilityAction(async () => {await request(`/api/knowledge/personal/${encodeURIComponent(doc.id)}`,"DELETE"); el("kb-results").replaceChildren(); ++capabilityState.queryId; await reloadKnowledgeDocuments(); capabilityNotice("资料及其索引已删除。");});
    }));
    more.append(moreSummary,menu);
    actTd.append(more);
    tr.append(actTd); tbody.append(tr);
  }
  table.append(thead,tbody); area.append(table);
  el("kb-more").hidden = capabilityState.offset >= capabilityState.total;
}
let kbContentDoc = null, kbChunksDocId = null, kbChunksStatus = "idle";
function showKbContentTab(tab) {
  const text = tab !== "chunks";
  el("kb-content-tab-text").setAttribute("aria-selected", String(text));
  el("kb-content-tab-chunks").setAttribute("aria-selected", String(!text));
  el("kb-content-text").hidden = !text;
  el("kb-content-chunks").hidden = text;
  if (!text) maybeLoadKbChunks();
}
function maybeLoadKbChunks() {
  const doc = kbContentDoc; if (!doc) return;
  if (kbChunksDocId === doc.id && (kbChunksStatus === "ready" || kbChunksStatus === "loading")) return;
  loadKbChunks(doc);
}
async function loadKbChunks(doc) {
  if (!doc) return;
  kbChunksDocId = doc.id; kbChunksStatus = "loading";
  const pane = el("kb-content-chunks");
  pane.replaceChildren(node("p","small-note","正在加载分段片段…"));
  const qs = doc.version ? `?version=${encodeURIComponent(doc.version)}` : "";
  try {
    const data = await request(`/api/knowledge/personal/${encodeURIComponent(doc.id)}/chunks${qs}`);
    if (kbContentDoc !== doc) return;
    kbChunksStatus = "ready";
    const chunks = Array.isArray(data.chunks) ? data.chunks : [];
    if (!chunks.length) { pane.replaceChildren(node("p","kb-empty","这份资料没有可显示的分段。")); return; }
    pane.replaceChildren(...chunks.map(chunk => {
      const wrap = node("div","kb-chunk"), head = node("div","kb-chunk-head");
      head.append(node("span","kb-chunk-ord",`第 ${chunk.ordinal ?? "?"} 段`));
      if (chunk.page != null) head.append(node("span","kb-chunk-page",`第 ${chunk.page} 页`));
      wrap.append(head,node("pre","kb-chunk-text",chunk.text || "（空片段）"));
      return wrap;
    }));
  } catch (error) {
    if (kbContentDoc !== doc) return;
    kbChunksStatus = "error";
    const box = node("div","kb-chunks-error");
    box.append(node("p","kb-empty",`分段片段加载失败：${error.message}`));
    box.append(capabilityButton("重试", () => {kbChunksStatus = "idle"; loadKbChunks(doc);}));
    pane.replaceChildren(box);
  }
}
function openKbContent(doc) {
  kbContentDoc = doc; kbChunksDocId = null; kbChunksStatus = "idle";
  el("kb-content-title").textContent = doc.title || doc.filename || "资料内容";
  const meta = el("kb-content-meta"); meta.replaceChildren();
  meta.append(node("span","",[doc.filename || "文件未提供", doc.group_name || "未分组", kbSizeText(doc.size), doc.chunks != null ? `${doc.chunks} 段` : "片段数未提供", doc.updated_at ? insightTime(doc.updated_at) : "时间未提供"].join(" · ")));
  const download = el("kb-content-download");
  download.href = appPath(`/api/knowledge/personal/${encodeURIComponent(doc.id)}/original`); download.download = doc.filename || "";
  el("kb-content-chunks").replaceChildren(node("p","kb-empty",doc.chunks != null ? `这份资料共 ${doc.chunks} 段，切到「分段片段」查看每段原文。` : "片段信息未提供。"));
  showKbContentTab("text");
  el("kb-content-dialog").showModal();
  loadKbContentText(doc);
}
async function loadKbContentText(doc) {
  const pane = el("kb-content-text"); pane.replaceChildren(node("p","small-note","正在读取原文…"));
  const ext = (doc.filename || "").toLowerCase().split(".").pop();
  if (!["txt","md","markdown"].includes(ext)) {
    pane.replaceChildren(node("p","kb-empty",`该格式（.${ext}）暂不支持在页面里预览正文，请点下方「下载原文」查看。`));
    return;
  }
  try {
    const res = await appFetch(`/api/knowledge/personal/${encodeURIComponent(doc.id)}/original`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    if (kbContentDoc !== doc) return;
    pane.replaceChildren(node("pre","kb-content-pre", text && text.trim() ? text : "（原文为空）"));
  } catch (error) {
    if (kbContentDoc === doc) pane.replaceChildren(node("p","kb-empty",`读取原文失败：${error.message}`));
  }
}
el("kb-content-tab-text").addEventListener("click", () => showKbContentTab("text"));
el("kb-content-tab-chunks").addEventListener("click", () => showKbContentTab("chunks"));
el("kb-content-close").addEventListener("click", () => el("kb-content-dialog").close());
el("kb-content-cancel").addEventListener("click", () => el("kb-content-dialog").close());
el("kb-content-dialog").addEventListener("close", () => {kbContentDoc = null;});
function checkKnowledgeFile(file) {
  if (!file || !capabilityState.supportedFileTypes.some(type => file.name.toLowerCase().endsWith(type))) throw new Error(`请选择服务端支持的文件：${capabilityState.supportedFileTypes.join("、")}。`);
  if (!file.size || file.size > 10 * 1024 * 1024) throw new Error("文件不能为空，且不能超过 10MB。");
}
async function uploadKnowledgeFile(file, documentId = "") {
  checkKnowledgeFile(file);
  const headers = {"Content-Type":"application/octet-stream","X-Local-Settings":"1","X-Doc-Filename":encodeURIComponent(file.name)};
  if (!documentId) {
    headers["X-Doc-Title"] = encodeURIComponent(el("kb-title").value.trim());
    headers["X-Doc-Group"] = encodeURIComponent(el("kb-group").value.trim());
    if (capabilityState.activeLibraryId) headers["X-Doc-Library"] = encodeURIComponent(capabilityState.activeLibraryId);
  }
  const path = documentId ? `/api/knowledge/personal/${encodeURIComponent(documentId)}/replace` : "/api/knowledge/personal/upload";
  capabilityNotice(documentId ? "正在提取新文件并更新索引…" : "正在上传、提取文字并建立索引…");
  const response = await appFetch(path,{method:"POST",headers,body:file});
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.detail?.message || (typeof data?.detail === "string" ? data.detail : `资料处理失败（HTTP ${response.status}）。`));
  el("kb-results").replaceChildren(); ++capabilityState.queryId; await reloadKnowledgeDocuments();
  capabilityNotice(documentId ? "资料已替换，旧片段与索引已移除。" : "资料已保存并建立索引，可查询。");
}
el("kb-upload-form").addEventListener("submit",event => {
  event.preventDefault(); const file = el("kb-file").files[0];
  capabilityAction(async () => {await uploadKnowledgeFile(file); el("kb-upload-form").reset();});
});
el("kb-replacement").addEventListener("change", () => {
  const file = el("kb-replacement").files[0], id = el("kb-replacement").dataset.documentId; if (!file || !id) return;
  if (!confirm(`用「${file.name}」替换这份资料并更新索引？`)) return;
  capabilityAction(() => uploadKnowledgeFile(file,id));
});
el("kb-rename-cancel").addEventListener("click", () => el("kb-rename-dialog").close());
el("kb-rename-form").addEventListener("submit",event => {
  event.preventDefault(); capabilityAction(async () => {
    try {
      await request(`/api/knowledge/personal/${encodeURIComponent(el("kb-rename-dialog").dataset.documentId)}`,"PATCH",{title:el("kb-rename-title").value.trim(),group:el("kb-rename-group").value.trim()});
      el("kb-results").replaceChildren(); ++capabilityState.queryId; await reloadKnowledgeDocuments(); el("kb-rename-dialog").close(); capabilityNotice("资料信息已保存。");
    } catch (error) {el("kb-rename-status").textContent = error.message; el("kb-rename-status").dataset.kind = "error";}
  });
});
el("kb-more").addEventListener("click", () => capabilityAction(() => reloadKnowledgeDocuments(true)));
el("kb-search-form").addEventListener("submit",event => {
  event.preventDefault(); const query = el("kb-query").value.trim(); if (!query) return;
  capabilityAction(async () => {
    const id = ++capabilityState.queryId; el("kb-results").replaceChildren(node("p","small-note","正在检索相关片段…"));
    try {
      const body = {query, top_k:5, group:el("kb-search-group").value.trim()};
      // 试查限定在「当前查看的库」，可包括未选入助手的库；不传则后端按助手所选库（未选=空）。
      if (capabilityState.activeLibraryId) body.library_id = capabilityState.activeLibraryId;
      const data = await request("/api/knowledge/personal/search","POST",body);
      if (id !== capabilityState.queryId) return;
      renderKnowledgeResults(data);
    } catch (error) {el("kb-results").replaceChildren(node("p","small-note",error.message)); throw error;}
  });
});
function kbHitMethod(match, data) {
  const map = {keyword:"关键词",bm25:"关键词",vector:"向量",hybrid:"混合"};
  if (Array.isArray(match.channels) && match.channels.length) return Array.from(new Set(match.channels.map(c => map[c] || c))).join(" + ");
  if (typeof data.hybrid === "boolean") return data.hybrid ? "混合检索" : "关键词检索";
  return data.retrieval_mode === "vector" ? "向量检索" : "关键词检索";
}
function kbMatchPosition(match) {
  const parts = [];
  if (match.page != null) parts.push(`第 ${match.page} 页`);
  if (match.ordinal != null) parts.push(`第 ${match.ordinal} 段`);
  return parts.join(" · ") || "位置未提供";
}
function renderKnowledgeResults(data) {
  const area = el("kb-results"); area.replaceChildren();
  if (["unavailable","error"].includes(data.status)) {
    area.append(node("p","insight-error",data.status === "unavailable" ? "知识库暂不可用，未取得可用依据。" : "检索失败，未取得可用依据。")); return;
  }
  const matches = data.matches || [];
  const header = node("div","kb-result-summary");
  header.append(node("strong","",matches.length ? `找到 ${matches.length} 个相关片段` : "没有找到相关片段"),node("span","small-note",matches.length ? "片段命中不等于答案，请点开原文核对。" : "换个说法，或先上传相关资料。"));
  area.append(header);
  for (const match of matches) {
    const entry = node("div","kb-match");
    const head = node("div","kb-match-head");
    head.append(node("span","kb-match-title",match.title || match.filename || "未命名资料"),node("span","kb-match-pos",kbMatchPosition(match)));
    entry.append(head);
    const sub = node("div","kb-match-sub");
    sub.append(node("span","kb-pill",`命中方式：${kbHitMethod(match,data)}`));
    if (match.group_name) sub.append(node("span","kb-pill",`分组 ${match.group_name}`));
    entry.append(sub);
    const det = node("details","kb-match-excerpt");
    det.append(node("summary","","展开片段原文"),node("p","kb-result-excerpt",match.excerpt || "片段正文未提供"));
    entry.append(det);
    if (match.document_id) {
      const original = node("a","text-button","下载来源原文");
      original.href = appPath(`/api/knowledge/personal/${encodeURIComponent(match.document_id)}/original`); original.download = match.filename || "";
      entry.append(original);
    }
    area.append(entry);
  }
}
function insightNotice(text = "", error = false) {
  el("insights-notice").textContent = text; el("insights-notice").dataset.kind = error ? "error" : "";
}
function insightNumber(value, suffix = "") {
  return typeof value === "number" && Number.isFinite(value) ? `${value}${suffix}` : "未提供";
}
function insightControls(kind) {
  const panel = insightState[kind];
  el(`insights-${kind}-prev`).disabled = panel.loading || panel.offset === 0;
  el(`insights-${kind}-next`).disabled = panel.loading || panel.offset + INSIGHT_PAGE >= panel.total;
  el("insights-refresh").disabled = insightState.kb.loading || insightState.tools.loading || insightState.traces.loading || insightState.errors.loading;
  el(`insights-${kind}`).setAttribute("aria-busy",String(panel.loading));
  const clearBtn = el(`insights-${kind}-clear`);
  if (clearBtn) {
    if (kind === "errors") {
      clearBtn.disabled = panel.loading || panel.total === 0;
    } else {
      let filtersMatch = false;
      try {filtersMatch = JSON.stringify(panel.filters) === JSON.stringify(insightFilterValues(kind));} catch {}
      clearBtn.disabled = panel.loading || panel.total === 0 || !filtersMatch || Object.keys(panel.filters).length === 0;
    }
  }
}
function insightTime(value) {
  if (!value) return "时间未提供";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN",{hour12:false});
}
function insightAnswerType(value) {return ({retrieval_only:"仅检索",tool_only:"仅工具调用",rag:"资料辅助回答",tool_answer:"工具续答",model_answer:"模型回答"})[value] || "未记录";}
function insightTableCell(text) {const td = node("td"); td.append(node("span","insight-cell-text",text)); return td;}
function insightEllipsisCell(text) {
  const td = node("td","insight-text-cell"), span = node("span","insight-truncate");
  const full = text == null ? "" : String(text);
  span.textContent = full; span.tabIndex = 0; span.dataset.fullText = full;
  td.append(span); return td;
}
function insightTableNode(value) {const td = node("td"); td.append(value); return td;}
function insightTableTag(text,variant) {const td = node("td"), tag = node("span","insight-tag",text); tag.dataset.variant = variant; td.append(tag); return td;}
function renderInsightRecords(kind, data) {
  const area = el(`insights-${kind}`), panel = insightState[kind]; area.replaceChildren();
  el(`insights-${kind}-meta`).textContent = `共 ${data.total} 条`;
  el(`insights-${kind}-page`).textContent = data.items.length ? `${panel.offset + 1}–${panel.offset + data.items.length} 条` : "";
  if (kind === "errors") {
    const labelEl = el("insights-tab-errors-label");
    if (labelEl) labelEl.textContent = data.total > 0 ? `异常日志 (${data.total})` : "异常日志";
  }
  if (!data.items.length) {area.append(node("p","insight-empty",panel.offset ? "本页已无记录，请返回上一页或刷新。" : insightFiltersActive(kind) ? "没有匹配的记录，试试调整搜索或筛选条件。" : kind === "errors" ? "暂无异常报错记录。" : "尚无记录。实际问答或调用后可在这里查看。")); return;}
  const statusLabels = {complete:"成功",ok:"成功",empty:"未命中",error:"失败",unavailable:"不可用",not_requested:"未调用",cancelled:"已取消",failed:"执行失败",interrupted:"已打断"};
  const sourceLabels = {text:"文字",voice:"网页语音",device:"硬件设备"};
  const errSourceLabels = {device:"语音硬件",desktop:"桌面节点",model:"模型与语音",tool:"工具调用",system:"服务端"};
  const table = node("table","insight-table"), head = node("thead"), hr = node("tr"), body = node("tbody");
  const columns = kind === "errors"
    ? ["模块","错误码","报错内容与上下文","时间"]
    : kind === "kb"
      ? ["问题","回答类型","得到的答案","时间","操作"]
      : kind === "tools"
        ? ["工具","状态","请求摘要","耗时","时间","操作"]
        : ["渠道/模式","模型 / ASR / TTS","问题","状态","耗时","时间","操作"];
  for (const label of columns) {const th = node("th","",label); th.scope = "col"; hr.append(th);}
  head.append(hr); table.append(head,body);
  for (const item of data.items) {
    const tr = node("tr","insight-row"), time = node("time","small-note",insightTime(item.ts));
    if (kind === "errors") {
      const msgCell = node("td", "insight-text-cell");
      msgCell.append(node("div", "", item.message || item.code));
      if (item.detail) {
        const det = node("details", "");
        det.append(node("summary", "small-note", "上下文详情"), node("pre", "insight-json", insightJson(item.detail)));
        msgCell.append(det);
      }
      tr.append(insightTableTag(errSourceLabels[item.source] || item.source || "系统", "type"), insightTableCell(item.code || "error"), msgCell, insightTableNode(time));
      body.append(tr);
      continue;
    }
    const detail = node("div","insight-row-actions");
    const itemId = kind === "traces" ? item.trace_id : item.id;
    const view = capabilityButton("详情",() => openInsightDetail(kind, itemId));
    const remove = node("button","icon-button insight-remove"); remove.type = "button"; remove.append(icon("trash"));
    remove.setAttribute("aria-label",`删除${kind === "kb" ? "知识库" : kind === "tools" ? "API" : "追踪"}记录 ${itemId}`); remove.title = "删除记录";
    const delTarget = kind === "traces" ? {...item, id: item.trace_id, question: item.user_text || item.trace_id} : item;
    remove.addEventListener("click",() => openInsightDelete(kind, delTarget)); detail.append(view,remove);
    if (kind === "kb") {
      tr.append(insightEllipsisCell(item.question ?? item.query_summary ?? "未记录"),insightTableTag(insightAnswerType(item.answer_type),"type"),insightEllipsisCell(item.answer || "暂无生成回答"),insightTableNode(time),insightTableNode(detail));
    } else if (kind === "tools") {
      const status = node("span","insight-status",statusLabels[item.status] || item.status || "未提供"); status.dataset.state = item.status || "unknown";
      tr.append(insightEllipsisCell(item.tool_name || "未提供"),insightTableNode(status),insightEllipsisCell(item.query_summary || "未提供"),insightTableCell(insightNumber(item.elapsed_ms," ms")),insightTableNode(time),insightTableNode(detail));
    } else {
      const status = node("span","insight-status",statusLabels[item.status] || item.status || "未提供"); status.dataset.state = item.status || "unknown";
      const channel = `${sourceLabels[item.source] || item.source || "未记录"} · ${item.voice_mode || "pipeline"}`;
      const stack = [item.model || null, item.asr_provider ? `ASR:${item.asr_provider}` : null, item.tts_provider ? `TTS:${item.tts_provider}` : null].filter(Boolean).join(" · ") || "未提供";
      const latency = item.first_audio_ms != null ? `${item.first_audio_ms} / ${insightNumber(item.elapsed_ms," ms")}` : insightNumber(item.elapsed_ms," ms");
      tr.append(insightTableCell(channel),insightEllipsisCell(stack),insightEllipsisCell(item.user_text || "未记录"),insightTableNode(status),insightTableCell(latency),insightTableNode(time),insightTableNode(detail));
    }
    body.append(tr);
  }
  area.append(table);
}
const insightDetailState = {kind:null, item:null};
function insightSourceText(source) {return [source.filename || "文件名未提供", source.page != null ? `第 ${source.page} 页` : null, source.ordinal != null ? `片段 ${source.ordinal}` : null].filter(Boolean).join(" · ");}
function insightScoreText(source) {
  const parts = [], label = {bm25:"BM25",rrf:"RRF 融合",cosine:"余弦"}[source.score_type] || source.score_type || "分数";
  if (typeof source.score === "number") parts.push(`${label} ${Number(source.score.toPrecision(4))}`);
  if (typeof source.bm25_score === "number" && source.score_type !== "bm25") parts.push(`BM25 ${Number(source.bm25_score.toPrecision(4))}`);
  if (typeof source.cosine_score === "number") parts.push(`余弦 ${Number(source.cosine_score.toPrecision(4))}`);
  if (typeof source.rrf_score === "number") parts.push(`RRF ${Number(source.rrf_score.toPrecision(4))}`);
  if (Array.isArray(source.channels) && source.channels.length) parts.push(`通道 ${source.channels.join("+")}`);
  return parts.length ? parts.join(" · ") : "分数未提供";
}
function insightJson(value) {return value === null || value === undefined ? "未提供" : typeof value === "string" ? value : JSON.stringify(value,null,2);}
function insightOriginalLink(source,label = "预览当时原文") {
  if (source.original_available === true && source.original_url) {const url = window.assistantPaths.localLink(source.original_url); if (url?.pathname.startsWith(appPath("/api/knowledge/personal/"))) {const link = node("a","text-button",label); link.href = url.href; if (source.filename) link.download = source.filename; return link;}}
  const state = source.original_state, text = state === "deleted" ? "原文已删除，仅保留当时片段快照。" : state === "replaced" ? "原文已替换，仅保留当时片段快照。" : "原文不可下载，仅保留当时片段快照。";
  return node("span","small-note",text);
}
async function openInsightDetail(kind, id) {
  hideInsightTooltip();
  el("insights-list-view").hidden = true; el("insights-detail-view").hidden = false;
  el("insights-detail-meta").textContent = ""; el("insights-detail").replaceChildren(node("p","insight-empty","正在加载详情…"));
  try {
    const data = await request(`/api/insights/${kind}/${encodeURIComponent(id)}`);
    insightDetailState.kind = kind; insightDetailState.item = data;
    if (kind === "traces") renderTraceDetail(data);
    else renderInsightDetail(data);
  }
  catch (error) {el("insights-detail").replaceChildren(node("p","insight-error",error.status === 404 ? "未找到该记录，或详情接口尚未加载。" : `详情加载失败：${error.message}`));}
}
function renderTraceDetail(item) {
  const area = el("insights-detail"); area.replaceChildren();
  el("insights-detail-meta").textContent = `${insightTime(item.ts)} · Turn ${item.trace_id}`;
  const head = node("div","insight-detail-head");
  head.append(node("h2","",item.user_text || "（无用户输入文本）"));
  const meta = node("div","insight-detail-tags");
  meta.append(node("span","insight-tag",`${item.source || "text"} · ${item.voice_mode || "pipeline"}`));
  meta.append(node("span","insight-tag",item.status || "未记录"));
  if (item.model) meta.append(node("span","insight-tag",`${item.provider || ""} ${item.model}`.trim()));
  if (item.asr_provider) meta.append(node("span","insight-tag",`ASR: ${item.asr_provider}`));
  if (item.tts_provider) meta.append(node("span","insight-tag",`TTS: ${item.tts_provider}`));
  if (item.first_audio_ms != null) meta.append(node("span","small-note",`首包 ${item.first_audio_ms} ms`));
  meta.append(node("span","small-note",`总耗时 ${insightNumber(item.elapsed_ms," ms")}`));
  if (item.total_tokens != null) meta.append(node("span","small-note",`Tokens ${item.total_tokens}`));
  if (item.error_code) meta.append(node("span","insight-tag",`错误 ${item.error_code}`));
  head.append(meta); area.append(head);
  const summaryCard = node("div","insight-answer-card");
  summaryCard.append(node("h3","","助手回复"),node("p","insight-answer-text",item.reply_text || "暂无回复正文。"));
  area.append(summaryCard);
  const tools = item.tool_calls || [];
  const toolBox = node("div","insight-answer-card");
  toolBox.append(node("h3","",`工具调用摘要（${tools.length}）`));
  if (!tools.length) toolBox.append(node("p","small-note","本轮未调用工具。"));
  else toolBox.append(node("pre","insight-json",insightJson(tools)));
  area.append(toolBox);
  const audits = item.audits || [];
  const auditBox = node("div","insight-answer-card");
  auditBox.append(node("h3","",`关联知识库与工具审计（${audits.length}）`));
  if (!audits.length) auditBox.append(node("p","small-note","本轮无关联 KB / API 审计细节。"));
  for (const audit of audits) {
    const det = node("details");
    det.append(node("summary","",`${audit.surface} · ${audit.tool_name || "-"} · ${audit.status || "-"} (${insightNumber(audit.elapsed_ms," ms")})`),node("pre","insight-json",insightJson(audit)));
    auditBox.append(det);
  }
  area.append(auditBox);
}
function renderInsightDetail(item) {
  const area = el("insights-detail"), kind = insightDetailState.kind; area.replaceChildren();
  el("insights-detail-meta").textContent = insightTime(item.ts);
  const head = node("div","insight-detail-head"); head.append(node("h2","",item.question ?? item.query_summary ?? "问题未记录"));
  const meta = node("div","insight-detail-tags");
  const typeTag = node("span","insight-tag",insightAnswerType(item.answer_type)); typeTag.dataset.variant = "type"; meta.append(typeTag);
  meta.append(node("span","insight-tag",item.evaluation_score == null ? "未评测" : `得分 ${item.evaluation_score}`));
  meta.append(node("span","insight-tag",item.hit === true ? "检索命中" : item.hit === false ? "未命中" : "命中未记录"));
  meta.append(node("span","small-note",`耗时 ${insightNumber(item.elapsed_ms," ms")}`)); head.append(meta); area.append(head);
  const tabs = node("div","insight-tabs"), panels = {}, addTab = (key,label) => {const b = node("button","",label); b.type = "button"; b.dataset.tab = key; b.setAttribute("aria-pressed","false"); b.addEventListener("click",() => insightDetailTab(key)); tabs.append(b);}, makePanel = key => {const p = node("div","insight-tab-panel"); p.dataset.panel = key; p.hidden = true; panels[key] = p; return p;};
  area.append(tabs);
  addTab("answer","答案对比");
  const answerPanel = makePanel("answer"), grid = node("div","insight-answer-grid"), botPanel = node("div","insight-answer-card");
  botPanel.append(node("h3","","机器人给出的答案"),node("p","insight-answer-text",item.answer || "暂无最终回答。检索片段不等于回答依据的准确结论。"));
  const sources = node("details","insight-answer-sources"); sources.append(node("summary","",`已向模型提供 ${(item.snapshots||[]).length} 个片段（实际引用见正文 [资料N]）`));
  const list = node("ul","insight-sources");
  for (const s of item.snapshots || []) {const li = node("li"); li.append(node("span","",`${insightSourceText(s)} · ${insightScoreText(s)}`),node("span","small-note",s.sent_to_model ? "已送入模型" : "未送入模型"),insightOriginalLink(s,"预览")); list.append(li);}
  if (!(item.snapshots||[]).length) list.append(node("li","small-note","当时未保存片段快照。"));
  sources.append(list); botPanel.append(sources);
  const correctPanel = node("div","insight-answer-card"); correctPanel.append(node("h3","","正确答案"));
  const ta = node("textarea","insight-correct-answer"); ta.rows = 6; ta.placeholder = "可人工填写正确答案供对比；未填写时为空。"; ta.value = item.correct_answer || "";
  const save = node("button","secondary-button","保存正确答案"); save.type = "button"; const status = node("p","small-note");
  save.addEventListener("click",async () => {if (insightDetailState.kind !== "kb") return; save.disabled = true; status.textContent = "正在保存…"; try {const updated = await request(`/api/insights/kb/${encodeURIComponent(item.id)}`,"PATCH",{correct_answer:ta.value.trim() || null}); item.correct_answer = updated.correct_answer ?? null; status.textContent = "已保存。";} catch (error) {status.textContent = error.message;} finally {save.disabled = false;}});
  correctPanel.append(ta,save,status); grid.append(botPanel,correctPanel); answerPanel.append(grid);
  if (insightDetailState.kind !== "kb") {ta.disabled = true; save.hidden = true; status.textContent = "只有知识库问答可填写正确答案。";}
  addTab("snapshots",`回溯文档片段（${(item.snapshots||[]).length}）`);
  const snapPanel = makePanel("snapshots");
  if (!(item.snapshots||[]).length) snapPanel.append(node("p","insight-empty","当时未保存片段快照；历史记录无法回溯，之后的检索会保存当时的片段。"));
  for (const s of item.snapshots || []) {
    const card = node("article","insight-snapshot"); card.append(node("h3","",s.title || s.filename || "片段"),node("p","small-note",`${insightSourceText(s)} · ${insightScoreText(s)} · ${s.sent_to_model ? "已送入模型" : "未送入模型"}`),node("pre","insight-snapshot-excerpt",s.excerpt || "片段正文未保存。"),insightOriginalLink(s));
    snapPanel.append(card);
  }
  addTab("calls",`调用记录（${(item.calls||[]).length}）`);
  const callPanel = makePanel("calls");
  if (!(item.calls||[]).length) callPanel.append(node("p","insight-empty","本次记录没有工具调用。"));
  for (const call of item.calls || []) {
    const card = node("article","insight-call"), header = node("div","insight-record-header");
    header.append(node("h3","",call.tool_name || "工具未提供"),node("span","insight-status",call.status || (call.http_status ? String(call.http_status) : "未提供"))); card.append(header);
    card.append(node("p","small-note",`HTTP ${call.http_status ?? "未提供"} · ${insightNumber(call.elapsed_ms," ms")}${call.error_code ? ` · 错误码 ${call.error_code}` : ""}${call.trigger_question ? ` · 触发问题：${call.trigger_question}` : ""}`));
    const request = node("details"); request.append(node("summary","","请求（脱敏）"),node("pre","insight-json",insightJson(call.request))); card.append(request);
    const response = node("details"); response.append(node("summary","","响应（脱敏）"),node("pre","insight-json",insightJson(call.response))); card.append(response);
    callPanel.append(card);
  }
  if ((item.parse_errors||[]).length) {
    addTab("errors",`解析错误（${item.parse_errors.length}）`);
    const errPanel = makePanel("errors"); errPanel.append(node("p","small-note","以下是文件解析诊断，不是知识片段，不参与召回。"));
    for (const error of item.parse_errors) errPanel.append(node("p","insight-error",typeof error === "string" ? error : error.message || error.error || JSON.stringify(error)));
  }
  for (const panel of Object.values(panels)) area.append(panel);
  insightDetailTab("answer");
}
function insightDetailTab(key) {
  for (const button of el("insights-detail").querySelectorAll(".insight-tabs button")) button.setAttribute("aria-pressed",String(button.dataset.tab === key));
  for (const panel of el("insights-detail").querySelectorAll(".insight-tab-panel")) panel.hidden = panel.dataset.panel !== key;
}
el("insights-detail-back").addEventListener("click",() => {hideInsightTooltip(); el("insights-detail-view").hidden = true; el("insights-list-view").hidden = false;});
function insightFilterValues(kind) {
  const values = {}, q = el(`insights-${kind}-q`).value.trim();
  if (q) values.q = q;
  if (kind === "errors") {
    const source = el("insights-errors-source").value;
    if (source) values.source = source;
    return values;
  }
  if (kind === "kb") {const type = el("insights-kb-type").value; if (type) values.answer_type = type;}
  else if (kind === "tools") {const status = el("insights-tools-status").value; if (status) values.status = status; const name = el("insights-tools-name").value.trim(); if (name) values.tool_name = name;}
  else {const source = el("insights-traces-source").value; if (source) values.source = source; const status = el("insights-traces-status").value; if (status) values.status = status;}
  const since = el(`insights-${kind}-since`).value, until = el(`insights-${kind}-until`).value;
  if (since && until && since > until) throw new Error("起始日期不能晚于结束日期。");
  if (since) values.since = new Date(`${since}T00:00:00`).toISOString();
  if (until) values.until = new Date(`${until}T23:59:59.999`).toISOString();
  return values;
}
function insightFiltersActive(kind) {return Object.keys(insightFilterValues(kind)).length > 0;}
async function loadInsightRecords(kind, offset = 0) {
  const panel = insightState[kind], id = ++panel.requestId;
  clearTimeout(panel.searchTimer); panel.controller?.abort();
  const controller = new AbortController(); panel.controller = controller;
  panel.loading = true; insightControls(kind); hideInsightTooltip();
  const area = el(`insights-${kind}`); area.replaceChildren(node("p","insight-empty","正在加载记录…"));
  el(`insights-${kind}-meta`).textContent = ""; el(`insights-${kind}-page`).textContent = "";
  try {
    const filters = insightFilterValues(kind);
    const params = new URLSearchParams({limit:String(INSIGHT_PAGE), offset:String(offset), ...filters});
    const data = await request(`/api/insights/${kind}?${params.toString()}`,"GET",undefined,controller.signal);
    if (id !== panel.requestId) return;
    if (!Array.isArray(data.items) || !Number.isInteger(data.total) || data.total < 0) throw new Error("审计记录格式无法读取，请更新服务后重试。");
    if (offset > 0 && !data.items.length && data.total > 0) return loadInsightRecords(kind,Math.floor((data.total - 1) / INSIGHT_PAGE) * INSIGHT_PAGE);
    panel.offset = offset; panel.total = data.total; panel.filters = filters; panel.items = data.items; renderInsightRecords(kind,data);
  } catch (error) {
    if (id !== panel.requestId || error.name === "AbortError") return;
    panel.total = 0; panel.offset = 0; panel.items = [];
    area.replaceChildren(node("p","insight-error",error.status === 404 ? "洞察接口尚未加载，请在服务更新后刷新。" : `记录加载失败：${error.message}`));
  } finally {if (id === panel.requestId) {panel.loading = false; panel.controller = null; insightControls(kind);}}
}
async function loadInsights() {
  insightNotice(); await Promise.allSettled([loadInsightRecords("kb"),loadInsightRecords("tools"),loadInsightRecords("traces"),loadInsightRecords("errors")]);
}
for (const kind of ["kb","tools","traces","errors"]) {
  el(`insights-${kind}-prev`).addEventListener("click",() => loadInsightRecords(kind,Math.max(0,insightState[kind].offset - INSIGHT_PAGE)));
  el(`insights-${kind}-next`).addEventListener("click",() => loadInsightRecords(kind,insightState[kind].offset + INSIGHT_PAGE));
}
el("insights-refresh").addEventListener("click",loadInsights);
let insightActiveTab = "kb", insightTipTimer = null;
function showInsightTab(tab) {
  insightActiveTab = ["kb","tools","traces","errors"].includes(tab) ? tab : "kb";
  for (const key of ["kb","tools","traces","errors"]) {
    const active = insightActiveTab === key;
    el(`insights-panel-${key}`).hidden = !active;
    el(`insights-tab-${key}`).setAttribute("aria-selected",String(active));
    el(`insights-tab-${key}`).tabIndex = active ? 0 : -1;
  }
  hideInsightTooltip();
}
function insightTooltip() {
  let tip = document.getElementById("insight-tooltip");
  if (!tip) {
    tip = node("div","insight-tooltip"); tip.id = "insight-tooltip"; tip.hidden = true; tip.setAttribute("role","tooltip");
    tip.addEventListener("pointerenter",() => clearTimeout(insightTipTimer));
    tip.addEventListener("pointerleave",hideInsightTooltip);
    document.body.append(tip);
  }
  return tip;
}
function hideInsightTooltip() {clearTimeout(insightTipTimer); const tip = document.getElementById("insight-tooltip"); if (tip) tip.hidden = true;}
function showInsightTooltip(node) {
  if (!node) return;
  const isHint = node.classList.contains("insight-hint");
  if (!isHint && node.scrollWidth <= node.clientWidth + 1) return;
  clearTimeout(insightTipTimer);
  const text = node.dataset.fullText || node.dataset.tip || node.textContent || "";
  const tip = insightTooltip(); tip.textContent = text; tip.hidden = false;
  const rect = node.getBoundingClientRect(), pad = 8;
  const width = tip.offsetWidth, height = tip.offsetHeight;
  const left = Math.min(Math.max(pad,rect.left),window.innerWidth - width - pad);
  let top = rect.bottom + 6;
  if (top + height > window.innerHeight - pad) top = Math.max(pad,rect.top - height - 6);
  tip.style.left = `${left}px`; tip.style.top = `${top}px`;
}
function insightTipSource(target) {return target instanceof Element ? target.closest(".insight-truncate,.insight-hint") : null;}
el("insights-tab-kb").addEventListener("click",() => showInsightTab("kb"));
el("insights-tab-tools").addEventListener("click",() => showInsightTab("tools"));
el("insights-tab-traces").addEventListener("click",() => showInsightTab("traces"));
el("insights-tab-errors").addEventListener("click",() => showInsightTab("errors"));
el("insights-view").addEventListener("keydown",event => {
  if (!event.target.classList || !event.target.classList.contains("insight-tab")) return;
  if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
  event.preventDefault();
  const order = ["kb","tools","traces","errors"];
  const idx = order.indexOf(insightActiveTab);
  const next = event.key === "Home" ? "kb" : event.key === "End" ? "errors"
    : order[(idx + (event.key === "ArrowLeft" ? order.length - 1 : 1)) % order.length];
  showInsightTab(next); el(`insights-tab-${next}`).focus();
});
el("insights-view").addEventListener("pointerover",event => {const node = insightTipSource(event.target); if (node) showInsightTooltip(node);});
el("insights-view").addEventListener("pointerout",event => {const node = insightTipSource(event.target); if (!node) return; const tip = document.getElementById("insight-tooltip"); if (tip && event.relatedTarget && tip.contains(event.relatedTarget)) return; insightTipTimer = setTimeout(hideInsightTooltip,120);});
el("insights-view").addEventListener("focusin",event => {const node = insightTipSource(event.target) || event.target.querySelector?.(".insight-hint"); if (node) showInsightTooltip(node);});
el("insights-view").addEventListener("focusout",event => {const tip = document.getElementById("insight-tooltip"); if (insightTipSource(event.target) && !tip?.matches(":hover")) hideInsightTooltip();});
el("insights-view").addEventListener("scroll",hideInsightTooltip,true);
window.addEventListener("resize",hideInsightTooltip);
document.addEventListener("scroll",event => {const tip = document.getElementById("insight-tooltip"); if (!tip?.contains(event.target)) hideInsightTooltip();},true);
document.addEventListener("keydown",event => {const tip = document.getElementById("insight-tooltip"); if (event.key === "Escape" && tip && !tip.hidden) {hideInsightTooltip(); event.preventDefault(); event.stopPropagation();}},true);
showInsightTab("kb");
for (const kind of ["kb","tools","traces","errors"]) {
  const panel = insightState[kind], search = el(`insights-${kind}-q`);
  const schedule = event => {if (event.isComposing) return; clearTimeout(panel.searchTimer); panel.searchTimer = setTimeout(() => loadInsightRecords(kind,0),300); insightControls(kind);};
  const controls = kind === "kb"
    ? ["insights-kb-type","insights-kb-since","insights-kb-until"]
    : kind === "tools"
      ? ["insights-tools-status","insights-tools-name","insights-tools-since","insights-tools-until"]
      : kind === "traces"
        ? ["insights-traces-source","insights-traces-status","insights-traces-since","insights-traces-until"]
        : ["insights-errors-source"];
  search.addEventListener("input",schedule); search.addEventListener("compositionend",schedule);
  search.addEventListener("keydown",event => {if (event.key === "Enter" && !event.isComposing) {event.preventDefault(); loadInsightRecords(kind,0);}});
  for (const id of controls) el(id).addEventListener(id.endsWith("-name") ? "input" : "change",id.endsWith("-name") ? schedule : () => loadInsightRecords(kind,0));
  el(`insights-${kind}-reset`).addEventListener("click",() => {search.value = ""; for (const id of controls) el(id).value = ""; loadInsightRecords(kind,0);});
  if (kind === "errors") {
    el("insights-errors-clear")?.addEventListener("click", async () => {
      if (!confirm("清空所有已记录的系统异常日志？")) return;
      try {
        await request("/api/insights/errors", "DELETE");
        await loadInsightRecords("errors", 0);
        insightNotice("异常日志已清空。");
      } catch (error) { insightNotice(error.message, true); }
    });
  } else {
    el(`insights-${kind}-clear`)?.addEventListener("click",() => openInsightDelete(kind));
  }
}
async function openInsightDelete(kind, item = null) {
  hideInsightTooltip();
  const panel = insightState[kind], filters = item ? {} : {...panel.filters};
  if (!item && (!Object.keys(filters).length || panel.loading || !panel.total)) return;
  const pending = {kind,id:item?.id ?? null,filters,total:item ? 1 : 0,busy:false,ready:false};
  insightDeleteState = pending;
  const label = kind === "kb" ? "知识库记录" : kind === "tools" ? "API记录" : "追踪记录";
  el("insight-delete-title").textContent = item ? `删除${label}` : `清空筛选的${label}`;
  el("insight-delete-count").textContent = item ? "将删除 1 条记录" : "正在确认匹配数量…";
  el("insight-delete-status").textContent = ""; el("insight-delete-confirm").disabled = true;
  el("insight-delete-cancel").disabled = false;
  const scope = el("insight-delete-scope"); scope.replaceChildren();
  if (item) scope.append(node("p","",item.question || item.query_summary || item.tool_name || `记录 ${item.id}`));
  else {
    const names = {q:"关键词",answer_type:"回答类型",status:"状态",tool_name:"工具",since:"起始时间",until:"结束时间"};
    for (const [key,value] of Object.entries(filters)) scope.append(node("p","",`${names[key] || key}：${key === "since" || key === "until" ? insightTime(value) : value}`));
  }
  el("insight-delete-dialog").showModal(); el("insight-delete-cancel").focus();
  try {
    if (!item) {
      const params = new URLSearchParams({limit:"1",offset:"0",...filters});
      const data = await request(`/api/insights/${kind}?${params}`);
      if (!Number.isInteger(data.total) || data.total < 0) throw new Error("无法确认匹配数量，请刷新后重试。");
      pending.total = data.total;
    }
    if (insightDeleteState !== pending || !el("insight-delete-dialog").open) return;
    pending.ready = pending.total > 0;
    el("insight-delete-count").textContent = `将删除 ${pending.total} 条记录`;
    el("insight-delete-confirm").disabled = !pending.ready;
  } catch (error) {if (insightDeleteState === pending) el("insight-delete-status").textContent = error.message;}
}
el("insight-delete-cancel").addEventListener("click",() => {if (!insightDeleteState?.busy) el("insight-delete-dialog").close();});
el("insight-delete-dialog").addEventListener("cancel",event => {if (insightDeleteState?.busy) event.preventDefault();});
el("insight-delete-dialog").addEventListener("close",() => {insightDeleteState = null;});
el("insight-delete-form").addEventListener("submit",async event => {
  event.preventDefault();
  const pending = insightDeleteState; if (!pending?.ready || pending.busy) return;
  pending.busy = true; el("insight-delete-confirm").disabled = true; el("insight-delete-cancel").disabled = true;
  el("insight-delete-status").textContent = "正在删除…";
  try {
    let deleted = 1;
    if (pending.id !== null) await request(`/api/insights/${pending.kind}/${encodeURIComponent(pending.id)}?confirm=true`,"DELETE");
    else {const result = await request(`/api/insights/${pending.kind}/clear`,"POST",{...pending.filters,confirm:true,expected_total:pending.total}); deleted = result.deleted;}
    el("insight-delete-dialog").close();
    await loadInsightRecords(pending.kind,insightState[pending.kind].offset);
    insightNotice(`已删除 ${deleted} 条记录。`);
  } catch (error) {
    pending.ready = false;
    el("insight-delete-status").textContent = error.status === 409 ? "匹配数量已变化，请取消并刷新后重新确认。" : `删除未确认成功：${error.message}。请取消并刷新记录核对。`;
    await loadInsightRecords(pending.kind,insightState[pending.kind].offset);
  } finally {pending.busy = false; el("insight-delete-cancel").disabled = false;}
});
let capabilityActiveTab = "tools";
function showCapabilityTab(tab) {
  capabilityActiveTab = tab === "kb" ? "kb" : "tools";
  const tools = capabilityActiveTab === "tools";
  el("capabilities-panel-tools").hidden = !tools;
  el("capabilities-panel-kb").hidden = tools;
  el("capabilities-tab-tools").setAttribute("aria-selected", String(tools));
  el("capabilities-tab-kb").setAttribute("aria-selected", String(!tools));
  el("capabilities-tab-tools").tabIndex = tools ? 0 : -1;
  el("capabilities-tab-kb").tabIndex = tools ? -1 : 0;
}
el("capabilities-tab-tools").addEventListener("click", () => showCapabilityTab("tools"));
el("capabilities-tab-kb").addEventListener("click", () => showCapabilityTab("kb"));
el("capabilities-view").addEventListener("keydown", event => {
  if (!event.target.classList || !event.target.classList.contains("insight-tab")) return;
  if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
  event.preventDefault();
  const next = event.key === "ArrowLeft" || event.key === "Home" ? "tools" : "kb";
  showCapabilityTab(next); el(next === "tools" ? "capabilities-tab-tools" : "capabilities-tab-kb").focus();
});
showCapabilityTab("tools");
el("capability-refresh").addEventListener("click", () => loadCapabilities().catch(error => capabilityNotice(error.message,true)));
function filterSettingsNav() {
  const query = el("settings-search").value.trim().toLowerCase(), nav = el("settings-nav");
  let group = null, hasMatch = false;
  const finalize = () => { if (group) group.hidden = !hasMatch; };
  for (const child of [...nav.children]) {
    if (child.classList.contains("settings-group")) { finalize(); group = child; hasMatch = false; }
    else { const match = !query || child.textContent.toLowerCase().includes(query); child.hidden = !match; if (match) hasMatch = true; }
  }
  finalize();
}
el("settings-search").addEventListener("input",filterSettingsNav);
document.querySelectorAll('#settings-nav [data-action="api-workbench"]').forEach(button => button.addEventListener("click",() => editExternalTool()));
let deviceData = null;
let deviceBusy = false;
let deviceDirty = false;
function renderDevice(data, populate = false) {
  deviceData = data;
  el("device-state").textContent = data.ready ? "设备控制连接已建立" : data.connected ? "设备已连接，正在核对能力" : data.last_bootstrap ? "设备已取得连接配置，等待控制连接" : "设备尚未连接";
  el("device-state-detail").textContent = data.last_error || (data.server_info ? `${data.server_info.name || "设备"} · 固件 ${data.server_info.version || "未知"}` : "");
  el("device-state-detail").hidden = !el("device-state-detail").textContent;
  const publicMode = Boolean(data.public_origin);
  el("device-host-row").hidden = publicMode;
  el("device-host").required = !publicMode;
  el("device-address-title").textContent = publicMode ? "连接到云端服务" : "连接到本机";
  el("device-launch-note").textContent = publicMode
    ? (data.gateway_running ? "设备入口已启动，使用下方固定域名地址。" : "设备入口尚未启动，请检查服务运行状态。")
    : (data.gateway_running ? "设备入口已启动，管理页面仅本机可访问。" : "设备入口未启动。请使用 .\\start.ps1 -Devices 启动服务。");
  el("device-local-url").value = data.ota_url || data.local_ota_url || "";
  if (populate) {
    el("device-host").value = data.setup?.lan_host || data.lan_candidates?.[0] || "";
    el("device-mac").value = data.setup?.device_id || "";
    el("device-original").value = data.setup?.original_ota_url || "";
    el("device-original-recorded").checked = Boolean(data.setup?.original_recorded);
    for (const key of ["text", "brightness", "theme"]) el(`device-${key}`).value = data.preferences[key];
    // Volume lives on the role page but is stored with the device preferences.
    el("device-volume").value = data.preferences.volume;
    applyTuning();
    deviceDirty = false;
  }
  el("device-setup-fields").disabled = deviceBusy || data.connected;
  el("device-preferences-fields").disabled = deviceBusy;
  el("device-copy-local").disabled = deviceBusy || !(data.ota_url || data.local_ota_url);
  el("device-copy-original").disabled = deviceBusy || !data.setup?.original_ota_url;
  el("device-recovery-value").textContent = !data.setup ? "尚未保存原设备设置。" : data.setup.original_ota_url ? "已保存原服务器地址。" : "已记录：原 OTA 字段为空，恢复时需要清空设备中的该字段。";
  el("device-apply").disabled = deviceBusy || deviceDirty || !data.ready;
  el("device-preferences-note").textContent = deviceDirty ? "有未保存修改，请先保存设置。" : "保存与应用是两个独立操作。";
  for (const button of document.querySelectorAll("#devices-view button[type=submit], #device-refresh")) button.disabled = deviceBusy;
  const area = el("device-application"); area.replaceChildren();
  if (!data.last_application) { area.append(node("p","small-note","尚无已保存设置的设备验证结果。")); return; }
  const labels = {volume:"音量", brightness:"亮度", theme:"主题", text:"屏幕文字"};
  const outcomes = {verified:"已读回确认", acknowledged:"设备已确认，未提供读回值", mismatch:"读回值与设置不一致", unsupported:"固件未提供此功能", sent:"已发送，请查看屏幕"};
  for (const [key,result] of Object.entries(data.last_application.results)) {
    const row = node("div","device-result-row");
    row.append(node("span","",labels[key] || key),node("span","",(outcomes[result.state] || result.state) + (result.readback !== null && result.readback !== undefined ? ` · ${result.readback}` : "")));
    area.append(row);
  }
  if (data.last_application.state === "failed") area.append(node("p","small-note","应用未完成，请检查连接。已经执行的部分设置可能已生效。"));
}
async function loadDevices(populate = false) { renderDevice(await request("/api/devices"),populate); }
async function deviceAction(action) {
  if (deviceBusy) return;
  deviceBusy = true; if (deviceData) renderDevice(deviceData);
  try { await action(); notice(); }
  catch (error) { notice(error.message,"error"); }
  finally { deviceBusy = false; if (deviceData) renderDevice(deviceData); }
}
el("device-refresh").addEventListener("click",() => deviceAction(() => loadDevices()));
el("device-setup-form").addEventListener("submit", event => {
  event.preventDefault(); deviceAction(async () => {
    const body = {lan_host:deviceData?.public_origin ? "" : el("device-host").value.trim(),device_id:el("device-mac").value.trim(),original_ota_url:el("device-original").value.trim(),original_recorded:el("device-original-recorded").checked};
    renderDevice(await request("/api/devices/setup","PUT",body),true);
  });
});
el("device-preferences-form").addEventListener("input",() => { deviceDirty = true; if (deviceData) renderDevice(deviceData); });
el("device-preferences-form").addEventListener("submit",event => {
  event.preventDefault(); deviceAction(async () => {
    const body = {text:el("device-text").value,volume:Number(el("device-volume").value),brightness:Number(el("device-brightness").value),theme:el("device-theme").value};
    renderDevice(await request("/api/devices/preferences","PUT",body),true);
  });
});
el("device-apply").addEventListener("click",() => deviceAction(async () => {
  try { renderDevice(await request("/api/devices/apply","POST")); }
  finally { await loadDevices(); }
}));
for (const [id,key] of [["device-copy-local","local"],["device-copy-original","original"]]) {
  el(id).addEventListener("click",async () => {
    const text = key === "local" ? (deviceData?.ota_url || deviceData?.local_ota_url) : deviceData?.setup?.original_ota_url;
    try { await navigator.clipboard.writeText(text); notice("地址已复制。"); }
    catch { notice("无法写入剪贴板，请在输入框中选择地址后手动复制。","error"); }
  });
}
let desktopData = null;
let desktopBusy = false;
function renderDesktopNodes(data) {
  desktopData = data;
  el("desktop-state").textContent = data.online_count > 0
    ? `已连接 ${data.online_count} 台个人电脑`
    : "个人电脑节点（暂无在线电脑）";
  el("desktop-state-detail").textContent = data.last_error || "连接你的 Windows 或 Mac 电脑后，Agent 可看屏幕（Computer Use）、读写文件/剪贴板并请求确认操控。";
  el("desktop-cmd-macos").value = data.commands?.macos || "";
  el("desktop-cmd-windows").value = data.commands?.windows || "";
  for (const os of ["macos", "windows"]) {
    el("desktop-download-" + os).disabled = desktopBusy || !data.gateway_token || !data.websocket_url;
  }
  const list = el("desktop-nodes"); list.replaceChildren();
  const nodes = Array.isArray(data.nodes) ? data.nodes : [];
  if (!nodes.length) {
    list.append(node("p", "small-note", "尚未连接任何 Windows 或 Mac 节点；展开下方「接入新电脑」复制启动命令。"));
    return;
  }
  for (const item of nodes) {
    const card = node("div", `desktop-node-card${item.online ? " online" : ""}`);
    const head = node("div", "desktop-node-head");
    const titleWrap = node("div", "desktop-node-title");
    titleWrap.append(node("strong", "", item.name || item.node_id));
    titleWrap.append(node("span", "desktop-os-badge", item.os === "macos" ? "macOS" : item.os === "windows" ? "Windows" : item.os));
    if (item.is_default) titleWrap.append(node("span", "desktop-default-badge", "默认"));
    head.append(titleWrap);
    head.append(node("span", `desktop-status-dot ${item.online ? "online" : "offline"}`, item.online ? "在线" : "离线"));
    card.append(head);
    const screenInfo = item.screen?.width ? `${item.screen.width}×${item.screen.height}` : "未知分辨率";
    const meta = [item.hostname || item.node_id, screenInfo, ...(item.capabilities || [])].filter(Boolean).join(" · ");
    card.append(node("p", "small-note", meta));
    const acts = node("div", "capability-item-actions");
    if (item.online) {
      const snapBtn = node("button", "secondary-button", "查看当前屏幕"); snapBtn.type = "button"; snapBtn.disabled = desktopBusy;
      snapBtn.addEventListener("click", () => desktopAction(async () => {
        const res = await request(`/api/desktop/nodes/${encodeURIComponent(item.node_id)}/screenshot`, "POST");
        const preview = el("desktop-screen-preview"), img = el("desktop-preview-img");
        const win = res.active_window?.title || res.active_window?.app || "";
        el("desktop-preview-meta").textContent = `${item.name} · ${res.screen?.width || 0}×${res.screen?.height || 0}${win ? ` · ${win}` : ""}`;
        img.src = appPath(`/api/desktop/nodes/${encodeURIComponent(item.node_id)}/screenshot?t=${Date.now()}`);
        preview.hidden = false;
      }));
      acts.append(snapBtn);
    }
    if (!item.is_default) {
      const defBtn = node("button", "secondary-button", "设为默认"); defBtn.type = "button"; defBtn.disabled = desktopBusy;
      defBtn.addEventListener("click", () => desktopAction(async () => {
        renderDesktopNodes(await request("/api/desktop/default", "PUT", {node_id: item.node_id}));
        notice(`已将「${item.name}」设为默认电脑。`, "success");
      }));
      acts.append(defBtn);
    }
    const delBtn = node("button", "text-button", "移除记录"); delBtn.type = "button"; delBtn.disabled = desktopBusy;
    delBtn.addEventListener("click", () => {
      if (!confirm(`移除电脑节点「${item.name}」的记录？`)) return;
      desktopAction(async () => {
        renderDesktopNodes(await request(`/api/desktop/nodes/${encodeURIComponent(item.node_id)}`, "DELETE"));
      });
    });
    acts.append(delBtn);
    card.append(acts);
    list.append(card);
  }
}
function renderPublicDesktopStatus(health) {
  desktopData = null;
  const online = Number(health?.desktop_online_nodes || 0);
  el("desktop-state").textContent = online > 0
    ? `当前云端已连接 ${online} 台个人电脑`
    : "个人电脑节点（公网只读）";
  el("desktop-state-detail").hidden = true;
  const setupBox = document.querySelector(".desktop-setup-box");
  if (setupBox) setupBox.hidden = true;
  const list = el("desktop-nodes"); list.replaceChildren();
  const card = node("div", `desktop-node-card desktop-readonly-card${online > 0 ? " online" : ""}`);
  const head = node("div", "desktop-node-head");
  const titleWrap = node("div", "desktop-node-title");
  titleWrap.append(node("strong", "", "个人电脑节点管理仅限本机回环访问"));
  head.append(titleWrap, node("span", `desktop-status-dot ${online > 0 ? "online" : "offline"}`, online > 0 ? `${online} 台在线` : "暂无在线"));
  card.append(head, node("p", "small-note", "公网访问时已自动隐藏桌面配对令牌、一键启动命令及截屏预览，以保护电脑控制权限。"));
  list.append(card);
}
async function loadDesktopNodes() {
  try {
    const data = await request("/api/desktop");
    const setupBox = document.querySelector(".desktop-setup-box");
    if (setupBox) setupBox.hidden = false;
    el("desktop-state-detail").hidden = false;
    renderDesktopNodes(data);
  } catch (error) {
    if (error.status === 403 || error.code === "desktop_admin_local_only") {
      const health = await request("/health").catch(() => null);
      renderPublicDesktopStatus(health);
      return;
    }
    throw error;
  }
}
async function desktopAction(action) {
  if (desktopBusy) return;
  desktopBusy = true;
  if (desktopData) renderDesktopNodes(desktopData);
  try { await action(); }
  catch (error) { notice(error.message, "error"); }
  finally { desktopBusy = false; if (desktopData) renderDesktopNodes(desktopData); }
}
el("desktop-refresh")?.addEventListener("click", () => desktopAction(() => loadDesktopNodes()));
el("desktop-preview-close")?.addEventListener("click", () => { el("desktop-screen-preview").hidden = true; });
el("desktop-rotate-token")?.addEventListener("click", () => {
  if (!confirm("重置令牌后，所有已连接的 Mac / Windows 电脑都会断开并使用下方新命令重连，确定继续？")) return;
  desktopAction(async () => {
    renderDesktopNodes(await request("/api/desktop/token/rotate", "POST"));
    notice("桌面节点接入令牌已重置。", "success");
  });
});
for (const [btnId, inputId] of [["desktop-copy-macos", "desktop-cmd-macos"], ["desktop-copy-windows", "desktop-cmd-windows"]]) {
  el(btnId)?.addEventListener("click", async () => {
    const val = el(inputId)?.value; if (!val) return;
    try { await navigator.clipboard.writeText(val); notice("启动命令已复制。", "success"); }
    catch { notice("无法写入剪贴板，请手动选中命令复制。", "error"); }
  });
}
function downloadDesktopLauncher(platform) {
  const url = desktopData?.websocket_url, token = desktopData?.gateway_token;
  if (!url || !/^wss?:\/\/[A-Za-z0-9.:[\]_-]+\/[A-Za-z0-9./_-]*$/.test(url) ||
      !token || !/^[A-Za-z0-9_-]+$/.test(token)) {
    notice("启动信息不可用，请在本机刷新电脑节点后重试。", "error");
    return;
  }
  const windows = platform === "windows";
  const lines = windows ? [
    "@echo off", "setlocal DisableDelayedExpansion", "chcp 65001 > nul", 'cd /d "%~dp0"',
    'if exist "desktop_node\\__main__.py" goto run', 'set "PROJECT_DIR="',
    'set /p "PROJECT_DIR=请输入 xiaoyuan 项目目录: "',
    'if not defined PROJECT_DIR goto missing', 'cd /d "%PROJECT_DIR%" || goto missing',
    'if not exist "desktop_node\\__main__.py" goto missing', ":run",
    'set "PYTHON=python"', 'if exist ".venv\\Scripts\\python.exe" set "PYTHON=.venv\\Scripts\\python.exe"',
    '"%PYTHON%" -m desktop_node --server "' + url + '" --token "' + token + '"',
    "pause", "exit /b", ":missing", "echo 未找到 desktop_node，请将脚本放到项目目录后重试。", "pause",
  ] : [
    "#!/bin/bash", 'cd -- "$(dirname -- "$0")" || exit 1', "if [[ ! -f desktop_node/__main__.py ]]; then",
    '  read -r -p "请输入 xiaoyuan 项目目录: " project_dir', '  cd -- "$project_dir" || exit 1', "fi",
    '[[ -f desktop_node/__main__.py ]] || { echo "未找到 desktop_node"; exit 1; }',
    "python=python3", "[[ ! -x .venv/bin/python ]] || python=.venv/bin/python",
    'exec "$python" -m desktop_node --server "' + url + '" --token "' + token + '"',
  ];
  const download = node("a");
  download.download = "xiaoyuan-desktop" + (windows ? ".bat" : ".command");
  const blob = new Blob([lines.join(windows ? "\r\n" : "\n") + "\n"], {type:"text/plain;charset=utf-8"});
  const objectUrl = URL.createObjectURL(blob);
  download.href = objectUrl;
  document.body.append(download);
  download.click();
  download.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  notice(windows ? "脚本包含接入令牌，请仅在自己的电脑上使用。"
    : "脚本包含接入令牌，请勿分享。若无法双击，先在终端执行 chmod +x xiaoyuan-desktop.command。", "success");
}
for (const os of ["macos", "windows"]) {
  el("desktop-download-" + os).addEventListener("click", () => downloadDesktopLauncher(os));
}
let activeDeviceTab = "desktop";
const deviceTabs = {desktop:"desktop-panel", hardware:"hardware-panel"};
function showDeviceTab(tab) {
  activeDeviceTab = tab;
  for (const [name, panelId] of Object.entries(deviceTabs)) {
    const selected = tab === name, button = el("devices-tab-" + name);
    el(panelId).hidden = !selected;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  const load = tab === "hardware" ? loadDevices(!deviceData) : loadDesktopNodes();
  load.catch(error => notice(error.message, "error"));
}
for (const name of Object.keys(deviceTabs)) {
  const button = el("devices-tab-" + name);
  button.addEventListener("click", () => showDeviceTab(name));
  button.addEventListener("keydown", event => {
    if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "desktop" : event.key === "End" ? "hardware"
      : name === "desktop" ? "hardware" : "desktop";
    showDeviceTab(next);
    el("devices-tab-" + next).focus();
  });
}
document.querySelectorAll("[data-device-tab-link]").forEach(button => button.addEventListener("click", () => {
  const tab = button.dataset.deviceTabLink;
  navigate("devices", true, tab);
  el("devices-tab-" + tab).focus();
}));
function renderRuntimeStatus(health) {
  for (const [id, label, online] of [
    ["runtime-hardware", "硬件", health?.device_connected === true],
    ["runtime-desktop", "电脑", health?.desktop_online_nodes > 0],
  ]) {
    const button = el(id);
    button.dataset.online = String(online);
    const status = !health ? "状态未知" : online ? "在线" : "离线";
    button.title = label + "：" + status;
    button.setAttribute("aria-label", button.title);
  }
}
let runtimeStatusLoading = false;
async function loadRuntimeStatus() {
  if (runtimeStatusLoading) return;
  runtimeStatusLoading = true;
  try {
    const health = await request("/health");
    renderRuntimeStatus(health);
    el("context-note").textContent = "历史重建最多 " + health.history_turns + " 轮 / " +
      (health.context_history_chars?.toLocaleString("zh-CN") || "—") + " 字符，旧记录按需查";
  } catch { renderRuntimeStatus(null); }
  finally { runtimeStatusLoading = false; }
}
setInterval(() => {
  if (document.hidden) return;
  if (state.view === "devices" && activeDeviceTab === "hardware" && !deviceBusy) loadDevices().catch(() => { el("device-state").textContent = "无法读取硬件状态"; });
  if (state.view === "devices" && activeDeviceTab === "desktop" && !desktopBusy) loadDesktopNodes().catch(() => {});
  if (state.view === "chat") loadRuntimeStatus();
}, 3000);
function routeView() {
  const path = window.assistantPaths.routePath();
  if (path === "/settings") return {"#api":"connections", "#tts":"connections", "#role":"role", "#capabilities":"capabilities", "#insights":"insights"}[location.hash] || recalled("atoms3r.settingsSection") || "role";
  return {"/devices":"devices"}[path] || "chat";
}
window.addEventListener("popstate", () => navigate(routeView(),false));
(async () => {
  navigate(routeView(), false);
  try {
    applyConfig(await request("/api/settings")); state.loaded = true; refreshControls();
    await loadQwenVoices();
    // Voices must load before the saved TTS config resolves its cloned sample to an id.
    await loadVoices();
    try { applyTtsConfig(await request("/api/settings/tts")); ttsLoaded = true; refreshControls(); }
    catch (error) { el("tts-result").textContent = error.message; }
    await loadSessions();
    await loadDevices(true);
    const active = recalled("atoms3r.active");
    if (active) {
      try {
        state.detail = await request(`/sessions/${encodeURIComponent(active)}`); state.active = active;
        if (state.view === "chat") { el("view-title").textContent = state.detail.title; document.title = `${state.detail.title} · 小圆`; }
      } catch (error) {
        if (error.code === "session_not_found") remember("atoms3r.active",null);
        else notice(error.message,"error");
      }
    }
    renderSessions(); renderMessages();
    if (state.view === "connections" && savedConfig.voice_mode === "pipeline" && savedConfig.api_key_configured) await refreshModelChoices();
    await loadRuntimeStatus();
  } catch (error) { notice(error.message, "error"); }
  refreshControls();
})();
