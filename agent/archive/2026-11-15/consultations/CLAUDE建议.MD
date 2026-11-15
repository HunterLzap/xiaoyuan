I'll verify the candidate services and pricing against official sources first, since several of the names you were given may not be real or current.

Status: I've verified the Volcengine, Alibaba, OpenAI, Gemini and MiMo docs and pricing and run the cost math. One last check on regional availability, then I'll write up the full consultation.

Status: research is done. Below is the consultation, with each section tagged **[Verified]**, **[Judgment]** or **[Test]**. All prices were checked on 2026-10-31 against official pages unless I say otherwise.

## 0. Short answer

Don't frame the first step as ASR→LLM→TTS versus native. The browser audio front end is needed in both: continuous capture, a playback path the browser's echo canceller can use as a reference, instant local stop, and mute. That front end is where "no headphones" is won or lost. **[Judgment]**

On the backend I recommend prototyping a native realtime model first (Qwen-Audio-3.1-Realtime) and keeping your cascade as a "my cloned voice" mode. Both modes would share one UI and one SQLite history.

## 1. Recommended approach

**Native realtime via Qwen-Audio-3.1-Realtime, with your backend as a thin relay and history store.** **[Judgment, built on verified facts]**

- **Turn-taking:** The official guide describes a `smart_turn` mode that combines acoustic and semantic cues. Filler sounds such as "嗯" or "啊" do not interrupt the conversation.
- **Rejecting others' voices:** In smart_turn mode you can pass pre-recorded audio of the target user, and the model locks onto that speaker and masks other voices and background noise. This is the only vendor feature I found aimed at TV and bystander speech.
- **Ambient speech:** When speech is detected but judged not to be a valid turn, the server sends an "ambient transcription" event instead of starting a turn, and that text never enters the context.
- **History:** You can inject history with `conversation.item.create` (user/assistant messages, with `previous_item_id` for placement). `max_history_turns` runs 1–50, default 20. SQLite stays the source of truth, and each session is seeded from it.
- **Audio context limit:** Audio history is capped at 50 turns or 300 cumulative seconds. Reopening a conversation therefore has to restore text, not audio.
- **Tools and cloning:** Function calling, web search and voice cloning are supported.
- **Echo handling:** This is the key caveat. Alibaba's own protocol table says WebSocket has no echo cancellation and the client must handle it, while WebRTC has it built in. Their official WebSocket demo even mutes the mic while the AI speaks and says interruption needs headphones. So the model does not replace client-side AEC (see Problem 3, Q10).
- **Protocols:** WebRTC is browser-native; AOQ is not supported in browsers. I did not read the WebRTC integration page for this model, so check its signaling and auth before committing.
- **What you give up:** The model's own speech uses Alibaba's voices or Alibaba-cloned voices. Cloned voices must be created with the realtime model as `target_model`. Your MiMo clone cannot be used inside the model's output.

**Hybrid that keeps the MiMo voice:** `modalities: ["text"]` turns off speech output. You then use the model as a listener (turn detection, ambient filtering, transcripts) and speak its text through MiMo. The cost is the model's first text sentence plus a full MiMo synthesis per sentence (see the MiMo caveat below). **[Test]**

## 2. Alternative

**Keep the cascade** if your MiMo voice identity is non-negotiable, or if A/B listening shows you can't accept another voice. Upgrade it with:

- browser VAD plus Smart Turn for turn-end detection,
- streaming ASR,
- WebRTC or a verified AEC-friendly playback path,
- a turn-id cancel protocol.

One verified blocker for this route:

- **MiMo clone streaming:** the official doc (updated 2026-07-15) says `mimo-v2.5-tts-voiceclone` has no low-latency streaming yet; its "stream" mode returns the whole result once, after all inference is done. Preset-voice `mimo-v2.5-tts` does stream. For a cloned voice, time-to-first-audio therefore equals full-sentence synthesis time, so keep the first chunk very short. Re-test, because this may have changed.
- **MiMo price:** The same page lists TTS as limited-time free. Don't build a budget on that.

