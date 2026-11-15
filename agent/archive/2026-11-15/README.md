# 2026-11-15 文档治理归档

状态：**历史资料，不是当前指令或状态来源**。接手从根 [AGENTS](../../../AGENTS.md) → [START](../../START.md) 开始；本目录不要求递归阅读。

## 治理前快照

`pre-governance/`保存Git工作树中文档同步前的27份原文：根README、原AGENTS及agent下除progress之外的文档。用于保留本轮收敛前的需求、架构、操作细节、设计与决策；progress原始证据正文继续原位保留，没有另复制整份大日志。

- 原AGENTS保存为 [AGENTS.before.md](pre-governance/AGENTS.before.md)，避免旧指令文件名被新Agent自动加载。
- 旧 [START](pre-governance/agent/START.md)、[架构](pre-governance/agent/docs/architecture.md)、[操作手册](pre-governance/agent/docs/operations.md)、[路线](pre-governance/agent/docs/roadmap.md)、[决策](pre-governance/agent/docs/decisions.md) 只说明当时记录。原文中“当前”“下一步”“必须登录”“未部署/未切换”等均不代表现状。
- 快照来自同步前的真实工作树文件，不根据Git HEAD重造后续未提交文档；原文保持，不批量改写历史结果。

## 历史咨询

根目录两份第三方咨询保留原文在此目录，根路径改为归档导航，防止推荐另一模型/语音链的旧建议被误读为用户当前要求：

- [ChatGPT建议](consultations/chatgpt建议.MD)
- [Claude建议](consultations/CLAUDE建议.MD)

其中的价格、模型名、推荐方案和执行指令属于各自当时的观点，不是已验证实现，不授权换模型、安装或部署。

## 原位归档的证据

为保留脚本、日志及历史链接，以下资料不移动，入口加归档说明；原文保留：

| 位置 | 分类与使用方式 |
| --- | --- |
| `output/*.md` | 当时的回归矩阵/用例、固件/AEC计划与架构咨询；不是当前计划，实跑结论查progress证据索引 |
| `output/ui128-draft-20261109/` | 多轮动画草案及资源规格；不据它重刷当前设备，原始图片/JSON不改 |
| `output/voice-test/ref/` | 当时收集的第三方参考，不是项目规范 |
| `logs/REPORT-de3764c-bailian-close.md` | 11月13日故障定位，后续修复已在Git历史；不是当前仍复现的定论 |
| `firmware/xiaozhi-esp32/开发日志-2026-11-11.md` | 当时开发总结，部分路径/待办已过期，不作为编译刷写说明 |
| `agent/docs/voice-cloning.md` | MiMo分模型历史流程，不作用于百炼实时塔菲音色 |

第三方固件其他板型、ESP-IDF/managed_components、模型许可与工具生成缓存保留原貌，不把其README/测试结果算成本项目完成证据。实际本板入口增加稳定/实验边界。

归档不等于删除失败、改写通过或批准执行旧命令。没有对应原始证据的结论继续标不确定；文档治理检查不等于重新测试产品。
