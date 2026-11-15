# 代码结构与扩展位置

> **当前口径（2026-11-08）**：下文的目录树是 2026-10 的历史基线，**缺实时语音与工具链模块**。当前实际关键模块（现状）：
> - 实时语音：`realtime.py`（`RealtimeTurn`，百炼实时会话、工具循环、续答）、`realtime_text.py`、`conversation.py`、`voice_chat.py`、`device_realtime.py`（设备播放/预缓冲/出站指标/取消）、`voice_transport.py`（设备协议与音频传输）、`audio_fx.py`（rate/pitch）、`audio_metrics.py`（只读音频计量）。
> - 提示与朗读：`prompt_builder.py`（`build_system_prompt`，实时/文字共用）、`prompt_context.py`（实时时间/诚实规则）、`speech_text.py`（朗读规范化）。
> - 工具与知识库：`tools.py`（工具注册/执行）、`tool_dialogue.py`（控制计划/多轮上限 `MAX_TOOL_ROUNDS=4`）、`personal_kb.py`（个人知识库，多库规划中）、`knowledge.py`（M5Stack 只读检索）、`weather.py`（天气查询工具）。
> - 其他：`community.py`（移植的 Opus/节奏/abort）、`ack_audio.py`（口癖缓存，已停用改正式首句）、`device_realtime.py` 的 `stream_epoch`/`pending_audio` 负责取消与迟到隔离。
> 新增能力在此增量扩展，不重写已跑通的实时音频链。

本次不移动、改名或拆分现有代码。业务入口仍是根目录原有路径；本目录只统一规范。

```text
backend/
  app/
    main.py             管理HTTP、页面入口、依赖组装和本机访问保护
    config.py           环境/私有配置和默认值
    settings_store.py   设置校验、原子保存、对外脱敏
    llm.py              ChatProvider接口、兼容API适配、已核实模型列表与统一错误
    tts.py              MiMo TTS HTTP/JSON合成、WAV解码校验，仅返回临时试听字节
    service.py          会话、最近上下文、模型请求、历史和用量协调
    history_store.py    SQLite完整会话快照
    schemas.py          请求、响应、历史与用量模型
    knowledge.py        M5Stack只读资料适配
    devices.py          单设备配对、OTA、WebSocket、MCP控制与状态
    app.html            工作区与SVG图标
    app.css             明暗主题和响应式布局
    app.js              原生页面状态与交互
  run_devices.py        同进程启动回环管理与独立设备入口
scripts/
  chat.py               文字HTTP命令行入口
  speech.py             模型下载与离线试听工具，尚非语音服务
tests/
  test_api.py           模型、配置、会话、用量与历史行为
  test_devices.py       身份、入口隔离、真实socket模拟控制与读回
  test_knowledge.py     官方检索、schema、只读边界与来源处理
data/                   私有SQLite与设备凭据，不作为源码
models/                 模型及下载包
output/                 样例与验证产物
.cache/                 项目内临时文件和下载缓存
.venv/                  网页与设备服务环境
.venv-speech/           独立本地语音环境
agent/                  当前规范、PRD、资源、进度与计划
```

## 后续新增的落点建议

- **单助手沿用现有 `SettingsStore`（不新增 `assistants` 表）**；多独立知识库需新增库归属字段（`kb_libraries` + 文档 `library_id`，检索按库硬过滤），为规划、需停机窗口，未实现。
- 模型供应商差异在llm适配器内处理，不进入页面或设备协议；只有已核实的参数才新增配置字段。
- 语音适配在 `backend/app/` 下按实际复杂度增加独立模块；先一套ASR/TTS与必要协调，不提前生成大量空目录或抽象基类。
- 设备音频与Opus编解码独立于ChatService业务输入；识别文字进入现有ChatRequest/服务层，最终schema调整配套最小测试。
- voice-studio保持独立云服务，通过已核实API适配；不把其字幕、翻译、合并页面复制进本仓库。
- 插件在V1之后依据首个真实能力确定目录和协议；当前不创建空插件系统，不实现市场、分发或远程代码安装。
- 云端部署配置须在确认认证/路由/数据位置后单独编写；现有本机启动脚本不是公网部署方案。

