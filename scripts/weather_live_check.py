# -*- coding: utf-8 -*-
import json
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
H = {"X-Local-Settings": "1", "Content-Type": "application/json; charset=utf-8"}


def call_weather(args):
    data = json.dumps({"arguments": args}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/tools/get_weather/call", data=data, method="POST", headers=H)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return {"ok": True, "body": json.loads(r.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "body": e.read().decode("utf-8", "replace")}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


def summarize_days(body):
    days = body.get("每日") or body.get("days") or body.get("每日预报") or []
    if isinstance(days, list):
        return {"count": len(days), "first": days[0] if days else None, "last": days[-1] if days else None,
                "keys": list(body.keys())}


res = {}
res["current_beijing"] = call_weather({"city": "北京"})
res["seven_beijing"] = call_weather({"city": "北京", "days": 7})
res["three_shanghai"] = call_weather({"city": "上海", "days": 3})
res["range_beijing"] = call_weather({"city": "北京", "start_date": "2026-11-10", "end_date": "2026-11-12"})
res["ambiguous_chaoyang"] = call_weather({"city": "朝阳"})
res["liaoning_chaoyang"] = call_weather({"city": "辽宁朝阳"})
res["no_city"] = call_weather({})

# condensed view for readability
out = {}
for k, v in res.items():
    if v.get("ok"):
        body = v["body"]
        if isinstance(body, dict) and any(x in body for x in ("每日", "days", "每日预报")):
            out[k] = {"ok": True, "summary": summarize_days(body)}
        elif isinstance(body, dict):
            out[k] = {"ok": True, "body": body}
        else:
            out[k] = {"ok": True, "body": body}
    else:
        out[k] = v

Path(r"E:\xiaodan\output\weather-live-check.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("written", {k: out[k].get("ok") for k in out})
