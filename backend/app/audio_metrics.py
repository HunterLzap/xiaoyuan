"""Passive audio accounting; never schedules, buffers or retains audio content."""
from collections import deque
from array import array
from math import sqrt
from time import monotonic
from zlib import crc32

PCM_BYTES_PER_MS = 48
FRAME_MS = 60
TRACE_LIMIT = 128
SILENCE_BLOCK_MS = 20
SILENCE_BLOCK_BYTES = SILENCE_BLOCK_MS * PCM_BYTES_PER_MS  # 960 bytes @ 24k mono s16
SILENCE_RMS = 180
SILENCE_MIN_MS = 120


def _offset(base, timestamp):
    return round((timestamp - base) * 1000, 2) if timestamp is not None else None


class PcmSignalMetrics:
    def __init__(self):
        self.pending = bytearray()
        self.position_ms = 0
        self.run_ms = 0
        self.run_start_ms = 0
        self.longest_ms = 0
        self.longest_start_ms = None
        self.runs = 0
        self.total_ms = 0
        self.checksum = 0
        self.previous_block = None
        self.repeated_non_silent_blocks = 0

    def record(self, chunk):
        self.checksum = crc32(chunk, self.checksum)
        buffer = self.pending + chunk
        usable = len(buffer) // SILENCE_BLOCK_BYTES * SILENCE_BLOCK_BYTES
        for start in range(0, usable, SILENCE_BLOCK_BYTES):
            block = buffer[start:start + SILENCE_BLOCK_BYTES]
            samples = array("h")
            samples.frombytes(block)
            rms = sqrt(sum(sample * sample for sample in samples) / len(samples))
            signature = crc32(block)
            if rms < SILENCE_RMS:
                if not self.run_ms:
                    self.run_start_ms = self.position_ms
                self.run_ms += SILENCE_BLOCK_MS
            else:
                if self.run_ms >= SILENCE_MIN_MS:
                    self.runs += 1
                    self.total_ms += self.run_ms
                    if self.run_ms > self.longest_ms:
                        self.longest_ms = self.run_ms
                        self.longest_start_ms = self.run_start_ms
                self.run_ms = 0
                if signature == self.previous_block:
                    self.repeated_non_silent_blocks += 1
            self.previous_block = signature
            self.position_ms += SILENCE_BLOCK_MS
        self.pending = bytearray(buffer[usable:])

    def snapshot(self):
        trailing = self.run_ms if self.run_ms >= SILENCE_MIN_MS else 0
        return {
            "block_ms": SILENCE_BLOCK_MS, "rms_threshold": SILENCE_RMS, "min_run_ms": SILENCE_MIN_MS,
            "longest_ms": max(self.longest_ms, trailing),
            "longest_start_ms": self.run_start_ms if trailing > self.longest_ms else self.longest_start_ms,
            "runs_ge_min": self.runs + bool(trailing), "total_ms": self.total_ms + trailing,
            "crc32": f"{self.checksum:08x}",
            "adjacent_identical_non_silent_blocks": self.repeated_non_silent_blocks,
        }


