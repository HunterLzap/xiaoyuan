"""Local HTTP client; never reads or sends a provider API key."""
import argparse
import json
import sys

import httpx


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="AtomS3R 本地文字对话测试")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--message", help="单次消息；不填则连续对话")
    parser.add_argument("--session", help="继续已有会话")
    args = parser.parse_args()
    session = args.session
    try:
        with httpx.Client(base_url=args.url, timeout=310, trust_env=False) as client:
            while True:
                message = args.message if args.message is not None else input("你（/new 新对话，/quit 退出）：").strip()
                if message == "/quit":
                    break
                if message == "/new":
                    if session:
                        response = client.delete(f"/sessions/{session}")
                        if response.status_code not in {204, 404}:
                            print(response.text)
                            continue
                    session = None
                    continue
                if not message:
                    continue
                body = {"message": message}
                if session:
                    body["session_id"] = session
                response = client.post("/chat", json=body)
                data = response.json()
                if response.is_error:
                    print(json.dumps(data, ensure_ascii=False))
                    if args.message is not None:
                        return 1
                    if isinstance(data.get("detail"), dict) and data["detail"].get("code") == "session_not_found":
                        session = None
                    continue
                session = data["session_id"]
                print(json.dumps(data, ensure_ascii=False, indent=2))
                if args.message is not None:
                    break
    except (httpx.HTTPError, EOFError, KeyboardInterrupt) as error:
        if isinstance(error, httpx.HTTPError):
            print("无法访问本地服务；请先启动 FastAPI。", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
