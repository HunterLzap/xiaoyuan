"""Run loopback-only management and a separate LAN device gateway in one process."""
import argparse
import asyncio
from contextlib import contextmanager
import logging
import os

import uvicorn

from .app.devices import DeviceHub, create_gateway
from .app.main import create_app
from .app.config import Settings
from .app.speech_bridge import SpeechRecognizer, SPEECH_PYTHON


def sanitize_proxy_environment() -> None:
    """Drop NO_PROXY values that break httpx.

    A NO_PROXY entry such as "[::1]" makes httpx raise InvalidURL("Invalid port: ':1]'"),
    which aborts startup because the model client is built in the app lifespan. Loopback
    and LAN service calls do not need a proxy, so the variable is safest kept minimal.
    """
    for name in ("no_proxy", "NO_PROXY"):
        value = os.environ.get(name)
        if not value:
            continue
        if "[" in value or "]" in value:
            os.environ[name] = "localhost,127.0.0.1,::1"


sanitize_proxy_environment()


class Server(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # asyncio.run handles Ctrl+C and cancels both servers together.
        yield


async def run(admin_port, device_port, require_public=False):
    # uvicorn configures only its own loggers; without a root handler the device
    # diagnostics are swallowed by logging's WARNING-only lastResort handler.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
    logging.getLogger("backend.app.devices").setLevel(logging.INFO)
    config = Settings()
    if require_public and not config.public_origin:
        raise ValueError("Public deployment requires AI_PUBLIC_ORIGIN and AI_ADMIN_PROXY_TOKEN")
    hub = DeviceHub(port=device_port, public_origin=config.public_origin,
                    public_base_path=config.public_base_path, speech=SpeechRecognizer(
        python=config.speech_python or SPEECH_PYTHON,
        threads=config.speech_threads, model_dir=config.asr_model_dir,
    ))
    admin = Server(uvicorn.Config(create_app(settings=config, device_hub=hub), host="127.0.0.1",
                                 port=admin_port, log_level="info", proxy_headers=False))
    device_host = "127.0.0.1" if config.public_origin else "0.0.0.0"
    device = Server(uvicorn.Config(create_gateway(hub), host=device_host, port=device_port,
                                   log_level="info", access_log=False, proxy_headers=False, ws_max_size=12000,
                                   ws_ping_interval=20, ws_ping_timeout=20))
    tasks = [asyncio.create_task(admin.serve()), asyncio.create_task(device.serve())]
    try:
        while not device.started:
            if any(task.done() for task in tasks):
                await asyncio.gather(*[task for task in tasks if task.done()])
                return
            await asyncio.sleep(0.05)
        hub.gateway_running = True
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        hub.gateway_running = False
        await hub.disconnect()
        await hub.speech.close()
        admin.should_exit = True
        device.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-port", type=int, default=os.environ.get("AI_ADMIN_PORT", "8000"))
    parser.add_argument("--device-port", type=int, default=os.environ.get("AI_DEVICE_PORT", "8003"))
    parser.add_argument("--public", action="store_true")
    arguments = parser.parse_args()
    if not (1 <= arguments.admin_port <= 65535 and 1 <= arguments.device_port <= 65535):
        parser.error("Management and device ports must be between 1 and 65535")
    if arguments.admin_port == arguments.device_port:
        parser.error("Management and device ports must differ")
    try:
        asyncio.run(run(arguments.admin_port, arguments.device_port, arguments.public))
    except KeyboardInterrupt:
        pass
