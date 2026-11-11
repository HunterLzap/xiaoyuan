import json


async def handleHelloMessage(conn, msg_json):
    audio_params = msg_json.get("audio_params") or {}
    audio_format = audio_params.get("format", "opus")
    if audio_format != "opus":
        from backend.app.llm import ProviderError
        raise ProviderError(422, "device_audio_format", "设备语音需要 Opus 音频格式。")
    conn.audio_format = audio_format
    conn.features = msg_json.get("features") or {}
    conn.client_aec = bool(conn.features.get("aec"))
    await conn.websocket.send(json.dumps(conn.welcome_msg))
