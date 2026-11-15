# 代码与运行位置地图

更新：2026-11-15。此处描述模块职责，不代表磁盘代码已被运行进程加载；版本与暂停事项见 [START](../START.md)。

## 三处环境

| 位置 | 职责 |
| --- | --- |
| `E:\xiaodan` | Windows运行副本、设备工具链、私有数据与文档 |
| `E:\xiaodan\.cache\repo-export` | 原电脑的Git工作树；新动画/UI/TCP及后端开发快照保留于此；新电脑使用实际clone根目录 |
| `/opt/xiaodan/current` | 云端release链接；共享配置/数据/日志在 `/opt/xiaodan/shared` |

不要把repo-export当普通缓存清理，不在运行副本初始化第二个Git仓库。稳定实时模块有意与工作树不同；文档同步只同步明确的文档文件，不递归复制整个仓库。

## 后端关键模块

路径相对各自程序根目录；实际任务先确认要改哪个环境。

| 位置 | 职责 |
| --- | --- |
| `backend/run_devices.py` | 单进程管理端/设备网关启动；Windows8000/8003，云端8010/8013 |
| `backend/app/main.py` / `devices.py` | 管理路由、OTA/设备WS鉴权、协商与MCP控制 |
| `realtime.py` / `realtime_text.py` | 百炼实时语音与实时模型文字会话/工具反馈；两种入口时序不同 |
| `device_realtime.py` / `voice_transport.py` | 设备实时桥接、Opus/发送节奏/预缓冲、播放结束与取消隔离 |
| `voice_chat.py` / `conversation.py` / `device_turn.py` | 网页/设备对话协调及显式分模型路径，不是切换实时音色的入口 |
| `prompt_builder.py` / `prompt_context.py` / `speech_text.py` | 角色/规则/时间/渠道提示与朗读规范化 |
| `tools.py` / `tool_dialogue.py` | 注册与选用范围、Schema/权限/控制意图、业务工具循环 |
| `text_tool_selection.py` | 网页实时文字候选并集与同轮补充加载；语音尚未接入 |
| `conversation_memory.py` | 活动历史预算与当前会话原文按需检索，无跨会话画像 |
| `weather.py` / `knowledge.py` / `api_requests.py` | 天气、M5官方只读资料、自定义HTTP API |
| `personal_kb.py` / `embeddings.py` / `audit_store.py` | 多库原文/FTS/向量/按库过滤与洞察快照 |
| `order_confirmation.py` | 特定订单编号确认，不等于通用外部写操作确认平台 |
| `service.py` / `history_store.py` / `schemas.py` | 会话/持久历史、Token明细结构与聚合 |
| `config.py` / `settings_store.py` | 配置读取、单助手选择、原子保存与私有凭据 |
| `audio_fx.py` / `audio_metrics.py` | 原语速/音调后处理与被动PCM/网关计量；不长期保存音频 |
| `qwen_voices.py` / `voices.py` / `tts.py` | 百炼/分模型音色元数据及显式TTS适配，不混接实时主线 |
| `ack_audio.py` / `community.py` / `speech_bridge.py` | 历史应答音、已有社区代码桥、本地worker；不是新主线依赖 |
| `app.html` / `app.js` / `app.css` / `paths.js` | 原生管理前端、用量展示及部署子路径支持 |
| `voice.js` / `voice-capture.js` | 网页音频采集、真实状态与播放 |

上述后端文件除首行外均位于 `backend/app/`。细节按实际代码核对，不因共享模块断言所有渠道都已通过。

## 固件、部署与数据

- `firmware/xiaozhi-esp32/main/application.cc`：唤醒/聆听/说话/结束状态；`main/audio/`：AFE、播放参考/AEC、编解码与播放；`main/protocols/`、`main/network/`：设备协议/TCP。
- `main/boards/atoms3r-echo-base/`与对应sdkconfig：板级显示/声音。工作树的 `robot_display.h`、`animations/`、新UI回调与TCP改动属于保留实验，不是当前稳定设备清单。
- `build-tafei-mn5-ui-anim`是动画实验构建目录，不据名称当稳定恢复产物；稳定原应用/assets及刷写证据按progress与已有备份定位，未经要求不构建/刷机。
- Git工作树 `deploy/`：Caddy路由/日志过滤、systemd、访问环境模板、脱敏runner；Windows运行副本的模板可能旧，不用于直接覆盖线上。
- `data/`：私有历史/知识库SQLite、设备/工具/音色配置；`models/voice/`：原音色样本。云端对应共享数据，不随代码回滚。
- `logs/`、`output/`、`.cache/device-backups/`：日志与历史证据；`firmware/backup/`：既有固件备份。保留原始记录，不当执行指令。
- `third_party/`、`.venv`、`.venv-speech`、现有模型：按现有用途保留；不为文档统一迁移、下载或重装。

产品行为、设计、操作与证据分别在PRD、architecture、operations、progress。根目录旧咨询报告只作历史意见，不是主线选型或自动操作授权。
