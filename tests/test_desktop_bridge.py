"""Tests for cross-platform Windows & macOS Desktop Node bridge, approvals, agent_profile, and Computer Use."""
from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.app.config import Settings
from backend.app.desktop import DesktopHub, is_sensitive_path
from backend.app.desktop_tools import (
    DesktopGuiActionTool,
    DesktopInspectScreenTool,
    DesktopReadFileTool,
)
from backend.app.devices import DeviceHub, create_gateway
from backend.app.error_log import ErrorLogStore
from backend.app.llm import Completion, ProviderError
from backend.app.main import create_app
from backend.app.prompt_builder import build_system_prompt
from backend.app.realtime import RealtimeTurn
from backend.app.settings_store import SettingsStore
from backend.app.text_tool_selection import TextToolSelection
from backend.app.tool_gateway import SideEffectConfirmationStore
from desktop_node.client import _describe_rpc_for_hud, _handle_request, default_node_id, execute_rpc
from desktop_node.platform_base import DesktopAdapter, DesktopRpcError
from desktop_node.platform_macos import MacOSDesktopAdapter
from desktop_node.platform_windows import WindowsDesktopAdapter

HEADERS = {"X-Local-Settings": "1", "Origin": "http://127.0.0.1"}


class _ScriptedLLM:
    def __init__(self, steps):
        self.steps = list(steps)
        self.seen_tools: list[list[str]] = []

    async def complete_stream(self, messages, tools=None):
        self.seen_tools.append([item["function"]["name"] for item in (tools or [])])
        step = self.steps.pop(0)
        for item in step:
            yield item

    async def close(self):
        return None


def _base_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        voice_mode="pipeline",
        provider="tokendance",
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="gpt-test",
        tts_provider="openai",
        tts_api_key="tts-key",
        tts_model="tts-1",
        tts_voice="alloy",
        m5stack_enabled=False,
        personal_kb_enabled=False,
        weather_enabled=False,
        desktop_enabled=True,
        usage_log_path=None,
        history_db_path=tmp_path / "conversations.sqlite3",
        personal_kb_db_path=tmp_path / "personal_kb.sqlite3",
        assistant_db_path=tmp_path / "assistant_state.sqlite3",
    )


def test_desktop_sensitive_path_guard_blocks_credentials():
    for path in (
        ".env",
        "~/.env.local",
        "~/.ssh/id_rsa",
        "/Users/demo/.ssh/id_ed25519",
        "C:\\Users\\demo\\project\\.env",
        "/tmp/cert.pem",
        "/opt/xiaodan/data/desktop_nodes.json",
    ):
        assert is_sensitive_path(path) is True
    assert is_sensitive_path("~/Desktop/notes.md") is False


def test_desktop_gateway_auth_reconnect_and_rpc_roundtrip(tmp_path):
    hub = DesktopHub(path=tmp_path / "desktop_nodes.json", port=8003)
    device_hub = DeviceHub(tmp_path / "devices.json")
    gw = create_gateway(device_hub, desktop_hub=hub)
    token = hub.gateway_token
    assert len(token) >= 20

    with TestClient(gw) as client:
        # 1. Invalid token is rejected without registering any node.
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/desktop/v1/", headers={"Authorization": "Bearer wrong-token"}):
                pass
        assert hub.active == {}

        # 2. First Mac node connects cleanly.
        with client.websocket_connect("/desktop/v1/", headers={"Authorization": f"Bearer {token}"}) as ws1:
            ws1.send_json({
                "type": "hello",
                "node_id": "macos-work",
                "name": "MacBook Pro",
                "os": "macos",
                "hostname": "ryan-mbp",
                "screen": {"width": 2880, "height": 1800},
                "capabilities": ["screenshot", "clipboard", "files", "open", "gui"],
            })
            welcome = ws1.receive_json()
            assert welcome["type"] == "welcome"
            assert welcome["node_id"] == "macos-work"
            assert hub.default_node_id == "macos-work"

            # 3. Same node_id reconnect evicts stale socket cleanly instead of 403 zombie lockout.
            with client.websocket_connect("/desktop/v1/", headers={"Authorization": f"Bearer {token}"}) as ws2:
                ws2.send_json({
                    "type": "hello",
                    "node_id": "macos-work",
                    "name": "MacBook Pro",
                    "os": "macos",
                    "hostname": "ryan-mbp",
                    "screen": {"width": 2880, "height": 1800},
                    "capabilities": ["screenshot", "gui"],
                })
                welcome2 = ws2.receive_json()
                assert welcome2["type"] == "welcome"
                assert "macos-work" in hub.active
                assert hub.resolve_node("mac").node_id == "macos-work"


