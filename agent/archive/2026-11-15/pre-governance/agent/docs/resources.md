# 已有资源与复用清单

> **当前口径（2026-11-08）**：资源服务于**一个硬件语音助手**（正常对话 + 按需调 API/知识库，简单快）。**当前实时主线是百炼 `qwen3.8-omni-flash-realtime`，音色为百炼塔菲复刻（`AI_RT_VOICE`）**；下文 MiMo / Kokoro / voice-studio 等为**分模型或历史候选**，不属于实时主线，未验收不写成可用。个人知识库按**多库**规划（新增库归属、检索服务端硬过滤，未实现）；M5Stack 官方只读检索是独立能力，不等于个人知识库。

## 本轮接入资源与已安装依赖（2026-10-30，历史）

- 用户已明确确认本批源码/VAD 下载及无用下载资源清理；安装仍须单独确认。固定提交 `1a095d5bed23e49a17f817c7f378e2a86f298dfc` 的按需源码、VAD 与 MIT LICENSE 已保存于 `E:\xiaodan\third_party\xiaozhi-server\`，原始本批共 2,700,941 字节；后续已裁掉未使用的管理/记忆/声纹等代码。没有下载 Java 管理台、MySQL、Redis、插件平台或其他模型引擎。源码移植差异记在该目录 NOTICE.md。
- VAD 使用同一提交的默认 `models/snakers4_silero-vad/src/silero_vad/data/silero_vad.onnx`，2,327,524 字节。现有 `models/asr/vad/silero_vad.int8.onnx` 为另一份 212,860 字节模型，不能仅改路径便认定输入与状态接口兼容。上游全部 core/config 源码共 4,275,474 字节，实际仅取需要的部分；连同默认 VAD 的物料上界约 6.6 MB，许可另计。
- 已按用户确认安装到既有 `E:\xiaodan\.venv-speech`：`onnxruntime==1.31.1`、`flatbuffers==25.12.19`、`packaging==26.3`、`protobuf==7.36.2`。实际轮子约 15.5 MB；已有 numpy 2.5.4 未升级，`pip check` 无损坏依赖。版本在 requirements-speech.txt。
- 安装时必须显式指定 `TEMP/TMP=E:\xiaodan\.cache\xiaozhi\tmp`、`PIP_CACHE_DIR=E:\xiaodan\.cache\pip`、`HF_HOME=E:\xiaodan\.cache\huggingface`、`TORCH_HOME=E:\xiaodan\.cache\torch`。不安装上游完整 requirements，不创建额外环境。
- 本机现有 `.venv-speech` 已有 numpy、av、opuslib-next、sherpa-onnx，且 `models/codecs/opus.dll` 已存在；`.venv` 尚无这些音频依赖，也没有 onnxruntime。保留已有环境和模型，不重复下载。
- 服务器适配补充：官方元数据确认 NumPy 2.5.4、PyAV 19.0.1 要求 Python >=3.12；requirements-speech.txt 的 Python 3.11 分支改用 NumPy 2.3.5 / PyAV 18.0.0（有 Linux x86_64 轮子），本机原版本保持，不下载或安装新包。跨平台 worker、公网地址和 Caddy/systemd 模板在本地代码中，不代表 Linux、Caddy 或2GB资源已运行通过。
- 清理盘点：Kokoro 仅供旧离线试听，约 181.09 MiB；SenseVoice、Opus、已有音色仍被正式路径引用。Kokoro 与缓存/旧产物的批量递归删除被自动审批拒绝，收窄至 Kokoro 明确目录后仍为 `blocked by policy`，因此均尚未清理；没有更换工具绕过。旧 int8 VAD 已不进入 VAD 路径，但新核心完整真实回合尚未接管；三个旧编排源文件同理，暂留待删。

2026-10-30最新状态：远端SSH已只读连通。遵守最新“禁止防御性测试与过度设计”指令，原社区隔离环境、假Provider、模拟SSE、测试库与测试物料计划已撤销，未执行下载安装。后续依真实接入需要列出源码、依赖、目标目录和安装内容，下载/安装仍先确认；不在远端写文档或修改旧voice-studio。

社区评估固定提交为 `1a095d5bed23e49a17f817c7f378e2a86f298dfc`。此前完成82模块静态读取与依赖梳理，但未安装或运行社区核心；旧候选依赖不作为当前安装要求。不装全量Java/MySQL/Redis，不在Windows安装Linux环境替代远端资源事实。真实MiMo调用和新核心的2核2GB资源占用均未实际运行。

盘点日期：2026-10-16。以下来自此前会话的代码/文件核对、资源盘点和历史行为验证；2026-10-17补充API配置闭环的隔离验证，未探测云服务器、合成语音或调用真实账户API。不记录凭据或私人聊天内容。

## 1. 资源总表

| 资源 | 位置或来源 | 已有证据 | 整合结论 |
| --- | --- | --- | --- |
| 文字聊天核心 | `backend/app/service.py`、`llm.py`、`schemas.py` | 此前只读核对；已有模拟上游测试 | 优先复用为网页与设备语音共用核心；真实账户仍待验收 |
| 在线MiMo TTS | `tts.py`、原设置页语音子页 | 独立配置与两种模型草稿WAV试听隔离通过 | **分模型/文本 TTS 候选；实时主线不走 MiMo**。真实合成听感/计费未验收，不接实时设备，不下载权重 |
| 模型配置 | `config.py`、`settings_store.py`、设置页 | 原子保存、密钥脱敏、草稿测试、模型列表/手填与环境变量优先；本轮配置闭环隔离验证通过 | 保留供应商可替换；不猜模型 ID、参数或价格 |
| 会话与历史 | `history_store.py`、`data/conversations.sqlite3` | SQLite快照存在，但启动全量加载、旧max_sessions限制与长期历史冲突；未读取私人记录 | 复用，历史 M4 曾计划改按需历史与有界活跃上下文；迁移前备份，不另建语音历史库 |
| 网页工作区 | `backend/app/app.html`、`app.css`、`app.js` | 此前核对灰阶明暗变量及页面结构 | 保留，按现有界面增加缺失状态与声音设置 |
| 设备网关 | `devices.py`、`device_realtime.py`、`backend/run_devices.py` | 已接 Opus/VAD/SenseVoice 与百炼实时语音，基础设备对话用户已确认可交流 | 复用OTA发现、鉴权和MCP控制；实机完整语音回合端到端（含打断听感）仍待确认 |
| 官方资料检索 | `knowledge.py`、`tests/test_knowledge.py` | 历史已验证官方只读检索；此前核对调用规则 | 保留为独立辅助能力，不扩大为个人知识库 |
| 本地 TTS | `models/tts/kokoro/`、`.venv-speech/`、`scripts/speech.py` | 历史离线输出三份WAV；此前复核文件与度量 | 保留为离线候选与对照，不认为已接入设备或能满足实时延迟 |
| 云端语音站 | 云服务器 `/opt/voice-studio` | 此前只读查代码、端口与健康接口 | 评估复用接口与语音适配；实际合成和服务保障仍待测 |
| 原小智平台 | 现有设备与账号 | 历史控制台检查；固件 2.2.6 | 保留原绑定及恢复路径，暂不烧录、不解绑、不迁移历史 |

## 2. Windows 本地语音资源

目录：模型 `models/tts/kokoro/kokoro-int8-multi-lang-v1_0/`；下载包 `models/downloads/`；试听 `output/speech/`；独立环境 `.venv-speech/`；缓存 `.cache/speech/`。

- 下载包 132,303,094 字节；`model.int8.onnx` 114,203,756 字节，`voices.bin` 28,200,960 字节。已有模型及其配套资源无需重复下载。
- 历史使用 sherpa-onnx 1.13.8、numpy 2.5.4；依赖见 `requirements-speech.txt`，不并入网页服务的 `.venv`。
- 量化包包含 53 个说话人，中文候选 45–52：xiaobei、xiaoni、xiaoxiao、xiaoyi、yunjian、yunxi、yunxia、yunyang。这些是 Kokoro 标签，不等于小智或微软同名音色。
- 历史核对 Kokoro 权重及该包 LICENSE 为 Apache-2.0，配套第三方资源单独保留；引用模型必须复核实际随包许可。

| 已有样例 | 音频时长 | 合成耗时 | RTF |
| --- | --- | --- | --- |
| `kokoro-xiaobei-1x.wav` | 8.626 秒 | 11.307 秒 | 1.311 |
| `kokoro-yunxi-1x.wav` | 6.639 秒 | 9.733 秒 | 1.466 |
| `kokoro-xiaobei-1.2x.wav` | 7.352 秒 | 9.736 秒 | 1.324 |

历史条件：CPU 4线程、PCM16 单声道 24kHz；加载约1.63–1.75秒，另计。历史检查覆盖非空、非静音、有限数值及WAV帧数；人工听感未验收。此前文档整理只复核样例和JSON度量，没有重新合成。整段生成慢于播放时长，不能当作低延迟闭环。

Windows 硬件历史盘点为 Ryzen 7 7735H、约15.2GiB可见内存、RTX4060 Laptop约8GB显存。未确认适用 CUDA/cuDNN，不以显卡存在推导 GPU 语音已经可用。

ASR尚未选定或完成样例。现已接受在线ASR，云端独立运行不依赖Windows识别模型。SenseVoiceSmall、faster-whisper仅为历史候选；MeloTTS Chinese未下载，Piper华严历史许可不明确。现有Kokoro保留本地对照，不默认部署到2GB云服务器。

## 3. 云服务器与 voice-studio

- 用户提供：2核、2GB内存、40GB存储；只读检查：Alibaba Cloud Linux 3，系统可见内存1870MiB，当时可用1405MiB；根盘约5.3GB已用、32GB可用。只是一次快照，不是并发容量或长期稳定性承诺。
- `/opt/voice-studio/backend` 运行 Python3.11/FastAPI；另有 Caddy，监听80/443；语音站后端监听8000，Caddy管理端口在回环地址。本项目的 Windows 8000 与云上8000是不同机器；同机部署时必须避开现有占用。
- 已看到 `/api/health`、`/api/voices`、`/api/synthesize`、自定义供应商测试/音色接口以及字幕、合并、翻译相关接口。健康接口返回 `ok`，列出 `edge-tts`、`api` 引擎。
- 已核对 edge-tts 实际连接 `speech.platform.bing.com`。它是在线语音访问，不是服务器本地部署了大型声音模型。
- 尚未验证实际合成、输出格式与机器人兼容性、调用鉴权、限流、稳定性或自定义 API 账户是否可用；未看到已可复用的 ASR 能力。
- 复用原则：优先评估现有语音 API 作为独立服务，不复制整套字幕/翻译产品进入机器人平台；不修改原站监听、域名、证书、数据或工作进程来腾资源。
- 本次不在云端安装、下载或部署。未来Linux安装目录与磁盘配额需另行明确并获操作授权，不能套用Windows路径或绕过现行下载约束；这不是新增消费预算审批。

## 4. 模型与 API 资源

文字兼容适配器使用 OpenAI Chat Completions；**实时语音走百炼 realtime WebSocket**（`realtime.py`），实时与文本路径均已实现工具调用循环（接口级）。真实付费调用与实机端到端听感未确认。SDK 自动重试关闭。

TokenDance是用户提供的现用资源线索。历史核对日期2026-10-14的示例Base URL为 `https://tokendance.space/gateway/v1`，不是已确认的MiMo TTS调用地址；账户配置、实际调用、准确协议和模型标识仍未验收。平台模型显示名不能自动作为API ID，文字模型与TTS不得共用一个未经核实的请求schema。

