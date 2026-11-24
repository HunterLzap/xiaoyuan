# 单硬件语音助手架构

更新：2026-11-24。本文说明当前设计和明确标注的未接入方案；运行版本、现场范围见 [START](../START.md)，历史探查见 [progress](progress.md)。

## 1. 当前结构

```text
设备语音 / 网页语音 / 网页文字工作台
                 ↓
会话与轮次：设置、agent_profile、历史重建、确认状态与审批卡片
                 ↓
共用策略：ToolGateway + SideEffectConfirmationStore (TTL + ID) + 意图校验
                 ↕
百炼原生实时 / OpenAI 兼容模型与工具反馈循环
                 ↓
ToolRegistry / TurnTools
 ├─ 天气、M5Stack官方资料、硬件声音控制、自定义HTTP API
 ├─ 所选个人知识库检索 & 当前会话历史检索
 └─ DesktopHub (/desktop/v1/ WSS) ↔ Windows / macOS 桌面节点 (desktop_node)
     ├─ 只读：列出节点、截屏+系统控件树(`AXUIElement`/`UIA`)+视觉观察(`norm1000`预换算)、剪贴板/目录/文件读取
     └─ 受确认保护：写剪贴板、打开应用/链接、GUI鼠标键盘(支持`element_index`/`click_and_type`/剪贴板粘贴/回读校验)、终端命令
                 ↓
服务端私有配置、SQLite历史/资料/向量/洞察与异常日志(system_errors)、desktop_nodes.json
```

FastAPI、原生HTML/CSS/JavaScript、SQLite；只有一个助手。实时主线为百炼 `qwen3.8-omni-flash-realtime`，直接生成塔菲复刻音色；保留既有语速/音调后处理。DeepSeek/MiMo仅为显式分模型路径，不作为实时语音的隐式替代。没有每轮必走的分类/规划/总结模型。

云端已在2核约1.87GB服务器运行，模型服务在供应商云端，本服务负责协议、执行与存储。实际路径与端口见 [operations](operations.md)；不能以本机文件推断在线已加载实现。

## 2. 助手、资源与检索范围

- **资源管理**配置天气/M5/自定义API和多独立知识库，管理启用/停用与资料，不自动扩大助手选用范围。
- **助手配置**沿用SettingsStore，保存提示词、工具ID与库ID选择；不新建多助手表。空选择不回退到全部开放。
- **执行**取助手选择与资源可用范围的交集；真正执行前仍查资源状态、Schema与权限。提示词和模型参数都不能越权。
- **知识库**已有 `kb_libraries` 与文档 `library_id`，group仅作标签；关键词/向量/覆盖率在服务端按库过滤，过滤在候选截断前完成。旧库已显式迁移，不在启动时重复ALTER或静默重建。
- **一致性**一轮使用相应配置范围，下一轮用新设置；声音沿用按音频段固定语速/音调的行为，不在同一段中跳变。

多库关键词与hybrid隔离已有真实证据，具体见progress。管理资源的手动试查与助手对话选择是不同入口，不能用手动试查成功证明助手选择边界已验证。

## 3. 工具执行与不同渠道

模型根据问题和真实结果决定是否继续调用，服务端验证并执行、回填结果。普通业务边界为每轮最多4轮工具循环、8次业务调用；当本轮包含桌面操控工具时放宽至最多10轮、20次调用且超时不少于90–120s，网页文字端通过 `POST /chat/stream`（SSE `session`/`tool`/`text`/`done`）实时呈现每一步工具进度，本地 `desktop_node/overlay.py` 通过点击穿透/不抢焦点悬浮边框与顶部状态条向用户实时感知操作。达到边界如实报告，不无限循环。

`TurnTools`执行前检查本轮控制意图与明确目标。报数不能被模型误调用音量工具而真的调音量；明确的已开放音量/声音控制继续执行并核对真实结果。只有可变更工具需要等待语音本轮转写用于校验，普通音频不因此统一等待。

| 渠道 | 工具定义与触发 |
| --- | --- |
| 网页实时文字 | `TextToolSelection`按任务线索、控制计划和最近真实调用选候选；复合需求取并集，保留省略追问 |
| 网页文字同轮加载 | 未预选能力通过 `_load_task_tools` 补入原注册表范围；更新定义后续答，仍走原权限/Schema/意图/审计 |
| 设备与网页实时语音 | 默认继续由 server_vad 自动触发并提供全量工具。非手动模式可按第 5 节启用转写后工具选择 |
| 显式分模型模式 | 保留自身适配器与共用执行策略，不能据文字或实时探查声称所有分模型场景已确认 |

工具加载不消耗业务8次/4轮额度，但模型续答次数和Token必须如实计入。未知问题可能多一次加载响应，不能承诺任何请求都更省或更快。定义裁剪不是执行保证，不能为了省Token将正常调用、复合指令和“那明天呢”挡掉。

写操作与电脑控制均走统一确认闭环：服务端 `SideEffectConfirmationStore` 为每项 `write`/`paid` 调用签发绑定 `(approval_id, session_id, turn_id, args_digest)` 的有限期（300s）待确认凭证，并返回 `pending_approval` 结构随消息持久化；网页端可在消息下方卡片一键「确认执行 / 确认并免问电脑操控 (3 分钟) / 取消执行」（`POST /api/approvals/{id}`，3 分钟免问租约 `approve_desktop_lease` 仅限 `desktop_open`、`desktop_gui_action` 与 `desktop_set_clipboard`，不涵盖 `desktop_run_command` 与外部 HTTP API），语音及纯文字渠道也可直接在下一轮回复“确认/取消”。读取 `.env`、`.ssh`、私钥、Keychains 等路径由网关工具与本地 `desktop_node` 双重拦截；`desktop_gui_action` 默认依据最近一次截图尺寸与目标电脑逻辑分辨率自动换算坐标，兼容 Retina 与 Windows DPI 缩放。系统各链条关键错误通过 `ErrorLogStore` 脱敏写入 `assistant_state.sqlite3`（最近 300 条），通过 `GET/DELETE /api/insights/errors` 暴露。

