import asyncio
import base64
import binascii
from collections.abc import AsyncIterator
import json
from contextlib import aclosing
from io import BytesIO
from pathlib import Path
import subprocess
from typing import Protocol
from urllib.parse import urlencode
from uuid import uuid4
import wave

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from . import audio_fx
from .audio_codec import pcm_to_wav, resample_pcm16_mono, strip_wav_header
from .config import ROOT, Settings
from .llm import ProviderError
from .speech_text import normalize_for_speech


class TTSProvider(Protocol):
    def synthesize_stream(self, text: str) -> AsyncIterator[bytes]: ...
    async def synthesize(self, text: str) -> bytes: ...
    async def close(self) -> None: ...

CLONE_MODEL = "mimo-v2.5-tts-voiceclone"
VOICEDESIGN_MODEL = "mimo-v2.5-tts-voicedesign"
PRESET_VOICES = ["mimo_default", "冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean"]
# The API rejects samples larger than 10 MB once base64 encoded.
CLONE_SAMPLE_BYTES = 7_500_000

# One process-wide HTTP client for the TTS upstream. Constructing an httpx.AsyncClient
# loads the CA store (~300ms on Windows); building one per turn put that cost on the
# first-packet path. Reuse a single client and pay it once at startup.
_SHARED_CLIENT: httpx.AsyncClient | None = None


def shared_client(timeout: float) -> httpx.AsyncClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        _SHARED_CLIENT = httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)
    return _SHARED_CLIENT


async def close_shared_client() -> None:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is not None and not _SHARED_CLIENT.is_closed:
        await _SHARED_CLIENT.aclose()
    _SHARED_CLIENT = None


def resolve_sample(path: str | Path) -> Path | None:
    """Resolve a configured voice sample path inside the project, or None."""
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError):
        return None
    if not resolved.is_file() or resolved.stat().st_size > CLONE_SAMPLE_BYTES:
        return None
    return resolved


