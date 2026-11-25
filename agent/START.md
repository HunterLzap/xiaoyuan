# 当前工作入口

更新：2026-11-25。本文只维护当前状态快照与操作边界；历史演进与原始实跑记录见 [progress](docs/progress.md)。

## 1. 版本与环境位置

| 对象 | 当前状态 | 说明 |
| --- | --- | --- |
| 代码基线（`main`） | `a87a8a8`（Mac 开发，双推 Gitee + GitHub） | 2026-11-25 完成主线模型切换、原生联网合并、UI 极简重构、电脑操控闭环、轨迹详情与语音/网页打断电脑操控 |
| 云端生产 | `47.112.16.195`（`https://ryan406.online/xiaoyuan/`） | `/opt/xiaodan/current` 挂载 `/opt/xiaodan/shared/{.env,data,logs}`，通过 `deploy/release_from_git.sh` 从只读镜像仓原子更新 |
| Windows 端 | `E:\xiaodan`（`main` 跟踪 GitHub `origin/main`） | 保留本机 `.env`、`data/` 与虚拟环境，负责本地语音/Windows 节点与真机联调 |
| 硬件设备 | AtomS3R + Echo Base（已配对并接云） | 沿用现有固件（2.2.6 / `5ccb283` 基线），本阶段未修改或重刷固件 |

## 2. 已实测与已上线能力（2026-11-25）

1. **实时主线切换至百炼 `qwen-audio-3.1-realtime-flash`**：
   - 支持百炼 `voice-enrollment` 音色复刻并已成功复刻塔菲音色；顶层 `voice`、`pcm`、`fun-asr` 转写与 `output_text` 多轮对话修复已在网页端实测通过。
   - 启用百炼内置联网搜索（`enable_search` + `search_options.enable_source`），天气查询已合并进原生联网搜索（无独立默认城市配置，缺城市时由模型追问），云端实测金价与天气问答可用。
   - 候选工具 ≤ 5 时跳过额外加载，过滤内置 `web_search`/`get_weather` 防冲突，并针对短“这就去查”空口承诺自动追加一次续问。
2. **跨平台个人电脑操控已打通（Mac 云端端到端实测通过）**：
   - `desktop_node` 已通过 `wss://ryan406.online/xiaoyuan/desktop/v1/` 从 `ryandeMacBook-Air.local`（1470×956）直连云端上线。
   - 支持 Set-of-Mark（SoM）高亮编号截图 + 系统控件树（macOS `AXUIElement` / Windows UIA）+ 百炼原生视觉多模态直连（`qwen3.8-max-0902` / `qwen3.5-plus` 等，`enable_thinking: False`）+ 首步交互确认卡片与 3 分钟同任务免问租约 + 本地点击穿透悬浮边框/顶部 HUD。
   - 云端实测 `qwen3.8-max-0902` 操控 Mac 打开 Antigravity 并在当前会话输入并发送消息成功。
3. **网页工作台、设备页与记录轨迹升级**：
   - 「模型」页精简为「日常对话与语音」「电脑操控模型（含 `测试` 按钮）」两张卡片，折叠「高级设置」仅保留 3 项可调参数（`人声灵敏度阈值`、`按需发工具`、`工具等待播报首响`）；「联网搜索」卡片精简为开关 + `测试` 按钮。
   - 消息「详情」展示 **等待耗时（`first_response_ms`）**、模型/来源与 Token 明细，去除估算费用与冗长提示。
   - 公网「设备 → 电脑」页面优先展示在线/离线电脑卡片（基于 `/health` 零密钥只读 `desktop_nodes`），2 步带复制按钮的接入命令默认折叠且令牌不含尖括号。
   - 「记录」分为 4 页签：**对话历史**（按会话聚合并对齐侧栏标题，详情为左树右详「Agent 执行轨迹」视图）、**知识库**（`kb_only=true` 仅检索）、**工具调用**、**异常**。

## 3. 待实机 / 待验证与暂缓事项

- **待用户在云端/实机测试**：
  - `a87a8a8` 新增的**语音与网页跨通道即时打断电脑操控**（在电脑执行任务时说“停止/别动了/住手/stop/关闭”或网页点击停止，立即取消 `tool_task` 与跨会话 `active_task`、撤回所有桌面租约、向桌端发送 `abort` 隐藏 HUD 并拒绝在途 RPC）：已完成本机增量 Lint（`new=0`）与 73 项自动化回归验证，待更新云端后配合真机或网页实时语音实测。
  - AtomS3R 硬件真机在 `qwen-audio-3.1-realtime-flash` 下的连续语音对话、首声延时、`ack_cache` 首响播报及结束/唤醒循环，待用户实际开机讲话确认。
- **待办（见 [roadmap](docs/roadmap.md)）**：云端每日自动备份异地目标与恢复演练；可选的本机 `desktop_node` 自启/快捷启动脚手架。
- **用户明确暂缓**：云端语音回复整段随机卡顿暂不排查；固件新表情/动画实验暂不接入与重刷。

## 4. 接手操作边界

- **只读与授权边界**：文档同步不自动触发服务重启、云端部署、固件刷写或付费模型探测；相关操作按任务授权执行。
- **设备串口与硬件禁忌**：不要盲开 `COM3` 或执行 `esptool`（此前触发过 USB 复位与下载模式）；不擅自改动固件与 OTA 地址。
- **敏感信息红线**：`GET /api/devices` 含完整带 Key OTA 地址、`.env`、`desktop_nodes.json`、SSH 私钥、NVS 读回文件不得整包打印或推入 Git。
