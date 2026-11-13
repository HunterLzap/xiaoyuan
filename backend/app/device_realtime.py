import asyncio
import base64
import ctypes as c
from ctypes.util import find_library
from contextlib import suppress
import logging
import os
from array import array
from math import ceil
from time import monotonic

from websockets.exceptions import ConnectionClosed

from .audio_metrics import PlaybackMetrics
from .community import AudioRateController
from .config import ROOT
from .llm import ProviderError
from .realtime import RealtimeTurn

logger = logging.getLogger(__name__)


# Text markers that identify a blocked control turn (see tool_dialogue.control_error).
# realtime.py emits the control message as text followed by an error with the same text;
# matching those lets the device speak a truthful line instead of going silent.
CONTROL_FAILURE_HINTS = ("不能确认", "没有执行", "未能完成请求", "未完成本次回读", "工具执行失败")
CONNECTION_ERROR_HINTS = ("实时语音中断",)

# Playback smoothing: buffer a few 60 ms Opus frames before the first send so the device
# does not start on a single frame and then starve while the provider is still producing.
# Bounded wait: a short answer or a slow first chunk flushes after PREBUFFER_MAX_SECONDS,
# it never hangs waiting for the full buffer.
PREBUFFER_FRAMES = 3
PREBUFFER_MAX_SECONDS = 0.18
PREBUFFER_LIMIT_MS = 420
FRAME_MS = 60
# A send-start gap over 1.5 frames is a pacing anomaly, not proof of speaker silence.
STARVE_GAP_MS = 90

class DeviceCodec:
    def __init__(self):
        self.decoder = self.encoder = None
        name = str(ROOT/"models"/"codecs"/"opus.dll") if os.name=="nt" else find_library("opus")
        if not name:
            raise RuntimeError("libopus unavailable")
        self.lib = c.CDLL(name)
        p, i = c.c_void_p, c.c_int
        for fn,args,ret in (
            ("opus_decoder_create",[i,i,c.POINTER(i)],p),("opus_encoder_create",[i,i,i,c.POINTER(i)],p),
            ("opus_decode",[p,c.c_char_p,i,p,i,i],i),("opus_encode",[p,c.c_char_p,i,p,i],i),
            ("opus_decoder_destroy",[p],None),("opus_encoder_destroy",[p],None)):
            method = getattr(self.lib,fn)
            method.argtypes,method.restype = args,ret
        err = i()
        self.decoder = self.lib.opus_decoder_create(16000,1,c.byref(err))
        self.encoder = self.lib.opus_encoder_create(24000,1,2049,c.byref(err))
        if not self.decoder or not self.encoder:
            self.close()
            raise RuntimeError("opus init failed")
        self.pending = bytearray()

    def decode(self,data):
        out = c.create_string_buffer(3840)
        size = self.lib.opus_decode(self.decoder,data,len(data),out,1920,0)
        if size < 0:
            raise ValueError("invalid opus frame")
        return out.raw[:2*size]

    def encode(self,data,finish=False):
        self.pending.extend(data)
        frame = 2880
        if finish:
            self.pending.extend(bytes((-len(self.pending)) % frame))
        while len(self.pending)>=frame:
            out = c.create_string_buffer(4096)
            size = self.lib.opus_encode(self.encoder, bytes(self.pending[:frame]),1440,out,len(out))
            if size < 0:
                raise ValueError("opus encode failed")
            del self.pending[:frame]
            yield out.raw[:size]

    def close(self):
        if self.decoder:
            self.lib.opus_decoder_destroy(self.decoder)
            self.decoder = None
        if self.encoder:
            self.lib.opus_encoder_destroy(self.encoder)
            self.encoder = None


