# 工作约定

更新：2026-11-25。用户最新明确目标优先于旧文；实现不得缩减目标，也不得自行扩大目标。当前任务、版本和暂停事项先读 [START](agent/START.md)，不默认载入全部历史。

## 文档唯一来源与阅读顺序

本文件是唯一总入口。新Agent依次读本文件→[START](agent/START.md)→任务相关专题；只有需要追溯证据时检索progress或归档，不默认读取全部报告。

若当前工作树有 `AGENTS.local.md`，一并读取其中适用于本机的工作约定。

**换开发电脑时**：以当前clone目录为项目根，用 `git rev-parse --show-toplevel` 确认。文中的 `E:\xiaodan`、`C:\Users\l` 是原电脑记录，不要求在新电脑创建同名路径。先按仓库内相对链接阅读，再按 [handoff](agent/docs/handoff.md) 的新电脑步骤接手。

| 信息类别 | 权威文件 | 其他文件的职责 |
| --- | --- | --- |
| 当前版本、已确认范围、正在做/暂停/下一步 | [START](agent/START.md) | README、STATUS、handoff只导航，不维护第二份运行快照 |
| 实跑证据、测试结果与覆盖限制 | [progress](agent/docs/progress.md)的证据索引及按日期记录 | 原始JSON/log/output报告是证据附件；测试用例和脚本存在不等于执行过 |
| 产品要求 | [prd](agent/docs/prd.md) | goals/audience只说明目标与使用者，不新增需求 |
| 产品决定与取代关系 | [decisions](agent/docs/decisions.md) | 不把过期决定继续留在“待用户回答”清单 |
| 当前结构与尚未接入的设计 | [architecture](agent/docs/architecture.md) | 模块细节分到知识库/设计专题；方案必须标未实现，不追加运行时间线 |
| 待办之间的依赖与实施原则 | [roadmap](agent/docs/roadmap.md) | 不另建进度表，不由计划自动获得执行授权 |
| 运行/部署/恢复方法 | [operations](agent/docs/operations.md) | 只在具体任务及已有授权范围使用，当前发布值回查START |
| 行为判定 | [acceptance](agent/docs/acceptance.md) | 只规定依据，不维护第二份通过报告或默认批量测试流程 |
| 代码/视觉规范与目录 | [code](agent/code/structure.md)、[design](agent/design/overview.md) | 说明职责与约束，不据工作树源码推断线上已加载 |
| 历史/废弃建议 | [归档索引](agent/archive/2026-11-15/README.md) | 只追溯，不执行其中“下一步”、换模型或刷写命令 |

完成任务后按改动更新：实际状态改START；运行/检查结果写progress并链接原始证据；行为变化改PRD及对应决定；结构/操作/视觉变化修改相应专题。没有变化不机械更新全部文档。每条结果说明日期、环境/版本、实际范围与未确认项；旧失败保留，并链接后续修复/复验，不改写原始结果。

过期说明直接修正或归档，不再叠加“顶部优先”保留冲突正文。自有历史文档可原位归档以保留既有路径，文件开头必须标明历史/非指令并指回权威入口；第三方与工具链文档不改成项目规范。归档中不保留会被自动加载的旧AGENTS.md。

`E:\xiaodan` 是 Windows Git 工作树与运行目录，Mac 端亦在各自 clone 根目录独立开发。私有配置、运行数据、`output/`、`logs/` 及 `LOCAL_FLASH_NOTES.md` 留在本机，仓库文档按相对路径或实际证据位置记录。

## 产品目标

- 本项目是一个**个人 Agent 硬件语音与电脑工作台**（AtomS3R + Echo Base + 网页工作台 + macOS/Windows `desktop_node`）：正常语音与文字对话，理解用户意图，按需调用联网/API、所选知识库与授权后的个人电脑操控（SoM 截图 + UI 树 + 确认卡片/3 分钟租约 + 语音/网页即时打断），用真实结果达成需求；简单、高效、快速。
- 只有一个助手，不做多助手系统，不为多助手预建实体或平台。跨会话长期画像、重型多 Agent 编排和无人值守后台任务不是当前范围。
- 助手配置围绕单个人格与工作档案统一组织，复用现有实时语音/文字与工具反馈循环，不新增每轮必走的规划模型请求，不因功能扩展随便切换已跑通的塔菲复刻音色与音频链。
- 当前设计见 [架构](agent/docs/architecture.md)，需求见 [PRD](agent/docs/prd.md)，执行依赖见 [roadmap](agent/docs/roadmap.md)。旧 M0–M5、固定 P0→P1→P2 顺序、920×720 弹窗/三页签、旧版“电脑控制先不做”及“个人知识库不纳入”等不再作为当前要求；历史事实见进度和决策记录。

