# Xiaozhi voice core

Source: xinnan-tech/xiaozhi-esp32-server
Revision: 1a095d5bed23e49a17f817c7f378e2a86f298dfc
License: MIT; see LICENSE.

This is a narrowed port into the existing FastAPI application, not the full
upstream server distribution. Local changes:

- core/connection.py keeps the LLM -> sentence queue -> TTS -> audio event
  pipeline, with asyncio tasks replacing upstream worker threads. Configuration,
  tools, reporting, memory and alternate engines are excluded. MiMo is supplied
  by the application's existing provider; no paid request retries are added.
  Streaming completion metadata is kept alongside text so an empty final answer
  can report the upstream stop reason without exposing reasoning content.
- core/providers/tts/base.py retains upstream quote-safe segmentation methods,
  with an incremental feed/flush interface.
- config/logger.py uses the application's standard Python logging, without
  loading upstream configuration, caches or loguru.
- core/handle/helloHandle.py retains the hello exchange without upstream MCP
  initialization and wakeup synthesis. Existing device authentication and MCP
  control stay in the application's gateway.
- The VAD provider uses standard logging without logging configuration values.
- Opus encoding retains its upstream implementation, with encoding errors
  propagated to the worker caller instead of silently dropping a frame. The
  abort handler retains its upstream implementation.
- AudioRateController propagates send errors and exposes wait_finished so a
  failed sender cannot leave the shared turn waiting indefinitely.

The application owns authentication, configuration and SQLite text history.
No audio recording is added to persistent history.
