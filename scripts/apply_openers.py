# -*- coding: utf-8 -*-
"""把“开口首响”规则追加进 AI_SYSTEM_PROMPT：随机选一句极短开场，再正式回答。
幂等：已含【开口首响】则不再重复追加。原文备份到 output/original-system-prompt.txt。"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(r"E:\xiaodan")
prompt = dotenv_values(ROOT / ".env").get("AI_SYSTEM_PROMPT") or ""

block = (
    "\n\n【开口首响】\n"
    "每次正式回答前，先用一句很短的开场白快速回应，再从下一句进入正式回答。\n"
    "开场白从这个固定清单里随机挑一句，每次尽量不一样，也不要自创或加长：\n"
    "来了喵／塔菲在／在呢喵／小菲来啦／小菲在／塔菲来咯／来咯来咯。\n"
    "开场白要极短（几个字），说完立刻进入正式内容；开场白不要带问句、不解释，"
    "也不要加波浪号或其他符号。"
)

outdir = ROOT / "output"
outdir.mkdir(exist_ok=True)
(outdir / "original-system-prompt.txt").write_text(prompt, encoding="utf-8")

if "【开口首响】" in prompt:
    new = prompt
    status = "ALREADY_PRESENT"
else:
    new = prompt.rstrip() + block
    status = "APPENDED"
(outdir / "new-system-prompt.txt").write_text(new, encoding="utf-8")
print(status, "orig_len=", len(prompt), "new_len=", len(new), "over4000=", len(new) > 4000)
if len(new) > 4000:
    print("ABORT_TOO_LONG")
    sys.exit(2)

data = json.dumps({"system_prompt": new}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/settings/assistant", data=data, method="PUT",
    headers={"X-Local-Settings": "1", "Content-Type": "application/json; charset=utf-8"})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()
        print("PUT_STATUS", r.status)
except urllib.error.HTTPError as e:
    print("PUT_ERR", e.code, e.read().decode("utf-8", "replace"))
    sys.exit(3)

g = urllib.request.Request("http://127.0.0.1:8000/api/settings", headers={"X-Local-Settings": "1"})
with urllib.request.urlopen(g, timeout=20) as r:
    s = json.loads(r.read().decode("utf-8"))
sp = s.get("system_prompt", "")
print("VERIFY contains_block=", "【开口首响】" in sp, "len=", len(sp),
      "prefix_ok=", sp.startswith(prompt.rstrip()))

t = urllib.request.Request("http://127.0.0.1:8000/api/settings/tts", headers={"X-Local-Settings": "1"})
with urllib.request.urlopen(t, timeout=20) as r:
    tt = json.loads(r.read().decode("utf-8"))
print("TTS_CHECK model=%s rate=%s pitch=%s voice_ok=%s" % (
    tt.get("tts_model"), tt.get("tts_rate"), tt.get("tts_pitch"), bool(tt.get("tts_voice"))))
print("OK")
