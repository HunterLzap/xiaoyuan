"""Event-handler regressions; no provider calls, audio hardware or server startup."""
import asyncio
import json
import unittest
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from websockets.exceptions import ConnectionClosedOK

from backend.app.device_realtime import DeviceRealtime
from backend.app.order_confirmation import RealtimeOrderGuard
from backend.app.realtime import RealtimeTurn


class RealtimeFailures(unittest.IsolatedAsyncioTestCase):
    def make_turn(self):
        turn = RealtimeTurn.__new__(RealtimeTurn)
        turn.turn_id = uuid4()
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

    def make_bridge(self):
        bridge = DeviceRealtime.__new__(DeviceRealtime)
        bridge.conn = SimpleNamespace(frames_dropped=0, ws=SimpleNamespace(close=AsyncMock()))
        bridge.turn = SimpleNamespace(
            ws=object(), reader=SimpleNamespace(done=lambda: False),
            turn_id=uuid4(), input_closed=False,
            append=AsyncMock(side_effect=ConnectionClosedOK(None, None)),
            finish=AsyncMock(side_effect=ConnectionClosedOK(None, None)), close=AsyncMock(),
        )
        bridge.codec = SimpleNamespace(decode=lambda packet: bytes(32))
        bridge._rx_diag_frames = 0
        bridge._rx_diag_max_rms = 0.0
        bridge._rx_diag_last_log = monotonic()
        bridge.hub = SimpleNamespace(last_error=None)
        bridge.playback_metrics = SimpleNamespace(mark=Mock())
        bridge._last_text = None
        bridge.stop_audio = AsyncMock()
        bridge.show_text = AsyncMock()
        return bridge

    async def test_provider_append_close_does_not_close_device(self):
        bridge = self.make_bridge()
        with self.assertLogs("backend.app.device_realtime", level="ERROR"):
            await bridge.append(b"packet")
        bridge.turn.close.assert_awaited_once()
        bridge.conn.ws.close.assert_not_awaited()
        self.assertTrue(bridge.turn.input_closed)
        bridge.stop_audio.assert_awaited_once_with(interrupt=True)
        bridge.show_text.assert_awaited_once_with(bridge.hub.last_error)

    async def test_provider_finish_close_does_not_close_device(self):
        bridge = self.make_bridge()
        with self.assertLogs("backend.app.device_realtime", level="ERROR"):
            await bridge.finish()
        bridge.turn.close.assert_awaited_once()
        bridge.conn.ws.close.assert_not_awaited()
        bridge.stop_audio.assert_awaited_once_with(interrupt=True)
        bridge.show_text.assert_awaited_once_with(bridge.hub.last_error)


if __name__ == "__main__":
    unittest.main()