def test_desktop_computer_use_screenshot_vision_and_scaling(tmp_path):
    hub = DesktopHub(path=tmp_path / "desktop_nodes.json", port=8003)
    fake_png = base64.b64encode(b"FAKEJPEGDATA").decode("ascii")
    recorded_gui: list[dict] = []

    class _FakeConn:
        node_id = "win-desktop"
        name = "Windows Desk"
        os_name = "windows"
        hostname = "win-pc"
        arch = "AMD64"
        capabilities = ["screenshot", "gui"]
        screen = {"width": 2560, "height": 1440}
        connected_at = "2026-11-16T00:00:00+00:00"
        last_seen_at = "2026-11-16T00:00:00+00:00"
        last_screenshot = None

        class _FakeWs:
            async def close(self, code=1000):
                pass

        ws = _FakeWs()

        def close(self):
            pass

        def public(self):
            return {"node_id": self.node_id, "name": self.name, "os": self.os_name, "online": True}

        async def rpc(self, action, params=None, timeout=25.0):
            if action == "screenshot":
                return {
                    "image_base64": fake_png,
                    "mime_type": "image/jpeg",
                    "image_width": 1280,
                    "image_height": 720,
                    "screen_width": 2560,
                    "screen_height": 1440,
                    "active_window": {"app": "Code", "title": "xiaoyuan - VS Code"},
                }
            if action == "gui_action":
                recorded_gui.append(params)
                return {"ok": True, **params}
            raise AssertionError(f"unexpected action {action}")

    hub.active["win-desktop"] = _FakeConn()  # type: ignore[assignment]

    async def fake_analyze(**kwargs):
        assert kwargs["img_w"] == 1280
        assert kwargs["scr_w"] == 2560
        return {"vision_analysis": "设置按钮大约在图像坐标 [640, 360]。"}

    hub._analyze_screenshot = fake_analyze  # type: ignore[method-assign]

    async def run():
        inspect_tool = DesktopInspectScreenTool(hub)
        res = await inspect_tool.run({"question": "设置按钮在哪"})
        assert res["screen"] == {"width": 2560, "height": 1440}
        assert res["image"]["width"] == 1280
        assert res["active_window"]["title"] == "xiaoyuan - VS Code"
        assert "640, 360" in res["vision_analysis"]
        assert hub.active["win-desktop"].last_screenshot["bytes"] == b"FAKEJPEGDATA"

        # Image pixel (640, 360) in 1280x720 must map cleanly to logical screen (1280, 720) in 2560x1440.
        gui_tool = DesktopGuiActionTool(hub)
        click_res = await gui_tool.run({"action": "click", "x": 640, "y": 360, "coord_space": "image"})
        assert click_res["screen_coords"] == {"x": 1280, "y": 720}
        assert recorded_gui == [{"action": "click", "x": 1280, "y": 720}]

        # Credential reads stay rejected even before RPC.
        read_tool = DesktopReadFileTool(hub)
        with pytest.raises(ProviderError) as err:
            await read_tool.run({"path": "~/.ssh/id_ed25519"})
        assert err.value.code == "access_denied"

    asyncio.run(run())


