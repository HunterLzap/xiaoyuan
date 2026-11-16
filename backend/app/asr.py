"""Online ASR adapters and device-side pipeline utterance detector."""
from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from io import BytesIO
import json
from time import monotonic
from typing import Protocol
from urllib.parse import urlencode
from uuid import uuid4
import wave

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .audio_codec import DeviceCodec, pcm_rms, pcm_to_wav, resample_pcm16_mono
from .config import Settings
from .llm import ProviderError
from .tts import shared_client

SPEECH_RMS_THRESHOLD = 320.0
MIN_SPEECH_MS = 180
TRAILING_SILENCE_MS = 720
MAX_UTTERANCE_MS = 30000
FRAME_MS = 60


class ASRProvider(Protocol):
    async def transcribe_wav(self, wav_bytes: bytes) -> dict: ...


def _effective_asr_model(settings: Settings) -> str:
    if settings.asr_provider == "bailian":
        return settings.asr_model or "qwen3-asr-flash-realtime"
    return settings.asr_model or "whisper-1"


class OpenAICompatibleASRProvider:
    """OpenAI-compatible /audio/transcriptions HTTP ASR client."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = http_client or shared_client(settings.timeout_seconds)

    async def transcribe_wav(self, wav_bytes: bytes) -> dict:
        config = self.settings
        api_key = config.effective_asr_api_key.get_secret_value().strip()
        base_url = config.effective_asr_base_url.rstrip("/")
        model = _effective_asr_model(config)
        if not api_key or not base_url or not model:
            raise ProviderError(422, "asr_not_configured", "请先在 API 接入中填写语音识别接口、模型和密钥。")
        data = {"model": model, "response_format": "json"}
        if config.asr_language:
            data["language"] = config.asr_language
        try:
            response = await self.client.post(
                f"{base_url}/audio/transcriptions",
                data=data,
                files={"file": ("utterance.wav", wav_bytes, "audio/wav")},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=config.timeout_seconds,
            )
        except httpx.TimeoutException:
            raise ProviderError(504, "asr_timeout", "语音识别超时，请缩短录音或重试。") from None
        except httpx.RequestError:
            raise ProviderError(502, "asr_connection", "无法连接语音识别服务，请检查接口地址和网络。") from None
        if response.status_code in {401, 403}:
            raise ProviderError(502, "asr_auth", "语音识别鉴权失败或权限不足，请检查语音识别密钥。")
        if response.status_code == 429:
            raise ProviderError(503, "asr_rate_limit", "语音识别限流或额度不足，请稍后重试。")
        if not response.is_success:
            raise ProviderError(502, "asr_upstream_error", "语音识别服务拒绝请求，请检查模型和接口地址。")
        try:
            payload = response.json()
            text = (payload.get("text") or "").strip() if isinstance(payload, dict) else ""
        except ValueError:
            text = response.text.strip()
        return {"text": text, "provider": "openai", "model": model}


def _wav_to_pcm16_16k(wav_bytes: bytes) -> bytes:
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as audio_file:
            if audio_file.getsampwidth() != 2:
                raise ProviderError(422, "voice_audio_invalid", "仅支持 16-bit WAV 音频。")
            rate = audio_file.getframerate()
            channels = audio_file.getnchannels()
            pcm = audio_file.readframes(audio_file.getnframes())
    except (wave.Error, EOFError):
        raise ProviderError(422, "voice_audio_invalid", "无效的 WAV 录音格式。") from None
    return resample_pcm16_mono(pcm, rate, 16000, channels)


class BailianASRProvider:
    """Alibaba Bailian qwen3-asr-flash-realtime WebSocket ASR client."""

    def __init__(self, settings: Settings, ws_connect=connect):
        self.settings = settings
        self.ws_connect = ws_connect

    def _endpoint(self) -> tuple[str, str, str]:
        config = self.settings
        api_key = config.effective_asr_api_key.get_secret_value().strip()
        model = _effective_asr_model(config)
        if not api_key:
            raise ProviderError(422, "asr_not_configured", "请先填写百炼语音识别 API Key。")
        base = config.effective_asr_base_url
        if "model=" in base:
            return base, api_key, model
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{urlencode({'model': model})}", api_key, model

    async def transcribe_wav(self, wav_bytes: bytes) -> dict:
        pcm = _wav_to_pcm16_16k(wav_bytes)
        if not pcm:
            return {"text": "", "provider": "bailian", "model": _effective_asr_model(self.settings)}
        return await self.transcribe_pcm(pcm)

    async def transcribe_pcm(self, pcm: bytes) -> dict:
        url, api_key, model = self._endpoint()
        transcript_parts: list[str] = []
        completed_text = ""
        session_cfg: dict = {
            "modalities": ["text"],
            "input_audio_format": "pcm",
            "sample_rate": 16000,
            "turn_detection": None,
        }
        if self.settings.asr_language:
            session_cfg["input_audio_transcription"] = {
                "model": model,
                "language": self.settings.asr_language,
            }
        try:
            async with asyncio.timeout(max(15.0, float(self.settings.timeout_seconds))):
                async with self.ws_connect(
                    url,
                    additional_headers={"Authorization": f"Bearer {api_key}"},
                    proxy=None,
                    close_timeout=2,
                    max_size=4 * 1024 * 1024,
                ) as socket:
                    first = json.loads(await socket.recv())
                    if first.get("type") == "error":
                        raise ProviderError(502, "asr_upstream_error", "百炼识别会话创建失败，请检查配置。")
                    await socket.send(json.dumps({
                        "event_id": uuid4().hex,
                        "type": "session.update",
                        "session": session_cfg,
                    }))
                    while True:
                        event = json.loads(await socket.recv())
                        kind = event.get("type")
                        if kind == "error":
                            raise ProviderError(502, "asr_upstream_error", "百炼识别参数不被支持，请核对模型与语言设置。")
                        if kind == "session.updated":
                            break
                    chunk_bytes = 3200
                    for offset in range(0, len(pcm), chunk_bytes):
                        chunk = pcm[offset:offset + chunk_bytes]
                        await socket.send(json.dumps({
                            "event_id": uuid4().hex,
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        }))
                    await socket.send(json.dumps({
                        "event_id": uuid4().hex,
                        "type": "input_audio_buffer.commit",
                    }))
                    await socket.send(json.dumps({
                        "event_id": uuid4().hex,
                        "type": "session.finish",
                    }))
                    while True:
                        raw = await socket.recv()
                        event = json.loads(raw)
                        kind = event.get("type")
                        if kind == "error":
                            raise ProviderError(502, "asr_upstream_error", "百炼实时识别返回错误。")
                        if kind == "conversation.item.input_audio_transcription.text":
                            piece = event.get("text") or event.get("stash") or ""
                            if piece:
                                transcript_parts.append(piece)
                        elif kind == "conversation.item.input_audio_transcription.completed":
                            completed_text = (event.get("transcript") or "").strip()
                        elif kind == "session.finished":
                            break
        except ProviderError:
            raise
        except TimeoutError:
            raise ProviderError(504, "asr_timeout", "百炼实时识别超时。") from None
        except (ConnectionClosed, OSError, ValueError, KeyError):
            raise ProviderError(502, "asr_connection", "无法完成百炼实时语音识别，请检查网络或配置。") from None
        text = completed_text or "".join(transcript_parts).strip()
        return {"text": text, "provider": "bailian", "model": model}


def build_asr_provider(settings: Settings, http_client: httpx.AsyncClient | None = None) -> ASRProvider | None:
    if settings.asr_provider == "local":
        return None
    if settings.asr_provider == "bailian":
        return BailianASRProvider(settings)
    return OpenAICompatibleASRProvider(settings, http_client=http_client)


async def transcribe_browser_wav(settings: Settings, wav_bytes: bytes, speech_recognizer=None) -> dict:
    provider = build_asr_provider(settings)
    if provider is not None:
        return await provider.transcribe_wav(wav_bytes)
    if speech_recognizer is None:
        raise ProviderError(502, "voice_asr_failed", "本地识别未初始化；请切换为在线识别 API。")
    result = await speech_recognizer.transcribe(wav_bytes)
    if result is None:
        raise ProviderError(502, "voice_asr_failed", "本地识别失败；请检查语音环境或切换在线识别 API。")
    return result


class DevicePipelineASR:
    """In-process Opus decode + endpointing for ESP32 device turns in pipeline API mode."""

    def __init__(self, settings_getter):
        self.settings_getter = settings_getter
        self.codec: DeviceCodec | None = None
        self.mode = "auto"
        self.voice_active = False
        self.buffer = bytearray()
        self.speech_ms = 0
        self.silence_ms = 0
        self.total_ms = 0
        self.last_metrics: dict = {}

    def start(self, mode: str) -> None:
        self.mode = "manual" if mode == "manual" else "auto"
        self.voice_active = False
        self.buffer.clear()
        self.speech_ms = 0
        self.silence_ms = 0
        self.total_ms = 0
        if self.codec is None:
            self.codec = DeviceCodec(decode=True, encode=False)

    def _reset_utterance(self) -> None:
        self.voice_active = False
        self.buffer.clear()
        self.speech_ms = 0
        self.silence_ms = 0
        self.total_ms = 0

    async def _transcribe_buffer(self, reason: str) -> dict | None:
        if self.speech_ms < MIN_SPEECH_MS or not self.buffer:
            self._reset_utterance()
            return None
        pcm = bytes(self.buffer)
        audio_seconds = round(self.total_ms / 1000, 3)
        speech_seconds = round(self.speech_ms / 1000, 3)
        self._reset_utterance()
        settings: Settings = self.settings_getter()
        provider = build_asr_provider(settings)
        if provider is None:
            return None
        started = monotonic()
        if isinstance(provider, BailianASRProvider):
            result = await provider.transcribe_pcm(pcm)
        else:
            result = await provider.transcribe_wav(pcm_to_wav(pcm, sample_rate=16000, channels=1))
        decode_seconds = round(monotonic() - started, 3)
        self.last_metrics = {
            "audio_seconds": audio_seconds,
            "speech_seconds": speech_seconds,
            "decode_seconds": decode_seconds,
            "end_reason": reason,
            "asr_provider": result.get("provider"),
            "asr_model": result.get("model"),
        }
        text = (result.get("text") or "").strip()
        if not text:
            return None
        return {"text": text, **self.last_metrics}

    async def push(self, opus_packet: bytes) -> dict | None:
        if self.codec is None:
            self.start(self.mode)
        assert self.codec is not None
        pcm = self.codec.decode(opus_packet)
        rms = pcm_rms(pcm)
        loud = rms >= SPEECH_RMS_THRESHOLD
        if loud:
            self.voice_active = True
            self.speech_ms += FRAME_MS
            self.silence_ms = 0
        elif self.voice_active:
            self.silence_ms += FRAME_MS
        if self.voice_active or self.mode == "manual":
            self.buffer.extend(pcm)
            self.total_ms += FRAME_MS
        if self.mode == "auto" and self.voice_active:
            if self.silence_ms >= TRAILING_SILENCE_MS and self.speech_ms >= MIN_SPEECH_MS:
                return await self._transcribe_buffer("vad_silence")
            if self.total_ms >= MAX_UTTERANCE_MS:
                return await self._transcribe_buffer("max_duration")
        return None

    async def finish(self) -> dict | None:
        return await self._transcribe_buffer("manual_stop" if self.mode == "manual" else "flush")

    def close(self) -> None:
        self._reset_utterance()
        if self.codec is not None:
            with suppress(Exception):
                self.codec.close()
            self.codec = None
