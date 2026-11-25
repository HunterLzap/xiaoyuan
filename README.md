# 小圆 · 个人硬件语音与桌面 Agent 工作台

更新：2026-11-25。

一个个人自用的 **AtomS3R 硬件语音 + 网页工作台 + 跨平台个人电脑操控** 助手：日常自然语音与文字对话，理解需求，按需调用百炼原生联网搜索、所选个人知识库、M5Stack 官方资料、自定义 HTTP API，以及经授权后的 macOS / Windows 电脑 GUI 与应用控制（支持语音/网页随时喊停打断），用真实结果办成事。保留单助手定位与轻量工具循环，不做多助手平台。

## 从这里接手

1. [AGENTS.md](AGENTS.md)：唯一工作约定与操作边界。
2. [统一入口](agent/agent.md) → [START](agent/START.md)：当前版本、已生效能力、实测状态、暂停事项及下一步。
3. 按任务查阅 [PRD](agent/docs/prd.md)、[架构](agent/docs/architecture.md)、[决策](agent/docs/decisions.md)、[操作手册](agent/docs/operations.md)、[代码地图](agent/code/structure.md)。仅在需要追溯运行实据时查看 [进度证据](agent/docs/progress.md)，不默认把全部历史带入上下文。

## 状态与证据

当前云端版本、已验证功能范围、待实机核实事项与剩余待办，**只维护在 [START](agent/START.md)** 与 [roadmap](agent/docs/roadmap.md)；实跑日志与自动化测试结果记在 [progress](agent/docs/progress.md)。本页只做入口导航，不维护第二份状态快照。

## 新电脑接手

```sh
git clone https://gitee.com/ryan406/xiaoyuan.git
cd xiaoyuan
```

然后阅读根目录 [AGENTS.md](AGENTS.md) 与 [agent/START.md](agent/START.md)，使用当前 `git rev-parse --show-toplevel` 作为项目根，具体接手细节见 [交接说明](agent/docs/handoff.md)。

Git 保存源码与保留的固件/动画实验，**不是线上私有运行数据的副本**。模型/设备密钥、`.env`、SQLite 历史与知识库数据、音色样本和 SSH 私钥不入库，拉取后先核对范围，不自动启动服务、部署或刷机。

## 三端与发布位置

| 端 | 位置 | 职责 |
| --- | --- | --- |
| Mac 开发端 | 各自 clone 根目录 | 日常功能开发、增量 Lint / JS 校验、Mac `desktop_node` 调试、`git push origin main` 双推 Gitee + GitHub |
| Windows 端 | `E:\xiaodan` | 本地语音环境、Windows `desktop_node` 与 AtomS3R 真机直连联调，保留本地 `.env`、`data/` |
| 云端生产 | `47.112.16.195` (`/opt/xiaodan/current`) | 对外域名 `https://ryan406.online/xiaoyuan/`；共享配置/库/日志在 `/opt/xiaodan/shared`，通过 `deploy/release_from_git.sh` 原子发布 |
