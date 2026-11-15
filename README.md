# AtomS3R 个人语音助手

更新：2026-11-15。

一个硬件语音助手（AtomS3R + Echo Base）：正常对话，理解需求，按需调用已配置的 API 与所选知识库，用真实结果回答。保留单助手、轻量工具循环，不做多助手平台或每轮前置规划模型。

## 从这里接手

1. [AGENTS.md](AGENTS.md)：工作约定与操作边界。
2. [统一入口](agent/agent.md) → [START](agent/START.md)：当前状态、版本、暂停事项及下一步。
3. 按任务读[架构](agent/docs/architecture.md)、[操作手册](agent/docs/operations.md)、[代码地图](agent/code/structure.md)。只有需要追溯时才读[进度证据](agent/docs/progress.md)，不要默认把全部历史带入上下文。

## 状态与证据

当前线上版本、设备连接证据、文字/语音优化的生效范围、随机卡顿暂停及下一步，**只维护在 [START](agent/START.md)**。本页不再复制运行状态。

测试与实际运行结果通过 [progress的证据索引](agent/docs/progress.md) 找到原始记录；行为判断标准见acceptance，文档职责与维护规则以AGENTS为准。

## 新电脑接手

```sh
git clone https://github.com/HunterLzap/xiaoyuan.git
cd xiaoyuan
```

然后读根目录AGENTS.md和agent/START.md。使用当前clone目录，不必复刻原电脑的E盘路径；具体方法见 [交接说明](agent/docs/handoff.md)。

Git保存开发源码、文档与保留的动画/TCP实验，**不是线上稳定发布的直接副本**。拉取后先阅读，不自动安装、启动、部署或刷机。模型/设备密钥、数据库、录音样本和SSH私钥不随Git迁移，缺少本机证据附件也不代表功能故障。

## 三个位置必须分清

| 位置 | 用途 |
| --- | --- |
| `E:\xiaodan` | 原电脑的Windows运行副本、私有数据、设备工具与本套文档 |
| `E:\xiaodan\.cache\repo-export` | 原电脑的Git工作树，保存新动画/TCP/后端开发快照；新电脑直接使用clone根目录 |
| `/opt/xiaodan/current` | 云端在线发布；配置、数据库、日志在 `/opt/xiaodan/shared` |

本机代码、工作树代码、云端已加载版本有意不同，不能整目录互相覆盖。文档在本机与 Git 工作树保持同版，业务代码不随文档同步。
