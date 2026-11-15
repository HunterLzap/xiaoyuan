# 有效资料与核对边界

更新：2026-11-15。本文件只登记资料来源与核对边界，不决定当前运行状态。百炼实时协议、动态工具、上下文与LiveKit参考集中在 [architecture](architecture.md)；模型/声音现状看START。

上游早期默认构建对此板未开放标准AEC选项，只说明当时上游代码；本项目后来已实现播放参考/AEC，不能据旧板型列表否定项目实现。当前能力与现场确认必须结合本项目Git/代码与progress，不把握手aec标志当成全部打断效果证明。

以下整合对当前项目有用的资料，历史资料按原核对日期理解；2026-10-17仅为M1的API配置重新核实下列模型列表官方协议，未核价或验真实账户。未来涉及版本、价格、模型ID、协议差异时须重新查官方来源。其他板型采购、过时套餐和无关教程不继续保留为项目规范。

## 硬件与资料检索

| 用途 | 来源 | 使用边界 |
| --- | --- | --- |
| K147产品、PinMap与库入口 | [M5Stack产品文档](https://docs.m5stack.com/en/core/AtomS3R-AI_Chatbot) | AtomS3R屏幕款与CAM/M12不能混用 |
| 底座Arduino驱动 | [M5Atomic-EchoBase](https://github.com/m5stack/M5Atomic-EchoBase) / [M5EchoBase.h](https://github.com/m5stack/M5Atomic-EchoBase/blob/main/src/M5EchoBase.h) | 文档称Atomic Voice Base时仍须核对实际链接及实物 |
| 官方小智接入教程 | [M5Stack教程](https://docs.m5stack.com/en/guide/atomic_voice_base/xiaozhi_voice_assistant) | 说明生态支持，不证明本项目实机已接入 |
| 官方资料检索 | [AI FAE](https://chat.m5stack.com/)；MCP入口 `https://mcp.m5stack.com/sse` | 本项目只调用只读knowledge_search，未授权knowledge_feedback |
| MCP Python SDK | [官方仓库](https://github.com/modelcontextprotocol/python-sdk) | 资料检索客户端不等于小智云外部工具服务 |
| 嵌入式Realtime参考 | [M5Stack SDK](https://github.com/m5stack/openai-realtime-embedded-sdk) | 不据此推断普通兼容模型支持Realtime |

历史核对K147音频引脚：I2C SDA G38、SCL G39；I2S底座输入DSDIN G5、LRCK G6、底座输出ASDOUT G7、SCLK G8。主控播放走G5、录音走G7。仅作后续核对线索，当前不改硬件或刷固件。

## 固件与协议

- 现有设备历史实查版本2.2.6：[板级源码](https://github.com/78/xiaozhi-esp32/blob/v2.2.6/main/boards/atoms3r-echo-base/atoms3r_echo_base.cc)、[OTA](https://github.com/78/xiaozhi-esp32/blob/v2.2.6/main/ota.cc)、[WebSocket](https://github.com/78/xiaozhi-esp32/blob/v2.2.6/main/protocols/websocket_protocol.cc)、[MCP](https://github.com/78/xiaozhi-esp32/blob/v2.2.6/main/mcp_server.cc)。实机行为优先按对应tag查证。
- 历史2026-10-15查到的[v2.5.2发布](https://github.com/78/xiaozhi-esp32/releases/tag/v2.5.2)和[板级配置](https://github.com/78/xiaozhi-esp32/blob/v2.5.2/main/boards/m5stack/atoms3r-echo-base/config.json)有对应8MB AtomS3R + Echo Base构建。这不是当前最新版承诺，也不是推荐升级或已验证升级路径。
- [版本化WebSocket说明](https://github.com/78/xiaozhi-esp32/blob/v2.5.2/docs/websocket.md)可辅助理解身份、hello、Opus、listen、TTS、abort、MCP；协议字段必须对照当前固件，不能跨tag照抄。
- [小智文档入口](https://xiaozhi.me/docs)包含版本混排内容；历史阅读过百科46个直接外链，不保留与本项目无关的逐篇摘录。官方云控制台与文档可能不同，账号权益以当前实际状态核对。
- [社区兼容服务端](https://github.com/xinnan-tech/xiaozhi-esp32-server)是候选参考，不是官方云源码；[配网页说明](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/docs/firmware-setting.md)不是本设备已成功切回的证据。
- [维护者MCP示例](https://github.com/78/mcp-calculator)用于理解云端外部工具。示例中任意表达式执行等实现不能照搬为权限边界。

历史控制台仅确认设备当时在线、板型与2.2.6版本，模型有预设菜单、记忆开启但0条、知识库未关联、MCP未连接。未验证真实声音、记忆召回、账号额度或任意API接入能力；不把旧菜单名称记成可调用模型ID。

## 历史：MiMo TTS协议核实（2026-10-17）

- TokenDance[基础TTS模型](https://tokendance.space/models/mimo-v2.5-tts)与[VoiceDesign模型](https://tokendance.space/models/mimo-v2.5-tts-voicedesign)的公开模型详情：`architecture.output_modalities=[audio]`，协议为`openai:chat-completions`；供应商说明直接链接小米合成文档。公开目录只有协议字段，不能单独证明模型返回文字。
- TokenDance[Chat Completions协议](https://tokendance.space/docs/protocol-openai-chat-completions.md)核实网关路径及Bearer认证；结合其模型详情引用的[小米MiMo TTS文档](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5)，使用assistant文本、user风格/音色描述、audio.format=wav及内置模型的audio.voice，读取message.audio.data。VoiceDesign不发送内置voice，不开启自动润色。
- 官方预置音色ID：mimo_default、冰糖、茉莉、苏打、白桦、Mia、Chloe、Milo、Dean。接口与字段按文档实现并模拟验证，真实TokenDance账户的转发兼容、音色可用性和实际计费仍未验收；不继承官网临时免费承诺。

## 语音与模型来源（历史核对，非当前选型清单）

- **当前实时主线**为百炼 `qwen3.8-omni-flash-realtime`（OpenAI 兼容 realtime，WebSocket）；实时模式的设备/网页语音与网页文字均以它为准。MiMo/Kokoro 属分模型或历史候选，下列条目为按其核对日期的历史记录。
- 2026-10-30核对 [TokenDance Chat Completions 示例](https://tokendance.space/docs/protocol-openai-chat-completions.md)：文字及流式示例都可省略 `max_tokens`，正文仍为 `message.content` / `delta.content`。本项目取消默认512限制，未配置时省略该字段，由服务端决定上限；不猜测另一固定上限或网关思考参数。
- 同日核对 [Spark-X2.5-4B 官方模型卡](https://huggingface.co/XHToken/Spark-X2.5-4B)：默认思考及 `chat_template_kwargs.enable_thinking` 的说明属于其自部署 SGLang/vLLM 示例，不能证明 TokenDance 网关支持同一扩展参数，本项目未发送。历史空正文请求缺少结束原因记录，不能据512输出计数断言发生了思考额度耗尽。
- 同日核对 [OpenAI Python 的完成类型](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion.py)与当前已安装SDK：`finish_reason=length` 表示达到输出上限，`content_filter` 表示内容过滤；可选 `completion_tokens_details.reasoning_tokens` 只在上游报告时使用。日志只记录受限结束原因和数值用量，不记录完整响应或思考正文；没有额外请求流式用量或自动重试。

- 2026-10-17核实[TokenDance官方文档索引](https://tokendance.space/llms.txt)、[模型文档Markdown](https://tokendance.space/docs/models.md)和[接入指南](https://tokendance.space/docs/ai-integration.md)：模型目录为`GET https://tokendance.space/gateway/v1/models`，无需鉴权，`data`包含`id`及`supported_protocols`。本项目仅展示包含`openai:chat-completions`的条目，不硬编码模型ID，不把目录当作账户权限或真实调用证据。
- 2026-10-17核实[OpenAI List models](https://developers.openai.com/api/reference/resources/models/methods/list)：`GET https://api.openai.com/v1/models`使用Bearer认证，读取`data[].id`。不据此推断任意兼容聊天服务必定提供列表；未知地址默认不请求，须用户明确确认协议或手填模型。

- [Kokoro模型](https://huggingface.co/hexgrad/Kokoro-82M)、[sherpa-onnx仓库](https://github.com/k2-fsa/sherpa-onnx)、[官方Kokoro说明](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html)：用于核对现有包、说话人与参数，不宣称已选最新模型。
- [MeloTTS Chinese](https://huggingface.co/myshell-ai/MeloTTS-Chinese)：历史备选，未下载。许可核对不能替代实际随包第三方许可。
- [edge-tts仓库](https://github.com/rany2/edge-tts)：云端现有依赖的来源线索；服务保障、授权与费用不因开源客户端存在就自动明确。
- [小米MiMo-V2.5-TTS官方说明](https://mimo.xiaomi.com/mimo-v2-5-tts)：此前会话于2026-10-16读取，确认语音合成系列及官方平台限时免费说明；不能推导TokenDance账户当前费率或接口。[TokenDance模型页](https://tokendance.space/models/mimo-v2.5-tts)当时未能读取正文，免费调用线索来自用户，实际适配仍待核实，本次未重新核价。
- [TokenDance首页](https://www.tokendance.space/)、[历史接入说明](https://tokendance.space/docs/alice)：地址和价格未来必须重新核对，17元仅是历史余额。
- [OpenAI Python接口文档](https://developers.openai.com/api/reference/python)：现有SDK调用的参考；供应商兼容性仍要真实请求验证。

不将面包板GPIO、电池/耳机接线、其他MCU的蓝牙或摄像头能力套到本套件；不因旧教程建议删除OTA分区、关闭UAC或忽略鉴权错误而弱化保护。