Python和语音环境、原始模型、生成样例与私有运行数据继续各自隔离。新资产位置见 [资源规范](../design/assets.md)，不因统一文档而迁移大文件。

## 当前完整目录与各文件职责（2026-11-11）

### 顶层目录

| 目录/文件 | 内容与职责 |
|---|---|
| `agent/` | 项目规范与文档中心：入口、当前工作、目标、路线、进度、决策、架构、验收、运维等 |
| `backend/` | 后端服务：FastAPI 管理端 + 小智兼容设备网关；`backend/app/` 为各业务模块，`run_devices.py` 为启动入口 |
| `data/` | 运行数据：会话历史 `conversations.sqlite3`、个人知识库 `personal_kb.sqlite3`、设备配对 `devices.json`、工具 `tools.json`、音色 `voices.json`/`qwen_voices.json` |
| `deploy/` | 云端部署：`xiaodan.service`、`assistant.caddy`/`caddy-access.conf`（反代与鉴权）、`access.env.example` |
| `firmware/` | 固件工程与工具链：`xiaozhi-esp32/` 主固件、`esp-idf*/` 工具链、`build-*` 构建目录、`backup/` 出厂整片备份、构建脚本 |
| `logs/` | 服务运行日志 |
| `models/` | 本地模型与素材：`asr/`（识别）、`tts/`、`voice/`（克隆音色样本）、`codecs/`、`downloads/` |
| `output/` | 证据与产物：回归 JSON、报告 Markdown、UI 草稿/截图、测试脚本 |
| `scripts/` | 辅助脚本：本地识别、应答音生成、资料迁移、语音合成等 |
| `tests/` | 自动化测试：`test_*.py` + `voice_browser.cjs` |
| `third_party/` | 第三方参考：`xiaozhi-server/`（`community.py` 挂载） |
| `.env` / `.env.example` | 私有配置（密钥/供应商/连接）与示例；密钥不进群 |
| `AGENTS.md` / `README.md` | 协作规范 / 项目说明与启动 |
| `requirements*.txt` / `start.ps1` / `setup-speech.ps1` / `pytest.ini` | 依赖与启动/测试配置 |

### 后端模块（`backend/app/`）