## 3. Bottlenecks, fixes, resources

| Bottleneck                         | Fix                                                          | Resources                                                    |
| ---------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| Waiting for a fixed silence window | VAD with a short stop, then Smart Turn or the model's own turn logic | Smart Turn on CPU, or nothing locally on the native route    |
| Whole-utterance ASR (SenseVoice)   | Streaming ASR or native model                                | Cloud ASR (Volcengine is listed at ¥1/hour post-paid for streaming ASR 2.0) or sherpa-onnx streaming |
| Cloned-voice TTS not streaming     | Short first clause; or switch route                          | None                                                         |
| Echo / false barge-in              | AEC-friendly playback, pause-then-confirm interruption       | Front-end work                                               |
| TV and bystander speech            | Voiceprint (Qwen) or hardware directionality                 | Qwen feature, or mic hardware                                |
| Cancel propagation                 | Turn-id protocol (Problem 3, Q9)                             | Backend work                                                 |
| 2 CPU / 2 GB server                | Native route: relay only. Cascade: keep heavy models off-box | Measure                                                      |

### Problem 1: latency

**Three different numbers:**

- **Vendor claims.** Seeduplex says stop-detection latency is about 250 ms shorter and barge-in rate 40% lower than half-duplex models, with interruption latency about 300 ms shorter. These are relative figures from the Doubao app, not end-to-end. OpenAI's GPT-Live-1 has a reported turn-taking latency of 0.798 s versus 1.41 s, which is also vendor-reported.
- **Time to first packet.** Not published for any candidate.
- **End-to-end** (you stop talking until you hear audio). Nobody can quote this for your setup. Measure it by recording the mic and the speaker output and comparing timestamps.

**Your seven questions:**

1. **Likely bottlenecks:** the end-of-turn wait, ASR finalization, the clone TTS first byte, and the LLM's first speakable clause. All of them need measuring. Instrument eight timestamps: speech end (ground truth from the recording), turn decision, ASR final, LLM first token, first speakable segment, TTS first byte, first sample scheduled, and `AudioContext.outputLatency` (plus `baseLatency`).
2. **SenseVoice** is not natively streaming. A sherpa-onnx project lists it as non-native streaming. A FunASR maintainer's answer, quoted in a GitHub issue, points to paraformer-zh-streaming for real-time use, but a user there called its accuracy weak and noted it was last updated January 2024. Candidates: sherpa-onnx streaming zipformer (Chinese or bilingual), cloud streaming ASR, or the native model. **[Test on your speech]**
3. **TTFT alone is not enough.** What matters is time to the first speakable segment, then TTS first audio, then the buffer. Cut the first chunk at the first clause, a few Chinese characters, and send later chunks as sentences.
4. **A faster text LLM** only shrinks the LLM slice. Non-reasoning flash-class settings matter more than the vendor. I can't quantify the gain without your measurements.
5. **Native models remove** the ASR-final wait, the text hand-off and sentence segmentation. They do **not** remove network RTT, the playback buffer, echo handling or provider queuing.
6. **Gateway effects.** TokenDance is an HTTP gateway compatible with the OpenAI, Claude and Gemini protocols, with base URL `https://tokendance.space/gateway/v1`. I found no evidence it relays realtime WebSocket protocols. Plan on direct provider keys for voice. Compare gateway versus direct LLM p50/p95, and watch context length, since prefill grows with history.
7. **App-controllable:** endpointing, segmentation, prewarmed connections, prompt caching, speculative LLM start on partial transcripts, buffer size, cancellation. **Provider-limited:** TTS synthesis speed, model prefill, the realtime model's internal turn logic.

### Problem 2: turn-end detection

