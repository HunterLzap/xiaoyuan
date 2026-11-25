"""Event-handler regressions; no provider calls, audio hardware or server startup."""
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from pydantic import SecretStr

from websockets.exceptions import ConnectionClosedOK

from backend.app import ack_cache
from backend.app.config import Settings
from backend.app.device_realtime import DeviceRealtime
from backend.app.history_store import HistoryStore
from backend.app.llm import ProviderError
from backend.app.order_confirmation import RealtimeOrderGuard
from backend.app.realtime import RealtimeTurn
from backend.app.service import ChatService
from backend.app.silence_gate import SilenceGate
from backend.app.tools import PERSONAL_KB_SPEC, WEATHER_SPEC, ToolRegistry, ToolSpec


class RealtimeFailures(unittest.IsolatedAsyncioTestCase):
    def make_turn(self):
        turn = RealtimeTurn.__new__(RealtimeTurn)
        turn.turn_id = uuid4()
        turn.turns_in_ws = 0
        turn.continuous = False
        turn.manual = False
        turn.source = "device_voice"
        turn._defer_response = False
        turn.ws = SimpleNamespace(
            recv=AsyncMock(side_effect=[json.dumps({
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "今天几号",
            }), asyncio.CancelledError()]),
            close=AsyncMock(),
        )
        turn.session = SimpleNamespace(history=[], messages=[], active_task=None)
        turn.tool_context = SimpleNamespace(question="", allowed=set(), begin_order_turn=Mock())
        turn.order_guard = RealtimeOrderGuard()
        turn.audio = SimpleNamespace(close=AsyncMock())
        turn.emit = AsyncMock()
        turn.refresh_tools = AsyncMock()
        turn.release_output = AsyncMock()
        turn.persist = AsyncMock()
        turn.tool_task = None
        turn.pending_audio = []
        turn.ignore_responses = set()
        turn.previous_item = None
        turn.active_response = None
        turn.response_done = False
        turn.transcription_done = False
        turn.transcription_ready = asyncio.Event()
        turn.saved = False
        turn.input_closed = False
        turn.control_continuation = False
        turn.control_notice = ""
        return turn

    async def test_transcription_reaches_user_event(self):
        turn = self.make_turn()
        with self.assertLogs("backend.app.realtime", level="INFO"):
            with self.assertRaises(asyncio.CancelledError):
                await turn.receive()
        turn.emit.assert_any_await("user", "今天几号")
        turn.release_output.assert_awaited_once()
        self.assertTrue(turn.input_closed)

    async def test_local_transcription_exception_is_logged_and_reported(self):
        turn = self.make_turn()
        turn.tool_context.begin_order_turn.side_effect = AttributeError("transcription handler failed")
        with self.assertLogs("backend.app.realtime", level="ERROR") as logs:
            await turn.receive()
        text = "\n".join(logs.output)
        self.assertIn("event=conversation.item.input_audio_transcription.completed", text)
        self.assertIn("AttributeError: transcription handler failed", text)
        self.assertIn("Traceback", text)
        kind, message = turn.emit.await_args.args
        self.assertEqual(kind, "error")
        self.assertIn("服务端实时语音处理失败", message)
        self.assertNotIn("额度", message)
        self.assertTrue(turn.input_closed)
        turn.ws.close.assert_awaited_once()

    async def test_cleanup_blocks_audio_before_closing_provider(self):
        turn = self.make_turn()
        turn.ws.recv.side_effect = ConnectionClosedOK(None, None)

        async def close():
            self.assertTrue(turn.input_closed)
            await turn.append(b"late audio")

        turn.ws.close.side_effect = close
        turn.ws.send = AsyncMock()
        with self.assertLogs("backend.app.realtime", level="ERROR"):
            await turn.receive()
        turn.ws.send.assert_not_awaited()
        self.assertIn("百炼实时连接中断", turn.emit.await_args.args[1])

    async def test_empty_transcription_finishes_answer_after_transcription_event(self):
        turn = self.make_turn()
        turn.sid = uuid4()
        turn.reply = "在呢，喊我有什么事？"
        turn.response_done = True
        turn.required_controls = set()
        turn.control_failure = None
        turn.config = SimpleNamespace(rt_model="qwen3.8-omni-flash-realtime")
        turn.provider = "百炼"
        turn.usage = None
        turn.session.history_persisted = False
        turn.tool_context.control_error = Mock(return_value=None)
        turn.tool_context.sources = Mock(return_value=[])
        turn.tool_context.summaries = Mock(return_value=[])
        turn.audio.finish = AsyncMock()
        turn.continuous = True
        turn.ws.recv.side_effect = [
            json.dumps({"type": "input_audio_buffer.speech_stopped"}),
            json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": ""}),
            asyncio.CancelledError(),
        ]

        async def persist(*args, **kwargs):
            turn.saved = True

        turn.persist.side_effect = persist
        with self.assertLogs("backend.app.realtime", level="INFO"):
            with self.assertRaises(asyncio.CancelledError):
                await turn.receive()
        turn.audio.finish.assert_awaited_once()
        turn.persist.assert_awaited_once_with("complete", audio_status="streamed")
        kinds = [call.args[0] for call in turn.emit.await_args_list]
        self.assertEqual(kinds, ["thinking", "user", "done"])
        self.assertTrue(turn.saved)

    async def test_provider_error_retains_details_without_credentials(self):
        turn = self.make_turn()
        turn.sid = uuid4()
        credential = "provider-credential-for-redaction-check"
        turn.config = SimpleNamespace(
            rt_api_key=SecretStr(credential), api_key=SecretStr(""), tts_api_key=SecretStr(""),
        )
        turn.ws.recv.side_effect = [json.dumps({
            "type": "error", "event_id": "event-volume-failure", "request_id": "request-volume-failure",
            "error": {"type": "invalid_request_error", "code": "invalid_value", "param": "session.tools",
                      "message": f"Invalid tools; credential={credential}", "Authorization": f"Bearer {credential}"},
        })]
        with self.assertLogs("backend.app.realtime", level="ERROR") as logs:
            await turn.receive()
        text = "\n".join(logs.output)
        self.assertIn("invalid_value", text)
        self.assertIn("session.tools", text)
        self.assertIn("request-volume-failure", text)
        self.assertIn("event-volume-failure", text)
        self.assertIn("Traceback", text)
        self.assertNotIn(credential, text)
        self.assertNotIn("Bearer ", text)
        turn.ws.close.assert_awaited_once()

    def make_bridge(self):
        bridge = DeviceRealtime.__new__(DeviceRealtime)
        bridge.conn = SimpleNamespace(frames_dropped=0, send=AsyncMock(), ws=SimpleNamespace(close=AsyncMock()))
        bridge._closed = False
        bridge._rotate_pending = bridge._rotating = bridge._idle_reconnect_used = False
        bridge.silence_gate = SilenceGate(enabled=False)
        bridge.turn = SimpleNamespace(
            continuous=False, saved=False,
            ws=object(), reader=SimpleNamespace(done=lambda: False),
            turn_id=uuid4(), input_closed=False,
            append=AsyncMock(side_effect=ConnectionClosedOK(None, None)),
            finish=AsyncMock(side_effect=ConnectionClosedOK(None, None)), close=AsyncMock(),
        )
        bridge.codec = SimpleNamespace(decode=lambda packet: bytes(32))
        bridge._rx_diag_frames = 0
        bridge._rx_diag_max_rms = 0.0
        bridge._rx_diag_last_log = monotonic()
        bridge.metrics_turn_id = str(bridge.turn.turn_id)
        bridge.uplink_frames = 0
        bridge.uplink_stalls = 0
        bridge.max_uplink_send_ms = 0
        bridge.input_queue = asyncio.Queue(maxsize=40)
        bridge.input_task = None
        bridge.uplink_queue_dropped = 0
        bridge.max_uplink_queue_ms = 0
        bridge._archive_metrics = AsyncMock()
        bridge.hub = SimpleNamespace(last_error=None)
        bridge.playback_metrics = SimpleNamespace(mark=Mock())
        bridge._last_text = None
        bridge.stop_audio = AsyncMock()
        bridge.show_text = AsyncMock()
        return bridge

    async def test_device_input_queues_during_provider_open_and_finishes_in_order(self):
        bridge = self.make_bridge()
        opening = asyncio.Event()

        async def open_provider():
            await opening.wait()

        bridge.turn.open = open_provider
        bridge.turn.append = AsyncMock()
        bridge.turn.finish = AsyncMock()
        bridge.codec.decode = lambda packet: packet
        first_packet, second_packet = bytes([1, 0]), bytes([2, 0])
        bridge.start()
        try:
            bridge.queue_audio(first_packet)
            bridge.queue_audio(second_packet)
            bridge.queue_audio(None)
            await asyncio.sleep(0)
            self.assertEqual(bridge.input_queue.qsize(), 3)
            bridge.turn.append.assert_not_awaited()
            opening.set()
            await asyncio.wait_for(bridge.input_task, 1)
            self.assertEqual([call.args[0] for call in bridge.turn.append.await_args_list],
                             [first_packet, second_packet])
            bridge.turn.finish.assert_awaited_once()
            self.assertEqual(bridge.conn.frames_dropped, 0)
        finally:
            bridge.input_task.cancel()
            await asyncio.gather(bridge.input_task, return_exceptions=True)

    async def test_provider_append_close_does_not_close_device(self):
        bridge = self.make_bridge()
        with self.assertLogs("backend.app.device_realtime", level="ERROR"):
            await bridge.append(b"packet")
        bridge.turn.close.assert_awaited_once()
        bridge.conn.ws.close.assert_not_awaited()
        self.assertTrue(bridge.turn.input_closed)
        bridge.stop_audio.assert_awaited_once_with(interrupt=True)
        bridge.show_text.assert_awaited_once_with(bridge.hub.last_error)

    async def test_end_intent_cancels_active_response_and_sends_device_to_sleep(self):
        turn = self.make_turn()
        bridge = self.make_bridge()
        bridge.turn = turn
        bridge.conn.listening = True
        bridge.conn.voice_session_id = uuid4()
        bridge.hub.now = monotonic
        bridge.answer_first_audio_at = None
        turn.emit.side_effect = bridge.emit
        turn.active_response = "resp_1"
        turn.pending_tools = {}
        turn.reply = "好的"
        turn.ws.send = AsyncMock()
        turn.ws.recv = AsyncMock(side_effect=[json.dumps({
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "塔菲，退下吧。",
        })])
        await turn.receive()
        self.assertIn("resp_1", turn.ignore_responses)
        sent_types = [json.loads(call.args[0])["type"] for call in turn.ws.send.await_args_list]
        self.assertIn("response.cancel", sent_types)
        self.assertIn("session.update", sent_types)
        turn.emit.assert_any_await("idle", {"reason": "end_intent"})
        self.assertTrue(turn.saved)
        self.assertFalse(bridge.conn.listening)
        self.assertIsNone(bridge.conn.voice_session_id)
        self.assertTrue(bridge.conn.close_after_chat)
        bridge.stop_audio.assert_awaited_once_with(interrupt=True)
        self.assertEqual([item.args[0] for item in bridge.conn.send.await_args_list][-2:], [
            {"type": "ui", "state": "sleep"},
            {"type": "tts", "state": "stop"},
        ])
        bridge.conn.ws.close.assert_awaited_once()

    async def test_voice_abort_task_intent_stops_desktop_and_cross_session_tasks(self):
        from backend.app.realtime import _is_abort_task_intent

        for phrase in ("停止", "别动了", "塔菲，停止操作吧！", "stop", "别操作了", "住手"):
            self.assertTrue(_is_abort_task_intent(phrase), phrase)
        for safe_phrase in ("怎么停止服务", "帮我取消明天的日程", "停止说话是什么意思"):
            self.assertFalse(_is_abort_task_intent(safe_phrase), safe_phrase)

        turn = self.make_turn()
        turn.continuous = True
        turn.active_response = "resp_abort"
        turn.pending_tools = {"c1": {"name": "desktop_gui_action"}}
        turn.ws.send = AsyncMock()
        turn.tool_task = asyncio.create_task(asyncio.sleep(10))
        web_desktop_task = asyncio.create_task(asyncio.sleep(10))
        confirmations = SimpleNamespace(revoke_all_desktop_leases=Mock())
        desktop = SimpleNamespace(abort_all=AsyncMock(return_value=1))
        turn.service = SimpleNamespace(
            sessions={"web-1": SimpleNamespace(active_task=web_desktop_task)},
            tool_gateway=SimpleNamespace(confirmations=confirmations),
            desktop=desktop,
        )
        turn.ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "别动了，停止操作"}),
            asyncio.CancelledError(),
        ])
        with self.assertRaises(asyncio.CancelledError):
            await turn.receive()
        self.assertTrue(web_desktop_task.cancelled() or web_desktop_task.done())
        self.assertIsNone(turn.tool_task)
        confirmations.revoke_all_desktop_leases.assert_called_once()
        desktop.abort_all.assert_awaited_once()
        turn.emit.assert_any_await("notice", "好的，已停止操作")
        for call in turn.emit.await_args_list:
            self.assertNotEqual(call.args[0], "idle")

        # "关闭" triggers both _abort_running_tasks and idle sleep
        turn2 = self.make_turn()
        turn2.continuous = False
        turn2.pending_tools = {}
        turn2.ws.send = AsyncMock()
        desktop2 = SimpleNamespace(abort_all=AsyncMock(return_value=1))
        turn2.service = SimpleNamespace(sessions={}, tool_gateway=None, desktop=desktop2)
        turn2.ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "关闭"}),
        ])
        await turn2.receive()
        desktop2.abort_all.assert_awaited_once()
        turn2.emit.assert_any_await("idle", {"reason": "end_intent"})

    async def test_provider_finish_close_does_not_close_device(self):
        bridge = self.make_bridge()
        with self.assertLogs("backend.app.device_realtime", level="ERROR"):
            await bridge.finish()
        bridge.turn.close.assert_awaited_once()
        bridge.conn.ws.close.assert_not_awaited()
        bridge.stop_audio.assert_awaited_once_with(interrupt=True)
        bridge.show_text.assert_awaited_once_with(bridge.hub.last_error)


