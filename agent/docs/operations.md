# 运行与恢复手册

更新：2026-11-23。按具体任务和已有授权使用本手册。运行快照见 [START](../START.md)。

## 1. 先分清环境

| 环境 | 程序与端口 | 数据与注意事项 |
| --- | --- | --- |
| Windows工作树与运行目录 | `E:\xiaodan`；管理端 `127.0.0.1:8000`，设备网关端口 `8003` | 保留本机私有 `.env`、`data/`、`logs/` 和已有虚拟环境 |
| 云端 | `47.112.16.195`；`/opt/xiaodan/current`，内部8010/8013 | `/opt/xiaodan/shared`保存.env/data/logs/.cache，release内链接到共享数据 |

Windows 从项目根执行 Git 操作。云端使用发布目录和已部署的配置，具体版本见 START。

## 2. 云端现状与只读查看

在线发布与最后确认时间只在START维护；原发布保留。`xiaodan.service`使用独立虚拟环境和服务用户，设备OTA/WS与网页共用 `/xiaoyuan` 前缀。

SSH已用现有密钥连通过，不需要用户重新提供密码：

```powershell
ssh.exe -i 'C:\Users\l\.ssh\aliyun_codex' -o BatchMode=yes -o StrictHostKeyChecking=yes root@47.112.16.195
```

进入服务器后可按任务只读查看，避免整段日志与私有数据回显：

```sh
readlink -f /opt/xiaodan/current
systemctl status xiaodan.service --no-pager
journalctl -u xiaodan.service --since '-10 min' --no-pager -o cat
```

应用/音频证据在 `/opt/xiaodan/shared/logs`，每轮指标为 `device-audio-turns.jsonl`。按北京时间与UTC换算、session_id/turn_id选择对应轮次，只输出摘要字段，不打印庞大trace。不要为查看状态额外请求模型。

公网API读取可用；`/health`的上游历史成功标志不是实时探测。**`GET /api/devices`完整响应含带key OTA地址，必须只选connected/ready/last_connected/last_error等所需字段输出。** 内部8010需代理凭据，不为读取绕过它。

## 3. Caddy与网页登录

用户已明确取消管理登录，页面直接访问；不要加回Basic Auth或生成管理员账号密码。免登录的范围是管理网页，不是取消设备鉴权或HTTPS/WSS。

- 沿用现有域名与Caddy2.6.4，未升级；既有站点导入 `/etc/caddy/xiaodan/routes.conf`。
- `/xiaoyuan/xiaozhi/ota/`、设备WS剥离前缀转127.0.0.1:8013，其余助手路径转8010；`/xiaoyuan`补尾斜杠。旧无前缀站点不抢占。
- `AI_PUBLIC_ORIGIN`只含HTTPS origin，路径另设 `AI_PUBLIC_BASE_PATH=/xiaoyuan`；不能把路径塞进origin。
- `/etc/xiaodan/access.env`存origin/base_path/端口和内部随机代理凭据；模型Key在shared/.env，不交Caddy。Caddy覆盖内部凭据头，应用仍校验回环、同源与写请求头；代理令牌不是用户登录密码。
- Caddy日志过滤片段 `/etc/caddy/xiaodan/log-filter.conf`保护OTA key和认证/Cookie/内部凭据；应用由 `deploy.run_public`脱敏写journal，设备URI access log关闭。
- 常规后端更新不需要Caddy reload。只有路由配置确实改变才按现行版本语法检查并reload；旧voice-studio已被用户放弃，不以其是否有语音会话阻塞本项目，也不主动删除或停掉它。

模板以Git工作树 `deploy/` 为开发来源：`assistant.caddy`、`log-filter.caddy`、`access.env.example`、`xiaodan.service`、`run_public.py`。线上渲染配置与模板不应混用；旧 `caddy-access.conf` 注入方案未使用。

## 4. 发布与回退边界

发布需要相应任务授权；本轮文档整理不部署。

1. 从明确稳定release/提交提取代码，合入限定改动；不能从脏工作树整体复制。保留原声音模型、音色和稳定实时模块。
2. 新程序位于 `/opt/xiaodan/releases/<版本>`，沿用shared配置/数据/日志与已有音色文件，不复制Windows虚拟环境。
3. 切换current后只重启本项目独立服务。重启会中断本项目活动语音；先核对本项目状态，不以旧站会话作前置条件。
4. 回退切回保留release，**不把旧数据库覆盖在线数据**；代码回退与数据恢复分开，不复活用户已删记录。

首次Caddy备份在 `/opt/xiaodan/incoming/caddy-before-20261115`。未经授权不commit/push、改安全组、升级代理或安装依赖。

## 5. 设备已接云，不再重复切换

