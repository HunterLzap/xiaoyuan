from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from . import voices
from .config import ROOT, Settings
from .llm import ProviderError

INDEX = ROOT / "data" / "qwen_voices.json"
SUPPORTED_MODELS = {
    "qwen-audio-3.1-realtime-flash",
    "qwen-audio-3.1-realtime-plus",
    "qwen-audio-3.0-realtime-flash",
    "qwen3.8-omni-flash-realtime",
    "qwen3.5-omni-flash-realtime",
    "qwen3.5-omni-plus-realtime",
    "qwen3-tts-vc-realtime",
}


def is_supported_target_model(model: str) -> bool:
    name = (model or "").strip()
    return name in SUPPORTED_MODELS or name.startswith(("qwen3-tts-vc-realtime", "qwen-audio-"))


def _is_voice_enrollment_model(model: str) -> bool:
    return (model or "").strip().lower().startswith("qwen-audio-")


def _active_target_model(settings: Settings) -> str:
    if settings.voice_mode == "pipeline" and settings.tts_provider == "bailian":
        return settings.tts_model
    return settings.rt_model


def _active_api_key(settings: Settings) -> str:
    if settings.voice_mode == "pipeline" and settings.tts_provider == "bailian":
        return settings.effective_tts_api_key.get_secret_value()
    return settings.rt_api_key.get_secret_value()


def _read_records() -> list[dict]:
    if not INDEX.is_file():
        return []
    try:
        value = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    records = value.get("voices") if isinstance(value, dict) else None
    return [item for item in records or []
            if isinstance(item, dict) and item.get("voice") and item.get("name")]


def _write_records(records: list[dict]) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=INDEX.parent,
                prefix="qwen-voices-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"voices": records}, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, INDEX)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _endpoint(settings: Settings) -> str:
    key = _active_api_key(settings).strip()
    if not key:
        raise ProviderError(422, "qwen_clone_unavailable", "请先保存百炼 API Key。")
    if settings.rt_workspace:
        return (f"https://{settings.rt_workspace}.cn-beijing.maas.aliyuncs.com"
                "/api/v1/services/audio/tts/customization")
    if settings.voice_mode == "realtime" and settings.rt_provider != "bailian":
        raise ProviderError(422, "qwen_clone_unavailable", "音色复刻仅支持已配置的百炼服务。")
    return "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"