class DeviceRealtime:
    def __init__(self,hub,conn,manual):
        self.hub,self.conn = hub,conn
        self.codec = DeviceCodec()
        self.controller = AudioRateController(frame_duration=60)
        self.speaking = False
        self.drain = None
        self.last_voice_at = None
        self.speech_stopped_at = None
        self.first_audio_at = None
        self.tts_started_at = None
        self.first_packet_at = None
        self.done_at = None
        # Diagnostics only: device firmware reports its own AEC capability in hello.
        # Recorded so the next real run can say whether server-side barge-in is even
        # possible instead of guessing.
        self.client_aec = bool(getattr(conn, "client_aec", False))
        self.frames_dropped_after_turn = 0
        # Last assistant text line seen from the provider. A control failure is emitted as
        # a text line followed by an error carrying the SAME line, which lets the device
        # tell it apart from a plain connection error without changing realtime.py.
        self._last_text = None
        # Playback smoothing / outbound diagnostics (per DeviceRealtime turn).
        self.prebuffer_frames = []
        self.prebuffer_started_at = None
        self.prebuffer_timer = None
        self.prebuffer_flush_lock = asyncio.Lock()
        self.sender_started = False
        self.last_send_at = None
        self.outbound_starvations = 0
        self.max_send_gap_ms = 0
        # Opening-greeting cache is retired: the first sound is the answer's first sentence.
        # Kept ack-phase measurements so a reloaded build still reports an empty ack segment.
        self.ack_last_error = None
        self.ack_cache_hits = 0
        self.ack_cache_misses = 0
        self.ack_first_packet_at = None
        self.stream_epoch = 0
        self.buffer_target_ms = 180
        self.buffer_state = None
        self.answer_started = False
        self.producer_done = False
        self.metrics_finalized = False
        self.starvation_total_ms = 0
        self.gap_phases = {"ack": 0, "answer": 0, "ack_to_answer": 0}
        self.last_packet_phase = None
        self.ack_end_at = None
        self.answer_first_packet_at = None
        self.answer_first_audio_at = None
        self.max_send_duration_ms = 0
        self.queue_exhaustions = 0
        self.playback_metrics = PlaybackMetrics()
        self._rx_diag_frames = 0
        self._rx_diag_max_rms = 0.0
        self._rx_diag_last_log = monotonic()
        self.turn = RealtimeTurn(hub.voice.service,conn.voice_session_id,"device_voice",self.emit,manual)
        self.turn.continuous = self.client_aec and not manual

    def accepting_audio(self) -> bool:
        """True while the provider turn is still live (reader running).

        Frames after a reply finished (reader done) or with no connection would be
        appended to a dead turn and silently vanish; those are counted as dropped.
        A short window while the turn is closing (input already committed) is left to
        RealtimeTurn.append's own guard and is not labelled dropped.
        """
        turn = self.turn
        return bool(turn.ws and turn.reader is not None and not turn.reader.done())

    async def append(self, packet):
        if not self.accepting_audio():
            # The turn reader is already gone (a reply finished, or open failed), yet the
            # device may keep streaming before the next listen start. Those frames used to
            # be appended to a dead turn and silently vanish while still counted as
            # received; count them as dropped so lost audio is visible.
            self.frames_dropped_after_turn += 1
            self.conn.frames_dropped += 1
            return
        pcm = self.codec.decode(packet)
        samples = array("h")
        samples.frombytes(pcm)
        rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5 if samples else 0.0
        self._rx_diag_frames += 1
        if rms > self._rx_diag_max_rms:
            self._rx_diag_max_rms = rms
        now = monotonic()
        if self._rx_diag_frames == 1 or now - self._rx_diag_last_log >= 1.0:
            logger.info("device_audio_rx frames=%s bytes=%s rms=%.1f max_rms=%.1f",
                        self._rx_diag_frames, len(packet), rms, self._rx_diag_max_rms)
            self._rx_diag_last_log = now
        if rms > 100:
            self.last_voice_at = now
            self.publish_metrics()
        try:
            await self.turn.append(pcm)
        except ConnectionClosed:
            await self._upstream_closed()

    async def finish(self):
        try:
            await self.turn.finish()
        except ConnectionClosed:
            await self._upstream_closed()

    async def _upstream_closed(self):
        # Only called for provider sends, never for the device WebSocket transport.
        logger.exception("device_realtime_upstream_closed turn_id=%s", self.turn.turn_id)
        self.turn.input_closed = True
        await self.turn.close()
        await self.emit("error", "百炼实时连接已关闭，请重新发起对话。")

    def publish_metrics(self):
        # A turn that never heard speech and produced no audio must not overwrite the last
        # real measurement (the earlier all-null snapshot came from exactly that).
        if self.first_audio_at is None and self.last_voice_at is None and self.speech_stopped_at is None:
            return

        def since(base, later):
            if base is None or later is None:
                return None
            return round((later - base) * 1000)

        def elapsed(later):
            return since(self.last_voice_at, later)

        # Two bases on purpose:
        # * from_last_voice keeps the historical "last loud frame" reference;
        # * from_speech_stopped uses the provider's speech-end event; audio/packet times
        #   are gateway observations and do not establish when the device speaker played.
        snapshot = {
            "at": self.hub.now(),
            "aec": self.client_aec,
            "continuous": self.turn.continuous,
            "frames_dropped_after_turn": self.frames_dropped_after_turn,
            "outbound_starvations": self.outbound_starvations,
            "max_send_gap_ms": self.max_send_gap_ms,
            "starvation_total_ms": round(self.starvation_total_ms),
            "gap_phases": dict(self.gap_phases),
            "queue_exhaustions": self.queue_exhaustions,
            "max_send_duration_ms": self.max_send_duration_ms,
            "buffer_target_ms": self.buffer_target_ms,
            "next_buffer_target_ms": self.buffer_state["target_ms"] if self.buffer_state else 180,
            "ack_to_answer_gap_ms": (max(0, since(self.ack_end_at, self.answer_first_packet_at))
                                     if self.ack_end_at is not None and self.answer_first_packet_at is not None else None),
            "answer_first_audio_ms": since(self.speech_stopped_at, self.answer_first_audio_at),
            "answer_first_packet_ms": since(self.speech_stopped_at, self.answer_first_packet_at),
            "ack_first_packet_ms": since(self.speech_stopped_at, self.ack_first_packet_at),
            "ack_cache_hits": self.ack_cache_hits,
            "ack_cache_misses": self.ack_cache_misses,
            "ack_last_error": self.ack_last_error,
            "playback_complete": self.metrics_finalized,
            "prebuffer_audio_ms": len(self.prebuffer_frames) * FRAME_MS,
            "controller_queued_audio_ms": len(self.controller.queue) * FRAME_MS,
            "audio_fx": self.turn.audio.metrics.snapshot(self.speech_stopped_at or self.turn.started),
            "gateway_audio": self.playback_metrics.snapshot(
                self.speech_stopped_at or self.turn.started, len(self.codec.pending)),
            "from_last_voice": {
                "speech_stopped_ms": elapsed(self.speech_stopped_at),
                "first_audio_ms": elapsed(self.first_audio_at),
                "tts_start_ms": elapsed(self.tts_started_at),
                "first_packet_ms": elapsed(self.first_packet_at),
                "response_done_ms": elapsed(self.done_at),
            },
            "from_speech_stopped": {
                "first_audio_ms": since(self.speech_stopped_at, self.first_audio_at),
                "tts_start_ms": since(self.speech_stopped_at, self.tts_started_at),
                "first_packet_ms": since(self.speech_stopped_at, self.first_packet_at),
                "response_done_ms": since(self.speech_stopped_at, self.done_at),
            },
        }
        # Keep the newest audio-bearing measurement; a later no-audio turn cannot erase it.
        previous = self.hub.last_realtime_latency
        if (self.first_audio_at is None and isinstance(previous, dict)
                and (previous.get("from_speech_stopped") or {}).get("first_audio_ms") is not None):
            return
        self.hub.last_realtime_latency = snapshot

    def _is_control_failure(self, data) -> bool:
        if not isinstance(data, str) or not data.strip():
            return False
        if any(hint in data for hint in CONNECTION_ERROR_HINTS):
            return False
        if data == self._last_text:
            return True
        return any(hint in data for hint in CONTROL_FAILURE_HINTS)

    async def show_text(self, text):
        """Show a truthful line on the device screen.

        Realtime mode's only valid voice is the 百炼 session's own configured voice
        (e.g. Taffy). Never synthesise the notice with the legacy MiMo TTS factory: that
        is a different provider/voice and would be an implicit mix. Spoken audio for the
        continued answer must come from the same realtime session (realtime.py继续
        response.create), arriving here as normal "audio" events. Until that lands, text
        display is the honest capability; this method stays silent on the speaker.
        """
        text = (text or "").strip()
        if not text:
            return
        with suppress(ProviderError):
            await self.conn.send({"type": "tts", "state": "sentence_start", "text": text})

    def _session_buffer(self):
        state = getattr(self.conn, "_realtime_buffer_state", None)
        if state is None or state["sid"] != self.conn.voice_session_id:
            state = {"sid": self.conn.voice_session_id, "target_ms": 180, "clean_turns": 0}
            self.conn._realtime_buffer_state = state
        self.buffer_state = state
        self.buffer_target_ms = state["target_ms"]

    def _adapt_buffer(self, gap_ms):
        if self.buffer_state is not None:
            target = min(PREBUFFER_LIMIT_MS, max(180, ceil((gap_ms + 120) / FRAME_MS) * FRAME_MS))
            self.buffer_state["target_ms"] = max(self.buffer_state["target_ms"], target)
            self.buffer_state["clean_turns"] = 0

    def _finish_metrics(self):
        if self.metrics_finalized:
            return
        self.metrics_finalized = True
        if self.buffer_state is not None and self.answer_first_packet_at is not None:
            if self.outbound_starvations:
                self.buffer_state["clean_turns"] = 0
            else:
                self.buffer_state["clean_turns"] += 1
                if self.buffer_state["clean_turns"] >= 3:
                    self.buffer_state["target_ms"] = 180
                    self.buffer_state["clean_turns"] = 0
        self.publish_metrics()

    def _cancel_prebuffer_timer(self):
        timer = self.prebuffer_timer
        if timer is asyncio.current_task():
            return
        self.prebuffer_timer = None
        if timer is not None and not timer.done():
            timer.cancel()

    def _reset_stream_state(self):
        self.playback_metrics.discard()
        self.stream_epoch += 1
        self._cancel_prebuffer_timer()
        self.prebuffer_frames.clear()
        self.prebuffer_started_at = None
        self.sender_started = False
        self.last_send_at = None
        self.last_packet_phase = None
        self.answer_started = False
        self.producer_done = False

    async def _queue_frames(self, frames, phase):
        if not frames:
            return
        self.playback_metrics.encoded(phase, len(frames))
        now = monotonic()
        if self.buffer_state is not None and (not self.sender_started or not self.answer_started):
            self.buffer_target_ms = self.buffer_state["target_ms"]
        exhausted = (self.sender_started and not self.controller.queue
                     and self.last_send_at is not None
                     and (now - self.last_send_at) * 1000 > STARVE_GAP_MS)
        if exhausted:
            self._adapt_buffer((now - self.last_send_at) * 1000)
            if self.buffer_state is not None:
                self.buffer_target_ms = self.buffer_state["target_ms"]
        buffering = (not self.sender_started or self.prebuffer_frames
                     or (phase == "answer" and not self.answer_started) or exhausted)
        if buffering:
            self.prebuffer_frames.extend((frame, phase) for frame in frames)
            await self._arm_prebuffer()
        else:
            for frame in frames:
                self.controller.add_audio((frame, phase))

    async def _arm_prebuffer(self):
        if not self.prebuffer_frames:
            return
        if self.prebuffer_started_at is None:
            self.prebuffer_started_at = monotonic()
        target_frames = ceil(self.buffer_target_ms / FRAME_MS)
        queued = len(self.controller.queue)
        if len(self.prebuffer_frames) + queued >= target_frames:
            await self._flush_prebuffer(force=True)
            return
        if self.prebuffer_timer is None or self.prebuffer_timer.done():
            self.prebuffer_timer = asyncio.create_task(self._prebuffer_timeout(self.stream_epoch))

    async def _prebuffer_timeout(self, epoch):
        try:
            remaining = self.buffer_target_ms / 1000 - (monotonic() - self.prebuffer_started_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            if epoch == self.stream_epoch and self.prebuffer_frames:
                await self._flush_prebuffer(force=True)
        except asyncio.CancelledError:
            return
        finally:
            if self.prebuffer_timer is asyncio.current_task():
                self.prebuffer_timer = None

    async def _send_packet(self, item):
        packet, phase = item
        now = monotonic()
        if self.last_send_at is not None:
            gap_ms = (now - self.last_send_at) * 1000
            self.max_send_gap_ms = max(self.max_send_gap_ms, round(gap_ms))
            if gap_ms > STARVE_GAP_MS:
                self.outbound_starvations += 1
                self.starvation_total_ms += max(0, gap_ms - FRAME_MS)
                location = "ack_to_answer" if self.last_packet_phase == "ack" and phase == "answer" else phase
                self.gap_phases[location] += 1
                self._adapt_buffer(gap_ms)
        self.last_send_at = now
        self.last_packet_phase = phase
        if phase == "ack":
            if self.ack_first_packet_at is None:
                self.ack_first_packet_at = now
            self.ack_end_at = now + FRAME_MS / 1000
        elif self.answer_first_packet_at is None:
            self.answer_first_packet_at = now
        if self.first_packet_at is None:
            self.first_packet_at = now
        metrics = self.playback_metrics
        started = metrics.send_start(phase)
        completed = False
        try:
            await self.conn.send_audio(packet)
            completed = True
        finally:
            metrics.send_end(phase, started, len(packet), completed)
        self.max_send_duration_ms = max(self.max_send_duration_ms, round((monotonic() - now) * 1000))
        if not self.controller.queue and not self.producer_done:
            self.queue_exhaustions += 1
        self.publish_metrics()

    async def _flush_prebuffer(self, force=False):
        async with self.prebuffer_flush_lock:
            await self._flush_locked(force)

    async def _flush_locked(self, force=False):
        if not self.prebuffer_frames:
            return
        if not force and len(self.prebuffer_frames) < ceil(self.buffer_target_ms / FRAME_MS):
            return
        self._cancel_prebuffer_timer()
        epoch = self.stream_epoch
        controller = self.controller
        if not self.speaking:
            self.speaking = True
            await self.conn.send({"type": "tts", "state": "start"})
            if epoch != self.stream_epoch:
                return
            if self.tts_started_at is None:
                self.tts_started_at = monotonic()
            controller.start_sending(self._send_packet)
        self.sender_started = True
        frames, self.prebuffer_frames = self.prebuffer_frames, []
        self.prebuffer_started_at = None
        for frame, phase in frames:
            controller.add_audio((frame, phase))
            if phase == "answer":
                self.answer_started = True

    async def prepare_playback(self, interrupt: bool = True):
        await self.stop_audio(interrupt=interrupt)
        self.controller = AudioRateController(frame_duration=60)

    async def emit(self,kind,data):
        conn = self.conn
        if kind in {"notice", "interrupt", "done", "next", "error"}:
            self.playback_metrics.mark(kind)
        if kind == "ready":
            conn.voice_session_id = self.turn.sid
        elif kind == "next":
            await self.prepare_playback(interrupt=True)
            self.first_audio_at = None
            self.first_packet_at = None
            self.tts_started_at = None
            self.done_at = None
            self.outbound_starvations = 0
            self.max_send_gap_ms = 0
            self.last_voice_at = None
            self.speech_stopped_at = None
            self.starvation_total_ms = 0
            self.gap_phases = {"ack": 0, "answer": 0, "ack_to_answer": 0}
            self.ack_end_at = None
            self.answer_first_packet_at = None
            self.answer_first_audio_at = None
            self.ack_first_packet_at = None
            self.ack_cache_hits = 0
            self.ack_cache_misses = 0
            self.max_send_duration_ms = 0
            self.queue_exhaustions = 0
            self.playback_metrics = PlaybackMetrics()
            self.turn.audio.metrics.reset()
            self.metrics_finalized = False
            self._last_text = None
        elif kind == "idle":
            conn.voice_session_id = None
            conn.close_after_chat = True
            is_end_intent = isinstance(data, dict) and data.get("reason") == "end_intent"
            await self.stop_audio(interrupt=is_end_intent)
            with suppress(Exception):
                await conn.ws.close()
        elif kind=="user":
            self.hub.last_utterance = {"at":self.hub.now(),"state":"recognized","text":data}
            await conn.send({"type":"stt","text":data})
        elif kind=="thinking":
            # First sound is the first sentence of the real answer, produced by the same
            # TTS/audio path as the rest of it. Nothing is played here.
            self._session_buffer()
            self.speech_stopped_at = monotonic()
            self.publish_metrics()
        elif kind=="notice":
            if self.answer_first_audio_at is not None:
                await self.prepare_playback()
            await self.show_text(data)
        elif kind=="interrupt":
            await self.prepare_playback()
        elif kind=="text":
            # Keep the last assistant line so a following error can be recognised as the
            # control-failure pattern (same line). Normal streaming display stays as before.
            self._last_text = data
        elif kind=="audio":
            if self.first_audio_at is None:
                self.first_audio_at = monotonic()
            if self.answer_first_audio_at is None:
                self.answer_first_audio_at = monotonic()
            pcm = base64.b64decode(data)
            self.playback_metrics.arrival("answer", len(pcm))
            chunk = list(self.codec.encode(pcm))
            await self._queue_frames(chunk, "answer")
        elif kind=="done":
            self.done_at = monotonic()
            self.publish_metrics()
            text_only = isinstance(data, dict) and data.get("audio_status") == "text_only"
            if text_only:
                reply = data.get("reply")
                if self.answer_first_audio_at is not None:
                    await self.prepare_playback()
                if reply:
                    await self.show_text(reply)
            self.producer_done = True
            tail = list(self.codec.encode(b"", True))
            self.playback_metrics.encoded("answer", len(tail))
            self.prebuffer_frames.extend((frame, "answer") for frame in tail)
            if self.prebuffer_frames:
                await self._flush_prebuffer(force=True)
            else:
                self._cancel_prebuffer_timer()
            if self.speaking:
                controller = self.controller
                epoch = self.stream_epoch

                async def drain():
                    await controller.wait_finished()
                    remaining = (self.last_send_at or monotonic()) + FRAME_MS / 1000 - monotonic()
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                    if epoch == self.stream_epoch:
                        self._finish_metrics()
                        await self.stop_audio()
                if self.turn.continuous:
                    self.drain = asyncio.create_task(drain())
                else:
                    await drain()
        elif kind=="error":
            self.hub.last_error = data
            if self._is_control_failure(data):
                # Control turn blocked: realtime.py already dropped the fake-success audio.
                # Show the truthful reason on screen and reset playback resources; spoken
                # audio (if the session continues) comes from realtime.py, not local TTS.
                await self.prepare_playback()
                await self.show_text(data)
            else:
                await self.stop_audio(interrupt=True)
                await self.show_text(data)

    async def stop_audio(self, interrupt: bool = False):
        self.playback_metrics.mark("stop_audio")
        timer = self.prebuffer_timer
        self._reset_stream_state()
        speaking, self.speaking = self.speaking, False
        controller = self.controller
        sender = controller.pending_send_task
        controller.reset()
        self.codec.pending.clear()
        drain, self.drain = self.drain, None
        tasks = [task for task in (timer, drain, sender)
                 if task is not None and task is not asyncio.current_task()]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.publish_metrics()
        if speaking:
            payload = {"type": "tts", "state": "stop"}
            if interrupt:
                payload["interrupt"] = True
            await self.conn.send(payload)

    async def close(self):
        try:
            await self.turn.close()
        finally:
            try:
                await self.stop_audio(interrupt=True)
            finally:
                self.codec.close()
