# 项目统一管理入口

更新：2026-11-08。此入口只维护当前有效约定；旧决策与运行证据分别保留在 decisions/progress，不在这里重复多套历史路线。

## 当前目标与设计

本项目只有一个硬件语音助手（AtomS3R + Echo Base）：正常对话，理解用户想做什么，按需调用 API 与所选知识库，用真实结果完成需求，简单、高效、快速。不要缩成普通问答，也不要扩成多助手或重型 Agent 平台。

- 助手配置：提示词 + 选用 API 能力 + 选用知识库，声音设置沿用现有行为。
- API 能力：天气、M5Stack 官方资料、自定义 API 放在同一资源管理入口；内置实现与 HTTP 接入可不同，不伪造接口。
- 知识库：多独立库，助手可选一个或多个；检索在服务端限制为所选范围。旧分组是标签，不冒充独立库。
- 对话：普通聊天直接答，需要时选工具→真实执行→拿结果继续答或继续调用；必要信息才询问，失败如实说明。工具描述自动提供给模型，不让用户在提示词里手写工具清单。
- 复用现有实时主线与工具反馈循环；不增加每轮前置规划调用，不做多助手实体、长期记忆、无人值守任务、插件市场或电脑控制。
- 文档同步后，用户已要求继续实现；本轮已执行后端/界面实现、显式数据迁移及本机真实文字/资料验证。当前已验证范围与未确认项见 progress，不再按旧“仅同步文档”判断现状；后续按已有授权推进，重大行为变化再沟通。

架构与数据边界看 [architecture](docs/architecture.md)，产品行为看 [PRD](docs/prd.md)，实施顺序看 [roadmap](docs/roadmap.md)。不再沿用旧 M0–M5 或固定 P0→P1→P2 顺序作为当前开工条件。P0–P3 仍可作模块索引，不能据其阻塞独立工作。

## 已有底座与实际状态

- 当前主线为百炼 `qwen3.8-omni-flash-realtime`；设备、网页语音及实时模式网页文字复用实时模型。DeepSeek/MiMo 只属分模型路径，不是实时模式的隐式替代。
- 基础设备交流已由用户现场确认。音色复刻、声音调节、API 工作台、单库混合检索与洞察已有实现，实时模式文字 RAG 有实际运行证据。
- 助手 API/库选择、多库归属/硬过滤和新管理布局已实现；真实迁移、上传/替换、双库关键词与 hybrid 向量隔离及文字组合查询/引用/显式取消已实跑。设备/网页语音真机听感仍未确认；外部写操作尚无完整对话确认流程。所有渠道不能因代码共用而自动记作通过。
- AEC/收放同听与插话打断是设备侧约束，Agent 配置改造不会自动解决；按键 abort 有历史实际证据。现场体验与服务端指标分开。
- 当前仍是 Windows 本地开发；目标云机 2 核约 1.87GB，不代表本机配置，也不代表已部署验收。云端运行、鉴权及备份等既有目标保留在 PRD/roadmap，待相应授权实施。

完整结果与缺口只维护在 [progress](docs/progress.md)，下一次从 [START](START.md) 继续，不重复开发已跑通功能。

## 工作与协作

- 用户最新明确目标优先；旧文若冲突，修正文中要求并标取代关系，不能靠一条总声明让旧要求继续误导。实现方式由负责人决定，产品效果和重大范围变化再与用户沟通。
- 主 Bot 统筹，子 Bot 按模块负责；开发团队多个 Bot 与产品多个助手无关。同一文件同时一位负责人，主 Bot 统一集成、服务/设备/迁移/付费调度。
- 先完成已授权范围内的真实功能与 AI 可独立进行的实际检查，再交用户集中做讲话、听感、按键、物理场景等现场体验。不要把接口是否接通推给用户。
- 不搭模拟 API、假数据或隔离测试后台，不安排冒烟/最小验证/分级验收流程，不为假想故障做通用兜底。保留鉴权、密钥、输入校验、并发、取消和数据保护。
- 保留已跑通音色、语速/音调、正式首句开场、历史和原资料；改重要已确认行为先沟通。查询按已开放范围自动用；外部修改/发送/删除/付费需按具体操作确认，没有闭环时保持受限。
- 不擅自提交、推送、部署、烧录、改设备地址、下载/安装或操作远端；已有密钥不等于无限付费调用。共享资源由主 Bot 按现有授权调度。
- 规划、已有代码、AI 实跑、用户现场确认分别记录。文档同步不是功能交付，不把历史未验收项补写通过。
- 沿用现有灰阶明暗主题和文档体系；只更新必要内容，不新建平行 PRD、计划或重复报告。配置保存不得清空历史，密钥/私人对话/录音不发群聊。

## 文档地图

| 文档 | 唯一职责 |
| --- | --- |
| [STATUS](STATUS.md) / [START](START.md) | 当前规范状态与继续工作的入口 |
| [goals](docs/goals.md) / [audience](docs/audience.md) | 产品目标、边界与真实场景 |
| [PRD](docs/prd.md) / [decisions](docs/decisions.md) | 产品行为与决定的取代关系 |
| [architecture](docs/architecture.md) / [knowledge-base-design](docs/knowledge-base-design.md) | 共用底层和多库 RAG 设计 |
| [roadmap](docs/roadmap.md) | 依赖、实施范围与开发分工 |
| [progress](docs/progress.md) / [acceptance](docs/acceptance.md) | 真实证据与产品行为判定 |
| [operations](docs/operations.md) / [resources](docs/resources.md) / [references](docs/references.md) | 运行操作、资源和公开依据 |
| [voice-cloning](docs/voice-cloning.md) | 声音复刻的历史事实和操作边界 |
| [handoff](docs/handoff.md) | 接手规则与当前交接说明 |
| [overview](design/overview.md) / [components](design/components.md) / [layout](design/layout.md) | 页面、交互与布局 |
| [tokens](design/tokens.md) / [naming](design/naming.md) / [assets](design/assets.md) | 配色、称呼、资产规范 |
| [conventions](code/conventions.md) / [structure](code/structure.md) | 工程约定和现有模块职责 |
