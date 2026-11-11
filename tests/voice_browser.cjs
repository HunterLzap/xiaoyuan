const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

(async () => {
  const root = path.resolve(__dirname, "..");
  const output = path.join(root, "output/playwright");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launchPersistentContext(path.join(output, "voice-profile"), {
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true, viewport: { width: 1365, height: 900 },
    args: ["--autoplay-policy=no-user-gesture-required"],
  });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const fixtures = {
      "/api/settings": { configured: true, api_key_configured: true, provider: "isolated",
        base_url: "https://example.invalid/v1", model: "isolated-text-model", models_protocol: "disabled",
        system_prompt: "隔离测试", m5stack_enabled: false, environment_overrides: [] },
      "/api/settings/tts": { configured: true, api_key_configured: true, use_text_connection: true,
        tts_model: "mimo-v2.5-tts", tts_voice: "mimo_default", tts_rate: 1, tts_pitch: 0 },
      "/api/voices": { cloned: [] }, "/sessions": [], "/health": { history_turns: 6 },
    };
    await page.route("**/*", async (route) => {
      const name = new URL(route.request().url()).pathname;
      if (name === "/" || name === "/app.css" || name === "/voice.js" || name === "/app.js") {
        const file = name === "/" ? "app.html" : name.slice(1);
        await route.fulfill({ path: path.join(root, "backend/app", file),
          contentType: file.endsWith(".html") ? "text/html" : file.endsWith(".css") ? "text/css" : "text/javascript" });
      } else if (fixtures[name]) {
        await route.fulfill({ body: JSON.stringify(fixtures[name]), contentType: "application/json" });
      } else {
        await route.abort();
      }
    });
    await page.addInitScript(() => {
      const state = window.voiceTest = { turns: [], starts: [], stops: 0, tracksStopped: 0 };
      const nativeFetch = window.fetch;
      const wav = new ArrayBuffer(44 + 4800);
      const view = new DataView(wav);
      const text = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
      text(0, "RIFF"); view.setUint32(4, wav.byteLength - 8, true); text(8, "WAVE");
      text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
      view.setUint16(22, 1, true); view.setUint32(24, 24000, true); view.setUint32(28, 48000, true);
      view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, "data"); view.setUint32(40, 4800, true);
      navigator.mediaDevices.getUserMedia = async () => {
        if (state.permissionWait) await new Promise((resolve) => { state.grant = resolve; });
        return { getTracks: () => [{ stop: () => { state.tracksStopped += 1; } }] };
      };
      window.MediaRecorder = class {
        static isTypeSupported() { return true; }
        state = "inactive";
        start() { this.state = "recording"; }
        stop() {
          this.state = "inactive";
          queueMicrotask(() => {
            this.ondataavailable?.({ data: new Blob([wav], { type: "audio/wav" }) });
            this.onstop?.();
          });
        }
      };
      const create = AudioContext.prototype.createBufferSource;
      AudioContext.prototype.createBufferSource = function () {
        const source = create.call(this);
        const start = source.start.bind(source);
        const stop = source.stop.bind(source);
        source.start = (when) => {
          state.starts.push({ at: performance.now(), when, duration: source.buffer.duration, sample: source.buffer.getChannelData(0)[0] });
          return start(when);
        };
        source.stop = () => { state.stops += 1; return stop(); };
        return source;
      };
      window.fetch = async (url, options) => {
        if (url === "/api/voice/asr") {
          state.asrSignal = options.signal;
          return new Response(JSON.stringify({ text: "隔离测试" }));
        }
        if (url === "/api/voice/reset") {
          if (state.resetFailure) return new Response("{}", { status: 500 });
          return new Response("{}");
        }
        if (url !== "/api/voice/turn") return nativeFetch(url, options);
        const turn = { signal: options.signal };
        const stream = new ReadableStream({
          start(controller) {
            turn.emit = (event, payload) => controller.enqueue(new TextEncoder().encode(
              `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`));
          },
          cancel() { turn.cancelled = true; },
        });
        state.turns.push(turn);
        return new Response(stream);
      };
      state.audio = (index, seconds = 0.2) => {
        const bytes = new Uint8Array(Math.round(24000 * seconds) * 2);
        for (let offset = 0; offset < bytes.length; offset += 2) bytes[offset] = 1;
        let binary = "";
        for (const value of bytes) binary += String.fromCharCode(value);
        state.turns[index].emit("audio", { pcm: btoa(binary) });
      };
    });
    await page.goto("http://127.0.0.1:18001/");
    await page.waitForFunction(() => document.getElementById("context-note").textContent.includes("6"));
    assert(await page.locator("#configure-link").isHidden());
    assert(await page.locator("#notice").isHidden());
    await page.evaluate(() => { document.getElementById("chat-view").hidden = false; });
    assert(await page.locator("#voice-panel").isHidden());
    assert(await page.locator("#message").isVisible());
    assert(await page.locator("#voice-stop").isHidden());
    assert(await page.locator("#messages .message").count() === 0);
    await page.locator("#message").fill("保留的文字草稿");
    await page.locator("#voice-toggle").click();
    assert(await page.locator("#message").isHidden());
    assert(await page.locator("#send").isHidden());
    assert(await page.locator("#voice-record").isVisible());
    await page.waitForFunction(() => document.getElementById("voice-stage").textContent.includes("再次点击"));
    assert.equal(await page.locator("#voice-record").textContent(), "结束并发送");
    await page.locator("#voice-toggle").click();
    assert.equal(await page.locator("#message").inputValue(), "保留的文字草稿");
    await page.locator("#voice-toggle").click();
    const stage = () => page.locator("#voice-stage").textContent();
    const record = async (count) => {
      if (!(await page.locator("#voice-record").textContent()).includes("结束")) {
        await page.locator("#voice-record").click();
        await page.waitForFunction(() => document.getElementById("voice-stage").textContent.includes("再次点击")).catch(async (error) => {
          console.error(await page.locator("#voice-stage").textContent(),
            await page.locator("#notice").textContent(), errors);
          throw error;
        });
      }
      assert.equal(await page.locator("#voice-record").textContent(), "结束并发送");
      await page.locator("#voice-record").click();
      await page.waitForFunction((expected) => window.voiceTest.turns.length === expected, count).catch(async (error) => {
        console.error(await page.locator("#voice-stage").textContent(),
          await page.locator("#notice").textContent(), errors);
        throw error;
      });
    };
    await record(1);
    await page.evaluate(() => { voiceTest.audio(0); voiceTest.audio(0); });
    await page.waitForFunction(() => voiceTest.starts.length === 2);
    assert.equal(await stage(), "正在播放回答…");
    const scheduled = await page.evaluate(() => voiceTest.starts);
    assert(Math.abs(scheduled[1].when - scheduled[0].when - scheduled[0].duration) < 0.001);
    await page.waitForFunction(() => document.getElementById("voice-stage").textContent === "正在生成剩余回答…");
    await page.evaluate(() => {
      voiceTest.audio(0, 0.4);
      voiceTest.turns[0].emit("text", { full: "模拟回答" });
      voiceTest.turns[0].emit("done", { ms: 900 });
    });
    await page.waitForFunction(() => document.getElementById("voice-stage").textContent === "正在播放回答…");
    assert(await page.locator(".voice-inline-play").isHidden());
    await page.waitForFunction(() => document.getElementById("voice-stage").textContent === "回答播放完成");
    assert(await page.locator(".voice-inline-play").isVisible());
    await page.locator(".voice-inline-play").click();
    await page.locator(".voice-inline-stop").click();
    assert.equal(await stage(), "已停止，可继续说话");
    assert(await page.evaluate(() => voiceTest.stops >= 3));
    await record(2);
    await page.evaluate(() => { voiceTest.audio(1, 3); voiceTest.audio(1, 3); });
    await page.waitForFunction(() => document.getElementById("voice-stage").textContent === "正在播放回答…");
    await record(3);
    const startsBefore = await page.evaluate(() => voiceTest.starts.length);
    await page.evaluate(() => {
      voiceTest.audio(1);
      voiceTest.turns[1].emit("text", { full: "迟到的旧回答" });
      voiceTest.turns[1].emit("done", {});
    });
    await page.waitForFunction(() => voiceTest.turns[1].cancelled);
    assert.equal(await page.evaluate(() => voiceTest.starts.length), startsBefore);
    assert.equal(await page.evaluate(() => voiceTest.turns[1].signal.aborted), true);
    assert(!(await page.locator(".voice-assistant").last().textContent()).includes("迟到"));
    await record(4);
    await page.evaluate(() => voiceTest.turns[3].emit("error", { message: "模拟模型连接失败" }));
    await page.waitForFunction(() => document.getElementById("voice-stage").textContent === "本次语音未完成");
    assert((await page.locator(".voice-assistant").last().textContent()).includes("模拟模型连接失败"));
    await record(5);
    await page.evaluate(() => {
      voiceTest.turns[4].emit("warning", { message: "语音合成失败，文字保留" });
      voiceTest.turns[4].emit("text", { full: "保留的文字" });
      voiceTest.turns[4].emit("done", {});
    });
    await page.waitForFunction(() => document.getElementById("voice-stage").textContent === "文字已完成，语音未完整播放");
    assert((await page.locator(".voice-assistant").last().textContent()).includes("保留的文字"));
    await page.evaluate(() => { voiceTest.permissionWait = true; });
    await page.locator("#voice-record").click();
    await page.locator("#voice-record").click();
    const stoppedBefore = await page.evaluate(() => voiceTest.tracksStopped);
    await page.evaluate(() => { voiceTest.grant(); voiceTest.permissionWait = false; });
    await page.waitForFunction((count) => voiceTest.tracksStopped > count, stoppedBefore);
    assert.equal(await page.evaluate(() => voiceTest.turns.length), 5);
    await page.locator("#voice-toggle").click();
    await page.locator("#voice-toggle").click();
    await page.waitForFunction(() => document.getElementById("voice-stage").textContent.includes("再次点击"));
    for (const width of [1365, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const theme of ["light", "dark"]) {
        await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
        for (const mode of ["voice", "text"]) {
          const geometry = await page.locator("#chat-form").evaluate((form) => ({
            left: form.getBoundingClientRect().left, right: form.getBoundingClientRect().right,
            height: form.getBoundingClientRect().height,
            width: window.innerWidth, scroll: form.scrollWidth, client: form.clientWidth,
          }));
          assert(geometry.left >= 0 && geometry.right <= geometry.width && geometry.scroll <= geometry.client + 1,
            JSON.stringify(geometry));
          assert(geometry.height < 180, JSON.stringify(geometry));
          await page.screenshot({ path: path.join(output, `voice-${width}-${theme}-${mode}.png`) });
          await page.locator("#voice-toggle").click();
        }
      }
    }
    assert.deepEqual(errors, []);
    const result = { passed: true, scenarios: [
      "audio before done", "ordered contiguous scheduling", "queue gap feedback",
      "done waits for playback", "replay and stop", "record interrupts playback",
      "late old events ignored", "model error", "TTS partial failure keeps text",
      "release before permission", "desktop/mobile light/dark",
      "single composer default text", "mode switch preserves draft", "messages in standard conversation", "click-to-start/stop recording", "inline replay and stop",
    ], scheduled };
    fs.writeFileSync(path.join(output, "voice-results.json"), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
