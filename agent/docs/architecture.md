# 单助手语音与桌面 Agent 架构

更新：2026-11-25。本文说明当前生效架构及明确标注的未实现项；线上版本与实测边界见 [START](../START.md)，历史测试证据见 [progress](progress.md)。

## 1. 整体结构

```text
设备语音 (AtomS3R) / 网页语音 (WebRTC/WS) / 网页文字 (SSE POST /chat/stream)
                 ↓
会话与轮次：SettingsStore、agent_profile、活跃上下文 (≤6轮/6000字符)、确认卡片与即时中断控制
                 ↓
共用网关：ToolGateway + SideEffectConfirmationStore (300s TTL + 3分钟桌面租约) + 意图校验
                 ↕
百炼实时主线 (qwen-audio-3.1-realtime-flash) / 桌面多模态视觉 (qwen3.8-max-0902 等) / 分模型备用
                 ↓
ToolRegistry / TurnTools
 ├─ 百炼内置原生联网搜索 (enable_search 统一承担常规搜索与天气，排除独立 web_search/get_weather)
 ├─ M5Stack 官方资料、硬件声音控制、自定义 HTTP API
 ├─ 多独立个人知识库检索 (SQLite FTS + 向量按库过滤) & 当前会话原文检索
 └─ DesktopHub (/desktop/v1/ WSS) ↔ Windows / macOS 桌面节点 (desktop_node)
     ├─ 只读：节点清单、截屏 + 系统控件树 (AXUIElement/UIA) + SoM 编号图 + 剪贴板/文件读取
     └─ 受确认保护：打开应用/链接、GUI 键鼠操控 (element_index/click_and_type/回读)、写剪贴板、终端命令
                 ↓
SQLite 持久化：聊天历史与消息轨迹 / 多库知识 / desktop_nodes.json / system_errors (≤300脱敏) / data/ack_cache/
```

技术栈为 FastAPI + 原生 HTML/CSS/JavaScript + SQLite；只有一个助手，无多助手实体，无每轮强制前置规划模型。

## 2. 实时主线与模型兼容（2026-11-25 更新）

- **实时主线 `qwen-audio-3.1-realtime-flash`**：
  - 协议适配（`realtime.py` / `realtime_text.py` / `qwen_voices.py`）：`session.update` 使用顶层 `voice` 参数、24k/16k `pcm` 音频格式、`fun-asr` 输入转写；`realtime_text.py` 在多轮历史中对助手回复传 `output_text` 类型而非 `input_text`。
  - **音色复刻**：通过百炼 `voice-enrollment` 管线生成并绑定塔菲复刻音色，保留 `audio_fx.py` 语速/音调后处理与各 `(mode, provider, model)` 作用域独立状态存储。
  - **百炼内置原生联网搜索（合并天气）**：`qwen-audio-*` 且开启联网搜索时，自动传入 `enable_search: true` 与 `search_options.enable_source: true`，并从工具列表中排除重复的 `web_search` 与 `get_weather` 函数工具；`prompt_builder.py` 指示模型直接使用内置联网回答实时信息与天气（缺城市时主动追问）。对 `qwen-audio-3.1-realtime-flash` 仅返回短“这就去查”而未触发搜索的空口承诺，自动在 `realtime_text.py` 触发一次纠偏续答。
  - **按需工具加载策略**：`TextToolSelection` 在启用工具总数 > 5 时按任务线索与最近调用筛选候选并支持 `_load_task_tools` 同轮补充；当开放工具 ≤ 5 个时跳过选工具开销直接下发全量候选，避免多余往返。
- **桌面操控视觉模型**：`build_desktop_planner_config` 在电脑操控回合默认路由至用户选定或百炼原生视觉模型（`qwen3.8-max-0902`、`qwen3.5-plus` 等），传递最新 1 帧带 SoM 方框截图（裁剪前序轮次旧图以控费），并对 `qwen3.5*`/`qwen3.8*` 传入 `extra_body={"enable_thinking": False}`。支持 `POST /api/settings/desktop-model/test` 快速验通。

## 3. 跨平台桌面操控与跨通道即时打断

