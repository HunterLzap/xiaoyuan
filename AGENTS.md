# 工作约定

更新：2026-11-16。用户最新明确目标优先于旧文；实现不得缩减目标，也不得自行扩大目标。当前任务、版本和暂停事项先读 [START](agent/START.md)，不默认载入全部历史。

## 文档唯一来源与阅读顺序

本文件是唯一总入口。新Agent依次读本文件→[START](agent/START.md)→任务相关专题；只有需要追溯证据时检索progress或归档，不默认读取全部报告。

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

`E:\xiaodan` 同时是 Windows Git 工作树与本机运行目录。私有配置、运行数据、`output/`、`logs/` 及 `LOCAL_FLASH_NOTES.md` 留在本机，仓库文档链接实际证据位置。

## 产品目标

- 本项目是一个硬件语音助手（AtomS3R + Echo Base）：正常对话，能理解用户想做什么，按需调用 API 和所选知识库，用真实结果达成需求；简单、高效、快速。
- 只有一个助手，不做多助手系统，不为多助手预建实体或平台。长期记忆、复杂规划器、无人值守任务、电脑控制不是当前范围。
- 助手配置集中放提示词、选用的 API 能力和选用的知识库；API 能力统一管理天气、M5Stack 官方资料和自定义 API；知识库按用户参考图做多独立库。资源“启用/停用”与助手“选入”不能混淆。
- 复用现有实时语音和工具反馈循环，不新增每轮必走的规划模型请求，不因 Agent 改造切换音色或改写已跑通的音频链。
- 当前设计见 [架构](agent/docs/architecture.md)，需求见 [PRD](agent/docs/prd.md)，执行依赖见 [roadmap](agent/docs/roadmap.md)。旧 M0–M5、固定 P0→P1→P2 顺序、920×720 弹窗/三页签及“个人知识库不纳入”等不再作为当前要求；历史事实见进度和决策记录。

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

- **任何 `backend/` 或 `tests/` Python 改动**：`.venv/bin/python scripts/lint_incremental.py`（Windows 用 `.venv\Scripts\python.exe`）。
- **个人知识库 / 多库检索 / 助手选库**（`personal_kb.py`、`tools.py`、`main.py` 相关）：`.venv/bin/pytest tests/test_personal_kb_isolation.py -v`
- **实时语音 / 设备桥接事件**（`realtime.py`、`device_realtime.py`）：`.venv/bin/pytest tests/test_realtime_failures.py -v`
- **多厂商语音兼容 / 网关与追踪**（`asr.py`、`tts.py`、`voice_profiles.py`、`tool_gateway.py`、`audit_store.py`）：`.venv/bin/pytest tests/test_voice_compat.py tests/test_gateway_trace.py -v`
- **音色复刻与音效**（`voices.py`、`audio_fx.py`）：`.venv/bin/pytest tests/test_voices.py -v`
- **M5Stack 官方资料检索**（`knowledge.py`）：`.venv/bin/pytest tests/test_knowledge.py -k "not chat_uses and not retrieval_failure"`
- **网页语音流式回合**（`voice_chat.py`）：`.venv/bin/pytest tests/test_voice_chat.py -k "not voice_routes and not reset_invalidates and not http_disconnect"`
- **设备配对 / OTA / 控制回读**（`devices.py`）：`.venv/bin/pytest tests/test_devices.py`（仅测配置/鉴权可用 `-k "not real_socket"`；`test_device_audio.py` 与 `test_device_conversation.py` 依赖 Windows `.venv-speech` 及 `output/speech/` 样例，Mac 自动跳过）
- **前端 JS**（`backend/app/*.js`）：`node --check <修改的 JS 文件>`（修改 `voice.js` 且在 Windows 具备 Chrome/Playwright 时跑 `node tests/voice_browser.cjs`）
- **历史旧套件边界**：`test_api.py`、`test_api_configuration.py`、`test_tts.py`、`test_settings_workflow.py` 及上述 `-k` 排除用例含默认 `voice_mode="realtime"` 等演进导致的历史失败；仅在改动对应设置/接口且用 `-k` 筛选相关用例时参考，不与本次改动混淆，也不擅自批量修改旧测试。

<!-- slopguard:start -->
## SlopGuard 质量门禁契约
- 每次代码改动结束前，必须运行 `slopguard verify` 直到退出码为 `0`。
- 修复 Bug 时，必须补充复现测试并运行 `slopguard verify --ablation`，确保通过 `RED -> GREEN` 消融验证。
- 严禁使用 `git commit --no-verify` 绕过 `pre-commit` 门禁。
- 严禁通过新增抑制注释（`# type: ignore`、`# noqa`、`@ts-ignore`、`eslint-disable`）或堆叠症状兜底来敷衍门禁；遇到 `probe:*` 告警时，按 `action_hint` 做最小根因修复或沉淀为可执行测试/Lint 规则后删掉注释。
<!-- slopguard:end -->