### MiMo-V2.5-TTS：2026-10-16新增线索

- 用户确认TokenDance目前有MiMo-V2.5-TTS可以免费调用，列为第一版优先验证的在线TTS候选；API由用户配置，费用自行管理。
- 此前查到[小米官方模型说明](https://mimo.xiaomi.com/mimo-v2-5-tts)，确认这是语音合成系列，官方页面称其自有MiMo平台限时免费；该信息不能直接证明TokenDance账户当日费率、额度或准确请求协议，本次未重新核价。
- [TokenDance模型页](https://tokendance.space/models/mimo-v2.5-tts)此前未能通过检索工具读取正文；免费描述按用户提供信息记录，不伪称已实测或已读该平台接口说明。
- 获得开发授权后核对平台实际模型ID、端点、鉴权、音色字段、输出格式、是否流式及实际延迟；再决定直接API适配还是复用voice-studio的自定义API能力，不安装新SDK或提前调用。
- TTS只负责把回复变成声音，ASR识别仍需单独选型；不额外加入音色设计、声音克隆等未要求功能。

模型资源登记至少包含供应商、协议、已核实地址、准确模型ID、支持参数、核对日期、真实调用结果与数据范围；价格仅在用户配置或官方已明确时记录，未知可留空，不阻塞工程计划。文档只记密钥保存方式，不记密钥值；不承诺限时免费永久延续。

已有 Token/费用记录区分未知用量、未知价格及未能估算的调用；草稿测试独立记录，不作为聊天统计或账单余额。不要为了做出总费用而补造缺失数据。

## 5. 数据、环境与复用去留

| 类别 | 处理方式 |
| --- | --- |
| `.venv`、现有 Python/前端模块与测试 | 原位保留，授权开发后做最小验证；不整体重装重写 |
| SQLite、`data/devices.json`、可能存在的 `.env` | 私有运行数据；不读取正文或凭据进入文档，迁移前按停写或一致性备份方案保护 |
| 现有 Kokoro 与三份试听 | 保留为候选和对照；不自动上传云端、不认定为 V1 必选 |
| voice-studio | 独立现有服务，评估接口复用；不将健康检查当合成通过 |
| M5Stack 检索、用量统计 | 接口与聊天内呈现保留，界面无独立页面；不扩大第一版交付范围 |
| 旧讨论和操作文档 | 有效内容已统一到 agent；按用户要求删除原文件，不保留旧版手册 |
| 个人知识库 | `personal_kb.py`、`tools.py` 的 `search_personal_knowledge` | 文档上传/分段/真实检索引用（文字 RAG 已成功） | **已实现单库 RAG**；多独立库（`kb_libraries` 归属、检索服务端硬过滤）为规划未实现 |
| 电脑控制、家居、长期记忆 | — | 目前没有已交付实现 | 保留候选，不宣称完成 |

项目目录当前没有可识别的 Git 仓库；`.gitignore` 存在不等于已有版本历史或可回滚。未来正式开发前需要确定版本管理和备份方式，本轮不擅自初始化或提交。
