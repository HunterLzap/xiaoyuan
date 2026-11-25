# 代码与运行位置地图

更新：2026-11-25。此处描述模块职责，不代表磁盘代码已被运行进程加载；实际版本与实测边界见 [START](../START.md)。

## 三端与运行目录

| 位置 | 职责 |
| --- | --- |
| Mac 开发根目录 | 日常开发、增量 Lint、JS 语法校验、`desktop_node` Mac 联调与 `git push origin main` 双推 Gitee + GitHub |
| `E:\xiaodan` | Windows Git 工作树、本地运行目录与本机私有数据（保留 `.env`、`data/`、`logs/`、虚拟环境） |
| `/opt/xiaodan/current` | 云端生产 release 软链；只读镜像仓 `/opt/xiaodan/repo`，共享配置/数据/日志位于 `/opt/xiaodan/shared` |

## 后端与桌端关键模块

后端模块除特别标注外均位于 `backend/app/`；跨平台桌端节点位于项目根 `desktop_node/`。

| 位置 | 职责 |
| --- | --- |
| `backend/run_devices.py` | 单进程管理端与设备网关启动入口；本地通常监听 8000/8003，云端内部监听 8010/8013 |
| `main.py` / `devices.py` / `desktop.py` | 管理 API、SSE 流对话(`/chat/stream`)、停止打断(`/chat/cancel`)、OTA/设备 WS、`/desktop/v1/` 跨平台节点中心与 `abort_all` |
| `realtime.py` / `realtime_text.py` | 百炼 `qwen-audio-3.1-realtime-flash`（及 OpenAI 兼容）实时语音与实时文字会话、内置联网搜索、`output_text` 多轮与语音即时打断 |
| `device_realtime.py` / `voice_transport.py` | 设备实时桥接、Opus/发送节奏/预缓冲、播放结束与取消隔离 |
| `voice_chat.py` / `conversation.py` / `device_turn.py` | 网页/设备对话协调及显式分模型 Pipeline 路径 |
| `prompt_builder.py` / `prompt_context.py` / `speech_text.py` | 角色/工作档案/内置联网规则/时间/渠道提示与朗读规范化 |
| `tools.py` / `desktop_tools.py` / `tool_dialogue.py` / `tool_gateway.py` | 工具注册/桌面操控工具、确认卡片闭环(`approval_id`/300s TTL/3 分钟租约与 `revoke_all_desktop_leases`)、参数归一化与 3 轮熔断 |
| `text_tool_selection.py` | 启用工具超过 5 项时的按需候选筛选与 `_load_task_tools` 同轮补充（自动排除已被原生联网取代的 `web_search`/`get_weather`） |
| `conversation_memory.py` | 活动历史预算（≤6 轮/6000 字符）与当前会话原文按需检索 |
| `knowledge.py` / `api_requests.py` / `weather.py` | M5 官方只读资料、自定义 HTTP API（`weather.py` 保留作兼容与分模型后备，主线默认走百炼原生搜索） |
| `personal_kb.py` / `embeddings.py` / `audit_store.py` | 多库原文/FTS/向量按库硬过滤、洞察读写、会话级 `Agent` 执行轨迹聚合 (`/api/insights/sessions`) |
| `service.py` / `history_store.py` / `schemas.py` / `error_log.py` | 会话与持久历史、`first_response_ms` 等待耗时、Token 明细聚合、SQLite 脱敏系统异常日志（`system_errors`） |
| `config.py` / `settings_store.py` / `qwen_voices.py` | 配置读取、单助手选择与 `(mode, provider, model)` 作用域持久状态、百炼 `voice-enrollment` 音色对接 |
| `audio_fx.py` / `audio_metrics.py` / `ack_cache.py` | 原语速/音调后处理、被动 PCM 计量、实时工具首响本地 PCM 缓存（`data/ack_cache/`） |
| `voices.py` / `tts.py` / `asr.py` | 分模型显式 TTS/ASR 适配与音色元数据 |
| `app.html` / `app.js` / `app.css` / `paths.js` | 极简单助手管理台、确认卡片/停止按钮、公网只读电脑状态卡片、4 页签「记录」与左树右详轨迹查看器、子路径适配 |
| `voice.js` / `voice-capture.js` | 网页音频采集、实时状态呈现与播放 |
| `desktop_node/` (`client.py` / `som.py` / `ui_tree.py` / `overlay.py` / `platform_macos.py` / `platform_windows.py`) | macOS/Windows 跨平台桌端连接客户端、SoM 高亮编号图渲染、系统辅助功能控件树、穿透边框 HUD（含收到 `abort` 立即隐藏） |

## 固件、部署与数据

- `firmware/xiaozhi-esp32/`：设备状态机、AFE、播放参考/AEC 与板级代码。工作树中的新动画与相关构建目录（如 `build-tafei-mn5-ui-anim`）属于保留实验，不经授权不编译或刷入设备。
- `deploy/`：Caddy 路由与日志过滤模板、systemd 配置、`release_from_git.sh` 原子发布脚本及 `backup_shared.sh` 热备脚本。
- `data/`、`models/voice/`、`logs/`、`output/`、`.env`：私有运行数据、音色样本与历史日志均留在各自运行机/云端 `/opt/xiaodan/shared`，不随 Git 迁移。