## 当前技术与数据边界

- **三端协作与版本同步**：**白天 Mac 开发、晚上 Windows 测试、服务部署在云端**，以 **Gitee（`https://gitee.com/ryan406/xiaoyuan.git`）** 作为国内高速同步与云端免密拉取主通道，Mac 本机 `origin` 配置一键双推同时同步至 GitHub（备份）与 Gitee。
  - **Mac 端**：负责日常功能开发、增量 Lint、JS 语法校验与无本地语音模型/无真机依赖的路由与单元测试；推送 `git push origin main` 自动同步双端仓库。
  - **Windows 端**：项目根直接关联 GitHub，`main` 跟踪 `origin/main`，本机补丁用独立分支维护。更新时保留本地 `.env`、`data/` 及虚拟环境，负责本地音频、浏览器实操和真机直连联调。
  - **云端（`47.112.16.195`）**：安装 Git 后维护公开只读镜像仓 `/opt/xiaodan/repo`（零密钥 HTTPS 拉取 Gitee），通过 [release_from_git.sh](deploy/release_from_git.sh) 导出构建至 `/opt/xiaodan/releases/` 并挂载 `/opt/xiaodan/shared/{.env,data,logs}`、原子切换 `/opt/xiaodan/current`；**不在运行目录直接 `git pull`**，以免破坏软链或权限属主。
- 技术栈为 FastAPI + 原生 HTML/CSS/JavaScript + SQLite；主线支持百炼 `qwen3.8-omni-flash-realtime` 与 OpenAI 兼容 Realtime，同时支持可切换的分模型 Pipeline（LLM + 在线/可选本地 ASR + MiMo/OpenAI/百炼 TTS）。
- 已有塔菲复刻音色、语速/音调处理、正式回答首句开场与基础交流继续保留，各 `(mode, provider, model)` 作用域音色与业务选用状态存入 `assistant_state.sqlite3`（不覆盖切换前配置）；改动已跑通/用户确认的功能前先说明并取得相应同意。当前实现和证据以 [progress](agent/docs/progress.md) 为准。
- 多库与助手能力选择已实现并完成部分真实验证，确切范围看 progress；不能将文字/资料操作通过写成所有语音链通过。外部写/发送/删除/付费工具没有完整对话确认时，不得自动放行。已明确开放的本地设备/声音控制按现有规则执行。
- 保留原配置、历史、知识库原文/索引、音色与录音样本；设置保存不得清空对话。完整文字历史与有限活跃上下文分离，不长期保存对话录音。
- API 地址、模型 ID、参数及工具支持查官方资料，不猜。密钥只存服务端私有配置，不发模型、不入固件/示例/Git，不在日志或群聊回显。
- 云端2核约1.87GB已部署，设备已切云并完成真实语音问答；云端随机卡顿仍在，用户明确暂缓解决。网页按用户要求免登录，不擅自加回账号密码；HTTPS/WSS、独立设备鉴权、内部代理凭据与同源保护保留。每日独立备份仍待实施，不能写成已交付。
- Windows 项目根为 `E:\xiaodan`，云端程序在 `/opt/xiaodan/current`。Git 开发快照与云端发布分别管理，部署和刷写按任务授权执行。当前版本与声音参数见 START 及原始证据。
- 不以旧上游板级AEC说明否定项目后来已有的播放参考/AEC实现；也不以 `aec=true` 或网关发完证明所有打断/播放场景通过。设备打开串口/RTS曾导致复位及下载模式，不把串口读取当成必然无副作用。

## 协作与操作

- 主 Bot 负责目标、派工、文件归属、集成和运行调度；同一文件同时只有一个修改负责人。开发用多个 Bot 不代表产品提供多个助手。
- 服务启动/重启、设备、数据库迁移及付费调用由主 Bot 按授权统一调度；先检查已有实例。并行仅用于互不争抢的工作，数据/编译任务按实际资源串行。
- 不擅自 commit/push/部署、烧录固件、改设备地址、安装/下载或操作远端。已有密钥不等于允许无限批量调用。本轮文档同步不自动授权这些操作，也不要求已授权的常规动作重新逐项审批。
- 下载/安装一旦获得授权，下载、模型、安装包、缓存和语音环境放在项目内，并显式设置项目内 TEMP/TMP/PIP_CACHE_DIR/HF_HOME/TORCH_HOME，不使用 C 盘下载目录。
- 沿用现有 Codex 灰阶明暗主题，不另选配色。沿用 [agent](agent/agent.md) 文档体系，不建平行 PRD/计划/报告；只更新有效信息，过期要求直接修正，历史证据标历史并保留。
- 默认中文、简短直白、先结论。汇报改了什么、实际结果和剩余阻塞，不堆术语，不要求用户替 AI 判断接口是否接通。