def test_approval_card_rest_and_chat_execution_persistence(tmp_path):
    llm = _ScriptedLLM([
        # Turn 1: agent attempts desktop_open -> blocked cleanly by SideEffectConfirmationStore -> asks user.
        [
            Completion(
                reply="",
                usage=None,
                finish_reason="tool_calls",
                tool_calls=[{
                    "id": "call-open-1",
                    "type": "function",
                    "function": {"name": "desktop_open", "arguments": '{"target": "https://example.com"}'},
                }],
            ),
        ],
        [
            "我准备在电脑上打开 https://example.com，请点击确认执行或直接回复确认。",
            Completion(reply="我准备在电脑上打开 https://example.com，请点击确认执行或直接回复确认。", usage=None, finish_reason="stop"),
        ],
        # Turn 2: after user clicks 确认执行 and sends confirmation turn -> retries and completes!
        [
            Completion(
                reply="",
                usage=None,
                finish_reason="tool_calls",
                tool_calls=[{
                    "id": "call-open-2",
                    "type": "function",
                    "function": {"name": "desktop_open", "arguments": '{"target": "https://example.com"}'},
                }],
            ),
        ],
        [
            "已为你打开 https://example.com。",
            Completion(reply="已为你打开 https://example.com。", usage=None, finish_reason="stop"),
        ],
    ])
    hub = DesktopHub(path=tmp_path / "desktop_nodes.json", port=8003)
    opened: list[dict] = []

    class _FakeDesktopNode:
        node_id = "mac-main"
        name = "My Mac"
        os_name = "macos"
        hostname = "mac"
        arch = "arm64"
        capabilities = ["screenshot", "open", "gui", "shell"]
        screen = {"width": 1440, "height": 900}
        connected_at = "2026-11-16T00:00:00+00:00"
        last_seen_at = "2026-11-16T00:00:00+00:00"
        last_screenshot = None

        class _FakeWs:
            async def close(self, code=1000):
                pass

        ws = _FakeWs()

        def close(self):
            pass

        def public(self):
            return {"node_id": self.node_id, "name": self.name, "os": self.os_name, "online": True}

        async def rpc(self, action, params=None, timeout=25.0):
            opened.append({"action": action, "params": params})
            return {"ok": True, "opened": params["target"]}

    hub.active["mac-main"] = _FakeDesktopNode()  # type: ignore[assignment]
    cfg = _base_settings(tmp_path)
    app = create_app(
        cfg,
        settings_store=SettingsStore(tmp_path / ".env"),
        provider_factory=lambda c: llm,
        desktop_hub=hub,
    )

    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        sel = client.put("/api/assistant/selection", json={"selected_tool_ids": ["desktop_control"], "selected_kb_ids": []}, headers=HEADERS)
        assert sel.status_code == 200

        # Also save agent_profile and verify prompt builder sees it.
        prof_res = client.put("/api/settings/assistant", json={"agent_profile": "Mac 代码目录在 ~/Projects"}, headers=HEADERS)
        assert prof_res.status_code == 200
        assert prof_res.json()["text"]["agent_profile"] == "Mac 代码目录在 ~/Projects"
        prompt = build_system_prompt(app.state.service.settings, "text", ["desktop_open"])
        assert "Mac 代码目录在 ~/Projects" in prompt

        # Turn 1: blocked -> pending_approval returned & persisted in SQLite transcript.
        res1 = client.post("/chat", json={"message": "打开 https://example.com"})
        assert res1.status_code == 200
        data1 = res1.json()
        sid = data1["session_id"]
        pa = data1["pending_approval"]
        assert pa is not None
        assert pa["tool_name"] == "desktop_open"
        assert pa["status"] == "pending"
        assert opened == []

        # Interactive REST approval button click.
        app_res = client.post(
            f"/api/approvals/{pa['approval_id']}",
            json={"decision": "approve", "session_id": sid},
            headers=HEADERS,
        )
        assert app_res.status_code == 200
        assert app_res.json()["status"] == "approved"

        # Turn 2: follow-up executes tool cleanly and updates prior message approval status to consumed.
        res2 = client.post("/chat", json={"message": "确认执行", "session_id": sid})
        assert res2.status_code == 200
        assert len(opened) == 1
        assert opened[0]["params"]["target"] == "https://example.com"
        assert res2.json()["pending_approval"] is None

        detail = client.get(f"/sessions/{sid}").json()
        first_assistant = [m for m in detail["messages"] if m["role"] == "assistant"][0]
        assert first_assistant["pending_approval"]["status"] == "consumed"

        # Verify RealtimeTurn also exposes guarded desktop write tools safely.
        ctx = app.state.service.tool_context(UUID(sid), uuid4(), "device_voice", "打开电脑")
        rt = RealtimeTurn(app.state.service, UUID(sid), "device_voice", lambda *a: None, True)
        rt.tool_context = ctx
        rt_names = {item["name"] for item in rt._realtime_tool_definitions()}
        assert {"desktop_inspect_screen", "desktop_open", "desktop_gui_action"} <= rt_names

        # Check admin /api/desktop & screenshot route without token leak in /health.
        health = client.get("/health").json()
        assert health["desktop_enabled"] is True
        assert health["desktop_online_nodes"] == 1
        assert "gateway_token" not in json.dumps(health)

        desk = client.get("/api/desktop", headers=HEADERS).json()
        assert desk["online_count"] == 1
        assert hub.gateway_token in desk["commands"]["macos"]
        assert hub.gateway_token in desk["commands"]["windows"]