- **桌面节点与 SoM / 控件树（`desktop_node/` + `desktop.py`）**：
  - macOS 使用原生 Swift `AXUIElement` 控件树、`CoreGraphics` SoM 标号图及 `NSPanel` 点击穿透悬浮框；Windows 使用 `.NET UIAutomationClient`、`System.Drawing`/Pillow SoM 及 `tkinter` 穿透状态条。
  - 首次进入写操作弹出交互式确认卡片（`POST /api/approvals/{id}`，300s TTL），支持签发 3 分钟桌面免问租约（`approve_desktop_lease` 覆盖 `desktop_open` / `desktop_gui_action` / `desktop_set_clipboard`；`desktop_run_command` 与外部 HTTP 写工具仍每次必问）。
  - 敏感凭据（`.env`、`.ssh`、私钥、Keychains）在网关工具与本地 `desktop_node` 双重硬拦截；`ToolConversation` 支持参数归一化（剥离 `null`、对齐别名）与连续 3 轮工具全错自动熔断。
- **跨通道即时打断（语音 / 网页喊停）**：
  - `tool_gateway.py` 提供 `revoke_all_desktop_leases()`，`desktop.py` 提供 `DesktopHub.abort_all()`（立即置失败所有在途 RPC Future 为 `desktop_aborted` 并向在线节点下发 `{"type": "abort"}`，`desktop_node/client.py` 收到后立即 `hud.hide()`）。
  - `realtime.py` 新增 `_is_abort_task_intent`（支持如“停止/别动了/停下/住手/stop”等整句或短句组合）与 `_abort_running_tasks()`，不仅取消当前实时会话的 `tool_task`，还会**跨会话取消正在运行的 `active_task`（如网页正在进行的桌面操作循环）**、撤回租约并广播 `abort`：触发打断词时播放简短确认（如“好的，已停止操作”）并留在连续聆听状态；触发 `speech_started` 或 `_is_end_intent`（如“关闭/退下”）同样清理全部桌面任务与租约。
  - 网页点击停止或发“停止”调用 `main.py` `stop_active_turn()`，同步撤回租约并调用 `desktop.abort_all()`。

## 4. 知识库隔离、首响缓存与追踪观测

- **多库硬过滤（`personal_kb.py`）**：助手配置保留 `selected_kb_ids`；服务端在 FTS 与向量召回前按 `library_id` 硬过滤。历史数据已完成显式迁移。
- **实时工具首响缓存（`ack_cache.py`）**：耗时工具执行时仅读取当前百炼音色的本地 PCM 缓存（`data/ack_cache/`）经既有音频链播放，设置页显式生成操作才调用上游。
- **会话聚合轨迹与公网只读状态（`audit_store.py` + `main.py`）**：
  - `GET /api/insights/sessions`、`GET /api/insights/sessions/{session_id}`、`DELETE /api/insights/sessions/{session_id}` 按会话归并聊天轮次、工具调用树与每步耗时/Token/等待耗时（`first_response_ms`），支撑网页「记录 → 对话历史」左树右详「Agent 执行轨迹」视图；「记录 → 知识库」按 `kb_only=true` 过滤仅展示纯检索记录；系统错误统一脱敏存入 `system_errors`（上限 300 条）。
  - `GET /health` 暴露只读无密钥 `desktop_nodes` 列表（`node_id / display_name / platform / online / screen`），支撑公网「设备 → 电脑」只读节点状态展示；真实配对令牌管理与截屏预览仅允许本机回环访问，配置公网代理时返回 403。

## 5. 保留但未默认启用的机制

- **转写后选工具模式**：`AI_RT_DEFER_RESPONSE_UNTIL_TRANSCRIPT=true`（非手动实时语音等待完整转写并校验 `session.updated` 后再发 `response.create`）保留为可选项，默认维持原 `server_vad` 自动响应以保证首声速度；实机复杂音频环境验证仍待后续完成。
- **固件动画与设备声音链**：新表情/动画实验代码留在 Git 工作树固件目录，不并入稳定服务发布；稳定链保留 60ms Opus、播放参考/AEC、`stream_epoch` 迟到隔离。

## 6. 参考资料

- [百炼客户端事件](https://help.aliyun.com/zh/model-studio/client-events) · [百炼服务端事件](https://help.aliyun.com/zh/model-studio/server-events) · [Anthropic Writing Tools for Agents](https://www.anthropic.com/research/writing-tools-for-agents) · [Effective Context Engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)。更多见 [references](references.md)。
