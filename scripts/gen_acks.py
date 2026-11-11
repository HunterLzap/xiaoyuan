"""一次性生成口癖首响的塔菲音色缓存（增量、可复核）。

按原话保留 7 句，但**合成输入去掉 ~/～**（避免 TTS 把波浪号念成“横杠”），
用当前百炼实时复刻音色（AI_RT_VOICE）各合成一段 PCM16/24kHz/单声道，落盘到
data/acks/ack_01.pcm ... ack_07.pcm + manifest.json。

关键约束：
- 保存**中性原始 PCM**（不套 tts_rate/tts_pitch，派生交给播放侧），避免以后二次处理。
- 增量：只重生成“无效/坏”的条目，其余复用；坏缓存不会因幂等被跳过。
  条目有效性 = 文件存在非空 + 字节与 manifest 一致 + phrase 对齐 + 合成输入为去~文本 + voice 与当前一致。
- 本次运行重生成条数有硬上限（默认 4），超过则拒绝执行，绝不遍历模型/自动重试。
- 记录真实 usage（供应商不给则 unknown）。

用法（在 E:\\xiaodan 下）：
    .venv\\Scripts\\python.exe scripts/gen_acks.py --dry-run   # 只看计划，不合成
    .venv\\Scripts\\python.exe scripts/gen_acks.py             # 按计划增量生成
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from websockets.asyncio.client import connect  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from backend.app.config import ROOT, Settings  # noqa: E402

PHRASES = [
    "来了喵~",
    "塔菲在~",
    "在呢喵~",
    "小菲来啦",
    "小菲在~",
    "塔菲来咯",
    "来咯来咯",
]

OUT_DIR = ROOT / "data" / "acks"
SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2  # PCM16
FORMAT = "pcm_s16le"
MAX_SYNTH_PER_RUN = 4  # 本次授权上限；超过拒绝执行

INSTRUCTIONS = (
    "你是一个只朗读指定短句的朗读器。用户会给你一句口头语，"
    "你只需用自然、轻快的语气说出这一句，不要添加、不要解释、不要重复、不要多说任何其他字。"
)


def synth_text(phrase: str) -> str:
    """合成输入：去掉会被念成“横杠”的 ~ / ～。"""
    return re.sub(r"[~～]", "", phrase).strip()


def _endpoint(settings: Settings) -> str:
    if settings.rt_provider != "bailian" or not settings.rt_workspace:
        raise SystemExit("仅支持已配置的百炼业务空间（rt_provider=bailian 且有 rt_workspace）。")
    if not settings.rt_api_key.get_secret_value():
        raise SystemExit("缺少百炼 API Key（AI_RT_API_KEY）。")
    if not settings.rt_voice:
        raise SystemExit("缺少实时音色 AI_RT_VOICE。")
    return (f"wss://{settings.rt_workspace}.cn-beijing.maas.aliyuncs.com"
            "/api-ws/v1/realtime?") + urlencode({"model": settings.rt_model})


async def _synthesize_one(settings: Settings, text: str, timeout: float = 25.0):
    """开一条实时连接，合成一句，返回 (原始 PCM16 字节, usage dict 或 None)。只尝试一次。"""
    endpoint = _endpoint(settings)
    audio = bytearray()
    usage = None
    try:
        async with connect(
            endpoint,
            additional_headers={"Authorization": "Bearer " + settings.rt_api_key.get_secret_value()},
            proxy=None,
            close_timeout=2,
            max_size=8 * 1024 * 1024,
        ) as socket:
            await socket.recv()  # session.created
            config = {
                "modalities": ["text", "audio"],
                "instructions": INSTRUCTIONS,
                "audio": {
                    "output": {
                        "voice": settings.rt_voice,
                        "format": {"type": "pcm", "sample_rate": SAMPLE_RATE},
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
                    "content": [{"type": "input_text", "text": text}],
                },
            }))
            await socket.send(json.dumps({
                "type": "response.create", "event_id": uuid4().hex,
            }))
            async with asyncio.timeout(timeout):
                while True:
                    event = json.loads(await socket.recv())
                    kind = event.get("type")
                    if kind == "response.audio.delta":
                        audio.extend(base64.b64decode(event["delta"]))
                    elif kind == "error":
                        raise RuntimeError(f"百炼返回 error: {event.get('error')}")
                    elif kind == "response.done":
                        usage = (event.get("response") or {}).get("usage")
                        break
    except (ConnectionClosed, OSError, TimeoutError) as exc:
        raise RuntimeError(f"连接/超时失败: {exc!r}") from None
    if not audio:
        raise RuntimeError("没有收到 response.audio.delta 音频。")
    return bytes(audio), usage


def _duration_seconds(nbytes: int) -> float:
    return round(nbytes / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH), 3)


def _trim_silence(raw: bytes, threshold: int = 300,
                  lead_ms: int = 30, trail_ms: int = 60) -> bytes:
    """裁掉首尾静音，保留少量边；峰值实测约 6000–9000，threshold 远低于语音。"""
    if len(raw) < 2:
        return raw
    n = len(raw) // 2
    samples = struct.unpack("<%dh" % n, raw)
    first = next((i for i in range(n) if abs(samples[i]) >= threshold), None)
    if first is None:
        return raw
    last = next((i for i in range(n - 1, -1, -1) if abs(samples[i]) >= threshold), None)
    lead = min(int(lead_ms * SAMPLE_RATE / 1000), first)
    trail = min(int(trail_ms * SAMPLE_RATE / 1000), n - 1 - last)
    a = max(0, first - lead)
    b = min(n, last + 1 + trail)
    return struct.pack("<%dh" % (b - a), *samples[a:b])


def _entry_valid(entry, index: int, settings: Settings, top_voice) -> bool:
    """判断某条缓存条目是否可复用（坏缓存 -> False，重新生成）。"""
    if not isinstance(entry, dict):
        return False
    phrase = PHRASES[index - 1]
    expected_synth = synth_text(phrase)
    if entry.get("phrase") != phrase:
        return False
    name = entry.get("file")
    path = OUT_DIR / name if name else None
    if path is None or not path.is_file():
        return False
    size = path.stat().st_size
    if size == 0:
        return False
    if entry.get("bytes") not in (None, size):
        return False
    # voice 必须与当前一致（顶层与条目都不能矛盾）
    if top_voice != settings.rt_voice:
        return False
    if entry.get("voice") not in (None, settings.rt_voice):
        return False
    # 合成输入校验：有条目字段就精确比对；缺字段时只有“去~后仍等于原话”的短语才可复用
    if "synthesis_text" in entry:
        if entry.get("synthesis_text") != expected_synth:
            return False
    elif expected_synth != phrase:
        return False
    return True


def _usage_total(gen_items: dict):
    totals: dict[str, float] = {}
    seen = False
    for item in gen_items.values():
        usage = item.get("usage")
        if isinstance(usage, dict):
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, (int, float)):
                    totals[key] = totals.get(key, 0) + value
                    seen = True
    return totals if seen else "unknown"


def _plan(settings: Settings):
    old = {}
    if (OUT_DIR / "manifest.json").is_file():
        try:
            old = json.loads((OUT_DIR / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
    top_voice = old.get("voice")
    old_files = {e.get("index"): e for e in old.get("files", []) if isinstance(e, dict)}
    reuse, regen = [], []
    for index in range(1, len(PHRASES) + 1):
        if _entry_valid(old_files.get(index), index, settings, top_voice):
            reuse.append(index)
        else:
            regen.append(index)
    return old, old_files, top_voice, reuse, regen


async def main(dry_run: bool) -> int:
    settings = Settings()
    print(f"model={settings.rt_model} voice={settings.rt_voice} workspace={settings.rt_workspace} "
          f"key_configured={bool(settings.rt_api_key.get_secret_value())}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _, old_files, top_voice, reuse, regen = _plan(settings)
    print(f"复用(有效)={reuse}  需重生成={regen}")
    for index in regen:
        print(f"  regen #{index}: {PHRASES[index-1]!r} -> 合成输入 {synth_text(PHRASES[index-1])!r}")

    if len(regen) > MAX_SYNTH_PER_RUN:
        raise SystemExit(f"需重生成 {len(regen)} 条，超过本次授权上限 {MAX_SYNTH_PER_RUN}；未执行，请 Lead 确认。")
    if dry_run:
        print("dry-run：未合成、未写盘。")
        return 0

    # 先逐条合成（每次一条连接、只尝试一次），成功即落盘，失败记录不重试
    gen: dict[int, dict] = {}
    failures: dict[int, str] = {}
    for index in regen:
        phrase = PHRASES[index - 1]
        text = synth_text(phrase)
        try:
            raw, usage = await _synthesize_one(settings, text)
        except Exception as exc:  # 不重试，如实记录
            failures[index] = str(exc)
            print(f"ack_{index:02d} 生成失败（不重试）：{exc}")
            continue
        pcm = _trim_silence(raw)
        (OUT_DIR / f"ack_{index:02d}.pcm").write_bytes(pcm)
        gen[index] = {"pcm": pcm, "usage": usage, "synthesis_text": text}
        print(f"ack_{index:02d}: {phrase!r} -> 合成 {text!r} -> {len(pcm)} bytes usage={usage}")

    # 汇总 manifest（兼容旧字段；新增 synthesis_text/voice/reused/usage/中性标记）
    files_meta = []
    for index in range(1, len(PHRASES) + 1):
        phrase = PHRASES[index - 1]
        name = f"ack_{index:02d}.pcm"
        path = OUT_DIR / name
        if index in gen:
            nbytes = len(gen[index]["pcm"])
            files_meta.append({
                "index": index, "phrase": phrase, "file": name,
                "synthesis_text": gen[index]["synthesis_text"],
                "normalized_input": gen[index]["synthesis_text"],
                "sha256": hashlib.sha256(gen[index]["pcm"]).hexdigest(),
                "bytes": nbytes, "duration_seconds": _duration_seconds(nbytes),
                "voice": settings.rt_voice, "reused": False,
                "usage": gen[index]["usage"] if gen[index]["usage"] is not None else "unknown",
            })
        else:
            # 复用（保留原文件）；失败条目也在此，标记 invalid 供下次重试
            nbytes = path.stat().st_size if path.is_file() else 0
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            entry = dict(old_files.get(index) or {})
            entry.update({
                "index": index, "phrase": phrase, "file": name,
                "synthesis_text": synth_text(phrase),
                "normalized_input": synth_text(phrase),
                "sha256": digest,
                "bytes": nbytes, "duration_seconds": _duration_seconds(nbytes),
                "voice": settings.rt_voice, "reused": True,
                "usage": "reused",
            })
            if index in failures:
                entry["invalid"] = True
                entry["error"] = failures[index]
            files_meta.append(entry)

    manifest = {
        "phrases": PHRASES,
        "sample_rate": SAMPLE_RATE,
        "format": FORMAT,
        "channels": CHANNELS,
        "sample_width_bytes": SAMPLE_WIDTH,
        "voice": settings.rt_voice,
        "model": settings.rt_model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_synthesis": len(PHRASES),
        "trimmed_silence": True,
        "audio_fx_applied": False,   # 中性原始 PCM，派生交给播放侧
        "neutral": True,
        "synthesis_calls_this_run": len(regen),
        "regenerated": sorted(gen),
        "reused": reuse,
        "failures": sorted(failures),
        "usage_total": _usage_total(gen),
        "total_bytes": sum(f["bytes"] for f in files_meta),
        "total_seconds": round(sum(f["duration_seconds"] for f in files_meta), 3),
        "files": files_meta,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest: {OUT_DIR / 'manifest.json'}")
    print(f"本次合成 {len(regen)} 条（成功 {len(gen)}，失败 {len(failures)}）；"
          f"复用 {len(reuse)}；usage_total={manifest['usage_total']}")
    if failures:
        raise SystemExit(f"有 {len(failures)} 条生成失败，已如实记录为 invalid，未重试。")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不合成、不写盘")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.dry_run)))