def test_cross_platform_adapters_and_safety_flags(tmp_path):
    (tmp_path / "readme.txt").write_text("hello desktop node", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=123", encoding="utf-8")

    class _DummyAdapter(DesktopAdapter):
        os_name = "windows"

        def screen_size(self):
            return {"width": 1920, "height": 1080}

        def active_window(self):
            return {"app": "Explorer", "title": "Desktop"}

        def capture_screenshot(self, max_width=1280, max_height=800, quality=80):
            return {"image_base64": "", "image_width": 1280, "image_height": 720}

        def clipboard_get(self):
            return {"text": "clip"}

        def clipboard_set(self, text):
            return {"ok": True, "length": len(text)}

        def open_target(self, target, kind="auto"):
            return {"ok": True, "opened": target}

        def gui_action(self, action, *, x=None, y=None, text=None, keys=None, scroll_y=0):
            return {"ok": True, "action": action, "x": x, "y": y}

    adapter = _DummyAdapter()
    listing = execute_rpc(adapter, "list_dir", {"path": str(tmp_path)})
    names = [e["name"] for e in listing["entries"]]
    assert "readme.txt" in names

    content = execute_rpc(adapter, "read_file", {"path": str(tmp_path / "readme.txt")})
    assert content["content"] == "hello desktop node"

    with pytest.raises(DesktopRpcError) as env_err:
        execute_rpc(adapter, "read_file", {"path": str(tmp_path / ".env")})
    assert env_err.value.code == "access_denied"

    with pytest.raises(DesktopRpcError) as gui_err:
        execute_rpc(adapter, "gui_action", {"action": "click", "x": 10, "y": 10}, allow_gui=False)
    assert gui_err.value.code == "gui_disabled"

    with pytest.raises(DesktopRpcError) as sh_err:
        execute_rpc(adapter, "run_command", {"command": "echo hi"}, allow_shell=False)
    assert sh_err.value.code == "shell_disabled"

    assert default_node_id("macos", "Ryan's MBP") == "macos-ryan-s-mbp"
    assert default_node_id("windows", "DESKTOP_01") == "windows-desktop_01"


def test_windows_and_macos_adapter_logic_with_os_mocks(monkeypatch):
    # Verify WindowsDesktopAdapter ctypes GUI dispatch without invoking real Win32 API.
    win_calls = []

    class _FakeUser32:
        def GetSystemMetrics(self, idx):
            return 2560 if idx == 0 else 1440

        def GetForegroundWindow(self):
            return 0

        def SetCursorPos(self, x, y):
            win_calls.append(("SetCursorPos", x, y))

        def mouse_event(self, flags, dx, dy, data, extra):
            win_calls.append(("mouse_event", flags, data))

        def SendInput(self, count, arr, size):
            win_calls.append(("SendInput", count))

    monkeypatch.setattr("desktop_node.platform_windows.ctypes", SimpleNamespace(
        windll=SimpleNamespace(user32=_FakeUser32()),
        POINTER=lambda x: x,
        sizeof=lambda x: 40,
        c_void_p=int,
        Structure=object,
        Union=object,
    ), raising=False)
    win = WindowsDesktopAdapter()
    assert win.screen_size() == {"width": 2560, "height": 1440}
    assert win.gui_action("click", x=100, y=200)["ok"] is True
    assert ("SetCursorPos", 100, 200) in win_calls
    mac_events = []

    class _FakeCG:
        class CGPoint:
            def __init__(self, x, y):
                self.x, self.y = x, y

        def CGMainDisplayID(self):
            return 1

        def CGDisplayPixelsWide(self, did):
            return 1728

        def CGDisplayPixelsHigh(self, did):
            return 1117

        def CGEventCreateMouseEvent(self, src, typ, pt, btn):
            return ("mouse", typ, pt.x, pt.y, btn)

        def CGEventCreateKeyboardEvent(self, src, code, down):
            return ["key", code, down, 0]

        def CGEventSetFlags(self, ev, flags):
            ev[3] = flags

        def CGEventPost(self, tap, ev):
            mac_events.append(ev)

        def CFRelease(self, ev):
            pass

    mac = MacOSDesktopAdapter()
    mac._cg = _FakeCG()
    assert mac.screen_size() == {"width": 1728, "height": 1117}
    assert mac.gui_action("click", x=300, y=400)["ok"] is True
    assert any(e[0] == "mouse" and e[2] == 300.0 and e[3] == 400.0 for e in mac_events)
    assert mac.gui_action("hotkey", keys=["cmd", "c"])["ok"] is True
    assert any(isinstance(e, list) and e[0] == "key" and e[1] == 8 for e in mac_events)

    # Confirm SideEffectConfirmationStore expires old pending actions and scopes desktop lease safely.
    store = SideEffectConfirmationStore(ttl_seconds=5.0)
    sid, t1, t2, t3 = uuid4(), uuid4(), uuid4(), uuid4()
    assert store.authorize(sid, t1, "desktop_open", {"target": "Safari"}) == "ask"
    pending = store.latest_for_turn(sid, t1)
    assert pending is not None and pending["status"] == "pending"
    assert store.decide(pending["approval_id"], "deny", session_id=sid)["status"] == "denied"
    store.begin_turn(sid, t2, "好")
    assert store.confirmed_action(sid, t2) is None

    # Granting desktop lease unlocks subsequent interactive desktop GUI actions but NEVER desktop_run_command.
    assert store.authorize(sid, t2, "desktop_open", {"target": "飞书"}) == "ask"
    p_open = store.latest_for_turn(sid, t2)
    assert p_open is not None
    assert store.decide(p_open["approval_id"], "approve_desktop_lease", session_id=sid)["status"] == "approved"
    store.begin_turn(sid, t3, "确认执行")
    assert store.authorize(sid, t3, "desktop_gui_action", {"action": "click", "x": 10, "y": 20}) == "execute"
    assert store.authorize(sid, t3, "desktop_set_clipboard", {"text": "abc"}) == "execute"
    assert store.authorize(sid, t3, "desktop_run_command", {"command": "whoami"}) == "ask"
    p_cmd = store.latest_for_turn(sid, t3)
    assert p_cmd is not None
    with pytest.raises(ProviderError) as lease_err:
        store.decide(p_cmd["approval_id"], "approve_desktop_lease", session_id=sid)
    assert lease_err.value.code == "lease_not_allowed"


def test_realtime_bailian_vision_fallback_and_app_alias(tmp_path, monkeypatch):
    # 1. Localized macOS app alias resolves /Applications/Lark.app when present.
    app_dir = tmp_path / "Applications"
    app_dir.mkdir()
    lark = app_dir / "Lark.app"
    lark.mkdir()
    monkeypatch.setattr("desktop_node.platform_macos.Path.home", lambda: tmp_path / "home")
    orig_path = MacOSDesktopAdapter._resolve_app_bundle

    def _patched_resolve(self, target):
        if target == "飞书":
            for cand in ("Lark", "Feishu"):
                p = app_dir / f"{cand}.app"
                if p.exists():
                    return str(p)
        return orig_path(self, target)

    monkeypatch.setattr(MacOSDesktopAdapter, "_resolve_app_bundle", _patched_resolve)
    launched = []

    def _fake_run(cmd, **kwargs):
        launched.append(cmd)
        if cmd == ["open", "-a", "飞书"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="Unable to find application named '飞书'")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("desktop_node.platform_macos.subprocess.run", _fake_run)
    res = MacOSDesktopAdapter().open_target("飞书", kind="app")
    assert res["ok"] is True
    assert res["opened"].endswith("Lark.app")
    assert launched[-1] == ["open", str(lark)]

    # 2. Realtime mode uses Bailian compatible-mode + qwen3-vl-plus fallback when text model is blank.
    rt_settings = Settings(
        _env_file=None,
        voice_mode="realtime",
        rt_provider="bailian",
        rt_workspace="ws-test",
        rt_api_key="rt-secret",
        model="",
    )
    hub = DesktopHub(path=tmp_path / "desktop_nodes.json", settings_getter=lambda: rt_settings)
    captured_requests = []

    class _FakeHttpClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            captured_requests.append((url, headers, json))
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": "屏幕左上角看到飞书搜索框 [500, 250, 700, 350]"}}]},
            )

    monkeypatch.setattr("backend.app.desktop.httpx.AsyncClient", _FakeHttpClient)
    vision_out = asyncio.run(hub._analyze_screenshot(
        b64=base64.b64encode(b"img").decode("ascii"),
        mime="image/jpeg",
        question="飞书搜索框在哪",
        img_w=1280,
        img_h=800,
        scr_w=1470,
        scr_h=956,
        os_name="macos",
    ))
    assert "飞书搜索框" in vision_out["vision_analysis"]
    assert vision_out["vision_coord_space"] == "norm1000"
    assert vision_out["suggested_screen_coords"][0]["screen_x"] == 882
    assert vision_out["suggested_screen_coords"][0]["screen_y"] == 287
    fake_conn = SimpleNamespace(last_screenshot={"image_width": 1280, "image_height": 800, "screen_width": 1470, "screen_height": 956}, screen={"width": 1470, "height": 956})
    assert hub.convert_coordinates(fake_conn, 600, 300, coord_space="norm1000") == (882, 287)  # type: ignore[arg-type]
    assert captured_requests[0][0] == "https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert captured_requests[0][2]["model"] == "qwen3-vl-plus"