class MiMoTTSProvider:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        if http_client is not None:
            self.client = http_client
            self._owns_client = True
        else:
            self.client = shared_client(settings.tts_timeout_seconds)
            self._owns_client = False

    async def synthesize_stream(self, text: str):
        text = normalize_for_speech(text)
        raw = self._synthesize_stream_raw(text)
        config = self.settings
        if audio_fx.is_neutral(1.0, config.tts_rate, config.tts_pitch):
            shaped = raw
        else:
            shaped = audio_fx.stream_pcm(raw, config.tts_rate, config.tts_pitch)
        try:
            async with aclosing(shaped):
                async for chunk in shaped:
                    yield chunk
        except (OSError, ValueError):
            raise ProviderError(502, "tts_audio_processing", "语音数据或语速音调处理未完成。") from None

    async def _synthesize_stream_raw(self, text: str):
        """Yield PCM16 mono 24 kHz audio as it arrives.

        The provider emits base64 PCM in streaming deltas; first audio lands in about a
        second instead of the ~3.5s a complete WAV takes, which is what makes the device
        start speaking before the whole answer exists.
        """
        config = self.settings
        self._validate(text)
        payload = self._payload(text, stream=True)
        try:
            async with self.client.stream(
                    "POST", config.effective_tts_base_url + "/chat/completions",
                    json=payload,
                    headers={"Authorization": "Bearer " + config.effective_tts_api_key.get_secret_value()},
                    timeout=config.tts_timeout_seconds) as response:
                self._raise_for_status(response.status_code)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if not body or body == "[DONE]":
                        if body == "[DONE]":
                            break
                        continue
                    try:
                        event = json.loads(body)
                    except ValueError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    audio = (choices[0].get("delta") or {}).get("audio") or {}
                    encoded = audio.get("data")
                    if not encoded:
                        continue
                    try:
                        chunk = base64.b64decode(encoded, validate=True)
                    except binascii.Error:
                        continue
                    if chunk:
                        yield chunk
        except httpx.TimeoutException:
            raise ProviderError(504, "tts_timeout", "语音合成超时；请缩短文本后重试。") from None
        except httpx.RequestError:
            raise ProviderError(502, "tts_connection", "无法连接语音服务；请检查接口地址和网络。") from None

    def _validate(self, text: str) -> None:
        config = self.settings
        if not config.effective_tts_api_key.get_secret_value():
            raise ProviderError(422, "tts_not_configured", "请先在API接入中填写当前语音服务使用的密钥。")
        if not text.strip():
            raise ProviderError(422, "tts_empty_text", "请输入要试听的文字。")
        if config.tts_model == "mimo-v2.5-tts-voicedesign" and not config.tts_instruction.strip():
            raise ProviderError(422, "tts_voice_description_required",
                                "VoiceDesign 需要音色描述，例如：温柔、自然、语速舒缓的年轻女声。")

    def _payload(self, text: str, stream: bool) -> dict:
        config = self.settings
        messages = []
        if config.tts_instruction.strip():
            messages.append({"role": "user", "content": config.tts_instruction.strip()})
        messages.append({"role": "assistant", "content": text.strip()})
        audio = {"format": "pcm16" if stream else "wav"}
        if config.tts_model == CLONE_MODEL:
            sample = resolve_sample(config.tts_clone_sample)
            if sample is None:
                from . import voices

                sample = resolve_sample(voices.sample_for(config.tts_voice))
            if sample is None:
                raise ProviderError(422, "tts_clone_sample_missing",
                                    "音色克隆需要一段项目内的参考音频；请重新选择一个克隆声音。")
            encoded = base64.b64encode(sample.read_bytes()).decode()
            mime = "audio/wav" if sample.suffix.lower() == ".wav" else "audio/mpeg"
            audio["voice"] = f"data:{mime};base64,{encoded}"
        elif config.tts_model == "mimo-v2.5-tts":
            audio["voice"] = config.tts_voice
        return {"model": config.tts_model, "messages": messages,
                "audio": audio, "stream": stream}

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status in {401, 403}:
            raise ProviderError(502, "tts_auth", "语音服务鉴权失败或权限不足；请检查语音密钥。")
        if status == 429:
            raise ProviderError(503, "tts_rate_limit", "语音服务限流或额度不足；请检查供应商控制台。")
        if status >= 400:
            raise ProviderError(502, "tts_upstream_error", "语音服务拒绝合成；请核对接口、模型和音色设置。")

    async def synthesize(self, text: str) -> bytes:
        config = self.settings
        text = normalize_for_speech(text)
        self._validate(text)
        payload = self._payload(text, stream=False)
        try:
            async with self.client.stream("POST", config.effective_tts_base_url + "/chat/completions",
                                          json=payload, headers={"Authorization": "Bearer " + config.effective_tts_api_key.get_secret_value()},
                                          timeout=config.tts_timeout_seconds) as response:
                if response.status_code in {401, 403}:
                    raise ProviderError(502, "tts_auth", "语音服务鉴权失败或权限不足；请检查语音密钥。")
                if response.status_code == 429:
                    raise ProviderError(503, "tts_rate_limit", "语音服务限流或额度不足；请检查供应商控制台。")
                if not response.is_success:
                    raise ProviderError(502, "tts_upstream_error", "语音服务拒绝合成；请核对接口、模型和音色设置。")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16 * 1024 * 1024:
                        raise ProviderError(502, "tts_audio_too_large", "试听音频过大，请缩短文本。")
            data = json.loads(body)
            encoded = data["choices"][0]["message"]["audio"]["data"]
            result = base64.b64decode(encoded, validate=True)
            with wave.open(BytesIO(result), "rb") as audio_file:
                if audio_file.getnframes() < 1 or not audio_file.readframes(1):
                    raise ValueError()
            # Speed and pitch are applied here so they are exact rather than left to the
            # model's interpretation of a style instruction.
            if not audio_fx.is_neutral(1.0, config.tts_rate, config.tts_pitch):
                try:
                    result = await audio_fx.apply(result, 1.0, config.tts_rate, config.tts_pitch)
                except (OSError, ValueError, subprocess.SubprocessError):
                    # Shaping is an enhancement; unshaped audio beats no audio.
                    pass
            return result
        except httpx.TimeoutException:
            raise ProviderError(504, "tts_timeout", "语音合成超时；未保存配置，可缩短文本后手动重试。") from None
        except httpx.RequestError:
            raise ProviderError(502, "tts_connection", "无法连接语音服务；请检查接口地址和网络。") from None
        except (KeyError, IndexError, TypeError, ValueError, binascii.Error, wave.Error, EOFError):
            raise ProviderError(502, "tts_invalid_audio", "语音服务未返回可播放的 WAV 音频；请核对协议。") from None

    async def close(self) -> None:
        # The shared client outlives individual turns; only close one we were handed.
        if self._owns_client and self.client is not None:
            await self.client.aclose()