> 注：跨平台桌面节点与确认卡片机制已在源码实现并通过自动化测试与 Mock 联调；云端发布更新及 Windows/macOS 真机连续对话操控待部署与现场试跑确认。

## 4. 提示、上下文、记忆与Token

提示由角色、日期/时间、必要工具规则、渠道朗读规范及工具定义组成，密钥不进入模型。语音首批只去除重复工具名单和重复闲聊提醒，保留角色、首句、完整报数与追问规则；网页文字另有compact分支，不能套用到语音。

- SQLite完整原文与活动上下文分开。当前本地重建最多最近6轮、6000字符；超长单条保留带省略标记的首尾，中断助手消息不作为完整回答重建。字符预算不是精确Token预算。
- `search_conversation_history`只按需读取当前会话旧原文，可按关键词/时间/角色查；不执行历史里的控制指令，不做跨会话画像或长期记忆。
- 连续设备语音达到默认 6 轮或 600 秒后，在正常回复已保存且播放队列收尾时更换上游 WS，按原模型和音色重建最近上下文。业务会话 ID 与设备连接沿用，轮换间隙丢弃上行过渡帧。
- `response.done`用量通过 `TokenUsage.from_provider`、`combine_usage`保存输入/输出/合计、文字/音频/缓存细项及逐次响应；缺项不补0。最终一条短回答可能经历多个模型响应。
- 输入不仅是用户几个字，还含提示、工具定义、上下文及语音输入；输出也可能含音频Token。逐块输入差分只能说明固定顺序的边际消耗，不是供应商逐项账单。历史旧记录缺模态字段时不可补造。
- 缓存明细不等于已启用缓存折扣；尚未证明当前实时主线支持何种显式缓存控制，不套用别的模型字段或价格。

历史精简样例及原始用量通过progress证据索引追溯，不在设计中维护另一份结果表；它们不是语音节省幅度或每轮保证，声音用量以该轮供应商回报为准。

## 5. 完整转写后选工具与待实现的查询覆盖

默认维持原有 server_vad 自动响应。非手动实时语音启用 `AI_RT_DEFER_RESPONSE_UNTIL_TRANSCRIPT=true` 后，上游握手暂不下发工具并关闭自动回答，保留 VAD 打断。完整转写先处理结束意图，再按当前任务更新工具。候选超过 5 项时复用 `TextToolSelection` 和 `_load_task_tools`。

接收循环通过 `session.updated` 事件推进回答。按发送顺序关联配置更新及所属轮次，只有当前轮等待的更新收到确认后才发送 `response.create`。新一轮说话或进入控制续答时撤销上一响应触发资格。真实音频下的确认与打断时序仍待验证。[百炼客户端事件](https://help.aliyun.com/zh/model-studio/client-events) · [百炼服务端事件](https://help.aliyun.com/zh/model-studio/server-events)

查询覆盖仍待实现。历史直连探查中，首问成功获取北京 11 月 15 日天气，追问“那明天呢”没有触发查询却复用了温度。查询结果应校验目标城市、日期和成功状态，旧结果确实覆盖目标时才复用。

## 6. 语音、动画与证据边界

11月15日恢复稳定应用/旧资源后，用户确认语音恢复；随后云端真实会话已接通，但整段回答随机卡顿仍在，用户已要求暂缓。网关发完与设备播放流畅是不同事实。

项目后来已有播放参考/AEC及持续上行实现，真实指标 `aec=true`；旧上游板级默认AEC说明不能否定项目当前实现，也不能据握手就宣称任何环境都能正确打断。保留已有状态、取消、`stream_epoch`与迟到隔离。

新动画已有解码配置问题及UI发送与音频共锁的耦合线索；稳定版也出现过TCP发送超时，未证明所有语音故障由动画导致。实验代码留在Git工作树，不并入当前云端发布，不盲调250ms期限、缓冲或音色。

- 实时工具首响只读当前百炼音色的本地 PCM 缓存，经原有音频链播报。设置中的显式生成操作才调用上游，缓存位于 `data/ack_cache/`。
- 带框截图预览只随聊天 SSE 工具完成事件发送，超过 350 KiB 时省略。页面仅保留最新预览，历史与审计沿用纯文本工具结果。

## 7. 采用过的成熟项目资料

以下是此前调查参考，不代表本轮重新联网核实，也不授权安装框架。再次依赖易变协议时查官方最新资料。

- [Anthropic工具设计](https://www.anthropic.com/research/writing-tools-for-agents)、[按需工具](https://www.anthropic.com/research/advanced-tool-use)、[上下文工程](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)：描述清晰、按需加载与上下文预算。
- [LangChain动态工具选择](https://docs.langchain.com/oss/python/langchain/tools#dynamic-tool-selection)、[短期记忆](https://docs.langchain.com/oss/python/langchain/short-term-memory)：候选选择与持久历史分离。
- [OpenAI工具guardrails](https://openai.github.io/openai-agents-python/guardrails/)：工具执行前校验，未引入其SDK。
- [LiveKit PR6642](https://github.com/livekit/agents/pull/6642)、[Realtime实现](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/llm/_realtime/openai.py)：分段与响应触发拆分。
- 百炼[客户端事件](https://help.aliyun.com/zh/model-studio/client-events)、[服务端事件](https://help.aliyun.com/zh/model-studio/server-events)：当前供应商协议依据。

其他资源见 [references](references.md)。不新增规划模型、多助手、通用代办平台或平行文档体系。