class AudioFxMetrics:
    def __init__(self):
        self.reset()

    def reset(self):
        self.streams = {
            name: {"bytes": 0, "chunks": 0, "first_chunk_bytes": 0, "first": None, "last": None,
                   "max_gap_ms": 0, "max_gap_at": None}
            for name in ("input", "output")
        }
        self.trace = deque(maxlen=TRACE_LIMIT)
        self.segments = deque(maxlen=16)
        self.events = 0
        self.signals = {name: PcmSignalMetrics() for name in self.streams}

    def record_pcm(self, name, chunk: bytes):
        if not chunk:
            return
        self.record(name, len(chunk))
        self.signals[name].record(chunk)

    def start_segment(self, rate, pitch):
        self.segments.append({"at": monotonic(), "tts_rate": float(rate), "tts_pitch": float(pitch)})

    def record(self, name, size):
        if not size:
            return
        now = monotonic()
        state = self.streams[name]
        if state["last"] is not None:
            gap_ms = (now - state["last"]) * 1000
            if gap_ms > state["max_gap_ms"]:
                state["max_gap_ms"] = gap_ms
                state["max_gap_at"] = now
        if state["first"] is None:
            state["first"] = now
            state["first_chunk_bytes"] = size
        state["last"] = now
        state["bytes"] += size
        state["chunks"] += 1
        self.trace.append((now, name, size, state["bytes"]))
        self.events += 1

    def snapshot(self, base):
        now = monotonic()
        streams = {}
        for name, state in self.streams.items():
            span = (state["last"] - state["first"]) * 1000 if state["first"] is not None else 0
            streams[name] = {
                "pcm_bytes": state["bytes"], "playable_ms": round(state["bytes"] / PCM_BYTES_PER_MS, 2),
                "chunks": state["chunks"], "first_ms": _offset(base, state["first"]),
                "last_ms": _offset(base, state["last"]), "arrival_span_ms": round(span, 2),
                "max_arrival_gap_ms": round(state["max_gap_ms"], 2),
                "max_arrival_gap_at_ms": _offset(base, state["max_gap_at"]),
                "since_last_arrival_ms": round((now - state["last"]) * 1000, 2) if state["last"] is not None else None,
                "first_chunk_playable_ms": round(state["first_chunk_bytes"] / PCM_BYTES_PER_MS, 2),
                "playable_ms_per_arrival_wall_ms": round((state["bytes"] - state["first_chunk_bytes"]) / PCM_BYTES_PER_MS / span, 3) if span > 0 else None,
            }
        return {
            "measurement": "PCM at audio_fx input/output; input may have been held by tool verification",
            "streams": streams,
            "input_internal_silence": self.signals["input"].snapshot(),
            "output_internal_silence": self.signals["output"].snapshot(),
            "segments": [{"at_ms": _offset(base, s["at"]), "tts_rate": s["tts_rate"], "tts_pitch": s["tts_pitch"]}
                         for s in self.segments],
            "trace_dropped": self.events - len(self.trace),
            "trace": [{"at_ms": _offset(base, at), "stage": name, "pcm_bytes": size,
                       "cumulative_playable_ms": round(total / PCM_BYTES_PER_MS, 2)}
                      for at, name, size, total in self.trace],
        }