class OpenAITTSProvider:
    """Standard OpenAI-compatible POST /audio/speech streaming TTS client."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        if http_client is not None:
            self.client = http_client
            self._owns_client = True
        else:
            self.client = shared_client(settings.tts_timeout_seconds)
            self._owns_client = False

    def _validate(self, text: str) -> None:
        config = self.settings
        if not config.effective_tts_api_key.get_secret_value():
            raise ProviderError(422, "tts_not_configured", "请先在 API 接入中填写语音合成服务密钥。")
        if not config.tts_model.strip():
            raise ProviderError(422, "tts_not_configured", "请先选择或填写语音合成模型。")
        if not text.strip():
            raise ProviderError(422, "tts_empty_text", "请输入要试听的文字。")

    def _payload(self, text: str, response_format: str) -> dict:
        voice = (self.settings.tts_voice or "alloy").strip() or "alloy"
        payload: dict = {
            "model": self.settings.tts_model,
            "input": text.strip(),
            "voice": voice,
            "response_format": response_format,
        }
        if self.settings.tts_instruction.strip():
            payload["instructions"] = self.settings.tts_instruction.strip()
        return payload

    async def synthesize_stream(self, text: str):
        text = normalize_for_speech(text)
        raw = self._synthesize_stream_raw(text)
        config = self.settings
        shaped = raw if audio_fx.is_neutral(1.0, config.tts_rate, config.tts_pitch) else audio_fx.stream_pcm(
            raw, config.tts_rate, config.tts_pitch)
        try:
            async with aclosing(shaped):
                async for chunk in shaped:
                    yield chunk
        except (OSError, ValueError):
            raise ProviderError(502, "tts_audio_processing", "语音数据或语速音调处理未完成。") from None

    async def _synthesize_stream_raw(self, text: str):
        config = self.settings
        self._validate(text)
        headers = {"Authorization": "Bearer " + config.effective_tts_api_key.get_secret_value()}
        header_buffer = bytearray()
        checked_header = False
        src_rate = 24000
        src_channels = 1
        try:
            async with self.client.stream(
                "POST",
                config.effective_tts_base_url + "/audio/speech",
                json=self._payload(text, "pcm"),
                headers=headers,
                timeout=config.tts_timeout_seconds,
            ) as response:
                MiMoTTSProvider._raise_for_status(response.status_code)
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    if not checked_header:
                        header_buffer.extend(chunk)
                        if len(header_buffer) < 44:
                            continue
                        checked_header = True
                        if header_buffer[:4] == b"RIFF":
                            parsed = strip_wav_header(bytes(header_buffer))
                            if parsed is not None:
                                frames, src_rate, src_channels = parsed
                                if frames:
                                    yield resample_pcm16_mono(frames, src_rate, 24000, src_channels)
                            elif len(header_buffer) > 44:
                                yield bytes(header_buffer[44:])
                            header_buffer.clear()
                        else:
                            yield bytes(header_buffer)
                            header_buffer.clear()
                    else:
                        yield resample_pcm16_mono(chunk, src_rate, 24000, src_channels)
            if not checked_header and header_buffer:
                yield bytes(header_buffer)
        except httpx.TimeoutException:
            raise ProviderError(504, "tts_timeout", "语音合成超时；请缩短文本后重试。") from None
        except httpx.RequestError:
            raise ProviderError(502, "tts_connection", "无法连接语音服务；请检查接口地址和网络。") from None

    async def synthesize(self, text: str) -> bytes:
        text = normalize_for_speech(text)
        self._validate(text)
        config = self.settings
        try:
            response = await self.client.post(
                config.effective_tts_base_url + "/audio/speech",
                json=self._payload(text, "wav"),
                headers={"Authorization": "Bearer " + config.effective_tts_api_key.get_secret_value()},
                timeout=config.tts_timeout_seconds,
            )
            MiMoTTSProvider._raise_for_status(response.status_code)
            raw = response.content
            if len(raw) > 16 * 1024 * 1024:
                raise ProviderError(502, "tts_audio_too_large", "试听音频过大，请缩短文本。")
            parsed = strip_wav_header(raw)
            if parsed is None:
                if len(raw) >= 2 and len(raw) % 2 == 0:
                    result = pcm_to_wav(raw, sample_rate=24000, channels=1)
                else:
                    raise ProviderError(502, "tts_invalid_audio", "语音服务未返回可播放的 WAV/PCM 音频。")
            else:
                result = raw
            if not audio_fx.is_neutral(1.0, config.tts_rate, config.tts_pitch):
                try:
                    result = await audio_fx.apply(result, 1.0, config.tts_rate, config.tts_pitch)
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            return result
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError(504, "tts_timeout", "语音合成超时；未保存配置，可缩短文本后手动重试。") from None
        except httpx.RequestError:
            raise ProviderError(502, "tts_connection", "无法连接语音服务；请检查接口地址和网络。") from None

    async def close(self) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()


class BailianTTSProvider:
    """Alibaba Bailian qwen3-tts-flash-realtime / qwen3-tts-vc-realtime WS streaming TTS."""

    def __init__(self, settings: Settings, ws_connect=connect):
        self.settings = settings
        self.ws_connect = ws_connect

    def _endpoint(self) -> tuple[str, str, str]:
        config = self.settings
        api_key = config.effective_tts_api_key.get_secret_value().strip()
        model = config.tts_model.strip() or "qwen3-tts-flash-realtime"
        if not api_key:
            raise ProviderError(422, "tts_not_configured", "请先填写百炼语音合成 API Key。")
        base = config.effective_tts_base_url
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{urlencode({'model': model})}", api_key, model

    async def synthesize_stream(self, text: str):
        text = normalize_for_speech(text)
        raw = self._synthesize_stream_raw(text)
        config = self.settings
        shaped = raw if audio_fx.is_neutral(1.0, config.tts_rate, config.tts_pitch) else audio_fx.stream_pcm(
            raw, config.tts_rate, config.tts_pitch)
        try:
            async with aclosing(shaped):
                async for chunk in shaped:
                    yield chunk
        except (OSError, ValueError):
            raise ProviderError(502, "tts_audio_processing", "语音数据或语速音调处理未完成。") from None

    async def _synthesize_stream_raw(self, text: str):
        if not text.strip():
            raise ProviderError(422, "tts_empty_text", "请输入要试听的文字。")
        url, api_key, _ = self._endpoint()
        voice = (self.settings.tts_voice or "Cherry").strip() or "Cherry"
        try:
            async with asyncio.timeout(float(self.settings.tts_timeout_seconds)):
                async with self.ws_connect(
                    url,
                    additional_headers={"Authorization": f"Bearer {api_key}"},
                    proxy=None,
                    close_timeout=2,
                    max_size=4 * 1024 * 1024,
                ) as socket:
                    first = json.loads(await socket.recv())
                    if first.get("type") == "error":
                        raise ProviderError(502, "tts_upstream_error", "百炼实时合成会话建立失败。")
                    await socket.send(json.dumps({
                        "event_id": uuid4().hex,
                        "type": "session.update",
                        "session": {
                            "voice": voice,
                            "mode": "commit",
                            "response_format": "pcm",
                            "sample_rate": 24000,
                        },
                    }))
                    while True:
                        event = json.loads(await socket.recv())
                        if event.get("type") == "error":
                            raise ProviderError(502, "tts_upstream_error", "百炼语音合成参数被拒绝，请检查模型和音色。")
                        if event.get("type") == "session.updated":
                            break
                    await socket.send(json.dumps({
                        "event_id": uuid4().hex,
                        "type": "input_text_buffer.append",
                        "text": text.strip(),
                    }))
                    await socket.send(json.dumps({
                        "event_id": uuid4().hex,
                        "type": "input_text_buffer.commit",
                    }))
                    await socket.send(json.dumps({
                        "event_id": uuid4().hex,
                        "type": "session.finish",
                    }))
                    while True:
                        event = json.loads(await socket.recv())
                        kind = event.get("type")
                        if kind == "error":
                            raise ProviderError(502, "tts_upstream_error", "百炼语音合成返回错误。")
                        if kind == "response.audio.delta" and event.get("delta"):
                            yield base64.b64decode(event["delta"])
                        elif kind == "session.finished":
                            break
        except ProviderError:
            raise
        except TimeoutError:
            raise ProviderError(504, "tts_timeout", "百炼语音合成超时；请缩短文本后重试。") from None
        except (ConnectionClosed, OSError, ValueError, KeyError, binascii.Error):
            raise ProviderError(502, "tts_connection", "无法连接百炼语音合成服务，请检查配置。") from None

    async def synthesize(self, text: str) -> bytes:
        pcm = bytearray()
        async with aclosing(self._synthesize_stream_raw(normalize_for_speech(text))) as stream:
            async for chunk in stream:
                pcm.extend(chunk)
        if not pcm:
            raise ProviderError(502, "tts_invalid_audio", "百炼语音合成未返回音频。")
        result = pcm_to_wav(bytes(pcm), sample_rate=24000, channels=1)
        config = self.settings
        if not audio_fx.is_neutral(1.0, config.tts_rate, config.tts_pitch):
            try:
                result = await audio_fx.apply(result, 1.0, config.tts_rate, config.tts_pitch)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        return result

    async def close(self) -> None:
        return None


def build_tts_provider(settings: Settings, http_client: httpx.AsyncClient | None = None) -> TTSProvider:
    if settings.tts_provider == "openai":
        return OpenAITTSProvider(settings, http_client=http_client)
    if settings.tts_provider == "bailian":
        return BailianTTSProvider(settings)
    return MiMoTTSProvider(settings, http_client=http_client)
