"""Local, explicitly generated Bailian realtime acknowledgements."""
import asyncio
import base64
from contextlib import suppress
import json
from pathlib import Path
from random import choice
from urllib.parse import urlencode
from uuid import uuid4

from websockets.exceptions import WebSocketException

from .config import ROOT, Settings
from .llm import ProviderError

DEFAULT_ACK_PHRASES = ["嗯，我帮你看看喵。", "稍等一下下喵。", "好哒，我马上查一下喵。"]
_CACHE_DIR = ROOT / "data" / "ack_cache"
_MAX_PCM_BYTES = 512 * 1024


def _read_manifest(directory: Path) -> dict:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return manifest if isinstance(manifest, dict) else {}


def _pcm_path(directory: Path, filename: object) -> Path | None:
    if isinstance(filename, str) and Path(filename).name == filename and filename.endswith(".pcm"):
        path = directory / filename
        if not path.is_symlink():
            return path
    return None


def _available_phrases(directory: Path, voice: str) -> list[dict]:
    manifest = _read_manifest(directory)
    phrases = manifest.get("phrases")
    if manifest.get("voice") != voice or not isinstance(phrases, list):
        return []
    available = []
    for entry in phrases[:5]:
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            continue
        path = _pcm_path(directory, entry.get("file"))
        try:
            if path is not None and path.is_file():
                size = path.stat().st_size
                if 0 < size <= _MAX_PCM_BYTES and size % 2 == 0 and size == entry.get("bytes"):
                    available.append(entry)
        except OSError:
            continue
    return available


def ack_cache_status(voice: str, *, cache_dir: Path | None = None) -> dict:
    phrases = _available_phrases(cache_dir or _CACHE_DIR, voice)
    return {"voice": voice, "count": len(phrases), "phrases": [item["text"] for item in phrases]}


def pick_ack_pcm(voice: str, *, cache_dir: Path | None = None) -> bytes | None:
    directory = cache_dir or _CACHE_DIR
    phrases = _available_phrases(directory, voice)[:3]
    if not phrases:
        return None
    entry = choice(phrases)
    path = _pcm_path(directory, entry["file"])
    if path is None:
        return None
    try:
        with path.open("rb") as stream:
            pcm = stream.read(_MAX_PCM_BYTES + 1)
        return pcm if len(pcm) == entry["bytes"] else None
    except OSError:
        return None


def _save_cache(directory: Path, voice: str, model: str, phrases: list[str], audio: list[bytes]) -> None:
    previous = _read_manifest(directory).get("phrases", [])
    generation = uuid4().hex
    directory.mkdir(parents=True, exist_ok=True)
    pending = directory / f".{generation}.json"
    entries = []
    try:
        for index, (text, pcm) in enumerate(zip(phrases, audio, strict=True)):
            filename = f"{generation}-{index}.pcm"
            entries.append({"text": text, "file": filename, "bytes": len(pcm)})
            (directory / filename).write_bytes(pcm)
        pending.write_text(json.dumps({"voice": voice, "model": model, "phrases": entries},
                                      ensure_ascii=False), encoding="utf-8")
        pending.replace(directory / "manifest.json")
    except OSError:
        for entry in entries:
            with suppress(OSError):
                (directory / entry["file"]).unlink(missing_ok=True)
        with suppress(OSError):
            pending.unlink(missing_ok=True)
        raise
    if isinstance(previous, list):
        for entry in previous:
            path = _pcm_path(directory, entry.get("file")) if isinstance(entry, dict) else None
            if path is not None:
                with suppress(OSError):
                    path.unlink(missing_ok=True)


async def synthesize_ack_phrases(settings: Settings, phrases: list[str] | None = None,
                                 *, cache_dir: Path | None = None) -> dict:
    from .realtime import DirectConnect

    key = settings.rt_api_key.get_secret_value()
    if settings.rt_provider != "bailian" or not key:
        raise ProviderError(422, "ack_bailian_required", "请先配置百炼实时语音和 API Key。")
    phrases = DEFAULT_ACK_PHRASES if phrases is None else [item.strip() for item in phrases]
    if not 1 <= len(phrases) <= 5 or any(not 1 <= len(item) <= 40 for item in phrases):
        raise ProviderError(422, "ack_invalid_phrases", "请提供 1 到 5 条短句，每条 1 到 40 字。")
    host = (f"{settings.rt_workspace}.cn-beijing.maas.aliyuncs.com" if settings.rt_workspace
            else "dashscope.aliyuncs.com")
    url = f"wss://{host}/api-ws/v1/realtime?" + urlencode({"model": settings.rt_model})
    if (settings.rt_model or "").strip().lower().startswith("qwen-audio-"):
        session: dict = {
            "modalities": ["text", "audio"],
            "turn_detection": None,
            "instructions": "只原样朗读用户提供的短句，不加任何前后缀，不解释。",
            "voice": (settings.rt_voice or "").strip() or "longanqian_v3.1",
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
        }
    else:
        session = {
            "modalities": ["text", "audio"], "turn_detection": None,
            "instructions": "只原样朗读用户提供的短句，不加任何前后缀，不解释。",
            "audio": {
                "input": {"format": {"type": "pcm", "sample_rate": 16000}},
                "output": {"format": {"type": "pcm", "sample_rate": 24000}},
            },
        }
        if settings.rt_model == "qwen3.8-omni-flash-realtime":
            session["audio"]["output"]["voice"] = settings.rt_voice
        else:
            session["voice"] = settings.rt_voice

    audio = []
    try:
        async with asyncio.timeout(90):
            async with DirectConnect(url, additional_headers={"Authorization": "Bearer " + key},
                                     proxy=None, close_timeout=2, max_size=4 * 1024 * 1024) as ws:
                async def send(kind, **fields):
                    await ws.send(json.dumps({"type": kind, "event_id": uuid4().hex, **fields}))

                if json.loads(await ws.recv())["type"] != "session.created":
                    raise ValueError()
                await send("session.update", session=session)
                if json.loads(await ws.recv())["type"] != "session.updated":
                    raise ValueError()
                for phrase in phrases:
                    await send("conversation.item.create", item={"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": phrase}]})
                    await send("response.create")
                    pcm = bytearray()
                    while True:
                        event = json.loads(await ws.recv())
                        kind = event["type"]
                        if kind == "error":
                            raise ValueError()
                        if kind in {"response.audio.delta", "response.output_audio.delta"}:
                            pcm.extend(base64.b64decode(event["delta"], validate=True))
                            if len(pcm) > _MAX_PCM_BYTES:
                                raise ValueError()
                        if kind == "response.done":
                            if event["response"].get("status") != "completed" or not pcm or len(pcm) % 2:
                                raise ValueError()
                            audio.append(bytes(pcm))
                            break
    except (WebSocketException, OSError, ValueError, KeyError, TypeError):
        raise ProviderError(502, "ack_generation_failed", "未能从当前百炼音色生成首响，请检查实时模型和音色设置。") from None

    try:
        await asyncio.to_thread(_save_cache, cache_dir or _CACHE_DIR, settings.rt_voice, settings.rt_model, phrases, audio)
    except OSError:
        raise ProviderError(500, "ack_cache_write_failed", "无法写入本机首响缓存。") from None
    return {"voice": settings.rt_voice, "count": len(audio), "phrases": phrases}