class _RealtimeSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.sent = []
        self.close = AsyncMock()
        self.feed("session.created")
        self.feed("session.updated")

    def feed(self, kind, **fields):
        self.incoming.put_nowait(json.dumps({"type": kind, **fields}))

    async def recv(self):
        event = await self.incoming.get()
        if isinstance(event, Exception):
            raise event
        return event

    async def send(self, raw):
        event = json.loads(raw)
        self.sent.append(event)
        self.outgoing.put_nowait(event)

    async def wait_for_send(self, kind):
        async with asyncio.timeout(1):
            while True:
                event = await self.outgoing.get()
                if event["type"] == kind:
                    return event

    def finish_turn(self, item_id, reply):
        self.feed("input_audio_buffer.speech_started", item_id=item_id)
        self.feed("conversation.item.input_audio_transcription.completed", item_id=item_id, transcript=f"问题 {item_id}")
        self.feed("response.text.delta", delta=reply)
        self.feed("response.done", response={"id": f"reply-{item_id}", "status": "completed"})


class RealtimeBatch2(unittest.IsolatedAsyncioTestCase):
    def make_service(self, history=None, **settings):
        cfg = Settings(_env_file=None, rt_api_key="test-key", usage_log_path=None, **settings)
        return ChatService(cfg, None, history_store=history)

    def make_bridge(self, service, manual=False):
        conn = SimpleNamespace(
            voice_session_id=None, client_aec=True, frames_dropped=0,
            send=AsyncMock(), ws=SimpleNamespace(close=AsyncMock()),
        )
        hub = SimpleNamespace(voice=SimpleNamespace(service=service), now=monotonic, last_realtime_latency=None)
        codec = SimpleNamespace(decode=lambda packet: packet, encode=Mock(return_value=[]), pending=[], close=Mock())
        with patch("backend.app.device_realtime.DeviceCodec", return_value=codec):
            bridge = DeviceRealtime(hub, conn, manual)
        bridge._write_metrics = Mock()
        return bridge

    def make_tool_turn(self, **settings):
        service = self.make_service(**settings)
        names = {"get_weather", "search_m5stack", "search_personal_knowledge", "get_device_status",
                 "search_conversation_history", "desktop_list_nodes"}
        service.tools = ToolRegistry([
            SimpleNamespace(spec=spec) for spec in (WEATHER_SPEC, PERSONAL_KB_SPEC)
        ] + [
            SimpleNamespace(spec=ToolSpec(name, name, {"type": "object", "properties": {}}))
            for name in sorted(names - {WEATHER_SPEC.name, PERSONAL_KB_SPEC.name})
        ])
        turn = RealtimeTurn(service, None, "web_voice", AsyncMock(), False)
        return turn, names

    def test_silence_gate_preroll_hangover_reset_and_bypass(self):
        gate = SilenceGate(hangover_frames=2, preroll_frames=2)
        for packet in (b"noise 1", b"noise 2", b"noise 3"):
            self.assertEqual(gate.process(packet, 20), [])
        self.assertEqual(gate.process(b"voice", 120), [b"noise 2", b"noise 3", b"voice"])
        self.assertEqual(gate.process(b"tail 1", 20), [b"tail 1"])
        self.assertEqual(gate.process(b"tail 2", 20), [b"tail 2"])
        self.assertEqual(gate.process(b"noise 4", 20), [])
        gate.reset()
        self.assertEqual(gate.process(b"new voice", 130), [b"new voice"])
        self.assertEqual((gate.dropped_frames, gate.passed_frames), (4, 6))
        bypass = SilenceGate(enabled=False)
        self.assertEqual(bypass.process(b"quiet", 0), [b"quiet"])
        self.assertEqual((bypass.dropped_frames, bypass.passed_frames), (0, 1))

    async def test_device_silence_gate_counts_drops_and_manual_is_passthrough(self):
        service = self.make_service()
        packet = bytes(32)
        for manual in (False, True):
            with self.subTest(manual=manual):
                bridge = self.make_bridge(service, manual=manual)
                bridge.turn.ws = object()
                bridge.turn.reader = SimpleNamespace(done=lambda: False)
                bridge.turn.append = AsyncMock()
                await bridge.append(packet)
                metrics = bridge.publish_metrics(force=True)
                self.assertEqual(metrics["uplink_silence_dropped"], int(not manual))
                self.assertEqual(metrics["uplink_silence_passed"], int(manual))
                if manual:
                    bridge.turn.append.assert_awaited_once_with(packet)
                else:
                    bridge.turn.append.assert_not_awaited()

    async def test_continuous_rotation_persists_then_drains_and_recovers_idle_socket(self):
        with TemporaryDirectory() as directory:
            history = HistoryStore(Path(directory) / "history.sqlite3")
            service = self.make_service(history, rt_max_continuous_turns=2, rt_max_continuous_seconds=0)
            bridge = self.make_bridge(service)
            old_turn = bridge.turn
            old_socket, rotated_socket, recovered_socket = (_RealtimeSocket() for _ in range(3))
            initial_ready, rotate_requested, release_playback = (asyncio.Event() for _ in range(3))
            completed = []
            emit = bridge.emit

            async def observe_old_events(kind, data):
                if kind == "done":
                    completed.append(data)
                    if len(completed) == 2:
                        bridge.speaking = True
                        bridge.controller.wait_finished = AsyncMock(side_effect=release_playback.wait)
                await emit(kind, data)
                if kind == "ready":
                    initial_ready.set()
                elif kind == "rotate_session":
                    self.assertEqual(data["turns"], 2)
                    rotate_requested.set()

            old_turn.emit = observe_old_events
            connect = AsyncMock(side_effect=[old_socket, rotated_socket, recovered_socket])
            disconnect = ConnectionClosedOK(None, None)
            with patch("backend.app.realtime.DirectConnect", connect):
                bridge.start()
                try:
                    await asyncio.wait_for(initial_ready.wait(), 1)
                    old_socket.finish_turn("one", "第一轮")
                    old_socket.finish_turn("two", "第二轮")
                    await asyncio.wait_for(rotate_requested.wait(), 1)
                    await asyncio.wait_for(old_turn.reader, 1)
                    self.assertEqual(connect.await_count, 1)
                    snapshot = history.get(old_turn.sid)
                    self.assertEqual([msg.content for msg in snapshot.messages],
                                     ["问题 one", "第一轮", "问题 two", "第二轮"])
                    self.assertTrue(snapshot.history_persisted)
                    bridge.conn.send.assert_any_await({"type": "ui", "state": "listening"})
                    self.assertNotIn({"type": "tts", "state": "stop"}, [c.args[0] for c in bridge.conn.send.await_args_list])
                    bridge.queue_audio(b"\x40\x01" * 16)
                    await asyncio.sleep(0.03)
                    self.assertFalse(bridge.input_task.done())
                    release_playback.set()
                    await asyncio.wait_for(bridge.drain, 1)
                    self.assertIsNot(bridge.turn, old_turn)
                    self.assertEqual([c.args[0] for c in bridge.conn.send.await_args_list].count(
                        {"type": "tts", "state": "stop"}), 1)
                    self.assertEqual(bridge.turn.sid, old_turn.sid)
                    self.assertTrue(bridge.turn.saved)
                    self.assertEqual(bridge.metrics_turn_id, str(bridge.turn.turn_id))
                    self.assertEqual([x["item"]["content"][0]["text"] for x in rotated_socket.sent
                                      if x["type"] == "conversation.item.create"],
                                     ["问题 one", "第一轮", "问题 two", "第二轮"])
                    self.assertFalse(bridge.input_task.done())
                    bridge.queue_audio(b"\x40\x01" * 16)
                    await rotated_socket.wait_for_send("input_audio_buffer.append")
                    rotated_socket.finish_turn("three", "第三轮")
                    rotated_socket.incoming.put_nowait(disconnect)
                    await asyncio.wait_for(bridge.turn.reader, 1)
                    await asyncio.wait_for(bridge._rotate_task, 1)
                    self.assertEqual(connect.await_count, 3)
                    self.assertTrue(bridge._idle_reconnect_used)
                    self.assertEqual(bridge.turn.sid, old_turn.sid)
                    self.assertTrue(bridge.turn.saved)
                    self.assertTrue(all(call.args == connect.await_args_list[0].args
                                        and call.kwargs == connect.await_args_list[0].kwargs
                                        for call in connect.await_args_list))
                    bridge.conn.ws.close.assert_not_awaited()
                    self.assertNotIn({"type": "ui", "state": "sleep"}, [c.args[0] for c in bridge.conn.send.await_args_list])
                finally:
                    await bridge.close()

    async def test_deferred_voice_tools_wait_for_the_matching_turn_update(self):
        turn, _ = self.make_tool_turn(rt_defer_response_until_transcript=True)
        turn.continuous = True
        ws = _RealtimeSocket()
        with patch("backend.app.realtime.DirectConnect", AsyncMock(return_value=ws)):
            await turn.open()
        try:
            initial = (await ws.wait_for_send("session.update"))["session"]
            self.assertEqual(initial["turn_detection"],
                             {"type": "server_vad", "create_response": False, "interrupt_response": True})
            self.assertEqual(initial["tools"], [])
            ws.feed("input_audio_buffer.speech_started", item_id="first")
            ws.feed("conversation.item.input_audio_transcription.completed", item_id="first", transcript="明天天气")
            update = (await ws.wait_for_send("session.update"))["session"]
            self.assertEqual({tool["function"]["name"] for tool in update["tools"]},
                             {"get_weather", "_load_task_tools"})
            self.assertIn("未加载不等于没有能力", update["instructions"])
            self.assertNotIn("response.create", [msg["type"] for msg in ws.sent])
            ws.feed("session.updated")
            await ws.wait_for_send("response.create")

            for item_id in ("old", "new"):
                ws.feed("input_audio_buffer.speech_started", item_id=item_id)
                ws.feed("conversation.item.input_audio_transcription.completed", item_id=item_id, transcript="查引脚")
                await ws.wait_for_send("session.update")
            ws.feed("session.updated")
            handled_old_ack = asyncio.Event()

            async def mark_thinking(kind, _):
                if kind == "thinking":
                    handled_old_ack.set()

            turn.emit.side_effect = mark_thinking
            ws.feed("input_audio_buffer.speech_stopped")
            await asyncio.wait_for(handled_old_ack.wait(), 1)
            self.assertEqual(sum(msg["type"] == "response.create" for msg in ws.sent), 1)
            ws.feed("session.updated")
            await ws.wait_for_send("response.create")
            self.assertEqual(sum(msg["type"] == "response.create" for msg in ws.sent), 2)
        finally:
            await turn.close()

    async def test_default_vad_still_sends_all_tools_in_handshake(self):
        turn, names = self.make_tool_turn()
        ws = _RealtimeSocket()
        with patch("backend.app.realtime.DirectConnect", AsyncMock(return_value=ws)):
            await turn.open()
        try:
            initial = (await ws.wait_for_send("session.update"))["session"]
            self.assertEqual(initial["turn_detection"], {"type": "server_vad"})
            self.assertEqual({tool["function"]["name"] for tool in initial["tools"]}, names)
        finally:
            await turn.close()

    async def test_handshake_retries_once_and_exposes_final_provider_error(self):
        service = self.make_service()
        first = _RealtimeSocket()
        first.incoming = asyncio.Queue()
        first.feed("session.created")
        first.incoming.put_nowait(OSError("handshake interrupted"))
        good = _RealtimeSocket()
        connect = AsyncMock(side_effect=[first, good])
        turn = RealtimeTurn(service, None, "device_voice", AsyncMock(), False)
        with patch("backend.app.realtime.DirectConnect", connect):
            await turn.open()
        try:
            self.assertEqual(connect.await_count, 2)
            self.assertIs(turn.ws, good)
            first.close.assert_awaited_once()
        finally:
            await turn.close()

        turn = RealtimeTurn(service, None, "device_voice", AsyncMock(), False)
        connect = AsyncMock(side_effect=OSError("unreachable"))
        with patch("backend.app.realtime.DirectConnect", connect), self.assertRaises(ProviderError) as error:
            await turn.open()
        self.assertEqual((error.exception.status, error.exception.code), (502, "realtime_connect"))
        self.assertEqual(connect.await_count, 2)