async def _request(settings: Settings, payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
            response = await client.post(
                _endpoint(settings),
                headers={
                    "Authorization": "Bearer " + _active_api_key(settings).strip(),
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise ProviderError(502, "qwen_clone_unreachable", "无法连接百炼音色复刻服务，请稍后重试。") from None
    if response.status_code != 200:
        code = data.get("code") if isinstance(data, dict) else None
        message = data.get("message") if isinstance(data, dict) else None
        detail = " · ".join(str(item) for item in (code, message) if item)[:180]
        raise ProviderError(422, "qwen_clone_failed",
                            "百炼未接受这次复刻。" + (f"（{detail}）" if detail else ""))
    if not isinstance(data, dict):
        raise ProviderError(502, "qwen_clone_invalid", "百炼返回了无法识别的音色结果。")
    return data


def _local_records(target_model: str) -> list[dict]:
    return [item for item in _read_records()
            if item.get("target_model") == target_model]


def _merge_remote(settings: Settings, remote: list[dict], target_model: str | None = None) -> list[dict]:
    model = target_model or _active_target_model(settings)
    local = {item["voice"]: item for item in _local_records(model)}
    result = []
    for item in remote:
        voice = item.get("voice") or item.get("voice_id")
        if not isinstance(voice, str) or not voice:
            continue
        item_model = item.get("target_model") or model
        if target_model and item.get("target_model") and item_model != target_model:
            continue
        if target_model and not item.get("target_model") and voice.startswith("qwen-audio-") and not voice.startswith(f"{target_model}-"):
            continue
        saved = local.get(voice)
        name = saved["name"] if saved else f"克隆音色 {voice[-6:]}"
        result.append({
            "voice": voice,
            "name": name,
            "target_model": item_model,
            "created": (saved or {}).get("created") or item.get("gmt_create"),
            "cloned": True,
        })
    known = {item["voice"] for item in result}
    result.extend(item for item in local.values() if item["voice"] not in known)
    return result


async def list_public(settings: Settings, target_model: str | None = None) -> list[dict]:
    model = target_model or _active_target_model(settings)
    if _is_voice_enrollment_model(model):
        data = await _request(settings, {
            "model": "voice-enrollment",
            "input": {"action": "list_voice", "page_index": 0, "page_size": 100},
        })
    else:
        data = await _request(settings, {
            "model": "qwen-voice-enrollment",
            "input": {"action": "list", "page_index": 0, "page_size": 100},
        })
    remote = data.get("output", {}).get("voice_list") or []
    return _merge_remote(settings, [item for item in remote if isinstance(item, dict)], target_model=model)


async def create(settings: Settings, raw: bytes, filename: str, name: str, target_model: str | None = None) -> dict:
    model = (target_model or _active_target_model(settings)).strip()
    if not is_supported_target_model(model):
        raise ProviderError(422, "qwen_clone_model", "当前模型不支持百炼音色复刻。")
    local = voices.process_upload(raw, filename, name)
    try:
        sample = voices.resolve(local.get("sample", ""))
        if sample is None:
            raise ProviderError(500, "qwen_clone_sample", "无法读取处理后的复刻音频。")
        encoded = sample.read_bytes()
        data_uri = "data:audio/mpeg;base64," + base64.b64encode(encoded).decode("ascii")
        if _is_voice_enrollment_model(model):
            payload = {
                "model": "voice-enrollment",
                "input": {
                    "action": "create_voice",
                    "target_model": model,
                    "prefix": "v" + secrets.token_hex(4),
                    "audio": data_uri,
                    "language_hints": ["zh"],
                },
            }
        else:
            payload = {
                "model": "qwen-voice-enrollment",
                "input": {
                    "action": "create",
                    "target_model": model,
                    "preferred_name": "v" + secrets.token_hex(7),
                    "audio": {"data": data_uri},
                    "language": "zh",
                    "text": "",
                },
                "parameters": {"skip_audio_process": False, "voice_clone_mode": "normal"},
            }
        data = await _request(settings, payload)
    finally:
        try:
            voices.delete(local["id"])
        except ProviderError:
            pass
    output = data.get("output") or {}
    voice = output.get("voice_id") or output.get("voice")
    if not isinstance(voice, str) or not voice:
        raise ProviderError(502, "qwen_clone_invalid", "百炼没有返回可用的音色 ID。")
    record = {
        "name": local["name"],
        "voice": voice,
        "target_model": model,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    records = [item for item in _read_records() if item.get("voice") != voice]
    records.append(record)
    _write_records(records)
    return record


async def delete(settings: Settings, voice: str) -> None:
    if _is_voice_enrollment_model(_active_target_model(settings)) or voice.startswith("qwen-audio-"):
        await _request(settings, {
            "model": "voice-enrollment",
            "input": {"action": "delete_voice", "voice_id": voice},
        })
    else:
        await _request(settings, {
            "model": "qwen-voice-enrollment",
            "input": {"action": "delete", "voice": voice},
        })
    _write_records([item for item in _read_records() if item.get("voice") != voice])


async def preview(settings: Settings, voice: str, text: str) -> bytes:
    from io import BytesIO
    from urllib.parse import urlencode
    from uuid import uuid4
    import wave

    base = (f"wss://{settings.rt_workspace}.cn-beijing.maas.aliyuncs.com"
            "/api-ws/v1/realtime?") if settings.rt_workspace else "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?"
    endpoint = base + urlencode({"model": settings.rt_model})
    audio = bytearray()
    try:
        async with connect(
            endpoint,
            additional_headers={"Authorization": "Bearer " + settings.rt_api_key.get_secret_value()},
            proxy=None,
            close_timeout=2,
            max_size=4 * 1024 * 1024,
        ) as socket:
            await socket.recv()
            if (settings.rt_model or "").strip().lower().startswith("qwen-audio-"):
                config = {
                    "modalities": ["text", "audio"],
                    "voice": voice,
                    "output_audio_format": "pcm",
                    "instructions": "只朗读用户提供的试听文字。",
                    "turn_detection": None,
                }
            else:
                config = {
                    "modalities": ["text", "audio"],
                    "instructions": "只朗读用户提供的试听文字。",
                    "audio": {
                        "output": {
                            "voice": voice,
                            "format": {"type": "pcm", "sample_rate": 24000},
                        },
                    },
                    "turn_detection": None,
                }
            await socket.send(json.dumps({
                "type": "session.update", "event_id": uuid4().hex, "session": config,
            }))
            while json.loads(await socket.recv()).get("type") != "session.updated":
                continue
            await socket.send(json.dumps({
                "type": "conversation.item.create",
                "event_id": uuid4().hex,
                "item": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": text[:80]}],
                },
            }))
            await socket.send(json.dumps({
                "type": "response.create", "event_id": uuid4().hex,
            }))
            async with asyncio.timeout(20):
                while True:
                    event = json.loads(await socket.recv())
                    if event.get("type") in {"response.audio.delta", "response.output_audio.delta"}:
                        audio.extend(base64.b64decode(event["delta"]))
                    elif event.get("type") == "error":
                        raise ValueError()
                    elif event.get("type") == "response.done":
                        break
    except (ConnectionClosed, OSError, TimeoutError, ValueError, KeyError):
        raise ProviderError(502, "qwen_voice_preview_failed", "复刻音色试听失败，请检查百炼连接。") from None
    if not audio:
        raise ProviderError(502, "qwen_voice_preview_empty", "复刻音色没有返回试听音频。")
    output = BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(audio)
    from .audio_fx import apply
    return await apply(output.getvalue(), speed=settings.tts_rate, pitch=settings.tts_pitch)