def test_error_log_store_redaction_and_routes(tmp_path):
    db_path = tmp_path / "assistant_state.sqlite3"
    store = ErrorLogStore(path=db_path, max_rows=55)
    for idx in range(60):
        store.record("model", f"err_{idx}", f"sample error {idx}")
    listed = store.list(limit=100)
    assert listed["total"] == 55

    store.record(
        "device",
        "device_realtime_error",
        "connect failed https://host/v1?key=topsecret_val Header: Bearer abcdef123456 with my-raw-secret",
        detail={"token": "hidden_tok", "url": "wss://host/ws?token=tok_xyz"},
        secrets=("my-raw-secret",),
    )
    reopened = ErrorLogStore(path=db_path, max_rows=55)
    dev_rows = reopened.list(source="device")
    assert dev_rows["total"] == 1
    row = dev_rows["items"][0]
    assert "topsecret_val" not in row["message"]
    assert "abcdef123456" not in row["message"]
    assert "my-raw-secret" not in row["message"]
    assert row["detail"]["token"] == "[已隐藏]"
    assert "tok_xyz" not in row["detail"]["url"]

    cfg = _base_settings(tmp_path)
    app = create_app(
        cfg,
        settings_store=SettingsStore(tmp_path / ".env"),
        provider_factory=lambda c: _ScriptedLLM([]),
    )
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        app.state.error_log.record("desktop", "desktop_rpc_timeout", "mac rpc timed out")
        res = client.get("/api/insights/errors", params={"source": "desktop", "q": "timed out"})
        assert res.status_code == 200
        payload = res.json()
        assert payload["total"] == 1
        assert payload["items"][0]["code"] == "desktop_rpc_timeout"

        cleared = client.delete("/api/insights/errors", headers=HEADERS)
        assert cleared.status_code == 200
        assert cleared.json()["deleted"] >= 1
        assert client.get("/api/insights/errors").json()["total"] == 0


