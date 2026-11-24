# 当前工作入口

更新：2026-11-24。本文只写当前快照；历史过程与原始证据在 [progress](docs/progress.md)。

## Windows SlopGuard 本机配置（2026-11-24）

- Windows 的 SlopGuard 配置、pre-commit 钩子和交付流程在本机维护，本机工作约定见 `AGENTS.local.md`。共享仓库保留桌面权限修复和回归用例。验证记录见 [progress](docs/progress.md#windows-slopguard-门禁本地化2026-11-24)。

## Windows 本机同步（2026-11-23）

- `E:\xiaodan` 已统一为 Windows 项目的 Git 工作树与运行目录。`main` 与 GitHub `origin/main` 同为 `d567120`，本机从 `local/windows-sync` 运行。旧 `.cache/repo-export` 已移出项目，11 月 16 日本机刷写记录保留在忽略文件 `LOCAL_FLASH_NOTES.md`。
- 现有 `.venv` 已启动管理页面与 API，监听 `127.0.0.1:8000`。已读回历史、个人知识库和本机音色配置。桌面节点管理仅限本机回环，公网代理模式禁用该管理接口。启动、备份和验证范围见 [progress](docs/progress.md#windows-工作树统一与本机启动验证2026-11-23)。

## 11 月 17 日开发记录与暂停事项

已完成**个人 Agent 核心底座重构、Agent 优先单用户 UI 重构、Windows/macOS 跨平台桌面控制方案 A 体验增强、全系统脱敏异常日志中心（`异常日志`）**开发与 Mac 本机自动化验证：

1. **硬件闭环与云端基线**：云端当前在线 `82afc7c-20261117-093433`（上轮 `82afc7c` 与 `5ccb283` 固件已验证硬件对话、待机动画与 Mac `desktop_node` 首次上线、`观察电脑屏幕 · 684ms` 及 `desktop_open` 卡片确认闭环）。
2. **本轮打包范围（方案 A + 通用应用解析 + 异常日志，待推送与云端更新）**：
   - **Agent 内核与确认租约**：`SideEffectConfirmationStore` 支持 `approval_id` / 300s TTL / `POST /api/approvals/{id}` 交互确认卡片，新增 `approve_desktop_lease`（3 分钟桌面操控免重复弹窗，仅限 `desktop_open` / `desktop_gui_action` / `desktop_set_clipboard`，`desktop_run_command` 与外部 HTTP API 仍强制逐次确认）；工具提示约束未审批不提前口头承诺已完成。
   - **跨平台桌面节点增强（`desktop_node/` + `backend/app/desktop.py`）**：WebSocket 直连禁用代理（`proxy=None`，可选 `--use-system-proxy`）与 30s 应用层心跳；Windows 与 macOS 通用应用名解析（中英文别名表 + macOS `Info.plist`/`zh-Hans.lproj`/`InfoPlist.strings`/Spotlight `mdfind` + Windows 开始菜单 `.lnk`/`.url`/注册表 `App Paths`/UWP `Get-StartApps`）；百炼实时模式下默认使用 `compatible-mode/v1` + `qwen3-vl-plus`（可自定义 `desktop_vision_model`）看图定位。
   - **全系统异常日志中心（`error_log.py` + `执行洞察 → 异常日志`）**：统一收集硬件设备、桌面节点、模型对话/工具失败、FastAPI 4xx/5xx（含 500 堆栈摘要）到 `assistant_state.sqlite3` `system_errors` 表（上限 300 条并自动脱敏 `?key=`/`Bearer`/密钥），新增 `GET/DELETE /api/insights/errors` 与 Web 端「执行洞察 → 异常日志」分页筛选与清空面板。
   - **全链路实时执行感知（网页 + 桌面终端 + 本机屏幕框）**：新增 `POST /chat/stream` SSE 事件流与前端实时步骤胶囊（`app.js` 显示 `tool` 执行状态、参数摘要、看图/坐标明细与静态资源防缓存 `?v=__ASSET_VERSION__`）；`desktop_node/client.py` 控制台打印 RPC 起止耗时与 macOS 权限体检；新增跨平台点击穿透透明悬浮窗 `desktop_node/overlay.py`（macOS 原生 Swift `NSPanel` 避免刘海遮挡及抢焦点，Windows `tkinter` + `WS_EX_TRANSPARENT|WS_EX_NOACTIVATE` + `WDA_EXCLUDEFROMCAPTURE` 避开截屏），操作期间显示全屏蓝青边框及顶部「小圆正在操作电脑」状态胶囊。
   - **视觉坐标系校准与权限/Electron 防护（继 `13410ab` 实机排查后修复）**：百炼 Qwen-VL（`qwen3-vl-plus`）采用原生 `0..1000` 归一化坐标解析并由服务端预换算返回 `suggested_screen_coords`（同步支持 `coord_space='norm1000'`）；`platform_macos.py` 在未获「录屏与系统录音」或「辅助功能」权限时明确报错 `screen_capture_denied` / `accessibility_denied` 而不是静默返回成功，并清除 `type_text` 修饰键残留 + 分片延时以适配飞书/Lark 等 Electron 窗口；`desktop_gui_action` 返回 `verified_on_screen: false` 阻止模型未截屏核实就虚报完成。
   - **控件树精准定位 + 剪贴板复合输入 + 强规划模型路由（借鉴 `open-computer-use` 核心机制）**：新增 `desktop_node/ui_tree.py`（macOS 原生 Swift `AXUIElement` 含 Electron `AXManualAccessibility`，Windows .NET `UIAutomationClient`），`desktop_inspect_screen` 同步返回带精准中心坐标的 `ui_elements` 控件列表、`desktop_gui_action` 支持 `element_index` 直接命中与 `click_and_type` / `paste_text` / `submit`（非 ASCII 自动剪贴板备份粘贴防丢字）及操作后 `focused_element` 即时回读校验；`build_desktop_planner_config` 在桌面任务回合（可配置 `desktop_planner_model`）自动将 `realtime` 默认规划切换为百炼 `qwen-plus` / 用户主文字模型，普通聊天与语音实时对话保持不变。
   - **多步桌面连贯执行升级**：激活桌面工具时单轮上限放宽至 `16` 轮 / `28` 次调用、`timeout` 放宽至 `120s+`（满额追加收尾提示并清理意外 `<｜DSML｜>` 标记），`TextToolSelection` 覆盖“打开应用/飞书/找人聊天”自然指令，`desktop_inspect_screen` 即使省略 `question` 也强制启用视觉看图，兼容 `key_press`/`press_key`/单字符串 `keys` 别名，授权提示与规则明确引导搜完联系人后点击下拉列表人物卡片而非顶部「消息」筛选标签。
   - **原生多模态直连看图 + Set-of-Mark 方框标注 + 统一模型配置中心（2026-11-17）**：新增 `desktop_node/som.py`（macOS 原生 Swift CoreGraphics 与 Windows .NET `System.Drawing` / Pillow 零额外服务依赖在截屏上绘制精确匹配 `ui_elements[].index` 的彩色高亮编号框 `[0]`, `[1]`…）；`ToolConversation` 对原生多模态模型直接传入最新带框 `image_url`（同时自动裁剪更早轮次图片保持 `O(1)` 图像开销），跳过 `_analyze_screenshot` 二次看图转发；有百炼 Key 时电脑操控默认路由至 `qwen3.5-plus`（并针对百炼 `qwen3.5*` 桌面工具回合传 `extra_body={"enable_thinking": False}` 提速降本，另可选 `qwen3.5-flash`）；顶栏模型胶囊与「模型与连接」合并为统一配置视角。
   - **参数强兼容、3 轮报错熔断、随时停止开关与设置 UI 去噪（2026-11-17）**：解决 `qwen3.5-plus` 传入 `null` 可选字段、浮点坐标及 `type`/`coordinate` 别名导致 `desktop_gui_action` 在 Schema 校验层 `0ms` 连续失败 14 轮的问题（`_normalize_tool_arguments` + `SchemaValidationError` 返回精确字段错误 + 连续 3 轮全错熔断）；新增 `POST /chat/cancel`、运行中对话栏与输入框停止按钮 `#stop-turn` / `.pending-stop-button` 及“停止/停下/别动/取消”文本打断指令；并将 `.api-panel .settings-row` 标签列拓宽至 `108px`，彻底清理模型/档案/技能页中堆叠的多行小字说明与冗余角标。
   - **Agent 优先单用户 UI**：保留 Codex 灰阶主题、「Agent 与档案」「技能与知识」「终端节点（Windows/Mac + AtomS3R）」及语音面板完整功能。

- 保留既有实时主线模型 `qwen3.8-omni-flash-realtime`、塔菲复刻音色与唤醒/待机/卡顿暂缓约定，不擅自更改语音服务或重置历史数据。
- **11 月 17 日记录的待验证范围**包含云端发布后的 Mac/Windows 桌面操控与硬件报错捕获。11 月 23 日仅更新 Windows 本机，云端当前发布待另行核对。

## 版本与位置

| 对象 | 最后确认事实 | 接手注意 |
| --- | --- | --- |
| 稳定基线 | 历史基线 `bd639a9` / 固件与网关 `5ccb283` / 桌面首版 `82afc7c` | 追溯点；本轮提交在 `82afc7c` 之后推进 |
| Windows | `E:\xiaodan`，`main` 为 `d567120`，本机启动分支为 `local/windows-sync` | 本机私有配置和数据沿用原路径 |
| Git 开发快照 | 三端协同：Mac `main` → `git push origin main` 双推 Gitee + GitHub | 本地凭据与私钥不入库 |
| 云端发布（11 月 17 日记录） | `/opt/xiaodan/current` → `/opt/xiaodan/releases/82afc7c-20261117-093433`（`https://ryan406.online/xiaoyuan/`） | 当时 Caddy 已配置 `/xiaoyuan/desktop/v1`，方案 A 与异常日志待发布 |
| 云端运行数据 | `/opt/xiaodan/shared` | `.env`、data、logs、缓存独立于 release；回滚代码不回滚数据库 |
| 设备 | AtomS3R + Echo Base，固件按 `5ccb283` (`2,777,232B` app-flash，COM3) 与对应 `generated_assets.bin` | 上轮真机对话+待机动画+“退下/关闭”直接待机已实测通过；本次未改动固件 |

Windows 本机进程以 11 月 23 日启动日志为准。云端与设备未在这次本机同步中重查。实时主线保留百炼 `qwen3.8-omni-flash-realtime`、原塔菲复刻音色和末次语速1.2/音调+3。`main`的开发快照不等于该云端release；需要运行/发布时先按architecture/operations区分模块，不用“Git已提交”推断声音已验证。

云端当前版本保留前几版文字/Token/工具优化；语音首批只在 `tool_dialogue.py`、`prompt_builder.py` 去除重复说明并复用共用校验/用量。`realtime.py`、`device_realtime.py`、`audio_fx.py`、`voice_transport.py`、`speech_text.py`、`prompt_context.py` 与前一云端稳定发布一致。工作树同名文件可能含实验改动，不能混为在线代码。

## 设备接云已确认到哪一步

- 11月15日21:25:07，设备完整 OTA 请求鉴权通过；21:26:45.471166+08:00建立真实设备语音连接。
- 会话 `6ee66d7b-c3ac-42b9-8d75-475cafb5d9a0` 有5轮实际问答；报数轮 `5d516f73-2aae-4539-821f-71b1f5f735c5`：“从一数到三。”→“好呀，一、二、三。”。这轮确实经过自有云端。
- 报数34个60ms音频包全部发送，编码/发送CRC一致，最大发送间隔61ms，无网关断供。只证明服务器发送连续，**不能证明设备收到后连续播放**。
- 21:28:27.839624+08:00连接结束，服务收到关闭码1000；这是历史连接状态，不可把后续 `connected=false` 当成未接云，也不能仅凭关闭码认定“退一下吧”正确回待机。
- 设备最近回报 Wi-Fi 为 `CMCC-g24u`、信号弱；没有该轮设备收包/解码/播放记录。弱信号及PCM低能量段均未证明卡顿原因。
- 稳定恢复后用户曾确认“恢复了”；这项历史现场确认有效，但不代表云端卡顿、所有结束词和全部物理场景已通过。

## 已实现与仍待办

| 项目 | 当前范围与限制 |
| --- | --- |
| 单助手与多库 | 单用户自动同步 `/api/assistant/selection`（API单开关+知识库行内挂载+新建默认挂载）；服务端库过滤不变 |
| 个人 Agent 与确认 | `agent_profile` 持久化写入提示词；`SideEffectConfirmationStore` 支持 `approval_id`/TTL/交互确认卡片与语音“确认”；未重做多助手 |
| 跨平台桌面控制 | `DesktopHub (/desktop/v1/)` + 9个桌面读写/GUI/终端工具 + `desktop_node/` (Win/Mac)；WebSocket、缩放换算与门禁已通过自动化测试，**双端实机长连接与浏览器真实界面待上云后实测** |
| 工具误调用 | 共用执行层校验本轮控制意图及明确目标，报数零工具有真实记录；不承诺所有工具场景都正确 |
| Token 明细 | 保存供应商输入/输出/合计、文字/音频/缓存明细和响应次数；缺项不填0。多次响应按轮汇总；不是纯输出字数或最终账单 |
| 网页实时文字 | 已按任务下发候选并集，保留复合指令、追问和 `_load_task_tools` 同轮补充；未知需求可能多一次模型续答 |
| 语音工具 | 仍下发全部已开放工具，保留原 server_vad 自动响应；只做共用校验/用量与提示去重，**未接入转写后选工具** |
| 上下文/记忆 | 完整 SQLite 历史保留；本地重建最近最多6轮/6000字符，按需查当前会话原文；无跨会话画像、无每轮总结模型 |
| 连续实时上下文 | 同一供应商 WS 的旧项未主动裁剪；6轮预算仅约束本地重建，不能宣称连续语音上下文已完全有界 |
| 天气追问 | 直连文字驱动语音探查中“那明天呢”错误复用旧日期数据；提供了工具但模型没调用，尚未修复，也未证明由本轮改动导致 |
| 转写后响应 | 当前模型接受 `create_response=false` / `interrupt_response=true` 回显；未输入真实音频，方案未接生产；细节见 architecture |
| 云备份 | 每日独立备份、保留30天仍是目标；没有已完成部署/恢复的证据，不写已交付 |

## 接手操作边界

先读 [AGENTS](../AGENTS.md)、[统一入口](agent.md)；按任务读 [architecture](docs/architecture.md)、[operations](docs/operations.md)、[代码地图](code/structure.md)。发生版本变化时再查实际进程/release，不为阅读文档启动或重启服务。

- 用户本次已授权Git提交与同步远端；不因此部署、下载/安装、改设备地址、刷固件、开串口或发模型请求。
- SSH只读检查曾获授权，连接方法见operations；本轮无须重查远端。后续操作依据用户具体任务与已有授权，不重复请示常规小步骤。
- 不盲开COM3或执行esptool：此前打开串口曾触发USB复位，RTS复位曾使设备进入下载模式；用户拔插后已恢复。
- `GET /api/devices` 包含完整带key OTA地址，禁止整包输出；NVS读回文件、`.env`、devices.json不得完整打印。
- 优先参考官方资料和成熟项目已有做法，再适配现有实现；不靠堆提示词、批量付费探查或无限深挖一个假设推动工作。

接下来由用户选择恢复哪项工作；卡顿、新动画、转写后选工具均不能由旧待办自动触发执行。