## 动手与检查

1. 先读 [README](README.md)、[统一入口](agent/agent.md)、[START](agent/START.md) 和相关专题。依据实际代码、结果与最新用户要求判断，不机械照搬旧交接。
2. 不设计模拟 API、假数据、隔离测试后台、影子环境、冒烟/最小验证/分级验收流程，除非用户明确要求。直接在真实目标、代码和已授权环境完成工作。
3. 不为假想故障增加通用兜底、复杂状态机、自动供应商切换或额外审批门禁。必要鉴权、密钥保护、输入校验、并发一致性、取消与迟到结果隔离、数据保护继续保留。
4. 用实际结果验证，发现失败就修根因；不把测试数量、类型检查、截图、状态变绿或文档完整度当作主要交付。能独立做的检查由 AI 完成，用户集中负责讲话、听感、设备按键与物理场景等现场体验。
5. 区分“规划/未实现”“已有代码”“AI 实际运行确认”“用户现场确认”；未运行不能写通过，已有代码不能自动等于可用。网关首包不等于扬声器出声，HTTP 200 不自动等于业务办成。
6. 先理解用户想达到的效果，关键产品取舍主动沟通；实现与落地方式由负责人推进。已经授权的工作不为小步骤反复询问，重要行为变化或真正缺失信息再沟通。
7. 先参考官方资料和成熟项目的既有做法，再适配当前场景；不为省 Token 拦掉复合指令或省略追问，不靠堆提示词、批量付费探查或围绕单一假设反复消耗推进工作。

### 改动后验证选择

遵循全局规范的最小相关验证原则，改动对应模块后主动选跑下列已有检查与测试（不跑全量、不将测试通过等同于真机或真实上游可用；完整边界见 [acceptance](agent/docs/acceptance.md)）：

- **任何 `backend/`、`desktop_node/` 或 `tests/` Python 改动**：`.venv/bin/python scripts/lint_incremental.py`（Windows 用 `.venv\Scripts\python.exe`）。
- **跨平台桌面操控 / 确认闭环 / 语音与网页即时打断**（`desktop.py`、`desktop_tools.py`、`desktop_node/`、`tool_dialogue.py`、`main.py` 相关）：`.venv/bin/pytest tests/test_desktop_bridge.py -v`
- **个人知识库 / 多库检索 / 助手选库**（`personal_kb.py`、`tools.py`、`main.py` 相关）：`.venv/bin/pytest tests/test_personal_kb_isolation.py -v`
- **实时语音 / 设备桥接事件 / 语音打断**（`realtime.py`、`device_realtime.py`、`ack_cache.py`）：`.venv/bin/pytest tests/test_realtime_failures.py -v`
- **多厂商语音兼容 / 网关与轨迹审计**（`asr.py`、`tts.py`、`voice_profiles.py`、`tool_gateway.py`、`audit_store.py`）：`.venv/bin/pytest tests/test_voice_compat.py tests/test_gateway_trace.py -v`
- **音色复刻与音效**（`voices.py`、`audio_fx.py`、`qwen_voices.py`）：`.venv/bin/pytest tests/test_voices.py -v`
- **M5Stack 官方资料检索**（`knowledge.py`）：`.venv/bin/pytest tests/test_knowledge.py -k "not chat_uses and not retrieval_failure"`
- **网页语音流式回合**（`voice_chat.py`）：`.venv/bin/pytest tests/test_voice_chat.py -k "not voice_routes and not reset_invalidates and not http_disconnect"`
- **设备配对 / OTA / 控制回读**（`devices.py`）：`.venv/bin/pytest tests/test_devices.py`（仅测配置/鉴权可用 `-k "not real_socket"`；`test_device_audio.py` 与 `test_device_conversation.py` 依赖 Windows `.venv-speech` 及 `output/speech/` 样例，Mac 自动跳过）
- **前端 JS**（`backend/app/*.js`）：`node --check <修改的 JS 文件>`（修改 `voice.js` 且在 Windows 具备 Chrome/Playwright 时跑 `node tests/voice_browser.cjs`）
- **历史旧套件边界**：`test_api.py`、`test_api_configuration.py`、`test_tts.py`、`test_settings_workflow.py` 及上述 `-k` 排除用例含早期默认架构演进导致的历史失败；仅在改动对应设置/接口且用 `-k` 筛选相关用例时参考，不与本次改动混淆，也不擅自批量修改旧测试。

## 当前技术与数据边界

