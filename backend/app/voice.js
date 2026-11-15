(function () {
  "use strict";
  const appPath = window.assistantPaths.path;
  const appFetch = window.assistantPaths.fetch;

  const el = (id) => document.getElementById(id);
  const panel = el("voice-panel");
  if (!panel) return;
  const messages = el("messages");
  const scroll = el("chat-scroll");
  if (!messages || !scroll) return;

  let recorder = null;
  let realtime = null;
  let audioContext = null;
  let playHead = 0;
  const sources = new Set();
  let generation = 0;
  let controller = null;
  let streamDone = false;
  let resetting = false;
  let pendingByte = null;
  let audioFailed = false;
  let voiceMode = false;
  let recording = false;
  let starting = false;
  let progress = null;
  let lastPlay = null;
  let serverTurn = null;
  let playbackReported = false;

  function notifyServer(path, body, id = generation) {
    return appFetch(path, {
      method:"POST", keepalive:true,
      headers:{"Content-Type":"application/json", "X-Local-Settings":"1"},
      body:JSON.stringify(body),
    }).then(async response => {
      if (!response.ok) throw new Error("语音状态未能保存，请刷新查看历史。");
    }).catch(error => {
      if (id === generation) setStage(error.message);
    });
  }

  function reportPlayback(state) {
    if (!serverTurn?.session_id || playbackReported) return;
    playbackReported = true;
    const turn = serverTurn;
    notifyServer("/api/voice/playback", {...turn, state}).then(() =>
      window.atoms3rVoiceMessages?.syncHistory(turn.session_id).catch(() => {}));
  }

  function follow() {
    if (scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 160) {
      scroll.scrollTop = scroll.scrollHeight;
    }
  }
  function setStage(text) { el("voice-stage").textContent = text; }
  function setOrbState(state) { el("voice-orb").dataset.state = state; }
  function setVoiceTitle() {
    el("voice-session-title").textContent = (el("view-title").textContent || "当前对话").trim();
  }
  function clearTranscript() {
    el("voice-current-user").hidden = true;
    el("voice-current-user").textContent = "";
    el("voice-current-assistant").hidden = true;
    el("voice-current-assistant").textContent = "";
  }
  function setUserTranscript(text) {
    const line = el("voice-current-user");
    line.textContent = text;
    line.hidden = false;
  }
  function setAssistantTranscript(text) {
    const line = el("voice-current-assistant");
    line.textContent = text;
    line.hidden = false;
    const area = line.parentElement;
    area.scrollTop = area.scrollHeight;
  }
  function setError(text = "") {
    if (!progress?.article) return;
    let target = progress.article.querySelector(".request-error");
    if (!target) {
      target = document.createElement("div");
      target.className = "request-error";
      progress.article.append(target);
    }
    target.hidden = !text;
    target.textContent = text;
    if (text) follow();
  }
  function setProgress(text) {
    window.atoms3rVoiceMessages?.updateAssistant(progress?.article, text);
    progress?.article?.setAttribute("aria-busy", "true");
    follow();
  }
  function setStopActive(active) {
    if (!el("voice-stop")) return;
    el("voice-stop").disabled = !active;
    el("voice-stop").hidden = !active;
  }
  function setRecordActive(active) {
    starting = false;
    recording = active;
    el("voice-record").textContent = active ? "结束并发送" : "开始录音";
    el("voice-record").classList.toggle("active", active);
    el("voice-record").disabled = false;
    el("voice-record").removeAttribute("aria-busy");
  }
  function setRecordStarting() {
    starting = true;
    recording = false;
    el("voice-record").textContent = "正在开启麦克风…";
    el("voice-record").classList.remove("active");
    el("voice-record").disabled = true;
    el("voice-record").setAttribute("aria-busy", "true");
    setOrbState("connecting");
  }
  function setMode(enabled) {
    if (!enabled) {
      cancelTurn();
      setRecordActive(false);
      clearTranscript();
    }
    voiceMode = enabled;
    document.body.classList.toggle("voice-mode", enabled);
    el("app-shell").inert = enabled;
    el("app-shell").setAttribute("aria-hidden", String(enabled));
    panel.hidden = !enabled || el("chat-view").hidden;
    el("message").hidden = enabled;
    el("message").required = !enabled;
    el("send").hidden = enabled;
    el("use-knowledge").hidden = enabled;
    el("voice-toggle").setAttribute("aria-pressed", String(enabled));
    el("voice-toggle").setAttribute("aria-label", enabled ? "切换到文字输入" : "开始语音输入");
    el("voice-toggle").title = enabled ? "文字输入" : "语音输入";
    el("voice-toggle").querySelector("use").setAttribute("href", enabled ? "#i-keyboard" : "#i-mic");
    el("input-hint").hidden = enabled;
    if (enabled) {
      clearTranscript();
      setVoiceTitle();
      setOrbState("connecting");
      setStage("正在开启麦克风…");
      startRecording();
    } else {
      el("message").focus();
    }
  }

  function createVoiceMessage(text) {
    progress?.article?.remove();
    progress = null;
    clearReply();
    const article = window.atoms3rVoiceMessages?.appendExchange(text, "正在思考…");
    if (!article) throw new Error("对话界面尚未就绪。");
    article.dataset.voiceGeneration = String(generation);
    const stop = document.createElement("button");
    stop.type = "button";
    stop.className = "text-button voice-inline-stop";
    stop.textContent = "停止回答";
    stop.addEventListener("click", () => stopCurrent(article));
    article.querySelector(".message-footer")?.prepend(stop);
    progress = { article, stop, receivedText:false };
    setUserTranscript(text);
    setAssistantTranscript("正在思考…");
    setVoiceTitle();
    setStopActive(true);
    follow();
    return progress;
  }

  function updateAssistant(text) {
    if (!progress) return;
    window.atoms3rVoiceMessages.updateAssistant(progress.article, text);
    setAssistantTranscript(text);
    if (text !== "正在思考…" && text !== "正在播放回答…") progress.receivedText = true;
    follow();
  }

  function clearReply() {
    lastPlay?.remove();
    lastPlay = null;
  }

  function cancelTurn() {
    const previous = serverTurn;
    const unfinished = previous && (!streamDone || sources.size > 0);
    if (unfinished) reportPlayback("interrupted");
    generation += 1;
    if (realtime) {
      realtime.cleanup();
      realtime = null;
    }
    controller?.abort();
    if (unfinished && previous.session_id) notifyServer("/api/voice/stop", previous);
    serverTurn = null;
    playbackReported = false;
    controller = null;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    recorder = null;
    setRecordActive(false);
    stopPlayback();
    audioFailed = false;
    streamDone = false;
    progress?.article?.querySelector(".voice-inline-stop")?.remove();
    progress = null;
    clearReply();
    setStopActive(false);
    setOrbState("idle");
  }

  function fail(error, id) {
    if (id !== generation) return;
    const article = progress?.article;
    reportPlayback("failed");
    cancelTurn();
    setRecordActive(false);
    setStopActive(false);
    if (article) {
      article.querySelector(".voice-inline-stop")?.remove();
      if (!article.querySelector(".message-body")?.textContent?.trim()
          || article.querySelector(".message-body").textContent === "正在思考…") {
        window.atoms3rVoiceMessages?.updateAssistant(article, "语音回答未完成");
      }
      const failure = document.createElement("div");
      failure.className = "request-error";
      failure.textContent = error.message || "连接中断，请重新说话。";
      article.append(failure);
      scroll.scrollTop = scroll.scrollHeight;
    }
    setOrbState("error");
    setAssistantTranscript(error.message || "语音回答未完成");
    setStage(article ? "本次语音未完成" : (error.message || "麦克风未能启动"));
  }

  function stopPlayback() {
    for (const source of sources) {
      source.onended = null;
      try { source.stop(); } catch { }
      source.disconnect();
    }
    sources.clear();
    playHead = 0;
    pendingByte = null;
  }

  function updatePlayback(id) {
    if (id !== generation) return;
    if (sources.size) {
      setOrbState("speaking");
      setStage("正在播放回答…");
      if (progress?.article && !progress.article.querySelector(".voice-inline-stop")) {
        const stop = document.createElement("button");
        stop.type = "button";
        stop.className = "text-button voice-inline-stop";
        stop.textContent = "停止回答";
        stop.addEventListener("click", () => stopCurrent(progress.article));
        progress.article.querySelector(".message-footer")?.prepend(stop);
        progress.stop = stop;
      }
    }
    else if (!streamDone) {
      setOrbState("thinking");
      setStage("正在生成剩余回答…");
    }
    else {
      setStage(audioFailed ? "文字已完成，语音未完整播放" :
        (lastPlay || realtime) ? "回答播放完成" : "文字已完成，未收到语音");
      if (realtime && recording) setStage("正在听…");
      setStopActive(false);
      progress?.article?.querySelector(".voice-inline-stop")?.remove();
      if (lastPlay) lastPlay.hidden = false;
      controller = null;
      setOrbState(audioFailed ? "error" : realtime && recording ? "listening" : "idle");
      reportPlayback(audioFailed || (!lastPlay && !realtime) ? "failed" : "played");
    }
  }

  async function prepareAudio() {
    const ctx = audioContext || (audioContext = new AudioContext());
    if (ctx.state === "suspended") await ctx.resume();
    return ctx;
  }

  function enqueuePacket(encoded, id) {
    if (id !== generation) return;
    if (!realtime && progress && !progress.receivedText) updateAssistant("正在播放回答…");
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length + (pendingByte === null ? 0 : 1));
    let offset = 0;
    if (pendingByte !== null) bytes[offset++] = pendingByte;
    for (let index = 0; index < binary.length; index += 1) bytes[offset + index] = binary.charCodeAt(index);
    pendingByte = bytes.length % 2 ? bytes[bytes.length - 1] : null;
    const frames = Math.floor(bytes.length / 2);
    if (!frames) return;
    const ctx = audioContext;
    const buffer = ctx.createBuffer(1, frames, 24000);
    const channel = buffer.getChannelData(0);
    const view = new DataView(bytes.buffer);
    for (let index = 0; index < frames; index += 1) channel[index] = view.getInt16(index * 2, true) / 32768;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => {
      sources.delete(source);
      source.disconnect();
      updatePlayback(id);
    };
    playHead = Math.max(playHead, ctx.currentTime + 0.03);
    sources.add(source);
    source.start(playHead);
    playHead += buffer.duration;
    updatePlayback(id);
  }

  async function startRealtime(stream,id) {
    const capture = new AudioContext({sampleRate:16000});
    const url = new URL(appPath("/api/voice/realtime"),location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const sid = window.atoms3rVoiceMessages.sessionId();
    if (sid) url.searchParams.set("session",sid);
    let ws,source,mic,receivedDone = false,reply = "",ready = false;
    const closeCapture = () => {
      stream.getTracks().forEach(track => track.stop());
      source?.disconnect(); mic?.disconnect();
      if (capture.state !== "closed") capture.close().catch(()=>{});
    };
    realtime = {cleanup() {closeCapture(); if (ws && ws.readyState < 2) ws.close();},
      finish() {if (ready) mic.port.postMessage("finish");}};
    try {
      await capture.audioWorklet.addModule(appPath("/voice-capture.js"));
      await capture.resume();
      if (id !== generation) return;
      source = capture.createMediaStreamSource(stream);
      mic = new AudioWorkletNode(capture,"voice-capture");
      ws = new WebSocket(url);
      mic.port.onmessage = ({data}) => {
        if (id !== generation || ws.readyState !== WebSocket.OPEN) return;
        ws.send(data);
        if (data === "finish") { ready = false; closeCapture(); }
      };
      setStage("正在连接实时模型…");
      ws.onmessage = ({data:raw}) => {
        if (id !== generation) return;
        const {type,data} = JSON.parse(raw);
        if (type === "error") {fail(new Error(data),id); return;}
        if (type === "idle") {
          cancelTurn(); setStage("对话已结束"); return;
        }
        if (type === "next") {
          if (sources.size) reportPlayback("interrupted");
          stopPlayback(); serverTurn = data; playbackReported = false; reply = "";
          receivedDone = streamDone = false; progress = null;
          clearTranscript(); setOrbState("listening"); setStage("正在听…"); return;
        }
        if (type === "ready") {
          ready = true; serverTurn = data;
          source.connect(mic); mic.connect(capture.destination);
          setRecordActive(true); setOrbState("listening"); setStage("正在听…");
        } else if (type === "thinking") {
          if (!ready) setRecordActive(false);
          setStopActive(true); setOrbState("thinking"); setStage("正在回答…");
        } else if (type === "user") {
          createVoiceMessage(data); window.atoms3rVoiceMessages.bindSession(serverTurn);
          if (reply) updateAssistant(reply);
        } else if (type === "text") {
          reply = data; setAssistantTranscript(data); if (progress) updateAssistant(data);
        } else if (type === "audio") {
          enqueuePacket(data,id);
        } else if (type === "done") {
          receivedDone = true; streamDone = true;
          if (progress) updateAssistant(data.reply);
          window.atoms3rVoiceMessages.completed(data,progress?.article);
          if (!sources.size) updatePlayback(id);
        }
      };
      ws.onerror = () => fail(new Error("实时语音连接失败。"),id);
      ws.onclose = () => {
        if (id !== generation) return;
        closeCapture();
        if (!receivedDone) fail(new Error("实时语音连接已结束。"),id); else setRecordActive(false);
      };
    } catch (error) {
      if (id === generation) fail(error,id);
    }
  }
  async function startRecording() {
    if (recording || starting || resetting || !voiceMode) return;
    cancelTurn();
    const currentId = generation;
    controller = new AbortController();
    setRecordStarting();
    setStage("正在开启麦克风…请在浏览器中允许使用");
    let stream;
    try {
      await Promise.all([
        prepareAudio(),
        navigator.mediaDevices.getUserMedia({ audio: {
          echoCancellation: true, noiseSuppression: true, channelCount: 1,
        } }).then((value) => {
          stream = value;
          if (currentId !== generation || !starting) value.getTracks().forEach((track) => track.stop());
        }),
      ]);
      if (currentId !== generation || !starting) return;
      if (window.atoms3rVoiceMessages.realtime()) {
        await startRealtime(stream,currentId);
        return;
      }
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
      const current = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorder = current;
      const chunks = [];
      current.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      current.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        if (currentId !== generation) return;
        recorder = null;
        finishRecording(chunks, currentId, controller.signal).catch((error) => fail(error, currentId));
      };
      current.start();
      setRecordActive(true);
      setOrbState("listening");
      setStage("正在录音…再次点击结束");
      el("voice-record").focus();
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop());
      fail(new Error("无法使用麦克风或音频设备，请检查浏览器权限。"), currentId);
    }
  }

  function stopRecording() {
    if (!recording) return;
    setRecordActive(false);
    if (realtime && streamDone) {cancelTurn(); setStage("对话已结束"); return;}
    if (realtime) {realtime.finish(); setStage('正在回答…'); setOrbState('thinking'); setStopActive(true); return;}
    if (!recorder) {
      cancelTurn();
      setStage("未开始录音，请重试");
      return;
    }
    if (recorder.state !== "inactive") recorder.stop();
    setOrbState("thinking");
    setStage("正在识别…");
  }

  function toggleRecording() {
    if (recording) stopRecording();
    else startRecording();
  }

  async function finishRecording(chunks, id, signal) {
    if (!chunks.length) throw new Error("没有录到声音，请再试一次。");
    const wav = await toWav(new Blob(chunks, { type: chunks[0].type }));
    if (id !== generation) return;
    setOrbState("thinking");
    setStage("正在识别…");
    const response = await appFetch("/api/voice/asr", {
      method: "POST", signal,
      headers: { "Content-Type": "application/octet-stream", "X-Local-Settings": "1" }, body: wav,
    });
    const data = await response.json().catch(() => null);
    if (id !== generation) return;
    if (!response.ok) throw new Error(data?.detail?.message || "识别失败，请重新说话。");
    const text = (data.text || "").trim();
    if (!text) throw new Error("没听清，请再说一次。");
    createVoiceMessage(text);
    await runTurn(text, id, signal);
  }

  async function toWav(blob) {
    const arrayBuffer = await blob.arrayBuffer();
    const ctx = audioContext || (audioContext = new AudioContext());
    const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
    const channels = decoded.numberOfChannels;
    const frames = decoded.length;
    const merged = new Float32Array(frames);
    for (let channel = 0; channel < channels; channel += 1) {
      const data = decoded.getChannelData(channel);
      for (let index = 0; index < frames; index += 1) {
        merged[index] += data[index] / channels;
      }
    }
    const buffer = new ArrayBuffer(44 + frames * 2);
    const view = new DataView(buffer);
    const writeText = (offset, text) => {
      for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index));
    };
    writeText(0, "RIFF"); view.setUint32(4, 36 + frames * 2, true); writeText(8, "WAVE");
    writeText(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); view.setUint32(24, decoded.sampleRate, true);
    view.setUint32(28, decoded.sampleRate * 2, true); view.setUint16(32, 2, true);
    view.setUint16(34, 16, true); writeText(36, "data"); view.setUint32(40, frames * 2, true);
    let offset = 44;
    for (let index = 0; index < frames; index += 1) {
      const sample = Math.max(-1, Math.min(1, merged[index]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  async function runTurn(text, id, signal) {
    setOrbState("thinking");
    setStage("正在思考…");
    setProgress("正在思考…");
    const packets = [];
    serverTurn = {session_id:window.atoms3rVoiceMessages.sessionId(), turn_id:crypto.randomUUID()};
    playbackReported = false;
    const response = await appFetch("/api/voice/turn", {
      method: "POST", signal,
      headers: { "Content-Type": "application/json", "X-Local-Settings": "1" },
      body: JSON.stringify({ text, ...serverTurn }),
    });
    if (id !== generation) return;
    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => null);
      throw new Error(data?.detail?.message || "请求失败，请检查模型连接。");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (id === generation && !streamDone) {
        const { value, done } = await reader.read();
        if (id !== generation) return;
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          if (id !== generation || streamDone) break;
          const lines = part.split("\n");
          const name = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
          const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
          if (!name || !data) continue;
          const payload = JSON.parse(data);
          if (name === "session") {
            serverTurn = {session_id:payload.session_id, turn_id:payload.turn_id};
            window.atoms3rVoiceMessages.bindSession(payload);
            if (payload.history_persisted === false) setError("历史记录暂时无法写入本机。");
          } else if (name === "stage") {
            if (payload.stage === "llm_first") {
              setOrbState("thinking");
              setStage("正在合成语音…");
            }
          } else if (name === "text") {
            updateAssistant(payload.full);
          } else if (name === "audio") {
            packets.push(payload.pcm);
            enqueuePacket(payload.pcm, id);
          } else if (name === "warning") {
            audioFailed = true;
            setError(payload.message || "语音合成失败，文字回答仍会保留。");
          } else if (name === "done") {
            if (pendingByte !== null) throw new Error("语音数据不完整，请重新说话。");
            streamDone = true;
            el("voice-stage").title = `模型与合成 ${payload.ms}ms`;
            const article = progress?.article;
            window.atoms3rVoiceMessages.completed(payload, article);
            progress = { article };
            if (article && !audioFailed && packets.length) {
              const replay = document.createElement("button");
              replay.type = "button"; replay.className = "text-button"; replay.textContent = "重播";
              replay.hidden = audioFailed || !packets.length;
              replay.addEventListener("click", async () => {
                if (replay.disabled) return;
                replay.disabled = true;
                const audio = packets;
                stopPlayback();
                setStopActive(true);
                try {
                  await prepareAudio();
                  for (const packet of audio) enqueuePacket(packet, id);
                  streamDone = true;
                  progress = { article };
                  updatePlayback(id);
                } catch (error) { replay.disabled = false; return; }
                replay.disabled = false;
              });
              replay.classList.add("voice-inline-play");
              article.querySelector(".message-footer")?.append(replay);
              lastPlay = replay;
              replay.hidden = true;
            }
            updatePlayback(id);
          } else if (name === "error") {
            throw new Error(payload.message || "回答失败，请检查模型与语音配置。");
          }
        }
      }
      if (id === generation && !streamDone) throw new Error("回答连接中断，请重新说话。");
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  function stopCurrent(article = progress?.article) {
    cancelTurn();
    if (article) {
      const status = document.createElement("div");
      status.className = "voice-message-status";
      status.textContent = "回答已停止";
      article.append(status);
    }
    setOrbState("idle");
    setStage("已停止，可继续说话");
  }

  el("voice-toggle").addEventListener("click", () => setMode(!voiceMode));
  el("voice-record").addEventListener("click", toggleRecording);
  el("voice-stop").addEventListener("click", () => stopCurrent());
  el("voice-keyboard").addEventListener("click", () => setMode(false));
  el("voice-exit").addEventListener("click", () => setMode(false));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && voiceMode && !el("settings-dialog").open) {
      event.preventDefault();
      setMode(false);
    }
  });
  window.addEventListener("atoms3r:chat-rendered", cancelTurn);
  window.addEventListener("pagehide", cancelTurn);
  const observer = new MutationObserver(() => {
    const chat = el("chat-view");
    panel.hidden = chat.hidden || !voiceMode;
    if (chat.hidden) cancelTurn();
  });
  const chatView = el("chat-view");
  if (chatView) {
    observer.observe(chatView, { attributes: true, attributeFilter: ["hidden"] });
    panel.hidden = true;
  }
})();
