import base64
import binascii
import json
from contextlib import aclosing
from io import BytesIO
from pathlib import Path
import subprocess
import wave

import httpx

from . import audio_fx
from .config import ROOT, Settings
from .llm import ProviderError
from .speech_text import normalize_for_speech

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