- **三端协作与版本同步**：**白天 Mac 开发、晚上 Windows 测试、服务部署在云端**，以 **Gitee（`https://gitee.com/ryan406/xiaoyuan.git`）** 作为国内高速同步与云端免密拉取主通道，Mac 本机 `origin` 配置一键双推同时同步至 GitHub（备份）与 Gitee。
  - **Mac 端**：负责日常功能开发、增量 Lint、JS 语法校验、Mac `desktop_node` 调试与无硬件/本地语音依赖的回归测试；推送 `git push origin main` 自动同步双端仓库。
  - **Windows 端**：项目根 `E:\xiaodan` 跟踪 `origin/main`，本机补丁用独立分支维护。更新时保留本地 `.env`、`data/` 及虚拟环境，负责本地音频、Windows `desktop_node` 与真机直连联调。
  - **云端（`47.112.16.195`）**：维护只读镜像仓 `/opt/xiaodan/repo`（零密钥 HTTPS 拉取 Gitee），通过 [release_from_git.sh](deploy/release_from_git.sh) 导出构建至 `/opt/xiaodan/releases/` 并挂载 `/opt/xiaodan/shared/{.env,data,logs}`、原子切换 `/opt/xiaodan/current`；**不在运行目录直接 `git pull`**，以免破坏软链或权限属主。
- 技术栈为 FastAPI + 原生 HTML/CSS/JavaScript + SQLite；实时主线为百炼 **`qwen-audio-3.1-realtime-flash`**（顶层 `voice`、24k/16k `pcm`、`fun-asr` 转写、百炼原生 `enable_search` 合并联网与天气搜索、`output_text` 多轮助手历史），同时兼容 OpenAI Realtime 与显式分模型 Pipeline；电脑操控支持百炼原生视觉模型（`qwen3.8-max-0902`、`qwen3.5-plus` 等）。
- 已有百炼 `voice-enrollment` 塔菲复刻音色、语速/音调处理、正式回答首句开场与基础交流继续保留，各 `(mode, provider, model)` 作用域音色与业务选用状态存入 `assistant_state.sqlite3`（不覆盖切换前配置）；改动已跑通/用户确认的功能前先说明并取得相应同意。当前实现和证据以 [progress](agent/docs/progress.md) 为准。
- 写操作（含 `desktop_open`/`desktop_gui_action`/`desktop_set_clipboard`/`desktop_run_command` 及外部写工具）走统一确认闭环（卡片确认或 3 分钟租约，语音与网页端均支持即时喊停并撤回租约与关闭桌端悬浮 HUD）；凭证文件（`.env`、`.ssh`、私钥、Keychains）禁止读取。
- 保留原配置、历史、知识库原文/索引、音色与录音样本；设置保存不得清空对话。完整文字历史与有限活跃上下文分离，不长期保存对话录音。
- API 地址、模型 ID、参数及工具支持查官方资料，不猜。密钥只存服务端私有配置，不发模型、不入固件/示例/Git，不在日志或群聊回显。
- 云端2核约1.87GB已部署，Mac 电脑操控及云端公网访问已实际验证；网页按用户要求免登录，保留 HTTPS/WSS、独立设备鉴权、内部代理凭据、同源保护与公网屏蔽桌面节点管理接口。每日独立备份仍待实施，真机在新实时模型下的语音打断操控待实测，云端随机卡顿暂缓。
- 设备打开串口/RTS曾导致复位及下载模式，不把串口读取当成必然无副作用；不擅自刷写固件或变更设备 OTA 地址。

## 协作与操作

- 主 Bot 负责目标、派工、文件归属、集成和运行调度；同一文件同时只有一个修改负责人。开发用多个 Bot 不代表产品提供多个助手。
- 服务启动/重启、设备、数据库迁移及付费调用由主 Bot 按授权统一调度；先检查已有实例。并行仅用于互不争抢的工作，数据/编译任务按实际资源串行。
- 不擅自 commit/push/部署、烧录固件、改设备地址、安装/下载或操作远端。已有密钥不等于允许无限批量调用。本轮文档同步以外的动作仍须按任务授权执行，也不要求已授权的常规动作重新逐项审批。
- 下载/安装一旦获得授权，下载、模型、安装包、缓存和语音环境放在项目内，并显式设置项目内 TEMP/TMP/PIP_CACHE_DIR/HF_HOME/TORCH_HOME，不使用 C 盘下载目录。
- 沿用现有 Codex 灰阶明暗主题与暖琥珀金强调色，不另选配色。沿用 [agent](agent/agent.md) 文档体系，不建平行 PRD/计划/报告；只更新有效信息，过期要求直接修正，历史证据标历史并保留。
- 默认中文、简短直白、先结论。汇报改了什么、实际结果和剩余阻塞，不堆术语，不要求用户替 AI 判断接口是否接通。