| Approach                                | Strength                            | Limit                                                      |
| --------------------------------------- | ----------------------------------- | ---------------------------------------------------------- |
| Fixed silence                           | Simple                              | Cuts off thinkers, or feels slow                           |
| Silero-class VAD                        | Cheap; good at "is anyone speaking" | Says nothing about completeness or who is speaking         |
| ASR endpointing                         | Free with streaming ASR             | Mostly acoustic and punctuation-based                      |
| Text-semantic                           | Understands unfinished sentences    | Needs a transcript, so adds latency unless run on partials |
| Smart Turn (audio)                      | Uses prosody                        | Needs a VAD trigger; accuracy varies                       |
| Built-in (Qwen `smart_turn`, Seeduplex) | Integrated                          | Vendor-dependent                                           |

Answers:

1. **Best fit for casual Mandarin:** a hybrid. Use a short-stop VAD, then an audio turn model, plus a timeout fallback. On the native route, use the vendor's mode. **[Judgment]**
2. **VAD limits:** yes. VAD detects speech presence, not completeness and not speaker identity.
3. **Semantic detection latency:** yes, unless it runs on streaming partials ahead of time.
4. **Your backend VAD:** I haven't seen your code. Check whether it accepts 16 kHz frames, exposes start/stop callbacks, and can run per-connection. What is still missing: a streaming protocol, a listening/thinking/speaking state machine, a barge-in policy and cancellation.
5. **Where models run:** vad-web ships a roughly 2 MB WASM VAD model for the browser. Smart Turn v3 is about 8 MB, runs in 12 ms on modern CPUs, 60 ms on a c8g.medium and about 95 ms on a t3.medium (2 vCPU), and lists Chinese accuracy of 88.57% on the vendor's own set. A third-party Chinese benchmark shows noticeably lower F1 for Smart-Turn-v3 on a different Chinese dataset. Don't trust either number until you test your own speech. Memory use isn't published.
6. **Noise vs. speech:** different techniques. Keyboard, fan and impacts are handled by noise suppression plus VAD gating plus a minimum duration. TV and bystanders are speech, so VAD can't separate them. That needs a speaker-aware method: a voiceprint, directional hardware, or "is this addressed to me" logic.

### Problem 3: speaker interruption

1. **When built-in AEC is enough:** when the audio you play goes through a path the browser uses as its echo reference, at moderate volume, with a fixed mic/speaker position. Evidence is mixed and partly old. A WebRTC issue reports that Chrome cancelled only audio from the RTCPeerConnection, while Safari cancelled non-WebRTC audio and Firefox depended on matching sample rates. A W3C thread notes newer Chrome applies echo cancellation across all browser audio. Behavior differs by browser, OS and version, so this needs a test matrix. **[Test]**
2. **Where the reference comes from:** the browser's audio pipeline, not your code. There is currently no way for a page to choose the reference source.
3. **Web Audio PCM playback:** it may not be a reliable reference. A 2026 troubleshooting guide says only the browser's standard playback paths or WebRTC receiver tracks reliably serve as reference; custom Web Audio playback may not. This is a secondary source, so confirm on your own browsers.
4. **Verification:** play TTS with nobody speaking, record the raw mic track, and measure the residual level against the playback level. Do this per browser, device and volume. If the residual is high, change the playback path. Options: an unmuted `` element on a loopback RTCPeerConnection (a known, awkward workaround), a real WebRTC receive track, or a software AEC in an AudioWorklet with an explicit reference.
5. **WebRTC vs WebSocket:** both are transport. AEC is browser audio processing on the capture side, tied to the render path. WebRTC helps because your playback becomes a path the AEC knows. It is not automatic for custom playback.
6. **AEC3, residual suppression, noise suppression, double-talk detection:** all are bundled in the browser's WebRTC processing and you can't tune them there. Only if they fall short would you move to WebRTC AudioProcessing in WASM or a native client.
7. **Preserving your speech during double-talk:** the canceller adapts, but strong echo can distort near-end speech. Reduce echo at the source (lower volume, duck TTS on suspected speech). Confirm real interruption with content, not energy alone: duration, transcript, or the voiceprint.
8. **Not cancelling on a cough or "嗯":** use pause-then-confirm. LiveKit does exactly this: `interruption.min_duration`, `min_words`, `false_interruption_timeout` and `resume_false_interruption` (defaults 2.0 s and true). Pause playback within about 100 ms, then either cancel on confirmation or resume. **A Mandarin trap:** Pipecat's `MinWordsUserTurnStartStrategy` counts a Chinese transcript as one word, so a "min 3 words" setting blocks interruptions. Count characters instead.
9. Immediate stop, front and back:
   - **Browser:** stop every scheduled `AudioBufferSourceNode` and flush the worklet ring buffer. Keep chunks small. Alibaba's sample clears its player queue on `speech_started` and notes that chunk size affects cancel latency.
   - **Backend:** send `response.cancel`, cancel LLM and TTS tasks, and tag every audio chunk with a turn id so stale chunks are dropped.
   - **History:** store only the text that was actually played.
