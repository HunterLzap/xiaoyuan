# Agent 接手说明

更新：2026-11-25。本文件只规定接手方式与工作流；当前版本与待办只在 [START](../START.md) 维护。

## 接手顺序

1. 读根 [AGENTS](../../AGENTS.md)、[README](../../README.md)、[统一入口](../agent.md) 和 [START](../START.md)。
2. 明确本轮任务与暂停边界：云端音频整段随机卡顿与固件新动画仍处于用户要求暂缓状态，未经指示不要主动启动排查或编译刷写。
3. 按需查阅 [PRD](prd.md)、[架构](architecture.md)、[操作手册](operations.md)、[代码地图](../code/structure.md)；仅在追溯实跑证据时检索 [progress](progress.md) 对应日期段落。

## 三端协同与新电脑接手

1. **主源码仓**：`https://gitee.com/ryan406/xiaoyuan.git` 与备份仓 `https://github.com/HunterLzap/xiaoyuan.git`（Mac 端 `origin` 配置一键双推）。新电脑 clone 后以 `git rev-parse --show-toplevel` 为根目录，不必复刻原 Windows 的 `E:\xiaodan` 路径。
2. **Mac / Windows / 云端分工**：
   - **Mac 端**：负责日常代码开发、增量 Lint、JS 校验、Mac `desktop_node` 调试与无硬件依赖测试。
   - **Windows 端（`E:\xiaodan`）**：保留本机 `.env`、`data/`、`logs/` 与 `.venv`/`.venv-speech`，负责本地语音、`desktop_node` Windows 端与真机联调。
   - **云端（`47.112.16.195`）**：维护只读镜像仓 `/opt/xiaodan/repo`，发布时按任务授权运行 `deploy/release_from_git.sh` 原子切换 `/opt/xiaodan/current` 并复用 `/opt/xiaodan/shared`；禁止在运行目录直接 `git pull`。
3. **不入库内容**：模型/设备密钥、`.env`、SQLite 历史/知识库、音色样本、`desktop_nodes.json`、SSH 私钥、虚拟环境和本地日志不在 Git 中。不因新机缺少这些文件而清空设置或重建凭据。

## 不要重复已经办完的事

- 硬件设备已接通自有云端，网页已按用户决定免登录；不要把“切云 OTA”或“加回账号密码”当成待办。
- 单助手绑定、多独立个人知识库、会话内检索、百炼 `qwen-audio-3.1-realtime-flash` 主线（含塔菲 `voice-enrollment` 复刻与原生 `enable_search` 合并天气）、跨平台 `desktop_node` 操控、会话级「Agent 执行轨迹」与语音/网页跨通道即时打断桌面操控**均已完成编码与对应阶段验证**，勿从零重建。

## 必须保留的边界

- 云端生产 release、Git 最新开发快照与固件工作树实验彼此独立；代码进 `main` 不等于云端已部署或真机已验证。
- 涉及 `COM3`/串口、`esptool` 刷固件、更改设备 OTA 地址、公网暴露真实 `desktop_nodes` 配对令牌与截屏预览的动作均有严格禁忌，参见 [operations](operations.md) 与 [START](../START.md)。
- 交付口径严格区分：**已有代码 / 本地自动化通过 / 云端浏览器实测 / 硬件真机实测**，未在真机测过的声音链路不写已实机通过。
