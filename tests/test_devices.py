import asyncio
from contextlib import asynccontextmanager, suppress
import json
import socket

from fastapi.testclient import TestClient
import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from backend.app.config import Settings
from backend.app.devices import DeviceHub, DeviceSetup, DevicePreferences, create_gateway
from backend.app.main import create_app
from backend.app.settings_store import SettingsStore
from backend.run_devices import Server


MAC = "aa:bb:cc:dd:ee:ff"
SETUP = {"lan_host": "192.168.1.20", "device_id": MAC,
         "original_ota_url": "https://original.example/xiaozhi/ota/", "original_recorded": True}
HEADERS = {"X-Local-Settings": "1", "Origin": "http://127.0.0.1"}
TOOLS = {"self.get_device_status", "self.audio_speaker.set_volume",
         "self.screen.set_brightness", "self.screen.set_theme"}


def test_setup_validation_recovery_and_persistence(tmp_path):
    hub = DeviceHub(tmp_path / "device.json")
    asyncio.run(hub.configure(DeviceSetup(**SETUP)))
    asyncio.run(hub.save_preferences(DevicePreferences(volume=41, brightness=70, theme="light", text="测试屏幕")))
    restored = DeviceHub(hub.path)
    assert restored.setup.original_ota_url == SETUP["original_ota_url"]
    assert restored.preferences.volume == 41 and restored.token == hub.token
    assert "firmware" not in restored.public()
    assert DeviceSetup(**(SETUP | {"original_ota_url": ""})).original_ota_url == ""
    for change in ({"original_recorded": False}, {"lan_host": "127.0.0.1"}, {"device_id": "unknown"},
                   {"original_ota_url": "javascript:alert(1)"}):
        with pytest.raises(ValueError):
            DeviceSetup(**(SETUP | change))
    with pytest.raises(ValueError):
        DevicePreferences(brightness=0)


def test_admin_stays_local_and_gateway_exposes_no_management(tmp_path):
    hub = DeviceHub(tmp_path / "device.json")
    app = create_app(Settings(_env_file=None, api_key="", model="", history_db_path=None,
                              usage_log_path=None, m5stack_enabled=False), device_hub=hub)
    with TestClient(app, base_url="http://127.0.0.1", client=("192.168.1.50", 5000)) as client:
        assert client.get("/devices").status_code == 403
        assert client.get("/api/devices").status_code == 403
        assert client.put("/api/devices/setup", headers=HEADERS, json=SETUP).status_code == 403
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5000)) as client:
        assert client.put("/api/devices/setup", json=SETUP).status_code == 403
        assert client.put("/api/devices/setup", headers=HEADERS, json=SETUP).status_code == 200
        assert client.post("/api/devices/apply", headers=HEADERS).status_code == 409
        assert client.get("/devices").status_code == 200
    with TestClient(create_gateway(hub)) as client:
        for path in ("/settings", "/api/settings", "/sessions", "/api/devices", "/docs"):
            assert client.get(path).status_code == 404
        assert client.post("/xiaozhi/ota/", headers={"Device-Id": MAC}).status_code == 403
        response = client.post("/xiaozhi/ota/", params={"key": hub.token}, headers={"Device-Id": MAC})
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"websocket", "server_time", "firmware"}
        assert data["websocket"]["version"] == 1 and data["websocket"]["token"] == hub.token
        assert data["websocket"]["url"] == "ws://192.168.1.20:8003/xiaozhi/v1/"
        # XiaoZhi firmware needs a firmware block to accept the reply, but this bridge
        # must never advertise an upgrade: empty url and the reported version.
        assert data["firmware"] == {"version": "1.0.0", "url": ""}
        sent = client.post("/xiaozhi/ota/", params={"key": hub.token}, headers={"Device-Id": MAC},
                           json={"application": {"version": "1.6.1"}})
        assert sent.json()["firmware"] == {"version": "1.6.1", "url": ""}
        assert client.post("/xiaozhi/ota/", params={"key": hub.token}, headers={"Device-Id": "00:00:00:00:00:00"}).status_code == 403


def test_first_bootstrap_pairs_only_with_secret_and_retains_identity(tmp_path):
    hub = DeviceHub(tmp_path / "device.json")
    asyncio.run(hub.configure(DeviceSetup(**(SETUP | {"device_id": ""}))))
    with TestClient(create_gateway(hub)) as client:
        assert client.post("/xiaozhi/ota/", headers={"Device-Id": MAC}).status_code == 403
        assert hub.setup.device_id == ""
        assert client.post("/xiaozhi/ota/", params={"key": hub.token}, headers={"Device-Id": MAC}).status_code == 200
        assert DeviceHub(hub.path).setup.device_id == MAC
        assert client.post("/xiaozhi/ota/", params={"key": hub.token}, headers={"Device-Id": "00:00:00:00:00:00"}).status_code == 403