10. **Does native replace AEC?** No. Per Alibaba's own table, WebSocket has no echo cancellation. Model-side features (smart_turn, voiceprint) decide whether to interrupt but don't remove echo from the input. For Seeduplex, the API docs I read describe input-level and noise-level requirements and say nothing about speaker echo. The "interference-resistant" demos come from the Doubao app, and I can't confirm the API matches them.

## 4. Candidates and pricing (verified 2026-10-31)

### A. Qwen-Audio-3.1-Realtime (Alibaba Cloud Model Studio)

**Names:** `qwen-audio-3.1-realtime-plus`, `qwen-audio-3.1-realtime-flash`, and the older `qwen-audio-3.0-realtime-plus/flash` are all real. Two doc inconsistencies are worth checking in the console:

- The guide's "supported models" list names 3.1-plus, 3.0-plus and 3.0-flash.
- A separate flash page exists. It says it was updated Oct 28, 2026.

**Prices per million tokens:**

- **Plus (Beijing):** text input ¥5, audio input ¥40, text output ¥40, audio output ¥150, with 60 RPM and 100,000 TPM. In Singapore it is $0.8 / $6.4 / $6.4 / $24.
- **Flash (Beijing):** $0.212 text in, $0.848 audio in, $0.636 text out, $1.696 audio out. Singapore is slightly higher.
- **When audio is output:** only audio is charged; the accompanying text is free.
- **Audio conversion:** 12.5 tokens per second in both directions for realtime models, with anything under 1 s counted as 1 s.
- **History is re-billed:** earlier turns' audio and text are billed as input again on later turns.
- **Free quota:** documented for the 3.0 series in a secondary article (1M tokens). I could not confirm it for 3.1.

**Limits:**

- **Concurrency:** no separate WebSocket concurrency limit.
- **Max session length:** not found.
- **Mandarin:** Mandarin and many dialects are listed.
- **Mainland access:** Beijing-region pricing and keys exist. Whether your specific account qualifies is **[Test]**.

### B. Volcengine Seeduplex (豆包实时语音模型 3.0)

**What it is:** a native full-duplex model. The API launched June 18 as an invite test. I couldn't confirm whether it is still invite-only or whether a personal account can activate it. Check the console. Don't rely on a third-party article claiming a huge free quota and ¥0.012/minute: it conflicts with the official token pricing, so ignore it.

**API facts:**

- It uses a WebSocket with JSON events, model `1.2.6.1`, 16 kHz input, 24 kHz output, and supports tools and cloned voices.
- Input must be sent in 20 ms frames at real-time pace, and the model needs a continuous stream or explicit mute/unmute events.
- **History:** inject user/assistant pairs, or reuse the previous session id. The server keeps the last 20 turns by default. Instructions plus history are capped at 64K tokens.
- **Idle limit:** a connection with no interaction for 10 minutes is released.
- **Rate limits:** default 60 QPM and 100K TPM.

**Prices per million tokens:**