class RealtimeAcknowledgements(unittest.IsolatedAsyncioTestCase):
    async def test_ack_cache_generates_pcm_manifest_for_exact_bailian_voice(self):
        cfg = Settings(_env_file=None, rt_api_key="fixture-bailian-key", rt_model="qwen3.8-omni-flash-realtime", rt_voice="test-voice")
        socket = _RealtimeSocket()
        pcm = bytes([1, 0]) * 240
        phrases = ["我帮你看看喵。", "稍等一下喵。"]
        for _ in phrases:
            socket.feed("response.audio.delta", delta=base64.b64encode(pcm).decode())
            socket.feed("response.done", response={"status": "completed"})

        connections = []

        @asynccontextmanager
        async def connect(url, **kwargs):
            connections.append((url, kwargs))
            yield socket

        with TemporaryDirectory() as directory, patch("backend.app.realtime.DirectConnect", connect):
            cache_dir = Path(directory)
            result = await ack_cache.synthesize_ack_phrases(cfg, phrases, cache_dir=cache_dir)
            self.assertEqual(result, {"voice": "test-voice", "count": 2, "phrases": phrases})
            self.assertEqual(len(connections), 1)
            self.assertTrue(connections[0][0].startswith("wss://dashscope.aliyuncs.com/"))
            self.assertEqual(socket.sent[0]["session"]["audio"]["output"],
                             {"format": {"type": "pcm", "sample_rate": 24000}, "voice": "test-voice"})
            self.assertEqual([item["type"] for item in socket.sent], [
                "session.update", "conversation.item.create", "response.create",
                "conversation.item.create", "response.create",
            ])
            manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["model"], cfg.rt_model)
            self.assertEqual([entry["text"] for entry in manifest["phrases"]], phrases)
            for entry in manifest["phrases"]:
                self.assertEqual(entry["bytes"], len(pcm))
                self.assertEqual((cache_dir / entry["file"]).read_bytes(), pcm)
            self.assertEqual(ack_cache.pick_ack_pcm("test-voice", cache_dir=cache_dir), pcm)
            self.assertIsNone(ack_cache.pick_ack_pcm("other-voice", cache_dir=cache_dir))

    async def test_tool_ack_uses_matching_cache_before_first_slow_tool(self):
        cfg = Settings(_env_file=None, rt_voice="test-voice", rt_ack_enabled=True)
        service = ChatService(cfg, None)
        turn = RealtimeTurn(service, None, "web_voice", AsyncMock(), False)
        turn.send = AsyncMock()
        turn.refresh_tools = AsyncMock()
        context = turn.tool_context
        execution_order = []

        async def push(chunk):
            execution_order.append(("audio", chunk))

        async def execute(*args):
            execution_order.append(("tool", args[0]))
            return {"result": "ok"}

        turn.audio = SimpleNamespace(push=push, finish=AsyncMock())
        context.execute = execute
        pcm = b"\x01\x00" * 2600

        with TemporaryDirectory() as directory, patch.object(ack_cache, "_CACHE_DIR", Path(directory)):
            cache_dir = Path(directory)
            items = [{"name": "web_search", "arguments": "{}", "call_id": "search"}]
            turn.tool_rounds = 1
            await turn.run_tools(items, turn.turn_id, context)
            self.assertEqual(execution_order, [("tool", "web_search")])

            ack_cache._save_cache(cache_dir, cfg.rt_voice, cfg.rt_model, ["测试首响"], [pcm])
            execution_order.clear()
            await turn.run_tools(items, turn.turn_id, context)
            self.assertEqual(execution_order, [
                ("audio", pcm[:4800]), ("audio", pcm[4800:]), ("tool", "web_search"),
            ])

            for rounds, name, options, reply in (
                (2, "web_search", {}, ""),
                (1, "get_weather", {}, ""),
                (1, "web_search", {"rt_ack_enabled": False}, ""),
                (1, "web_search", {"rt_provider": "compatible"}, ""),
                (1, "web_search", {"rt_voice": "other-voice"}, ""),
                (1, "web_search", {}, "我已经开口了"),
            ):
                with self.subTest(rounds=rounds, name=name, options=options, reply=reply):
                    execution_order.clear()
                    turn.config = cfg.model_copy(update=options)
                    turn.tool_rounds = rounds
                    turn.reply = reply
                    await turn.run_tools([{**items[0], "name": name}], turn.turn_id, context)
                    self.assertEqual(execution_order, [("tool", name)])

            for audio_ms, blocked in ((0, False), (None, True)):
                execution_order.clear()
                turn.config = cfg
                turn.reply = ""
                turn.first_audio_ms = audio_ms
                turn.output_blocked = Mock(return_value=blocked)
                await turn.run_tools(items, turn.turn_id, context)
                self.assertEqual(execution_order, [("tool", "web_search")])

    async def test_qwen_audio_realtime_session_native_search_and_voice_support(self):
        from backend.app import qwen_voices
        from backend.app.tools import ToolRegistry, ToolSpec

        self.assertTrue(qwen_voices.is_supported_target_model("qwen-audio-3.1-realtime-flash"))
        cfg = Settings(_env_file=None, rt_provider="bailian", rt_model="qwen-audio-3.1-realtime-flash",
                       rt_voice="longanqian_v3.1", rt_api_key="fixture-bailian-key")
        service = ChatService(cfg, None)
        turn = RealtimeTurn(service, None, "web_voice", AsyncMock(), False)
        registry = ToolRegistry([
            SimpleNamespace(spec=ToolSpec("get_weather", "weather", {"type": "object", "properties": {}})),
            SimpleNamespace(spec=ToolSpec("web_search", "search", {"type": "object", "properties": {}})),
            SimpleNamespace(spec=ToolSpec("search_m5stack", "m5", {"type": "object", "properties": {}})),
        ])
        turn.tool_context = SimpleNamespace(
            registry=registry, tool_gateway=None,
            allowed={"get_weather", "web_search", "search_m5stack"}, order_state_text=lambda: "",
        )
        session = turn._build_session_config()
        self.assertEqual(session["voice"], "longanqian_v3.1")
        self.assertEqual(session["input_audio_format"], "pcm")
        self.assertEqual(session["output_audio_format"], "pcm")
        self.assertEqual(session["input_audio_transcription"], {"model": "fun-asr", "language": "zh"})
        self.assertTrue(session["enable_search"])
        self.assertEqual(session["search_options"], {"enable_source": True})
        self.assertNotIn("audio", session)
        tool_names = [item["function"]["name"] for item in turn._realtime_tool_definitions(nested=True)]
        self.assertEqual(tool_names, ["search_m5stack"])

        socket = _RealtimeSocket()
        pcm = bytes([1, 0]) * 120
        socket.feed("response.audio.delta", delta=base64.b64encode(pcm).decode())
        socket.feed("response.done", response={"status": "completed"})

        @asynccontextmanager
        async def connect(url, **kwargs):
            yield socket

        with TemporaryDirectory() as directory, patch("backend.app.realtime.DirectConnect", connect):
            result = await ack_cache.synthesize_ack_phrases(cfg, ["稍等一下。"], cache_dir=Path(directory))
            self.assertEqual(result["count"], 1)
            self.assertEqual(socket.sent[0]["session"]["voice"], "longanqian_v3.1")
            self.assertEqual(socket.sent[0]["session"]["output_audio_format"], "pcm")

        requests = []

        async def fake_request(settings, payload):
            requests.append(payload)
            action = payload["input"]["action"]
            if action == "create_voice":
                return {"output": {"voice_id": "qwen-audio-3.1-realtime-flash-v1234-taffy"}}
            if action == "list_voice":
                return {"output": {"voice_list": [{"voice_id": "qwen-audio-3.1-realtime-flash-v1234-taffy"}]}}
            return {"output": {}}

        with TemporaryDirectory() as directory:
            index_path = Path(directory) / "qwen_voices.json"
            sample_path = Path(directory) / "taffy.mp3"
            sample_path.write_bytes(b"mp3-bytes")
            with (
                patch.object(qwen_voices, "INDEX", index_path),
                patch.object(qwen_voices.voices, "process_upload", return_value={"id": "tmp1", "name": "塔菲", "sample": "tmp.mp3"}),
                patch.object(qwen_voices.voices, "resolve", return_value=sample_path),
                patch.object(qwen_voices.voices, "delete"),
                patch.object(qwen_voices, "_request", side_effect=fake_request),
            ):
                created = await qwen_voices.create(cfg, b"wav-bytes", "taffy.wav", "塔菲", target_model="qwen-audio-3.1-realtime-flash")
                self.assertEqual(created["voice"], "qwen-audio-3.1-realtime-flash-v1234-taffy")
                listed = await qwen_voices.list_public(cfg, target_model="qwen-audio-3.1-realtime-flash")
                self.assertEqual(listed[0]["name"], "塔菲")
                await qwen_voices.delete(cfg, created["voice"])

        self.assertEqual(requests[0]["model"], "voice-enrollment")
        self.assertEqual(requests[0]["input"]["action"], "create_voice")
        self.assertEqual(requests[0]["input"]["target_model"], "qwen-audio-3.1-realtime-flash")
        self.assertLessEqual(len(requests[0]["input"]["prefix"]), 10)
        self.assertTrue(requests[0]["input"]["audio"].startswith("data:audio/mpeg;base64,"))
        self.assertEqual(requests[0]["input"]["language_hints"], ["zh"])
        self.assertEqual(requests[1]["input"]["action"], "list_voice")
        self.assertEqual(requests[2]["input"], {"action": "delete_voice", "voice_id": "qwen-audio-3.1-realtime-flash-v1234-taffy"})

    async def test_realtime_text_skips_loader_under_six_tools_uses_output_text_and_reports_error(self):
        from backend.app.realtime_text import RealtimeTextProvider

        cfg = Settings(
            _env_file=None,
            rt_provider="bailian",
            rt_model="qwen-audio-3.1-realtime-flash",
            rt_api_key="fixture-secret-key",
        )
        registry = ToolRegistry([
            SimpleNamespace(spec=ToolSpec("get_weather", "weather", {"type": "object", "properties": {}})),
            SimpleNamespace(spec=ToolSpec("web_search", "search", {"type": "object", "properties": {}})),
            SimpleNamespace(spec=ToolSpec("search_m5stack", "m5", {"type": "object", "properties": {}})),
        ])
        ctx = SimpleNamespace(
            session_id="s1", turn_id="t1", question="今日金价", history=(),
            registry=registry, current_registry=lambda: registry, tool_gateway=None,
            allowed={"get_weather", "web_search", "search_m5stack"}, outputs=[], secrets=["fixture-secret-key"],
            order_state_text=lambda: "", mark_sent=lambda *_: None,
            definitions=lambda **kw: registry.definitions(nested=kw.get("nested", False)),
        )
        socket = _RealtimeSocket()
        socket.feed("response.output_text.delta", delta="今天黄金大约760元一克喵。")
        socket.feed("response.done", response={"status": "completed", "usage": {"input_tokens": 10, "output_tokens": 5}})

        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield socket

        provider = RealtimeTextProvider(cfg)
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "今天北京天气"},
            {"role": "assistant", "content": "今天北京晴喵。"},
            {"role": "user", "content": "今日金价"},
        ]
        chunks = []
        with patch("backend.app.realtime_text.DirectConnect", connect):
            async for item in provider.complete_stream(messages, tool_context=ctx):
                chunks.append(item)

        self.assertEqual(chunks[0], "今天黄金大约760元一克喵。")
        session_cfg = socket.sent[0]["session"]
        tool_names = [t["function"]["name"] for t in session_cfg["tools"]]
        self.assertEqual(tool_names, ["search_m5stack"])
        self.assertNotIn("_load_task_tools", tool_names)
        created_items = [x["item"] for x in socket.sent if x["type"] == "conversation.item.create"]
        self.assertEqual(created_items[1]["role"], "assistant")
        self.assertEqual(created_items[1]["content"][0]["type"], "output_text")

        err_socket = _RealtimeSocket()
        err_socket.feed("error", error={"code": "InvalidParameter", "message": "bad item with fixture-secret-key"})

        @asynccontextmanager
        async def connect_err(*args, **kwargs):
            yield err_socket

        with patch("backend.app.realtime_text.DirectConnect", connect_err), self.assertRaises(ProviderError) as err:
            async for _ in provider.complete_stream(messages, tool_context=ctx):
                pass
        self.assertIn("InvalidParameter", err.exception.message)
        self.assertNotIn("fixture-secret-key", err.exception.message)
        self.assertIn("[已隐藏]", err.exception.message)

    async def test_native_search_prompt_and_stub_nudge(self):
        from backend.app.prompt_builder import build_system_prompt
        from backend.app.realtime_text import RealtimeTextProvider

        cfg = Settings(
            _env_file=None,
            rt_provider="bailian",
            rt_model="qwen-audio-3.1-realtime-flash",
            rt_api_key="fixture-secret-key",
        )
        prompt = build_system_prompt(cfg, "text", ["search_m5stack"], compact=True, native_search=True)
        self.assertIn("内置联网搜索", prompt)
        self.assertIn("问天气未说明城市时直接反问城市", prompt)
        self.assertIn("禁止只说“这就去查/稍等”就结束回复", prompt)

        registry = ToolRegistry([
            SimpleNamespace(spec=ToolSpec("get_weather", "weather", {"type": "object", "properties": {}})),
            SimpleNamespace(spec=ToolSpec("web_search", "search", {"type": "object", "properties": {}})),
        ])
        ctx = SimpleNamespace(
            session_id="s1", turn_id="t2", question="今日金价", history=(),
            registry=registry, current_registry=lambda: registry, tool_gateway=None,
            allowed={"get_weather", "web_search"}, outputs=[], secrets=[],
            order_state_text=lambda: "", mark_sent=lambda *_: None,
            definitions=lambda **kw: registry.definitions(nested=kw.get("nested", False)),
        )
        socket = _RealtimeSocket()
        socket.feed("response.output_text.delta", delta="小菲这就去查今日金价喵。")
        socket.feed("response.done", response={"status": "completed", "usage": {"input_tokens": 100, "output_tokens": 10}})
        socket.feed("response.output_text.delta", delta="今天国内金价大约762元/克喵。")
        socket.feed("response.done", response={
            "status": "completed",
            "search_info": {"search_results": [{"title": "今日金价", "url": "https://example.com"}]},
            "usage": {"input_tokens": 120, "output_tokens": 12, "plugins": {"search": {"count": 1}}},
        })

        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield socket

        provider = RealtimeTextProvider(cfg)
        chunks = []
        with patch("backend.app.realtime_text.DirectConnect", connect):
            async for item in provider.complete_stream([{"role": "user", "content": "今日金价"}], tool_context=ctx):
                chunks.append(item)

        text = "".join(c for c in chunks if isinstance(c, str))
        self.assertIn("小菲这就去查今日金价喵。", text)
        self.assertIn("今天国内金价大约762元/克喵。", text)
        self.assertEqual([x["type"] for x in socket.sent].count("response.create"), 2)
        self.assertEqual(chunks[-1].usage.prompt_tokens, 220)
        self.assertEqual(chunks[-1].usage.completion_tokens, 22)


if __name__ == "__main__":
    unittest.main()