用户已将私有文件 `E:\xiaodan\.cache\private\device-cloud-ota-address.txt` 的**完整地址整行**存入OTA配置。该文件是完整URL，不是key，不在后面再拼接域名或其他参数；不在聊天或文档回显文件内容。

11月15日21:25:07真实OTA通过；21:26:45建立云端WS并完成包括报数的真实问答。OTA只下发时间/连接参数，不是刷固件；返回云端WSS与独立设备凭据。云端连接不要求设备和Windows同一局域网，只需设备Wi-Fi可上网。

设备按需唤醒才开启音频通道，待机或结束后API可能离线；单次connected=false不足以判断OTA失败或退回小智。按同一时间的会话/连接日志确认路由，不靠声音相似度猜服务。

COM3曾因打开串口触发USB复位，RTS/esptool复位曾进入下载模式，用户拔插后已恢复。**不盲开串口、复位、重刷或读取NVS**；NVS含Wi-Fi/OTA秘密，不得完整打印。Windows PktMon旧脚本采192.168.1.5↔192.168.1.6:8003，是当时本机路径，不能用于证明现在云端链路。

固件2.2.6应用指纹与恢复版末次一致，但当前assets图像内容没有独立重新确认。新动画源码/资源/构建产物不等于设备运行稳定版，不能从当前工作树直接编译刷入。

原平台恢复只在用户明确要求时操作：先按已保留原OTA值恢复（历史原值为空），不猜默认地址、不解绑；必须独立真实对话后才能记恢复成功。不要把恢复方法当作当前待办。

## 6. 语音问题如何读证据

用户当前反馈整段随机两处卡顿后继续，已暂停。最后报数轮网关34包全发、最大间隔61ms、无断供；这些不能证明设备连续播放。PCM低能量段可能包含自然停顿，弱Wi-Fi只是线索，均未定因。

音频指标中的 `playback_complete` 是网关结束状态，不是扬声器回执。`aec=true`是设备声明/当前实现事实，不等于所有插话场景通过。项目已做播放参考/AEC，不再使用11月8日“上游此板未开放AEC”否定它。

稳定链沿用60ms Opus、初始180ms预缓冲、420ms上限、90ms断供统计阈值和原声音参数（末次rate=1.2/pitch=+3）。这些是排查对照值，不是本轮调参任务。收到完整转写后再选工具方案未接入生产，不能在查卡顿时顺手改VAD/响应触发。

## 7. Windows启动与配置参考

已安装环境继续复用，**先检查已有实例，不自动重启本机旧稳定进程**。仅在相应任务需要启动时：

```powershell
Set-Location E:\xiaodan
.\start.ps1 -Devices
```

或用现有项目解释器启动 `-m backend.run_devices`（同一进程管理8000/设备8003）；仅管理端可用 `-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers`。不同时启动冲突实例，不加workers。桌面节点管理接口仅允许本机回环，并在配置公网代理时返回 403。

配置来自环境变量/私有.env，环境优先。网页保存、获取模型列表、草稿调用分开，保存不清空历史；密钥留空保留原值，更换地址必须重新输入对应密钥。准确字段与默认值以当前config/schemas为准，不在手册重复旧512输出上限。

实时模式使用 `AI_RT_*` / `AI_RT_VOICE`，分模型 `AI_TTS_*`与本地speech worker不替代它。云端未配置本地worker时audio_enabled=false不代表百炼实时失败，不为此安装ASR或切模型。

知识库迁移已完成，不重跑。确遇尚未迁移的旧库时先一致性保护，再由主负责人显式执行 `scripts/migrate_kb_libraries.py`；不静默清库。embedding曾依靠进程变量开启，持久配置和每个目标的当前取值需按任务核实，不因历史实跑就保证所有环境已开启。

## 8. 数据、备份与下载

完整文字历史、知识库原文/索引、音色元数据与原样本保留；不长期保存聊天录音。数据库迁移/迁移数据使用SQLite备份机制或停写后一致性复制，不能只复制活动库主文件。密钥/NVS/带key地址不入Git、模型或普通日志。

每日独立备份、保留30天是目标，尚无已部署任务/实际恢复证据；目的地待定。本轮不上传数据或创建任务。将来恢复须保护在线数据并处理手动删除语义；同盘副本不冒充独立备份。

有下载/安装授权且确有需要时，Windows所有产物留项目内，并显式设置：

```powershell
$env:TEMP='E:\xiaodan\.cache\tmp'
$env:TMP='E:\xiaodan\.cache\tmp'
$env:PIP_CACHE_DIR='E:\xiaodan\.cache\pip'
$env:HF_HOME='E:\xiaodan\.cache\huggingface'
$env:TORCH_HOME='E:\xiaodan\.cache\torch'
```

先创建所需目录，其他下载器另设项目内输出；不重装现有环境，不把Kokoro/MiMo历史候选上传为生产依赖。