- Text input ¥10, audio input ¥80, cached text ¥5, cached audio ¥5, text output ¥80, audio output ¥300.
- Audio converts at about 6.25 tokens per second of input and 25 per second of output.
- Input tokens include context, system prompt and cloning audio.
- **Cloned voice slots:** post-paid ¥138 per voice, charged at first synthesis, and usable with the realtime model.
- **Billing-page inconsistency:** the page's worked example uses a text-output rate that doesn't match its table. Verify against your first bills.

### C. Cascade with faster text LLM and your TTS

- **Text model:** unconfirmed. Check your TokenDance logs.
- **TTS options:** MiMo (see caveats above), or Volcengine TTS 2.0 at ¥3 per 10,000 characters post-paid.
- **ASR:** see Problem 1.

### D. Verified but probably unusable from mainland China

- **OpenAI:** gpt-realtime-2.1 audio costs $32 in, $64 out, $0.40 cached per million. The mini is $10/$20 (secondary source). OpenAI's supported-country page says a location not listed is unsupported, and China was not on that list when API traffic was blocked in 2024. That is dated news, so recheck the current list. **GPT-Live-1** is full duplex at $0.05 per minute, billed per second, with backend model usage extra. OpenAI's cost guide treats idle session time as billable.
- **Gemini 3.8 Live:** official page shows $3 per million audio input and $12 per million output (about $0.005 and $0.018 per minute). I did not verify mainland availability.

### Cost estimate

Scenario: 10 min of your speech, 10 min of AI speech, 30 days. Floors exclude context replay. The replay figures rest on my assumptions: 60 turns per day, and about 2,700 spoken characters per day. Treat them as ranges.