def test_windows_app_resolver_shortcuts_and_uwp(tmp_path, monkeypatch):
    monkeypatch.setattr("desktop_node.platform_windows.Path.home", lambda: tmp_path / "home")
    prog_data = tmp_path / "ProgramData"
    start_programs = prog_data / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    start_programs.mkdir(parents=True)
    feishu_lnk = start_programs / "Feishu.lnk"
    feishu_lnk.write_text("", encoding="utf-8")

    monkeypatch.setenv("ProgramData", str(prog_data))
    monkeypatch.delenv("AppData", raising=False)
    monkeypatch.delenv("PUBLIC", raising=False)

    adapter = WindowsDesktopAdapter.__new__(WindowsDesktopAdapter)
    assert adapter._resolve_windows_app("飞书") == ("file", str(feishu_lnk))

    # Remove shortcuts and test UWP Get-StartApps JSON fallback.
    feishu_lnk.unlink()
    monkeypatch.setattr(
        "desktop_node.platform_windows.subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"Name": "WeChat", "AppID": "Tencent.WeChat_8wekyb3d8bbwe!App"}]),
            stderr="",
        ),
    )
    assert adapter._resolve_windows_app("微信") == ("uwp", "Tencent.WeChat_8wekyb3d8bbwe!App")


def test_chat_stream_sse_progress_and_multistep_desktop_limit(tmp_path, monkeypatch):
    # 1. TextToolSelection matches "打开飞书找张三聊天" directly without saying "电脑/桌面".
    cfg = _base_settings(tmp_path)
    hub = DesktopHub(path=tmp_path / "desktop_nodes.json", port=8003)
    app = create_app(
        cfg,
        settings_store=SettingsStore(tmp_path / ".env"),
        provider_factory=lambda c: _ScriptedLLM([
            # Turn 1: initial open blocked before lease
            [Completion(reply="", usage=None, finish_reason="tool_calls", tool_calls=[{
                "id": "c-ask", "type": "function",
                "function": {"name": "desktop_open", "arguments": '{"target": "飞书"}'},
            }])],
            ["请先确认打开飞书。", Completion(reply="请先确认打开飞书。", usage=None, finish_reason="stop")],
            # Turn 2: after approve_desktop_lease -> 6 consecutive tool rounds (> old limit 4!)
            [Completion(reply="", usage=None, finish_reason="tool_calls", tool_calls=[{
                "id": "r1", "type": "function",
                "function": {"name": "desktop_open", "arguments": '{"target": "飞书"}'},
            }])],
            [Completion(reply="", usage=None, finish_reason="tool_calls", tool_calls=[{
                "id": "r2", "type": "function",
                "function": {"name": "desktop_inspect_screen", "arguments": '{"question": "飞书是否前置"}'},
            }])],
            [Completion(reply="", usage=None, finish_reason="tool_calls", tool_calls=[{
                "id": "r3", "type": "function",
                "function": {"name": "desktop_gui_action", "arguments": '{"action": "hotkey", "keys": ["command", "k"]}'},
            }])],
            [Completion(reply="", usage=None, finish_reason="tool_calls", tool_calls=[{
                "id": "r4", "type": "function",
                "function": {"name": "desktop_gui_action", "arguments": '{"action": "type_text", "text": "张三"}'},
            }])],
            [Completion(reply="", usage=None, finish_reason="tool_calls", tool_calls=[{
                "id": "r5", "type": "function",
                "function": {"name": "desktop_inspect_screen", "arguments": '{"question": "联系人位置"}'},
            }])],
            [Completion(reply="", usage=None, finish_reason="tool_calls", tool_calls=[{
                "id": "r6", "type": "function",
                "function": {"name": "desktop_gui_action", "arguments": '{"action": "click", "x": 180, "y": 140}'},
            }])],
            ["已打开飞书并切换到张三的对话框。", Completion(reply="已打开飞书并切换到张三的对话框。", usage=None, finish_reason="stop")],
        ]),
        desktop_hub=hub,
    )
    rpc_calls = []

    class _FakeNode:
        node_id = "mac-main"
        name = "My Mac"
        os_name = "macos"
        hostname = "mac"
        arch = "arm64"
        capabilities = ["screenshot", "open", "gui", "shell"]
        screen = {"width": 1470, "height": 956}
        connected_at = "2026-11-17T00:00:00+00:00"
        last_seen_at = "2026-11-17T00:00:00+00:00"
        last_screenshot = None

        class _Ws:
            async def close(self, code=1000):
                pass

        ws = _Ws()

        def close(self):
            pass

        def public(self):
            return {"node_id": self.node_id, "name": self.name, "os": self.os_name, "online": True}

        async def rpc(self, action, params=None, timeout=25.0):
            rpc_calls.append(action)
            if action == "screenshot":
                return {
                    "image_base64": base64.b64encode(b"fake").decode("ascii"),
                    "mime_type": "image/jpeg",
                    "image_width": 1280,
                    "image_height": 800,
                    "screen_width": 1470,
                    "screen_height": 956,
                    "active_window": {"app": "Lark", "title": "飞书"},
                }
            return {"ok": True}

    hub.active["mac-main"] = _FakeNode()  # type: ignore[assignment]
    monkeypatch.setattr(
        "backend.app.desktop.DesktopHub._analyze_screenshot",
        lambda self, **kw: asyncio.sleep(0, result={"vision_analysis": "搜索框在左侧"}),
    )

    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        sel = client.put("/api/assistant/selection", json={"selected_tool_ids": ["desktop_control"], "selected_kb_ids": []}, headers=HEADERS)
        assert sel.status_code == 200

        # Check TextToolSelection preloading on app-launch phrasing without saying "电脑"
        ctx = app.state.service.tool_context(app.state.service.new_session(), uuid4(), "text", "帮我打开飞书找张三聊天")
        tts = TextToolSelection(ctx)
        assert "desktop_open" in tts.active_names()
        assert "desktop_gui_action" in tts.active_names()

        res1 = client.post("/chat", json={"message": "帮我打开飞书找张三聊天"})
        assert res1.status_code == 200, res1.text
        r1 = res1.json()
        sid = r1["session_id"]
        pa_id = r1["pending_approval"]["approval_id"]
        dec = client.post(
            f"/api/approvals/{pa_id}",
            json={"decision": "approve_desktop_lease", "session_id": sid},
            headers=HEADERS,
        )
        assert dec.status_code == 200

        # Stream turn 2 over /chat/stream SSE and verify real-time tool events + 6-round completion.
        with client.stream("POST", "/chat/stream", json={"session_id": sid, "message": "确认执行"}) as stream_res:
            assert stream_res.status_code == 200
            raw_sse = "".join(stream_res.iter_text())

        events = []
        for block in raw_sse.strip().split("\n\n"):
            ev_name, ev_data = "", ""
            for line in block.splitlines():
                if line.startswith("event:"):
                    ev_name = line[6:].strip()
                elif line.startswith("data:"):
                    ev_data = line[5:].strip()
            if ev_name and ev_data:
                events.append((ev_name, json.loads(ev_data)))

        tool_events = [item for item in events if item[0] == "tool"]
        assert any(ev["phase"] == "start" and ev["tool_name"] == "desktop_open" and ev["detail"] == "飞书" for _, ev in tool_events)
        assert any(ev["phase"] == "end" and ev["tool_name"] == "desktop_gui_action" and ev["status"] == "ok" for _, ev in tool_events)
        done_payload = [ev for kind, ev in events if kind == "done"][-1]
        assert "已打开飞书" in done_payload["reply"]
        assert len(rpc_calls) == 6
        # Verify masking in progress summary for typed text
        type_ev = [ev for _, ev in tool_events if ev.get("tool_name") == "desktop_gui_action" and "输入" in ev.get("detail", "")]
        assert type_ev and "张三" not in type_ev[0]["detail"]
        assert "2 字" in type_ev[0]["detail"]