| 文件 | 功能 |
|---|---|
| `main.py` | 管理端 FastAPI 应用与全部路由（设置/对话/工具/知识库/洞察/语音），对外 8000 |
| `run_devices.py` | 启动入口：同时启动管理端 8000 与设备网关 8003 |
| `config.py` | 配置读取、根目录、供应商与密钥、校验 |
| `settings_store.py` | 设置持久化（提示词、API 连接、助手选用 API/库、音色、音量），原子写 |
| `schemas.py` | 请求/响应数据结构与字段校验 |
| `service.py` | 对话业务流程编排（一次请求 → 模型 → 工具 → 回答 → 历史） |
| `conversation.py` | 设备对话回路（识别文本 → 模型 → 语音回放，按协议下发 tts/句子/音频/停止） |
| `device_turn.py` | 设备端流式对话管线（边生成边按句合成，缩短首音） |
| `device_realtime.py` | 设备端实时语音（实时模型/opus）回合 |
| `devices.py` | 小智设备网关：OTA 引导、WebSocket 鉴权握手、连接与设备控制 |
| `realtime.py` / `realtime_text.py` | 实时模型 WebSocket 会话（语音/文字） |
| `voice_chat.py` / `voice_transport.py` | 浏览器语音对话（按住说话，返回文字与语音）及传输 |
| `llm.py` | 大模型客户端封装与错误类型 |
| `prompt_builder.py` / `prompt_context.py` | 系统提示构建（角色+内置规则+当前时间上下文） |
| `tools.py` | 工具注册与执行（天气/M5/个人库/自定义 API/设备控制），按助手选择过滤 |
| `tool_dialogue.py` | 工具调用循环（模型→工具→真实结果→续答），含订单确认执行拦截 |
| `order_confirmation.py` | 订单编号跨轮确认状态（复述/确认/否认/更正、按会话隔离） |
| `api_requests.py` | 自定义 API 请求执行与安全校验 |
| `weather.py` | Open-Meteo 天气客户端（实况+多日、中文、缓存） |
| `knowledge.py` | M5Stack 官方资料只读检索 |
| `personal_kb.py` | 个人知识库（上传解析分片、索引、按库检索、原文/片段） |
| `embeddings.py` | 云端向量调用 + 本地余弦/RRF |
| `tts.py` | 语音合成封装（分句合成、返回音频） |
| `voices.py` / `qwen_voices.py` | 复刻音色保存/处理/查询、百炼复刻音色 |
| `audio_fx.py` | 合成音频后处理（音量/语速/音调） |
| `ack_audio.py` | 中性应答/确认音的本地音频派生 |
| `audio_metrics.py` | 音频被动计量（不缓存内容） |
| `speech_bridge.py` | 网关到本地流式识别 worker 的桥（stdin/stdout 转发帧） |
| `speech_text.py` | 语音朗读文本规范化（符号/日期/百分比/小数口语化） |
| `history_store.py` | 会话历史 SQLite 原子快照 |
| `audit_store.py` | 审计（知识库/工具调用）记录 |
| `community.py` | 挂载 `third_party/xiaozhi-server` 参考实现路径 |
| `app.html` / `app.js` / `app.css` | 管理页前端（设置、设备、知识库等） |
| `voice.js` / `voice-capture.js` | 网页语音采集与播放 |

### 固件工程（`firmware/xiaozhi-esp32/`）

| 位置 | 内容 |
|---|---|
| `main/application.cc` | 应用状态机与语音主流程（唤醒/聆听/说话/打断状态切换） |
| `main/boards/atoms3r-echo-base/config.h` | 本板硬件定义（显示屏尺寸/偏移/镜像、音频 I2S/编解码引脚、按键） |
| `main/boards/atoms3r-echo-base/atoms3r_echo_base.cc` | 本板显示与音频初始化；显示驱动（ST7735 用 st7789 驱动 + 反相 + gap(2,1)）、像素 UI 与帧动画类 |
| `main/display/` | LVGL 显示基类（两套 SetupUI、emoji、gif） |
| `main/assets/` | 资产与主题加载（含自定义表情集合） |
| `main/audio/` | 音频编解码、AFE（唤醒/VAD）、ESP-SR |
| `partitions/v2/8m_tafei_mn5.csv` | 自定义分区表（app/ota/assets） |
| `sdkconfig.tafei-mn5*` | 本板构建配置（板型、8MB、唤醒词、模型） |
| `build-*` | 各构建产物；当前在用 `build-tafei-mn5-ui-anim` |
| `firmware/backup/` | 出厂整片备份（8MB，可恢复） |

### 文档与设计（`agent/`）

| 文件 | 内容 |
|---|---|
| `agent.md` / `START.md` / `STATUS.md` | 统一入口与协作角色 / 当前工作入口 / 规范基线状态 |
| `docs/goals.md` / `docs/roadmap.md` / `docs/prd.md` | 目标与边界 / 功能与实施路线 / 产品需求 |
| `docs/architecture.md` / `docs/decisions.md` / `docs/acceptance.md` | 架构 / 决策记录 / 验收标准 |
| `docs/operations.md` / `docs/references.md` / `docs/resources.md` | 运行运维 / 参考资料 / 资源清单 |
| `docs/knowledge-base-design.md` / `docs/voice-cloning.md` | 知识库设计 / 音色复刻 |
| `docs/handoff.md` / `docs/progress.md` / `docs/audience.md` | 交接 / 进度与证据（最详细） / 受众 |
| `design/*` | UI 设计：概览、布局、组件、设计变量、资产、命名 |
| `code/*` | 代码规范与结构（含本文件） |