| Option                   | Floor (speech only)                                          | With context replay                                          |
| ------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| Qwen plus (Beijing)      | ≈ ¥1.4/day ≈ ¥43/mo                                          | up to ≈ ¥9/day if a full 3,750-token audio history is re-billed each turn |
| Qwen flash 3.1 (Beijing) | ≈ $0.019/day ≈ $0.6/mo                                       | up to ≈ $5.7/mo                                              |
| Seeduplex                | ≈ ¥5.0/day ≈ ¥150/mo (including ~2,700 chars of text output at ¥80/M) | cached ≈ +¥2.4/day; uncached worst case ≈ +¥38/day           |
| OpenAI gpt-realtime-2.1  | ≈ $0.96/day ≈ $29/mo                                         | cached ≈ +$0.19/day                                          |
| OpenAI mini              | ≈ $9/mo                                                      | not computed (uses the mini's own rates)                     |
| GPT-Live-1               | $1.50/day = $45/mo voice layer + backend                     | n/a                                                          |
| Gemini 3.8 Live          | ≈ $6.8/mo (≈ $9.5 if all 30 min of mic audio is billed)      | not computed (billing of replayed context not confirmed)     |
| Cascade                  | ASR ¥5–15/mo + TTS ≈ ¥24/mo (Volcengine) or free (MiMo, for now) + LLM ≈ ¥1–2/mo | n/a                                                          |

**Formula:** daily cost = Σ over turns of [ (new user audio seconds × tokens/s × input price) + (replayed history tokens × input or cached price) + (AI audio seconds × tokens/s × output price) ].

**Missing data that decides the bill:**

- whether silence you stream is billed (not documented for Seeduplex or Qwen in what I found);
- Qwen realtime caching rules;
- whether Seeduplex stores audio history as audio or text tokens;
- 3.1 free quotas;
- OpenAI's 10/20 tokens per second, which comes from secondary sources.

## 5. Open-source references

- **Pipecat.** Reuse `pipecat.audio.turn.smart_turn.local_smart_turn_v3.LocalSmartTurnAnalyzerV3`, which runs Smart Turn locally on ONNX and bundles the weights. Reuse `pipecat.turns.user_start` (`VADUserTurnStartStrategy`, `MinWordsUserTurnStartStrategy`) and the stop strategies. Interruptions are controlled on the start strategy. Mind issue #6402 for Chinese. A full-duplex-style interruption classifier exists as Krisp VIVA (`KrispVivaIPUserTurnStartStrategy`), which is a third-party model dependency.
- **Smart Turn repo.** `pipecat-ai/smart-turn`: 8 MB int8 and 32 MB fp32 ONNX, open data and training code.
- **LiveKit Agents.** `AgentSession` with `TurnHandlingOptions` is the best reference for pause-then-confirm. The pause logic lives in `agent_activity.py` (PR #5535 shows the thinking-state fix). Adaptive mode is the default on LiveKit Cloud or in dev mode. Outside those it depends on their hosted inference, so don't count on it being self-contained. **[Judgment]**
- **Alibaba official demo.** `realtime_demo.py` and `B64PCMPlayer.py` show cancellation: clear the buffer on `speech_started`, suppress remaining audio, then cancel the response.
- **Volcengine official demos.** `web_duplex_demo.zip` and `python3.7_duplex_demo.zip` (linked from the API page).
- **Open-LLM-VTuber.** Listed in the sherpa-onnx README as hands-free voice with interruption, running locally. I did not review its code.
- **Do you need LiveKit?** No, not for one user. Reuse the ideas (state machine, pause/resume, turn ids). Pipecat is the closer fit if you stay on the cascade. **[Judgment]**

### Your 2 CPU / 2 GB server

- **Native route:** a relay plus SQLite, which is light. Audio is about 32 KB/s per direction, plus base64 overhead.
- **Cascade:** depends on whether ASR and Smart Turn run locally. Upgrade if soak tests show audio underruns, high CPU, or memory pressure. I can't give a threshold without measurements.

## 6. Who does what

**You provide or decide:**

- the text model you actually use (from the TokenDance logs);
- how important the MiMo voice is, via an A/B listening test with a Qwen or Volcengine clone of the same sample;
- accounts and keys: Alibaba Cloud Beijing, Volcengine real-name, and whether Seeduplex is open to you;
- a monthly budget cap;
- your test hardware: speakers, mics, browsers, rooms;
- 30–50 recorded Mandarin utterances (with pauses and hesitation), plus TV audio, keyboard noise and a cough;
- consent to use your voice for cloning and voiceprint. Note that the voiceprint feature takes a publicly reachable URL, so use a short-lived signed URL.

**Developer builds and validates:**

- the browser audio engine: continuous capture, AEC-friendly playback, level-driven orb, local stop, mute, chat bubbles;
- a state machine and a turn-id cancellation protocol;
- relay and history persistence (only played text is stored);
- a latency instrumentation harness and a cost-reconciliation log;
- the AEC residual test, barge-in matrix, turn-end test, and a 30-minute 2c/2G soak test with reconnects.

## 7. Claims you asked me to check

| Claim                                           | Verdict                                                      |
| ----------------------------------------------- | ------------------------------------------------------------ |
| "Without headphones, wait for the AI to finish" | False as a general rule. It is a choice in Alibaba's sample code, not a limit |
| "WebRTC automatically gives reliable AEC"       | Partly. The browser AEC applies when playback is a path it knows. Custom playback and each browser need testing |
| "Native models solve echo at model level"       | Not supported by the docs I found. Alibaba says WebSocket needs client AEC |
| "Silero separates you from TV"                  | False. It detects speech, not speakers                       |
| "Native means no text history or cloned voice"  | False for history. For voice, you lose MiMo inside the model, but vendor cloning exists, and the hybrid keeps MiMo |
| "2c/2G definitely sufficient / insufficient"    | Neither. Depends on route and local models                   |
| 80/200/300 ms latency figures                   | None of the ones I found are end-to-end for your setup       |
| Prices from third-party or AI-generated pages   | I discarded those and used official pages. Exceptions are flagged: OpenAI's token timing and Qwen 3.0 free quota come from secondary sources |

I haven't seen your code or run any tests. Everything marked **[Test]** needs your hardware and speech.