def test_desktop_node_hud_description_and_handle_request():
    assert _describe_rpc_for_hud("open", {"target": "飞书"}) == ("打开应用或链接", "飞书")
    assert _describe_rpc_for_hud("gui_action", {"action": "type_text", "text": "top-secret"}) == ("输入文字", "10 字")
    assert _describe_rpc_for_hud("gui_action", {"action": "hotkey", "keys": ["command", "k"]}) == ("触发快捷键", "command+k")

    events = []

    class _FakeHud:
        def show(self, label, detail=""):
            events.append(("show", label, detail))

        def schedule_hide(self, delay=4.5):
            events.append(("schedule_hide", delay))

    class _FakeWs:
        def __init__(self):
            self.sent = []

        async def send(self, text):
            self.sent.append(json.loads(text))

    class _FakeAdapter:
        os_name = "macos"

        def screen_size(self):
            return {"width": 1000, "height": 800}

        def capture_screenshot(self, **kw):
            return {"image_base64": "x"}

    ws = _FakeWs()
    asyncio.run(_handle_request(
        ws,
        _FakeAdapter(),  # type: ignore[arg-type]
        {"request_id": "req-hud-1", "action": "screenshot", "params": {}},
        allow_shell=True,
        allow_gui=True,
        hud=_FakeHud(),
    ))
    assert events[0] == ("show", "观察电脑屏幕", "")
    assert events[1][0] == "schedule_hide"
    assert ws.sent[0]["ok"] is True

    # Verify HUD branding uses "小圆正在操作电脑" (no legacy "小安")
    sent_payloads = []
    from desktop_node.overlay import ScreenOverlayHUD
    hud = ScreenOverlayHUD(enabled=False)

    def _capture(payload):
        sent_payloads.append(payload)

    hud._send = _capture  # type: ignore[method-assign]
    hud.show("打开应用或链接", "飞书")
    assert sent_payloads[0]["text"].startswith("小圆正在操作电脑")
    assert "小安" not in sent_payloads[0]["text"]