class PlaybackMetrics:
    def __init__(self):
        self.phases = {
            phase: {"pcm_bytes": 0, "first_chunk_bytes": 0, "first_arrival": None, "last_arrival": None, "arrival_max_gap_ms": 0,
                    "encoded_frames": 0, "queued_frames": 0, "inflight": 0, "sent_frames": 0,
                    "discarded_frames": 0, "failed_frames": 0, "wire_bytes": 0,
                    "first_send": None, "last_send_complete": None, "send_call_ms_total": 0,
                    "peak_queue_frames": 0, "encoded_crc32": 0, "sent_crc32": 0}
            for phase in ("ack", "answer")
        }
        self.trace = deque(maxlen=TRACE_LIMIT)
        self.events = 0

    def _event(self, action, phase, now=None):
        now = monotonic() if now is None else now
        self.events += 1
        self.trace.append((now, action, phase,
                           self.phases["ack"]["queued_frames"], self.phases["answer"]["queued_frames"],
                           self.phases["answer"]["pcm_bytes"], self.phases["answer"]["sent_frames"]))

    def mark(self, event):
        self._event(event, "control")

    def arrival(self, phase, size):
        if not size:
            return
        now = monotonic()
        state = self.phases[phase]
        if state["last_arrival"] is not None:
            state["arrival_max_gap_ms"] = max(state["arrival_max_gap_ms"], (now - state["last_arrival"]) * 1000)
        if state["first_arrival"] is None:
            state["first_arrival"] = now
            state["first_chunk_bytes"] = size
        state["last_arrival"] = now
        state["pcm_bytes"] += size
        self._event("pcm_arrival", phase, now)

    def encoded(self, phase, packets):
        count = len(packets)
        if not count:
            return
        state = self.phases[phase]
        state["encoded_frames"] += count
        state["queued_frames"] += count
        state["peak_queue_frames"] = max(state["peak_queue_frames"], state["queued_frames"])
        for packet in packets:
            state["encoded_crc32"] = crc32(packet, state["encoded_crc32"])
        self._event("frames_staged", phase)

    def send_start(self, phase):
        now = monotonic()
        state = self.phases[phase]
        state["queued_frames"] -= 1
        state["inflight"] += 1
        if state["first_send"] is None:
            state["first_send"] = now
        self._event("send_start", phase, now)
        return now

    def send_end(self, phase, started, packet, completed):
        now = monotonic()
        state = self.phases[phase]
        state["inflight"] -= 1
        state["send_call_ms_total"] += (now - started) * 1000
        if completed:
            state["sent_frames"] += 1
            state["wire_bytes"] += len(packet)
            state["sent_crc32"] = crc32(packet, state["sent_crc32"])
            state["last_send_complete"] = now
        else:
            state["failed_frames"] += 1
        self._event("send_complete" if completed else "send_cancelled_or_failed", phase, now)

    def discard(self):
        for phase, state in self.phases.items():
            if state["queued_frames"]:
                state["discarded_frames"] += state["queued_frames"]
                state["queued_frames"] = 0
                self._event("queued_audio_discarded", phase)

    def snapshot(self, base, codec_pending_bytes):
        phases = {}
        for phase, state in self.phases.items():
            span = (state["last_arrival"] - state["first_arrival"]) * 1000 if state["first_arrival"] is not None else 0
            phases[phase] = {
                "pcm_bytes": state["pcm_bytes"], "arrived_playable_ms": round(state["pcm_bytes"] / PCM_BYTES_PER_MS, 2),
                "first_arrival_ms": _offset(base, state["first_arrival"]),
                "last_arrival_ms": _offset(base, state["last_arrival"]), "arrival_span_ms": round(span, 2),
                "max_arrival_gap_ms": round(state["arrival_max_gap_ms"], 2),
                "first_chunk_playable_ms": round(state["first_chunk_bytes"] / PCM_BYTES_PER_MS, 2),
                "playable_ms_per_arrival_wall_ms": round((state["pcm_bytes"] - state["first_chunk_bytes"]) / PCM_BYTES_PER_MS / span, 3) if span > 0 else None,
                "encoded_audio_ms": state["encoded_frames"] * FRAME_MS,
                "queued_audio_ms": state["queued_frames"] * FRAME_MS,
                "peak_queued_audio_ms": state["peak_queue_frames"] * FRAME_MS,
                "send_inflight_audio_ms": state["inflight"] * FRAME_MS,
                "sent_audio_ms": state["sent_frames"] * FRAME_MS,
                "discarded_audio_ms": state["discarded_frames"] * FRAME_MS,
                "failed_or_cancelled_audio_ms": state["failed_frames"] * FRAME_MS,
                "sent_wire_bytes": state["wire_bytes"],
                "encoded_packets": state["encoded_frames"], "sent_packets": state["sent_frames"],
                "encoded_crc32": f'{state["encoded_crc32"]:08x}', "sent_crc32": f'{state["sent_crc32"]:08x}',
                "first_send_ms": _offset(base, state["first_send"]),
                "last_send_complete_ms": _offset(base, state["last_send_complete"]),
                "send_wall_ms": round((state["last_send_complete"] - state["first_send"]) * 1000, 2)
                if state["first_send"] is not None and state["last_send_complete"] is not None else None,
                "send_call_ms_total": round(state["send_call_ms_total"], 2),
            }
        return {
            "measurement": "gateway only; sent duration includes final Opus frame padding, not speaker playback",
            "phases": phases, "encoder_partial_pcm_ms": round(codec_pending_bytes / PCM_BYTES_PER_MS, 2),
            "queued_audio_ms": sum(s["queued_frames"] for s in self.phases.values()) * FRAME_MS,
            "trace_dropped": self.events - len(self.trace),
            "trace": [{"at_ms": _offset(base, at), "event": event, "phase": phase,
                       "ack_queued_ms": ack * FRAME_MS, "answer_queued_ms": answer * FRAME_MS,
                       "answer_arrived_ms": round(pcm / PCM_BYTES_PER_MS, 2), "answer_sent_ms": sent * FRAME_MS}
                      for at, event, phase, ack, answer, pcm, sent in self.trace],
        }