@asynccontextmanager
async def network_bridge(tmp_path):
    hub = DeviceHub(tmp_path / "device.json")
    await hub.configure(DeviceSetup(**SETUP))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    hub.port = sock.getsockname()[1]
    server = Server(uvicorn.Config(create_gateway(hub), host="127.0.0.1", log_level="error", access_log=False,
                                   ws_max_size=12000, lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        hub.gateway_running = True
        yield hub, f"ws://127.0.0.1:{hub.port}/xiaozhi/v1/"
    finally:
        await hub.disconnect()
        server.should_exit = True
        await task
        sock.close()


async def emulate(ws, screen, calls, *, tools=TOOLS, reject=None, readback_wrong=False):
    current = {"audio_speaker": {"volume": 20}, "screen": {"brightness": 50, "theme": "dark"}}
    await ws.send(json.dumps({"type": "hello", "transport": "websocket", "version": 1, "features": {"mcp": True}}))
    first = json.loads(await ws.recv())
    assert first["type"] == "hello" and first["audio_params"]["format"] == "opus"
    async for raw in ws:
        message = json.loads(raw)
        if message["type"] == "tts":
            screen.append(message["text"])
            continue
        rpc = message["payload"]
        if rpc["method"] == "initialize":
            result = {"serverInfo": {"name": "fixture-atoms3r", "version": "2.2.6"}}
        elif rpc["method"] == "tools/list":
            result = {"tools": [{"name": name} for name in sorted(tools)]}
        else:
            params = rpc["params"]
            name, arguments = params["name"], params["arguments"]
            calls.append((name, arguments))
            if name == reject:
                result = {"isError": True, "content": [{"type": "text", "text": "test failure"}]}
            else:
                if name.endswith("set_volume") and not readback_wrong:
                    current["audio_speaker"]["volume"] = arguments["volume"]
                elif name.endswith("set_brightness"):
                    current["screen"]["brightness"] = arguments["brightness"]
                elif name.endswith("set_theme"):
                    current["screen"]["theme"] = arguments["theme"]
                value = current if name == "self.get_device_status" else True
                result = {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
        await ws.send(json.dumps({"type": "mcp", "payload": {"jsonrpc": "2.0", "id": rpc["id"], "result": result}}))


async def wait_ready(hub):
    async with asyncio.timeout(5):
        while hub.connection is None or not hub.connection.ready:
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("readback_wrong,missing_theme", [(False, False), (True, False), (False, True)])
def test_real_socket_settings_and_readback(tmp_path, readback_wrong, missing_theme):
    async def scenario():
        async with network_bridge(tmp_path) as (hub, url):
            headers = {"Authorization": f"Bearer {hub.token}", "Device-Id": MAC, "Protocol-Version": "1"}
            async with connect(url, additional_headers=headers) as ws:
                screen, calls = [], []
                task = asyncio.create_task(emulate(ws, screen, calls,
                    tools=TOOLS - {"self.screen.set_theme"} if missing_theme else TOOLS,
                    readback_wrong=readback_wrong))
                try:
                    await wait_ready(hub)
                    with pytest.raises(Exception, match="请先断开"):
                        await hub.configure(DeviceSetup(**SETUP))
                    await hub.save_preferences(DevicePreferences(volume=37, brightness=72, theme="light", text="本机连接验证"))
                    assert calls == []  # Saving must not silently apply changes.
                    app = create_app(Settings(_env_file=None, api_key="", model="", history_db_path=None,
                                              usage_log_path=None, m5stack_enabled=False), device_hub=hub)
                    async with app.router.lifespan_context(app):
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as admin:
                            response = await admin.post("/api/devices/apply", headers=HEADERS)
                            assert response.status_code == 200
                            result = response.json()["last_application"]["results"]
                            assert result["brightness"]["state"] == "verified"
                            assert result["volume"]["state"] == ("mismatch" if readback_wrong else "verified")
                            assert result["theme"]["state"] == ("unsupported" if missing_theme else "verified")
                            assert result["text"]["state"] == "sent"
                            async with asyncio.timeout(2):
                                while not screen:
                                    await asyncio.sleep(0.01)
                            assert screen == ["本机连接验证"]
                            assert calls[0][0] == calls[-1][0] == "self.get_device_status"
                            assert all(name in TOOLS for name, _ in calls)
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
    asyncio.run(scenario())


def test_real_socket_rejects_auth_and_command_failures(tmp_path):
    async def scenario():
        async with network_bridge(tmp_path) as (hub, url):
            with pytest.raises(InvalidStatus):
                async with connect(url, additional_headers={"Device-Id": MAC, "Authorization": "Bearer wrong"}):
                    pass
            headers = {"Device-Id": MAC, "Authorization": f"Bearer {hub.token}"}
            with pytest.raises(InvalidStatus):
                async with connect(url, additional_headers=headers, origin="http://untrusted.example"):
                    pass
            async with connect(url, additional_headers=headers) as ws:
                task = asyncio.create_task(emulate(ws, [], [], reject="self.audio_speaker.set_volume"))
                try:
                    await wait_ready(hub)
                    with pytest.raises(Exception, match="设备报告指令执行失败"):
                        await hub.apply()
                    assert hub.last_application["state"] == "failed"
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
    asyncio.run(scenario())
