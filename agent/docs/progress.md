# 当前进度与证据

更新时间：2026-11-24。**本文件是实跑/测试结果的唯一索引，不是当前执行清单**；当前版本、任务与暂停事项只看 [START](../START.md)。下方按时间保留过程，不删除早期失败，也不把旧“当前/下一步/未部署”当现行要求。

## Batch 1 后端存储与桌面操控（2026-11-24）

- Windows `E:\xiaodan`，基于 `29f9a15`，Python 3.12.0。桌面桥接、网关追踪、个人知识库隔离和实时语音失败回归共 38 项通过（含 5 项新增测试），0 项跳过，1 条 Starlette 弃用警告。[测试输出](E:/xiaodan/logs/batch1-pytest.log)
- 项目缓存内的 Pyright 1.1.414 补齐增量 Lint 所需工具，复验新增问题为 0。SlopGuard 初检发现项目基线已有的 6 处 `B904`，经授权补齐显式异常链。桌面 RPC 异常去重用例通过 RED → GREEN 消融，SlopGuard 跳过环境中未发现的 Pyright 与 Semgrep，Pyright 已由项目增量 Lint 执行。[增量 Lint](E:/xiaodan/logs/batch1-lint.log) · [门禁初检](E:/xiaodan/logs/batch1-slopguard.log) · [消融复验](E:/xiaodan/logs/batch1-slopguard-ablation.log)
- Git Bash 通过热备脚本语法与参数预演检查。Windows 缺少 `sqlite3` 命令，未执行实际热备、清理或恢复。云端、真机及模型上游未参与验证。[预演输出](E:/xiaodan/logs/batch1-backup-dry-run.log)

## Windows SlopGuard 门禁本地化（2026-11-24）

- 在 Windows `E:\xiaodan` 的 `5b659e2` 上停止跟踪 SlopGuard 配置与交付流程，原文件内容和 Git pre-commit 钩子保留在本机。原门禁条款移至本机 `AGENTS.local.md`，Git 本机忽略规则覆盖三个文件。
- 本机 `slopguard verify --json` 退出 0，0 findings。用现有 `.venv` 运行桌面管理权限与设备结束意图的 3 条回归，全部通过，出现 1 条 Starlette TestClient 弃用警告。本次验证范围为 Windows 开发工作树。[门禁结果](E:/xiaodan/logs/slopguard-local-verify-20261124.json) · [回归输出](E:/xiaodan/logs/slopguard-local-regressions-20261124.log)

## Windows SlopGuard 门禁与核心回归（2026-11-23）

- 使用本机 SlopGuard `da44d72` 完成项目初始化和 pre-commit 安装，`_sg_bin` 指向 `C:\Users\l\go\bin\slopguard.exe`。用 `git hook run pre-commit` 执行成功。本机配置沿用既有基线，`verify.test_cmd` 使用 `E:\xiaodan` 的现有 `.venv`，供 `--ablation` 调用。
- 新增两个桌面管理用例，覆盖持有内部代理凭据时公网 6 个管理操作仍返回 403，以及桌面控制关闭时本机配对可用、健康接口和外部访问均不返回节点令牌。扩展既有结束意图用例，验证「退下」取消实时响应、清除设备会话、下发待机和停止播放。配置的 3 条用例和两套相关测试的 29 条用例均通过。
- `verify --json` 退出 0、0 findings，执行新增注释探针与 Python 抑制注释基线检查。`ruff`、`pyright`、`semgrep` 因未安装而跳过，项目增量 Lint 也因缺少 Ruff 未运行完。[普通体检](E:/xiaodan/logs/slopguard-verify-20261123.json)
- 在 `d567120` 的临时工作树重放桌面令牌修复，`verify --ablation --json` 完成 RED → GREEN，退出 0，临时 Git 工作树已移除。本轮验证覆盖接口与后端状态机，未使用真机或请求上游模型。[消融记录](E:/xiaodan/logs/slopguard-ablation-20261123.json)
- 随后在现有 `.venv` 安装 Ruff `0.17.6`，两份回归测试文件的 Ruff 检查通过，SlopGuard 复验退出 0、0 findings。复验只跳过 `pyright` 和 `semgrep`。[Ruff 启用后的体检](E:/xiaodan/logs/slopguard-verify-with-ruff-20261123.json)

## Windows 工作树统一与本机启动验证（2026-11-23）

- 运行目录完整备份至 `E:\xiaodan_backup_before_sync_20261123_214111`。Robocopy 二次比对 138,105 个文件无差异，对 `.env`、`data/`、`models/` 和两份未提交文档共 440 个文件复核 SHA-256。[备份日志](E:/xiaodan_backup_before_sync_20261123_214111.robocopy.log)
- `E:\xiaodan` 成为项目唯一工作树，本机 `main` 与 GitHub `origin/main` 同为 `d567120`。远端开发记录留在原文档，旧工作树的 11 月 16 日本机记录移入忽略文件 `LOCAL_FLASH_NOTES.md`。旧嵌套目录已移出项目。
- 本地分支 `local/windows-sync` 的 `b6c7e29` 将所有桌面节点管理接口限制为本机回环，并拒绝配置了公网代理的 Web 访问。验证配置公网代理且内部代理凭据正确时，6 个桌面节点管理操作均返回 403。本机回环读状态返回 200，外部 Host 和非同源 Origin 分别返回 400、403。
- 按授权使用现有 `.venv` 启动 Windows 管理服务，PID 16244 监听 `127.0.0.1:8000`。首页与 JS/CSS 返回 200，配置读取正常，读回 148 个会话并打开其中一份历史，读取 1 库 1 文档及其原文，当前实时音色与已保存配置一致。2 份音色配置、1 个本机复刻条目可读。[启动日志](E:/xiaodan/logs/windows-sync-20261123-214111.log) · [复核结果](E:/xiaodan/logs/windows-sync-20261123-214111.verify.json)
- 完成启动后复核，`.env`、历史和知识库数据库、音色文件及其他原有数据和模型共 437 个文件与备份字节一致。助手状态库原有记录一致，仅新增异常日志表与索引。另新建 `data/desktop_nodes.json`。
- 相关已有用例 40 项通过，`app.js` 语法检查和两份 Python 文件编译检查通过。增量 Lint 因本机缺少 Ruff 未完成。此次为本机 HTTP 及数据读回检查，模型听感、桌面节点实操、8003 设备网关和云端发布未验证。

## 飞书 `0ms` 连续报错根治、停止控制与设置界面去噪（2026-11-17）

- **真实排查发现（来自 `2fc629d` 上云实测截图）**：
  - `qwen3.5-plus` 实测打开飞书（`1515ms`）与看屏定位 Friday 对话框（`1600ms`）均一次命中；但随后连续 14 次 `desktop_gui_action` 全部在 **`0ms`** 失败且耗尽 16 轮 / 109k Token，无处可按停止；设置页 `.api-panel .settings-row` 左列仅有 `92px`，导致长段说明小字竖向换行成狭窄长条。
  - **根因**：① `qwen3.5-plus` 向 `desktop_gui_action` 传入了大量带 `null` 值的可选参数（如 `x: null, y: null, node_id: null`）、浮点坐标及 `action="type"` 等别名，触发 `Draft202012Validator` `0ms` 拒收，且原异常仅回传笼统“工具参数不符合接口定义”，模型盲猜重试 14 轮；② 网页文字聊天运行期间禁用输入框、缺取消接口与停止按钮；③ 设置表单塞入冗余说明 `<p>` 与 `92px` 过窄列。
- **本轮改动**：
  - **参数归一化 + 字段级报错 + 3 轮熔断**：`backend/app/tool_dialogue.py` 新增 `_normalize_tool_arguments`（全局剔除 `None` 可选键，兼容 `type`/`paste`/`tap`/`key_press`/`coordinate`/`point`/`content`/`button` 与浮点/字符串整数换算），`backend/app/tools.py` 在 `SchemaValidationError` 时回传具体出错字段路径与校验信息，`ToolConversation` 在连续 3 轮工具全错后自动熔断收尾，避免死循环烧 Token。
  - **网页端与服务端随时停止**：`backend/app/schemas.py` & `main.py` 新增 `ChatCancelRequest`、`POST /chat/cancel` 及活跃任务下的 `_STOP_INTENT_RE` 拦截；`app.html`、`app.css`、`app.js` 新增发送区 `#stop-turn` 与进度条 `.pending-stop-button`（基于 `AbortController` + `/chat/cancel`），运行期间保持输入框可用，直接输入“停止/停下/别动/取消”亦可立即中断。
  - **UI 极简去噪与列宽对齐**：将 `.settings-page .api-panel .settings-row` 标签列拓宽为 `108px`，移除 `#desktop-model-panel`、个人档案、声音调节用量口径、电脑节点说明与技能卡片中的多行小字描述与多余角标，「纯视觉备用」收纳至「更多模型选项」折叠栏。
- **本机最终代码后验证（Mac Darwin / `.venv` Python 3.12.13）**：
  - `node --check backend/app/app.js && node --check backend/app/voice.js`、`.venv/bin/python -m py_compile desktop_node/*.py`：通过。
  - `.venv/bin/python scripts/lint_incremental.py`：`ruff=18, pyright=119, baseline=146, new=0`。
  - `tests/test_desktop_bridge.py`（18，含新增 `null`/浮点/`type` 归一化、字段报错 + 3 轮熔断测试、`/chat/cancel` + `"停止"` 打断活跃回合测试）+ `test_personal_kb_isolation.py` + `test_realtime_failures.py` + `test_voice_compat.py` + `test_voices.py`：**45 passed（3.58s）**。
  - `tests/test_gateway_trace.py`（单独跑 **3 passed（0.66s）**；首次与 `test_knowledge.py` 连跑时 `test_unified_traces_and_sqlite_business_state` 偶发既有的 `audit_tasks` 跨事件循环竞态）；`tests/test_knowledge.py -k "not chat_uses and not retrieval_failure"` **10 passed, 2 deselected（0.62s）**；`tests/test_voice_chat.py` 子集 **3 passed, 3 deselected（0.52s）**；`tests/test_settings_workflow.py` 分组设置子集 **7 passed, 4 deselected（0.79s）**。
- **尚未验证**：推云部署本版后在真实浏览器目视确认新 UI 排版、点击停止按钮，以及 `qwen3.5-plus` 真机飞书打字闭环。

## 多模态直连 Computer Use（SoM 标号方框 + 统一模型中心，2026-11-17）

- **解决的问题与方案**：针对“看图二传盲跑”准确率低、耗时翻倍，以及语音/文字/电脑模型配置分散的问题，完成两项核心升级与统一模型配置：
  1. **Set-of-Mark（SoM）视觉标框（`desktop_node/som.py`、`client.py`、`desktop.py`）**：利用 `ui_tree` 真实中心点与宽高，在桌端截图时同步生成带彩色边框及 `[0]`, `[1]`… 编号徽章的高亮标注图（macOS 原生 Swift CoreGraphics ~50ms 热绘制 + Windows .NET `System.Drawing` / Pillow，零云端新增依赖），并与 `ui_elements[].index` 一一对应。
  2. **原生多模态直连循环 + 百炼高性价比默认路由（`desktop.py`、`desktop_tools.py`、`tool_dialogue.py`、`service.py`、`llm.py`）**：查询百炼官方文档确认 `qwen3.5-plus`（0–128K 原价 ¥0.8 / ¥4.8 百万Token）与 `qwen3.5-flash`（¥0.2 / ¥2.0 百万Token）原生支持 `image_url` 与 `tools` Function Calling 且成本低于 `qwen3-vl-plus`（¥1.0 / ¥10.0）。已配置百炼 Key 时未手动指定桌面规划模型将自动路由至百炼 `qwen3.5-plus`；`ToolConversation` 直接将最新 SoM 截图作为 `user` 多模态帧喂给模型，自动裁剪前序轮次历史截图保持每轮仅 1 张图，同时跳过 `_analyze_screenshot` 二次看图调用；对 `qwen3.5*` 桌面工具回合传入 `extra_body={"enable_thinking": False}` 避免每步长思维链延迟与费用。手动填回 `qwen-plus` / `deepseek-*` 等纯文字模型仍自动兼容两步看图路径。
  3. **统一模型配置中心（`app.html`、`app.js`、`app.css`、`settings_store.py`）**：点击顶栏当前模型直接进入「模型与连接」；新增「当前生效模型一览」与常驻可见的「电脑操控模型（Computer Use）」卡片（内置 `qwen3.5-plus` / `qwen3.5-flash` / `qwen3-vl-plus` 与手动预设，显示实时路由与凭据复用状态），移除「技能与知识」里埋在折叠框内的重复输入框。
- **本机最终代码后验证（Mac Darwin / `.venv` Python 3.12.13）**：
  - macOS Swift SoM 真实截图渲染：编译缓存生成真实带 `[0]`、`[12]` 正向文字与对齐边框的 JPEG（热耗时 ~50.8ms，`read_file` 目视确认方向与标框准确）。
  - `node --check backend/app/app.js && node --check backend/app/voice.js`、`.venv/bin/python -m py_compile desktop_node/*.py`、`.venv/bin/python scripts/lint_incremental.py`（`ruff=18, pyright=119, baseline=146, new=0`）：通过。
  - 单元测试实跑结果：`tests/test_desktop_bridge.py`（16，含多模态直连与旧帧裁剪、百炼 `qwen3.5*` `enable_thinking=False`、SoM 编号映射/Mac 渲染、统一模型配置接口）+ `test_personal_kb_isolation.py` + `test_realtime_failures.py` + `test_voice_compat.py` + `test_voices.py` **43 passed（4.09s）**；`tests/test_gateway_trace.py` + `tests/test_knowledge.py -k "not chat_uses and not retrieval_failure"` **13 passed, 2 deselected（0.79s）**；`tests/test_voice_chat.py` 子集 **3 passed, 3 deselected（0.51s）**；`tests/test_settings_workflow.py` 分组设置子集 **7 passed, 4 deselected（0.83s）**；`tests/test_devices.py -k "not real_socket"` **4 passed, 4 deselected（30.99s）**。
- **尚未验证 / 留待后续确认（不宣称已实机验收）**：
  - 百炼在线 API 真实 `qwen3.5-plus` 端到端操控 Mac/Windows 飞书窗口并打开 Friday 对话框输入“你好”，以及 Windows .NET `System.Drawing` SoM 真实渲染，需推云部署并重启桌端节点后实测确认。

## 桌面规划模型百炼端点混用修正（2026-11-17，继 `d29cf1d` 填入 `qwen-plus` 报 400 后修复）

- **问题原因**：主文字接口同时配了非百炼网关（`tokendance.space` + `deepseek-flash-latest`）而语音配了百炼（`rt_provider="bailian"`）时，填入 `desktop_planner_model="qwen-plus"` 误把 `qwen-plus` 发往主文字 `base_url` 导致模型服务拒绝请求。
- **改动**：`backend/app/desktop.py` 抽取 `_is_bailian_model_name` / `_has_bailian_key` / `_bailian_compatible_base_url` / `_bailian_planner_copy`，视觉看图与桌面规划共用统一分流：当 `desktop_planner_model` 为 `qwen*`/`qvq*` 且主文字 `base_url` 不含 `aliyuncs.com`、已配百炼密钥时，自动走百炼 `compatible-mode/v1` + `rt_api_key`。
- **本机代码后验证**：`lint_incremental` `new=0`；`tests/test_desktop_bridge.py` + 核心套件 **43 passed（3.73s）**（含新增混合配置分流用例）；`test_devices -k "not real_socket"` **4 passed（31.13s）**；`test_knowledge` **10 passed（0.80s）**；`test_voice_chat` **3 passed（0.58s）**。云端真实 `qwen-plus` 端到端飞书实测待部署后验证。

## 飞书实测截屏盲点、DSML 上限泄露与控件卡补全修复（2026-11-17，`d29cf1d` 已推送）

- **真实排查发现（来自用户「打开飞书，找 Friday 并输入你好」与 `deepseek-flash-latest` 实测截图）**：
  - `83ed03c` 成功点击 `#1 搜索（⌘＋K）` 并向 `#21` 粘贴写入 `Friday`，但随后误点了顶部「消息」筛选标签并在第 10 轮后在聊天窗输出原始 `<｜DSML｜calls>` 文本。
  - 实查 4 处根因：① 后 4 次 `desktop_inspect_screen` 因模型省略 `question` 参数导致 `analyze_vision=False`（仅 684ms 未调 `qwen3-vl-plus`），规划模型完全看不到截图内容；② macOS `ui_tree.py` 过滤了带标签的 `AXGroup` Electron 列表卡片；③ 模型传 `action="key_press"` 与字符串 `"keys": "Escape"` 触发参数校验失败浪费 1 轮，第 10 轮 `tools=[]` 时 `deepseek-flash-latest` 吐出原始 DSML 标签；④ 搜索结果指引未强调区分联系人列表与顶部「消息」筛选标签。
- **本轮改动**：
  - `backend/app/desktop_tools.py`：`DesktopInspectScreenTool.run` 默认补齐综合看图描述与坐标问题并始终开启 `analyze_vision=True`。
  - `desktop_node/ui_tree.py`：在 macOS `AXUIElement` 扫描器补充保留带非空名称且为列表卡片尺寸（`24..760 × 18..160`）的 `AXGroup`。
  - `backend/app/tool_dialogue.py`：桌面上限扩至 `16` 轮 / `28` 次调用；`TurnTools.execute` 在 schema 校验前兼容 `key_press`/`press_key`/`press` 与字符串 `key`/`keys`；满轮收尾向模型追加禁 XML/DSML 提示并由 `_strip_dsml` 在流与 `complete()` 出口统一清洗；`DESKTOP_TOOL_NAMES` 显式区分下拉联系人卡片与顶部「消息」筛选按钮。
- **本机最终代码后验证（Mac Darwin / `.venv` Python 3.12.13）**：
  - `node --check backend/app/app.js && node --check backend/app/voice.js`、`.venv/bin/python -m py_compile desktop_node/*.py`：通过。
  - `.venv/bin/python scripts/lint_incremental.py`：`ruff=18, pyright=119, baseline=146, new=0`。
  - `.venv/bin/pytest tests/test_desktop_bridge.py tests/test_gateway_trace.py tests/test_personal_kb_isolation.py tests/test_realtime_failures.py tests/test_voice_compat.py tests/test_voices.py -v`：**43 passed, 0 failed（3.52s）**（含 `DesktopInspectScreenTool` 默认触发视觉、`TurnTools + ToolGateway` 校验 `key_press` + 字符串 `keys` 兼容、以及 `_strip_dsml` 清洗测试）。
  - `.venv/bin/pytest tests/test_devices.py -k "not real_socket" -v`：**4 passed, 4 deselected（30.94s）**；`.venv/bin/pytest tests/test_knowledge.py -k "not chat_uses and not retrieval_failure" -v`：**10 passed, 2 deselected（0.61s）**；`.venv/bin/pytest tests/test_voice_chat.py -k "not voice_routes and not reset_invalidates and not http_disconnect" -v`：**3 passed, 3 deselected（0.49s）**。
- **尚未验证 / 留待后续确认（不宣称已实机验收）**：
  - 推云部署本版后，在登录解锁状态的 Mac 飞书窗口实测「打开飞书 → 搜 Friday → 点联系人进入聊天窗 → 输入你好」。

## 控件树精准定位、剪贴板复合输入与强规划模型路由（2026-11-17，`83ed03c` 已推送）

- **改动范围**：
  - **跨平台系统辅助功能控件树与回读校验（`desktop_node/ui_tree.py`、`platform_base.py`、`platform_macos.py`、`platform_windows.py`）**：macOS 使用原生 Swift `AXUIElement`（开启 `AXManualAccessibility` / `AXEnhancedUserInterface` 以探测 Electron 控件，遍历多窗口并提取精确中心点坐标与聚焦元素）；Windows 使用标准库 PowerShell .NET `UIAutomationClient` 枚举前窗控件与 `BoundingRectangle` 中心。`capture_screenshot` 同步返回 `ui_elements` 与 `focused_element`；`gui_action` 完成后附带轻量 `post_action_readback`（聚焦控件角色/名称/文本值）。Mac 本机真实运行中的「飞书」窗口实测首次编绎含缓存提取出 18 个精确控件（含 `AXButton '搜索（⌘＋K）' (34, 143)`），热运行耗时约 83ms。
  - **按控件索引执行与可靠剪贴板粘贴输入（`desktop.py`、`desktop_tools.py`、`platform_base.py`、`client.py`）**：`desktop_gui_action` 新增 `element_index` 参数（按最近 `ui_elements` 索引精确取屏坐）、`click_and_type`、`paste_text` 与 `submit` 选项；`_paste_via_clipboard` 在发送粘贴快捷键前先尝试备份原剪贴板、写入目标文本并粘贴后恢复原剪贴板，macOS `type_text` 含非 ASCII 文本默认走剪贴板粘贴避免 Electron/IME 丢字。
  - **桌面多步任务强规划模型自动路由（`config.py`、`settings_store.py`、`voice_profiles.py`、`desktop.py`、`text_tool_selection.py`、`service.py`、`app.js`）**：新增可选配置项 `desktop_planner_model`（「技能与知识 → 个人电脑操控 → 规划与视觉模型」）；网页文字请求命中桌面意图或上一轮存在桌面调用/待确认时，若当前为 `realtime` 模式则通过 `build_desktop_planner_config` 自动切换至 OpenAI 兼容文本/工具模型（优先使用已配主文字模型，否则默认百炼兼容接口 `qwen-plus`）走 `ToolConversation` 连续执行并在结束后释放临时客户端，普通文字聊天与设备/网页实时语音主线完全不变。
- **本机最终代码后验证（Mac Darwin / `.venv` Python 3.12.13）**：
  - 真实飞书窗口 `inspect_ui_tree(os_name='macos')`：提取 18 个控件，命中 `搜索（⌘＋K）` at `(34, 143)`。
  - `node --check backend/app/app.js && node --check backend/app/voice.js`、`.venv/bin/python -m py_compile desktop_node/*.py`：通过。
  - `.venv/bin/python scripts/lint_incremental.py`：`ruff=18, pyright=119, baseline=146, new=0`。
  - `.venv/bin/pytest tests/test_desktop_bridge.py tests/test_gateway_trace.py tests/test_personal_kb_isolation.py tests/test_realtime_failures.py tests/test_voice_compat.py tests/test_voices.py -v`：**43 passed, 0 failed（3.62s）**（含新增 `element_index` 解析/越界拒绝、`click_and_type`、`_paste_via_clipboard` 备份恢复及 `build_desktop_planner_config` / `ChatService` 普通聊天 vs 桌面规划路由隔离测试）。
  - `.venv/bin/pytest tests/test_devices.py -k "not real_socket" -v`：**4 passed, 4 deselected（30.95s）**；`.venv/bin/pytest tests/test_knowledge.py -k "not chat_uses and not retrieval_failure" -v`：**10 passed, 2 deselected（0.66s）**；`.venv/bin/pytest tests/test_voice_chat.py -k "not voice_routes and not reset_invalidates and not http_disconnect" -v`：**3 passed, 3 deselected（0.55s）**。
- **尚未验证 / 留待后续确认（不宣称已实机验收）**：
  - Windows 端 `UIAutomationClient` `inspect_windows_ui` 脚本与真实桌面剪贴板粘贴尚未在 Windows 机器实跑。
  - 云端发布后，由 `qwen-plus` + `ui_elements` + `qwen3-vl-plus` 协同完成 Mac 飞书搜人输入框完整端到端实测仍待用户发布重启后确认。

## 视觉坐标校准、macOS 权限显式校验与「小圆」品牌统一（2026-11-17，`167600e` 已推送）

- **真实排查发现（来自用户「打开飞书 → Friday 对话框 → 输入你好」实机截图）**：
  - `desktop_node/overlay.py` 误写了「小安正在操作电脑」，已全部统一为 **「小圆正在操作电脑」**（`client.py` / `__init__.py` 同步改为 `Xiaoyuan`）。
  - Qwen3-VL（`qwen3-vl-plus`）按百炼官方规范默认在 `0..1000` 归一化空间输出坐标，原按 `1280×800` 图像像素比例放大导致点击偏移 20% 以上；`app.html` 静态脚本缺版本号在浏览器热刷新场景可能沿用旧缓存；`platform_macos.py` 在终端缺少 macOS 录屏或辅助功能权限时 `screencapture` 仅拍壁纸、`CGEventPost` 被静默忽略却返回 `ok=True`；`CGEventKeyboardSetUnicodeString` 在 `hotkey` 后未显式清零修饰键；`desktop_gui_action` 缺屏幕核实提醒，导致 `qwen3.8-omni-flash-realtime` 仅执行 2 次 GUI 动作就提前宣称“已输入”。
- **本轮改动**：
  - `backend/app/desktop.py` & `desktop_tools.py` & `tool_dialogue.py` & `app.html` & `main.py` & `app.js`：Qwen-VL 看图改用 `0..1000` 坐标指令并提取边界框/中心点预换算为 `suggested_screen_coords`，新增 `coord_space='norm1000'`；`desktop_gui_action` 返回 `verified_on_screen=False` 与强制复核指引；`TurnTools.summaries()` 保留桌面参数（隐藏输入正文）与关键结果，展开「调用了 N 次工具 · 查看」可见实际点击坐标与看图描述；静态前端资源增加 `__ASSET_VERSION__` 与 `Cache-Control: no-cache`。
  - `desktop_node/overlay.py` & `client.py` & `platform_macos.py` & `platform_windows.py`：统一 HUD 文案为「小圆正在操作电脑」；Mac 启动检查并提示「录屏与系统录音」「辅助功能」权限，截屏/点击无权限时立即报错 `screen_capture_denied` / `accessibility_denied`；`type_text` 清零 `CGEventSetFlags` 并分片间隔输入，`open_target` / `click` / `hotkey` 增加聚焦等待。
- **本机最终代码后验证（Mac Darwin / `.venv` Python 3.12.13）**：
  - Mac 原生 Swift HUD 重新编译缓存：`/Users/ryan/.cache/xiaodan/desktop-hud-9e393a3bc03c`。
  - `node --check backend/app/app.js && node --check backend/app/voice.js`、`.venv/bin/python -m py_compile desktop_node/*.py`：通过。
  - `.venv/bin/python scripts/lint_incremental.py`：`ruff=18, pyright=119, baseline=146, new=0`。
  - `.venv/bin/pytest tests/test_desktop_bridge.py tests/test_gateway_trace.py tests/test_personal_kb_isolation.py tests/test_realtime_failures.py tests/test_voice_compat.py tests/test_voices.py -v`：**41 passed, 0 failed（3.24s）**。
  - `.venv/bin/pytest tests/test_devices.py -k "not real_socket" -v`：**4 passed, 4 deselected（30.94s）**；`.venv/bin/pytest tests/test_knowledge.py -k "not chat_uses and not retrieval_failure" -v`：**10 passed, 2 deselected（0.78s）**；`.venv/bin/pytest tests/test_voice_chat.py -k "not voice_routes and not reset_invalidates and not http_disconnect" -v`：**3 passed, 3 deselected（0.52s）**。
- **尚未验证 / 留待后续确认（不宣称已实机验收）**：
  - 用户机端运行 `desktop_node` 的 `Terminal` 是否已在 Mac 系统设置勾选「录屏与系统录音」与「辅助功能」，以及部署本轮后实际目视确认飞书搜索 `Friday` 并输入「你好」与 Windows 端真机视觉操控仍待下一轮真机实测。

## 全链路执行感知（SSE + 桌面悬浮边框 HUD）与多步连贯操控升级（2026-11-17，`13410ab` 已推送）

- **解决的实际问题**：
  - 用户反馈“如何知道他在执行”且电脑操作期间需要在本机屏幕边缘与顶部看到正在操作的视觉感知；同时反馈“打开飞书并打开某人的对话框”做到打开飞书即停下。
- **改动范围**：
  - **实时 SSE 进度推送（`service.py` / `main.py` / `tool_dialogue.py` / `app.js` / `app.css`）**：`TurnTools` 挂载 `on_progress` 回调并在 `ChatService.turn()` 通过合并队列实时流式吐出 `tool`（`start` / `end`，输入文字自动脱敏为字数）；`POST /chat/stream` 输出 SSE（`session`/`tool`/`text`/`done`/`error`），前端在回答生成期间实时刷新动态状态与呼吸灯工具胶囊。
  - **跨平台屏幕边框与顶部 HUD（`desktop_node/overlay.py` / `client.py`）**：macOS 按 SHA 按需编译轻量原生 Swift `NSPanel`（`.nonactivatingPanel`、`ignoresMouseEvents = true`、`.canJoinAllSpaces | .fullScreenAuxiliary`、`sharingType = .none`，顶部胶囊避开 MacBook Air 刘海区域）；Windows 使用标准库 `tkinter` + Win32 `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` + `WDA_EXCLUDEFROMCAPTURE`（不抢焦点、鼠标穿透、截屏自动隐藏悬浮层）。`_handle_request` 执行前高亮并显示操作名，空闲 `4.5s` 自动隐藏，同时终端按 `logger.info` 输出 RPC 起止耗时日志（支持 `--no-hud` 禁用）。
  - **多步桌面连贯上限与前置等待（`tool_dialogue.py` / `tool_gateway.py` / `text_tool_selection.py` / `realtime_text.py` / `realtime.py` / `platform_macos.py` / `platform_windows.py`）**：激活桌面工具时 `turn_limits` 放宽至 `MAX_DESKTOP_TOOL_ROUNDS = 10` / `MAX_DESKTOP_TOOL_CALLS = 20`（普通轮次维持 `4 / 8`），`Turn` 超时下限放宽至 `90–120s`；`TextToolSelection` 覆盖“打开应用/飞书/找人/对话框”预设线索；`open_target` 启动应用后短暂等待 `0.6–0.7s` 让窗口前置；`order_state_text` 在 `approve_desktop_lease` / 确认恢复后提醒模型继续推进完原目标全部桌面步骤。
- **本机最终代码后实测与验证（Mac Darwin / `.venv` Python 3.12.13）**：
  - Mac 原生 Swift HUD 编译与进程调用实测：`.venv/bin/python` 调用 `ScreenOverlayHUD` 成功编译 `~/.cache/xiaodan/desktop-hud-b92a66648c4a` 并完成 `show` / `hide` / `close` 退出（`overlay_ok`）。
  - `node --check backend/app/app.js && node --check backend/app/voice.js`：通过（0 错误）。
  - `.venv/bin/python -m py_compile desktop_node/*.py`：通过（0 错误）。
  - `.venv/bin/python scripts/lint_incremental.py`：`ruff=18, pyright=119, baseline=146, new=0`。
  - `.venv/bin/pytest tests/test_desktop_bridge.py tests/test_gateway_trace.py tests/test_personal_kb_isolation.py tests/test_realtime_failures.py tests/test_voice_compat.py tests/test_devices.py tests/test_voices.py -v`：**49 passed, 0 failed（83.96s）**（新增覆盖 `/chat/stream` SSE 实时步骤推送、6 轮连续 Computer Use 不触发旧 4 轮上限、`TextToolSelection` 应用名匹配及 `_describe_rpc_for_hud` / `_handle_request`）。
  - `.venv/bin/pytest tests/test_knowledge.py -k "not chat_uses and not retrieval_failure" -v`：**10 passed, 2 deselected（0.91s）**。
  - `.venv/bin/pytest tests/test_voice_chat.py -k "not voice_routes and not reset_invalidates and not http_disconnect" -v`：**3 passed, 3 deselected（0.65s）**。
- **尚未验证 / 留待后续确认（不宣称已实机验收）**：
  - Windows 真机 `tkinter` + Win32 `WS_EX_TRANSPARENT` / `WDA_EXCLUDEFROMCAPTURE` 边框视觉效果与多步真实点击尚未在 Windows 运行验证；
  - Mac 本机视觉效果在 `desktop_node` 重启接云并从网页实际下发「打开飞书并打开某人对话框」后做现场目视确认。

## 方案 A 桌面体验增强、通用应用解析与全系统异常日志中心（2026-11-17，`69ea876` 已推送）

- **真实基线与现场问题（`82afc7c-20261117-093433`）**：
  - 真实 Mac 节点 `ryandeMacBook-Air.local`（`1470×956`）通过 `wss://ryan406.online/xiaoyuan/desktop/v1/` 接入云端；网页对话实测 `观察电脑屏幕 · 684ms` 正确识别前台 Chrome 窗口，触发 `打开电脑应用/链接` 确认卡片并点击「确认执行」执行闭环。
  - 暴露问题与用户新需求：① Mac 开启系统 SOCKS 代理时 `websockets` 报错缺少 `python-socks` 及 60s 空闲超时重连；② `open -a 飞书` 因本地包名为 `Lark.app` 未命中；③ 百炼实时模式下未自动回退 `qwen3-vl-plus` 视觉模型看图定位；④ 连续操控每次均需确认，且模型偶发提前口头承诺「这就帮你打开」；⑤ 硬件语音机器人切换至 Mac 端热区/或云端重启断开时屏幕显示「出错了」，系统尚缺统一可查的报错日志面板；⑥ 希望除飞书外扩展通用中英文应用解析。
- **本轮新增与修复范围**：
  - `desktop_node/client.py`：默认 `proxy=None` 直连（可选 `--use-system-proxy`）、增加 30s 应用层 `ping` 心跳、移除 60s `wait_for` 空闲断连。
  - `desktop_node/platform_macos.py` & `platform_windows.py`：通用应用名解析：中英文常见软件别名表 + macOS `.app` `Info.plist`/`zh-Hans.lproj`/`zh_CN.lproj`/`Base.lproj/InfoPlist.strings` 本地化显示名 + Spotlight `mdfind`；Windows 开始菜单/桌面 `.lnk`/`.url` + 注册表 `App Paths` + UWP `Get-StartApps` (`shell:AppsFolder\<AppID>`)。Mac 本机实读真实 `/Applications` 与 `/System/Applications` 验证命中：`飞书 -> /Applications/Lark.app`、`微信 -> /Applications/WeChat.app`、`腾讯会议 -> /Applications/TencentMeeting.app`、`剪映 -> /Applications/VideoFusion-macOS.app`、`WPS -> /Applications/wpsoffice.app`、`谷歌浏览器 -> /Applications/Google Chrome.app`、`计算器 -> /System/Applications/Calculator.app`、`Antigravity -> /Applications/Antigravity.app`。
  - `backend/app/desktop.py`、`config.py`、`settings_store.py`、`voice_profiles.py`：百炼实时模式下未单设视觉模型时默认使用 `compatible-mode/v1` + `qwen3-vl-plus`（`desktop_vision_model` 可在「技能与知识 → 个人电脑操控」选填覆盖）。
  - `tool_gateway.py`、`tool_dialogue.py`、`schemas.py`、`app.html`、`app.js`：`approve_desktop_lease` 支持「确认并免问电脑操控 (3 分钟)」（180s 租约，仅覆盖 `desktop_open`、`desktop_gui_action`、`desktop_set_clipboard`；`desktop_run_command` 与外部 HTTP API 仍强制逐次确认）；工具指令禁止未审批/未收到成功结果前口头声称已完成。
  - `backend/app/error_log.py`、`devices.py`、`device_realtime.py`、`voice_transport.py`、`service.py`、`main.py`、`app.html`、`app.js`：新增 `ErrorLogStore`（写入 `assistant_state.sqlite3` `system_errors` 表，上限 300 条，自动脱敏 `?key=`/`Bearer`/密钥），捕获硬件设备（OTA 403、WS 建连/保活/断连、语音桥告警与异常）、桌面节点（鉴权、超时、断连、视觉模型 HTTP 错误）、模型/工具执行失败与 FastAPI 4xx/500 异常；新增 `GET/DELETE /api/insights/errors` 及「执行洞察 → 异常日志」分页筛选与清空面板。
- **本机最终代码后完整自动化验证（Mac Darwin / `.venv` Python 3.12.13）**：
  - `node --check backend/app/app.js && node --check backend/app/voice.js`：通过（0 错误）。
  - `.venv/bin/python -m py_compile desktop_node/*.py`：通过（0 错误）。
  - `.venv/bin/python scripts/lint_incremental.py`：`ruff=19, pyright=120, baseline=146, new=0`。
  - `.venv/bin/pytest tests/test_desktop_bridge.py tests/test_gateway_trace.py tests/test_personal_kb_isolation.py tests/test_realtime_failures.py tests/test_voice_compat.py tests/test_devices.py tests/test_voices.py -v`：**47 passed, 0 failed（83.05s）**。覆盖桌面桥梁/WSL、Windows `.lnk` 与 UWP mock、Mac `Lark.app` 别名与百炼 `qwen3-vl-plus` 视觉回退 mock、`approve_desktop_lease` 作用域隔离、`ErrorLogStore` SQLite 持久化/上限裁剪/密钥脱敏与 `GET/DELETE /api/insights/errors`，以及既有网关、个人多库、实时失败、语音兼容、真实 socket 设备与音效测试。
  - `.venv/bin/pytest tests/test_knowledge.py -k "not chat_uses and not retrieval_failure" -v`：**10 passed, 2 deselected（0.81s）**。
  - `.venv/bin/pytest tests/test_voice_chat.py -k "not voice_routes and not reset_invalidates and not http_disconnect" -v`：**3 passed, 3 deselected（0.54s）**。
- **尚未验证 / 留待后续确认（不宣称已实机验收）**：
  - Mac 本机未安装 `playwright`，尚未运行 `node tests/voice_browser.cjs` 浏览器 DOM 回归及人工点击新版「执行洞察 → 异常日志」页面。
  - 云端 `47.112.16.195` 尚未拉取本次提交，Windows 端真实开始菜单/UWP/`SendInput` 点按、Mac 端真实开启 `飞书` / 百炼 `qwen3-vl-plus` 看图多轮操控及真机设备报错上云采集，待推云后由云端发布并重连节点实测确认。

## 个人 Agent 底座重构、Agent 优先 UI 与跨平台 Windows/Mac 桌面操控（2026-11-16，历史基线记录）

- **改动范围**：
  - Agent 内核与确认门禁：`tool_gateway.py` 升级 `SideEffectConfirmationStore`（签发 `approval_id`、300s TTL、脱敏参数预览、`pending_approval` 持久化到 `ChatResponse`/`TranscriptMessage`），`main.py` 新增 `POST /api/approvals/{approval_id}`；`config.py` / `settings_store.py` / `voice_profiles.py` / `prompt_builder.py` 新增 `agent_profile` 并注入全渠道系统提示；`realtime.py` 暴露受确认保护的写与桌面工具。
  - Agent 优先单用户 UI：`app.html` / `app.js` / `app.css` 移除「助手配置」内冗余双重勾选框和第二个保存按钮，改为「Agent 与档案」「技能与知识」（开启单开关自动同步 `/api/assistant/selection`，知识库行内挂载与新建默认挂载）「终端节点（Windows/Mac + AtomS3R）」，对话中呈现工具胶囊及交互式确认卡片，保留 Codex 灰阶主题。
  - 跨平台桌面桥梁与 Computer Use：`backend/app/desktop.py`（`/desktop/v1/` WebSocket、Token 持久化与轮换、断线重连防僵尸锁、屏幕视觉解析与坐标自适应换算）、`backend/app/desktop_tools.py`（9 个读写/GUI/命令工具与敏感路径 `.env`/`.ssh`/私钥硬拦截）、`desktop_node/`（Windows `ctypes`/PowerShell/.NET 与 macOS `CoreGraphics`/`screencapture`/`sips`/`pbpaste` 零重型依赖双端客户端）、`deploy/assistant.caddy` 新增 `/desktop/v1` 代理、`backend/run_devices.py` 提高网关 WebSocket `ws_max_size=8*1024*1024`（`/xiaozhi/v1/` 维持 `12000` 字节/包上限）。
- **已验证并提交为 `82afc7c`（随后在云端部署 `82afc7c-20261117-093433`）**：该基线在提交前通过 JS/py_compile/`lint_incremental`（`new=0`）及当时 `36 + 18 + 3` 项 pytest。

## Git开发快照与新电脑接手（2026-11-15）

- 用户在文档治理后明确授权将项目保存到Git，以便其他电脑/Agent统一接手。使用既有 `HunterLzap/xiaoyuan` 的main，不另初始化仓库、不建新分支、不强推；实际提交号和远端结果以Git历史为准。
- 本次保存此前已经存在的部署适配、工具/Token/上下文优化、测试源码、文档治理结果，以及保留的新动画/UI/TCP实验。**保存实验源码不等于上线或已通过听感**；线上稳定release继续独立运行，不能从main整包部署/刷入。
- 运行副本与工作树的文档保持同版；原电脑E盘路径、PID、COM3、SSH私钥路径与本地证据只作原环境记录。新电脑以clone根目录为准，阅读AGENTS→START→任务相关专题，完整步骤在handoff。
- 私有.env、模型/设备凭据、数据库、知识库原文、录音样本、SSH私钥、虚拟环境、logs/output原始记录及构建产物不进入本次Git快照。仓库保留结果摘要，缺原机附件时标为无法独立复核，不因此重新调用模型或修改设备。
- 本轮没有新增功能逻辑、运行产品测试、发模型请求、部署、重启或设备操作；卡顿继续按用户要求暂缓。提交前核对实际暂存清单与凭据排除情况，不将提交/推送当作运行验收。

## 证据索引与有效范围

下表只汇总已有记录，不表示本轮重跑。所有原始log/JSON/output位于Windows运行副本 `E:\xiaodan`，没有为了文档镜像复制私人数据进Git。下面绝对路径在本机和repo-export文档中都指向同一份原始证据。

| 日期/环境 | 证据 | 可确认的结果 | 不覆盖/注意事项 |
| --- | --- | --- | --- |
| 11月15日 / Git与代码只读 | Git HEAD bd639a9，前一提交ead6381；工作树在repo-export | 稳定基线确有语音修复；现工作树含未提交实验，不等于在线代码 | 本轮不提交、不还原工作树、不部署；本机磁盘不等于旧进程已加载 |
| 11月15日 / 历史本机测试 | [发送/播放日志](E:/xiaodan/logs/pytest-send-playback-finish-b8e4a2a-20261115.txt)、[动画批次日志](E:/xiaodan/logs/pytest-robot-ui-pack1-20261115.txt) | 两份末尾均15 passed、1 warning，分别7.37s/25.68s | 是各自当时代码的自动化结果，不是当前全仓重跑或设备听感；动画批次通过不证明动画无回归 |
| 11月8日 / 本机真实资料 | [双库记录](E:/xiaodan/output/regression-kb-two-lib-20261108.json)、[历史矩阵H/S节](E:/xiaodan/output/regression-matrix-20261108.md) | 关键词/hybrid双库各仅命中本库，向量参与有审计佐证 | 管理试查与助手选库不同；不覆盖当前云端真机语音RAG |
| 11月8日 / 取消契约复核 | [cancel-recheck](E:/xiaodan/output/cancel-recheck-20261108.json) | recheck=21/21；首字前可只有user.interrupted，无complete，空历史不能算通过 | 原始初测预期不同、旧失败保留；部分JSON中文标签乱码，数值/结构仍可核，不改写原始文件 |
| 11月8日 / 订单C8复核 | [C8复核](E:/xiaodan/output/order-confirm-c8-recheck-20261108.json) | recheck=5/5，确认后实际按BH1001发送、无PH1001猜测 | HTTP400/INVALID_ORDER_ID是业务拒绝，不能写查单成功；该文件不能独立证明整体35/35 |
| 11月8日 / 客户端实时WS | [guard结果](E:/xiaodan/output/voice-order-guard-results-20261108-183734.json) | 历史矩阵S节核为歧义8/8、天气6/6，共14/14 | 显式PH1001的实时音频输入缺PCM未验证；客户端收到音频不等于设备播完 |
| 11月15日 / 云端网页实时文字 | [tasktools-final](E:/xiaodan/logs/tasktools-final-20261115.json)、[复合指令](E:/xiaodan/logs/tasktools-compound-final-20261115.json) | 天气/追问真实get_weather；未知需求经_load_task_tools再查询；逐响应Token保留 | 不覆盖语音任务工具路由，也不承诺所有请求都省Token |
| 11月15日 / 文字驱动百炼音频 | [语音首批](E:/xiaodan/logs/voicelean-first-batch-20261115.json) | 报数零工具、3796输入/33输出（文字7/音频26），收到99840字节PCM | 不是麦克风输入/扬声器听感；不能当设备卡顿已修 |
| 11月15日 / 原控制执行方法 | [意图执行记录](E:/xiaodan/logs/voice-control-execution-20261115.json) | 报数不调音量，明确音量进入真实执行层 | 当时device_offline是实际失败，不是设备音量已调整 |
| 11月15日 / 供应商直连调查 | [语音路由调查](E:/xiaodan/logs/voice-routing-investigation-20261115.json) | “那明天呢”未调用工具、误复用旧日天气；响应开关被回显 | 配置探查未输入音频，不是完整真实语音时序验证，未接生产 |
| 11月15日21:26–21:28 / 云端真设备 | 本文件“真实设备云端语音接通”记录；云端shared/logs/device-audio-turns.jsonl，session/turn见该节 | 真实收到报数并答复；34包全发、最大间隔61ms，无网关断供 | 用户仍反馈整段随机两处卡顿后继续，根因未定，已要求暂停；缺该轮设备收包/解码/播放记录 |

### 本次治理检查（2026-11-15）

- 扫描根目录、agent、output、logs、tests、固件本板自有文档及Git镜像；区分上游固件/工具链/模型许可/生成缓存，保留上游原貌，不将其测试当本项目结果。
- 核查代码中的TextToolSelection使用范围、控制意图校验、Token字段、6轮/6000字符默认、4轮/8次业务边界和项目AEC实现；结合Git提交与既有JSON/log，修正“未部署/未切云/无Git/多库未实现/本板永不能AEC”等过期结论。
- 总入口为AGENTS；当前快照START、结果progress、要求PRD、决定decisions、设计architecture、依赖roadmap、操作operations、判定acceptance各司其职。README/STATUS/agent导航不再维护多份运行快照。
- 保留27份治理前规范快照、两份原始咨询；旧output报告/计划/动画草案、故障报告和固件开发日志原位归档，不改原始JSON/log。位置见 [归档索引](../archive/2026-11-15/README.md)。
- 用户最新卡顿描述已记录为“整段随机两处停顿后继续”，明确暂不解决；本轮没有业务修改、模型调用、服务/设备操作或产品测试。
- 整理后检查：32份入口/规范文档的177个本地引用，在运行副本及Git镜像均无缺失；25份原位归档/产物入口/本板文档的45个本地引用无缺失。修复了15个只在工作树中失效的历史证据相对链接，统一指向实际运行副本，未复制私人数据。
- 63份明确文档镜像（含30份归档文件）逐字节一致；27份治理前快照在同步前已与原工作树核对一致。活动规范中未再检出未部署/未切OTA/无Git/多库未实现/旧默认AEC断言；历史原文仍保留在归档或按日期过程记录。
- 本轮治理前后非文档Git差异SHA256均为 `f8ca80a1b654216c92efa4399ac83e259eace4c5bba339c7f6cef058e191bb6b`，原有非文档改动未变；没有提交或部署。外部站点链接未重新联网验证，归档快照内部旧相对链接按历史目录理解，不作为当前导航。

## 历史过程记录（只作证据追溯）

以下每节都是标题所指日期/版本的快照；其中的过程性下一步/权限/在线状态不可直接执行。后续修复或更正以相应新日期记录为准，不从单一旧报告推导现状。

## 真实设备云端语音接通，用户仍反馈卡顿（2026-11-15 21:32）

- 真实连接时间21:26:45.471166+08:00；会话6ee66d7b-c3ac-42b9-8d75-475cafb5d9a0保存5轮设备问答。报数turn_id为5d516f73-2aae-4539-821f-71b1f5f735c5，用户“从一数到三。”，助手“好呀，一、二、三。”。这次确实经自有云端及配置的百炼实时链路，不再只有OTA200证据；用户现场仍说卡顿，未确认流畅。
- 该轮原始PCM2400ms，处理后1992ms，34包编码/发送均完成（补齐2040ms），CRC一致，无丢弃/取消/发送失败；网关最大发送间隔61ms、断供0、队列耗尽0、发送调用总耗时3.15ms。speech_stopped至首包903ms，模型completed，1个响应段。其余4轮网关最大间隔61–65ms，均无断供。服务发送连续不能证明设备接收/解码/I2S连续。
- 报数原始PCM已有4段≥120ms低能量段、共1100ms；处理后4段共880ms、最长280ms。可能包含数字间正常停顿及句尾静音，不能仅凭此认定合成或变调故障，也未保存录音供回听。现有语速1.2/音调+3未修改。
- 设备最近状态回报network.ssid=CMCC-g24u、signal=weak；状态由既有15秒保活读取，不是实时RSSI采样轨迹。弱信号是调查线索，未证明卡顿由网络造成。21:28:27.839624+08:00会话结束，日志关闭码1000、last_error空；未取得设备状态机证据，不能直接认定“退一下吧”已正确回待机。
- 本轮只读云端会话/API/现有音频指标和稳定固件代码，没有额外模型请求、设备操作、串口打开、服务重启或业务参数修改。当前缺设备这轮的收包/解码/播放记录；先区分自然停顿与字音断裂，不盲调缓冲、不再改OTA/鉴权。工具/Token/动画工作继续暂停。

## 设备重新上电：真实OTA鉴权通过，语音连接待唤醒（2026-11-15 21:25）

- 用户明确反馈拔插USB完成。本轮仅检查云端API、Caddy请求记录和USB枚举，没有打开串口/复位/烧录或模型调用；COM3状态OK，无串口采集占用。
- Caddy在北京时间21:25:07.891记录真实设备POST /xiaoyuan/xiaozhi/ota/，带key，HTTP200；云端API last_bootstrap同步为2026-11-15T21:25:07.890745+08:00。地址保存与现有鉴权已经通过；没有理由继续要求用户改URL、改路径鉴权或关闭鉴权。
- 语音配置仍realtime/bailian/qwen3.8-omni-flash-realtime，rt_voice匹配原“塔菲”复刻记录。last_connected尚空、connected/ready为false、last_error为空，无语音会话记录。待机期间尚未开启语音通道不能直接判失败，下一步需用户叫“塔菲”并说一句话，AI再查真实WS与响应。
- OTA200只证明启动配置请求被服务接受，未证明设备已播放正确音色或唤醒/对话/待机全部通过。工具、Token、转写后响应控制、动画优化继续暂停。

## 设备接云与音色优先：完整OTA地址缺失鉴权，实际403（2026-11-15 20:57）

### 更正（21:22）：NVS实际已保存完整地址；403早于最后保存

- 停止自建串口采集后，用ESP-IDF esptool只读读取NVS分区0x9000/0x4000，再以官方nvs_tool解析。活动页面的`ota_url`字符串长度为93（含结尾0），内容是完整`https://ryan406.online/xiaoyuan/xiaozhi/ota/`且含`?key=`；另有一条已擦除的旧本机URL和一条已擦除的无key云URL。原始NVS文件只用于本地解析，未输出密钥。
- 对应云端Caddy记录：设备20:53–21:02的POST均无key、均403；用户最后保存后没有新的设备OTA POST。因此“设备最终保存缺key”的判断被推翻，之前建议改路径式鉴权也没有证据支持，未实施。当前状态不是鉴权设计故障，而是最后一次保存后未完成一次正常启动请求。
- 为触发检查，本轮停止自有采集并做只读NVS读取；esptool结束时的RTS复位使设备进入`DOWNLOAD(USB/UART0)`，后续`esptool run`未恢复应用日志。该下载模式是AI复位的副作用，没有写flash、没有刷固件。需要用户拔插USB供电一次恢复应用，不需要再改任何地址或按键。恢复后继续核对真实OTA请求、云端bootstrap/connected和塔菲音色。

- 用户暂停工具优化，报告音色像小智、授权自己修改OTA地址后又报告界面像新动画、按屏幕提示配网。本轮先查真实接入/固件状态，没有刷固件/资源、改后端或关闭设备鉴权。
- 本机与云端运行API配置均为bailian/qwen3.8-omni-flash-realtime，rt_voice相同，匹配data/qwen_voices.json中的原“塔菲”复刻。此前本机last_connected为16:03:39，云端一直没有last_bootstrap/last_connected；不能把云端优化当设备正在使用。
- 恢复读取既有串口后追到完整历史：16:33启动后一直请求旧本机OTA，16:34至18:09连续网络失败。18:09:03出现No protocol specified in the OTA config, using MQTT，随后18:09:04进入idle，20:40唤醒和对话正常进行但没有经过两套自有服务。稳定application代码在无有效MQTT/WS配置响应时确实选择MqttProtocol，可使用已有NVS配置；这条路径解释音色来源偏离，不能归因于云端更换音色。
- 用户配置后COM3原采集在20:51:10因USB I/O中止退出。20:57恢复既有脱敏采集，PID25704，未传ResetDevice，也未执行烧录；但新日志紧随打开串口记录rst:0x15 USB_UART_CHIP_RESET，说明实际发生一次USB启动，不能宣称本轮完全未重启设备。
- 最新启动指纹2.2.6、Nov11 2026 23:24:33、ELF67687035c，和15:59恢复记录一致；idle/listen/think/speak分别16/12/10/10帧全部加载。尚未读取当前assets分区哈希或取得画面，不能仅凭应用指纹否认用户看到新图。我们OTA尚未成功返回配置，不能说本次接云下发了新动画。
- 明确接入失败原因：20:57:22证书验证和ryan406.online:443连接成功，OTA返回403；串口保存URL只有/xiaoyuan/xiaozhi/ota/，没有key参数，后续重试仍403。devices.bootstrap在bootstrap_authorized失败时即403，last_bootstrap仅授权后更新，因此之前空记录不等于没有HTTP到达。上一条回复单独列出无key示意地址，易被用户误复制，已说明并致歉。已将API返回的完整设备OTA地址重新复制到剪贴板，保存于项目私有`.cache/private/device-cloud-ota-address.txt`，不输出密钥，不放日志/源码，不关闭鉴权解决。
- 稳定板级按钮代码：starting时单击EnterWifiConfigMode，否则ToggleChatState；正常idle是开对话，activating分支先改idle。本次实际按下瞬间不在可用日志内，无法断言提示配网的确切触发；先修正完整OTA使启动校验成功，再看按钮、待机、音色，避免把启动未完成混为动画回归。
- 当前需要用户在设备配网页自定义OTA框完整替换为剪贴板内容后保存；用户已明确授权切接入，仍未授权刷固件/动画。AI继续从脱敏串口和真实云端last_bootstrap/WS记录确认，不能以地址保存或HTTP200代替设备语音听感通过。工具/Token/转写后选工具继续暂停。

## 天气追问跳工具调查与转写后选工具接入评估（2026-11-15）

- 用户要求先查清“那明天呢”跳工具、参考成熟项目评估完整转写后选工具，保留唤醒/对话/待机，不再堆提示。本轮未改业务代码或提示、未部署/重启、未动设备/OTA/新动画。云端仍bd639a9-voice-20261115，服务MainPID268587/active/NRestarts0、发布manifest全部匹配；本机8000/8003仍PID17156。
- 新增直接使用真实供应商和原工具执行层的诊断脚本 `logs/inspect-voice-routing-20261115.py`，只进行配置往返及一组两问的连续会话；不创建测试后台/模拟API/合成麦克风。以与生产一致的response.function_call_arguments.done、response.output_item.done和response.done三处合并调用，保存实际arguments/output、上游回显工具及完整事件计数，补齐上轮直连脚本只查看最终output、未存天气参数/正文的证据缺口。
- 实际首问“查北京今天天气”：上游确认7工具，函数调用事件完整，真实get_weather(city=北京,days=1)成功。返回数据时间2026-11-15T20:15 Asia/Shanghai，coverage仅2026-11-15，今日阴、最高11.2/最低4.1、降水概率0；没有11月16日预报。随后的“那明天呢”仍在同一连接，上游确认7工具且get_weather仍在，转写是完整文字且response.create手动发出；本轮没有任何函数调用事件/输出，直接回答“明天北京还是阴天，气温在4.1到11.2度之间，降水概率0%”。已确认将今天值错误用于明天，不能解释为有效复用已取得的明日预报。
- 因此这次不是工具未下发、权限拦截、天气源站失败、ASR没听全或VAD抢先触发。完整语句与工具定义都在，模型仍选择直接答；不能推断其内部随机决策原因。应用层缺口可定位：output_blocked/control_error只约束控制/订单，没有查询结果的目标日期/城市覆盖检查，无工具响应可直接放行。天气summaries未保留request/response，重建active_context只有文字问答，也缺少可靠的结构化续接字段；但连续连接已复现，不能把新连接历史裁剪说成此次唯一根因。
- 官方边界：百炼Function Calling文档明确Qwen-Omni-Realtime不支持tool_choice/parallel_tool_calls，因此不能直接套required强制工具。工具下发与“必须拿到符合目标的真实结果”必须分开。建议复用TurnTools的真实执行，记录少量任务参数/结果覆盖元数据；明确的天气省略追问结合最近真实工具状态解析日期，已有成功数据确实覆盖目标才复用，不覆盖则实际查询，失败如实播报；不把所有“明天”都路由天气，不从上一轮口头回答反推事实。
- 协议实测：另开供应商连接，不发送音频、不调用response.create；默认server_vad/create_response=true/interrupt_response=true。更新create_response=false且interrupt_response=true，session.updated确实回显false/true，server_vad、0.5阈值、800ms静音、300ms前缀均保留；恢复true亦确认。只证明当前北京qwen3.8-omni-flash-realtime接受配置，不冒充已确认“音频仍切段/出转写/不会自动回答/插话正确”。
- 成熟实现：LiveKit官方PR6642（2026-08-02合并）和当前llm/_realtime/openai.py将create_response=False视为由客户端控制回答，明确interrupt_response为独立开关；这是可参考的职责拆分，不是百炼行为证明，也不照抄其关闭打断的配置。LangChain官方动态工具选择与State保留tool results的做法可复用，沿用现有注册表/SQLite，不安装框架或增加每轮分类模型。
- 已形成实际接入点：RealtimeTurn.open配置保留VAD但不自动回答；receive完整转写时先走现有结束意图，再启动带原turn_id的准备任务；复用TextToolSelection的候选并集/同轮加载思路但保留语音提示，等待session.updated后才response.create。接收循环继续处理事件，不能在同一receive处理分支等待一个也由自身接收的确认，避免死锁；新speech_started沿用原取消/迟到隔离。run_tools复用原执行和续答，补充查询结果覆盖检查。尚未把这套时序接入当前运行链，也未做真机听感验证。
- 证据原文 `logs/voice-routing-investigation-20261115.json`，已同步本机；包含真实天气结果、调用事件计数和配置回显，无密钥/完整角色提示/音频录音。成熟资料与代码链接见architecture最新节。

## 语音首批优化：云端已生效，本机激活受阻（2026-11-15）

- 用户授权Token明细、工具意图校验、提示说明去重；按任务加载仅讨论可行性。最终云端 `bd639a9-voice-20261115`，tasktools稳定release及原配置/数据/音色保留。只改tool_dialogue/prompt_builder两个业务文件；没有commit/push、设备操作、OTA/固件/新动画或Caddy修改。
- 用量和控制校验复用已有共用实现，不另造语音统计或权限框架。RealtimeTurn原有response.done→TokenUsage.from_provider→combine_usage→历史/页面流程保存文字/音频/缓存及逐响应用量，缺项不补0。可变更控制工具仍只在工具任务内等待本轮转写，沿用原turn_id、取消和迟到隔离；普通音频不新增转写等待。
- 最终提示只删除与函数定义重复的工具名单，以及通用规则已覆盖的末尾闲聊提醒；原规则、角色、语音朗读/首句/完整报数、专属工具说明和追问规则原文与顺序均保留。7工具配置2817→2630字符，只有两处delete，少187字符，不冒充Token节省；文字compact与默认提示均逐字一致。realtime/device_realtime/audio_fx/voice_transport/speech_text/prompt_context/tools/schemas与tasktools父版原文一致；开发工作树动画增量没有打包。
- 最终真实文字输入→百炼语音输出：报数1 2 3、零工具、输入3796/输出33/总3829；输出文字7、音频26，1次响应，收到99840字节PCM，仅证明供应商输出，不代表扬声器出声，也没有输入音频用量证据。全量语音工具定义/朗读规则仍发送，不能套用网页文字1210输入或46%降幅。证据 `logs/voicelean-first-batch-20261115.json`。
- 真实生产控制方法直接执行：报数plan为空、无控制调用；明确音量30真实执行set_device_volume(volume=30)，设备离线返回device_offline和失败文案。server_execute_explicit返回ok仅表示处理过，不等于工具或设备成功。故意给报数请求传volume=50在原执行层返回control_intent_required/未执行。上述没有模拟API或伪造设备成功；也未覆盖完整音频事件链。证据 `logs/voice-control-execution-20261115.json`。
- 探查中发现文字驱动语音可能跳过天气追问工具，也可能只口头承诺控制；这类直连探查不包含生产RealtimeTurn的输出拦截/明确控制补执行，不能混为生产全链路。天气源站另有geocode200/forecast连接失败，曾恢复取得真实天气；追问仍出现无工具数值。缩写和补强提示未可靠解决，已放弃该方向，最终仅删重复。没有定位追问现象的基线因果，不声称已经修复或归因于真机回归；待后续专门结合真实语音/响应控制证据处理。初始与中间失败保留在 `logs/voicelean-live-20261115.json`、`logs/voicelean-intermediate-20261115.json`、`logs/voicelean-continuous-20261115.json`，不把它们写成通过。
- 已读百炼官方客户端/服务端事件与LiveKit轮次控制：用户提议“完整转写后再选工具”在架构上可行；当前server_vad会自动启动响应，转写completed与响应不同步。要让选择赶在首响应前，须协调自动响应触发、session.updated与原turn_id/打断/结束意图，不能仅在转写回调换定义后假定首响应已使用新工具。未未经验证设置create_response等参数，未改VAD或改走独立STT/LLM/TTS。
- 云端最终发布hash全匹配，真实网页语音WS返回ready，服务active/NRestarts0；本机仍PID17156，启动于2026-11-15 15:58:28，运行OpenAPI仍仅3个旧Token字段。两次重启命令在执行前被自动审批以blocked by policy拒绝，未改用其他杀进程方式绕过；因此本机磁盘修改尚未生效。真机唤醒、连续对话、插话与退下待机仍需设备接通后的现场确认，本轮不标通过。

## 按任务下发工具定义与同轮加载已上线（2026-11-15）

- 授权：继续做按任务工具定义，保留正常调用、复合指令、“那明天呢”追问和稳定语音。参考LangChain官方预注册工具按上下文/状态选择、Anthropic按需加载与常用能力直接提供；Anthropic明确小于10工具时单纯先搜索可能收益有限，因此采用预加载＋同轮补充，不安装新框架、不增加每轮分类/规划请求、不使用百炼未确认的defer_loading参数。
- 新 `TextToolSelection` 仅在RealtimeTextProvider创建：当前任务线索/控制计划与最近一轮实际工具调用取并集。线索只决定预加载，不删除能力、不成为执行权限；未预选的已启用能力保留在加载入口目录。复合任务可多选，最近天气工具保留给省略式追问。没有硬性闲聊/报数白名单或只取一个候选。
- `_load_task_tools` 在本轮独立ToolRegistry中注册，复用TurnTools的JSON校验、最新选用范围、审计、call_id幂等、结果回填。加载只提供原已启用能力的定义，不执行业务、不提升权限；所有真实调用继续原Schema/控制意图/设备回读。业务8次调用/4轮循环额度不被加载占用；成功加载必须有新工具，失败/重复加载仍受现有循环上限约束。加载模型响应及用量照常累计，不宣称免费。
- 百炼在response.done后，通过官方session.update更换工具定义与完整文字提示，等待session.updated再续答；未改变定义的普通工具续答不额外更新。加载新定义后同轮单调保留已选工具。加载初次遇get_weather(location/date)校验失败，真实调用未发出；已回填真实参数Schema，最终city/start_date/end_date正确，不做参数别名猜测或静默放宽校验。
- 实际报数会话 `4e9a71bf-b156-47b8-adf4-81ce3aeca1fa` 回复 `1、2、3`，输入1210/输出6、1次响应、零工具；寒暄 `0230dd1a-28ec-4b4f-80f4-41a8e991b0ee` 输入1201、1次响应、零工具。上一版对应1676/1667，各减少466输入，约28%；相对最初2236/2227约46%。不把该比例推广到带检索正文或加载续答的任务。
- 最终天气会话 `2dec2334-69f8-444a-a442-75726a5ff0da`：北京今天天气及“那明天呢”分别get_weather=ok，均2次模型响应，无加载步骤；服务日志显示后者直接沿用get_weather。控制＋报数 `0e3449ca-14cc-450e-ba97-75efa901eac8` 真正请求volume=30，如实device_offline，同时继续数一二三，未冒充成功。
- 最终复合会话 `ed0b55dd-5092-4ff2-b5d4-9cfdaf3a5794` 同时get_weather/search_personal_knowledge=ok，2次响应，5个真实资料片段与引用；没有因选单一工具而漏掉另一项。引用是已上传roadmap的历史内容，不代表该旧文档事项仍是当前项目状态，未擅自更新知识库。
- 无预加载提示词的“北京明天适合室外晾被子吗？结合真实气象数据”会话 `d532a2da-66ad-4cef-bf10-8e8211e40004`：initial active=[]；随后加载get_weather并成功查询，3次响应、输入4862，完成真实回答。证明未预选能力可补充；相比直接下发会多一次模型续答，并非所有任务都更便宜/更快。
- 外网问题单独记录：首次天气与复合调用出现weather_unavailable，知识库仍成功；直接源站检查geocode/forecast均200，随后上述天气链与复合任务真实复跑成功。旧失败完整保留在 `logs/tasktools-live-20261115.json`；最终在 `logs/tasktools-final-20261115.json` 与 `logs/tasktools-compound-final-20261115.json`。不新增天气供应商切换、伪数据或自动重试层。
- 发布 `bd639a9-tasktools-20261115`，只更新tool_dialogue/realtime_text并新增text_tool_selection；父release与shared配置/历史/音色保留。新旧语音工具指令逐字一致，7个语音/提示模块原文不变，发布清单hash无差异，active/NRestarts0、约94MiB。本轮云服务必要重启；Caddy、本机服务、模型/音色、OTA、固件、新动画未动；文字功能通过不能自动写真机听感通过。

## 输入组成实测与文字提示精简（2026-11-15）

- 用户要求拆解两千多输入、参考成熟做法精简且不影响稳定语音。线上截图对应会话 `ec8f7082-e1e0-4314-95d6-efca5ecdab34` 首轮：用户原话2字符、没有早前消息、没有工具调用，输入2227/输出13。不是旧历史全文、知识库正文或音频造成此轮开销。
- 对同一百炼模型、原始文字配置和同一报数请求执行6次逐块增加的真实计量：问题/协议23；加角色后620（差597）；加时间/诚实755（差135）；加工具规则1186（差431）；加重复追问提醒1248（差62）；加四工具定义2236（差988）。角色847字符、时间/诚实224字符、工具规则815字符、重复提醒104字符；四工具为M5官方资料、个人知识库、天气、设备状态。方法是固定顺序的usage边际差分，不能称各部分天然独立Token数或供应商账单逐项拆分，不能把字符数冒充Token。脚本 `logs/measure-input-composition-20261115.py`、结果 `logs/input-composition-20261115.json`，不存密钥或完整角色提示。
- 参考Anthropic context engineering（保留高信息量、删除重复、最短不等于最好）、工具描述明确触发/参数，以及LangChain在调用入口变换prompt/工具暴露的机制；不安装新框架、不切模型、不加前置分类或规划请求。
- 新 `compact` 仅在RealtimeTextProvider显式启用，prompt_builder对voice一律关闭，其他原有调用默认原文；自定义业务/订单工具场景仍使用原完整系统规则。保留完整用户角色847字符、当前北京时间、诚实约束、引用/权限/控制执行规则；合并文字重复规则、移除工具名称的重复清单，缩短天气与个人检索描述。深拷贝仅改描述，工具名称、参数、必填/类型/范围/格式/额外参数约束不变，原全局定义未被修改。
- 代码比对确认同一配置下语音完整提示与上一版逐字一致，非compact默认文字提示也逐字一致；新旧去description后的工具Schema完全一致。realtime.py/device_realtime.py/audio_fx.py/voice_transport.py/speech_text.py/prompt_context.py均与上一release逐字一致，不改语音音频处理。
- 初次真实精简报数输入1649、零工具，但多说开场；寒暄“塔菲”因状态工具描述触发条件被删过多而查设备。根据真实失败恢复设备状态完整描述、明确仅用户询问状态/读数时调用，补回用户指定仅数字/正文时直接交付的格式规则；没有用关键词黑名单或额外分类请求掩盖问题。
- 最终线上报数会话 `903f891d-f386-4c3f-8411-a0742f705f11`：回复 `1 2 3`，输入1676/输出6/总1682，零工具；对比旧2236输入少560（约25%）。最终寒暄 `fef9f0c6-c451-4ff2-9c96-1e3c031e5ac8`：输入1667/输出11，零工具；对比截图2227同样少560。记录 `logs/textlean-final-20261115.json`。金额与各类任务节省比例不能由这两条泛化。
- 同一真实文字会话 `ab668906-7831-466f-8561-409e30c9fadb` 中，禁止调音量后报数零工具；明确音量30正常调用并如实device_offline；北京天气和省略式“那明天呢”分别真实get_weather成功，来源注明Open-Meteo。首次记录 `logs/textlean-live-20261115.json` 保留失败，不冒充最终成功。
- 已部署 `bd639a9-textlean-20261115`，父 `bd639a9-agent-20261115` 保留。只覆盖4个指定后端文件，shared/.env/数据/音色保留；云端xiaodan必要重启，本机服务、Caddy、设备OTA/固件未动。真实语音听感没有在本轮重测，不把文字精简比例套到语音；同一实时语音连接上下文整理仍保持上一轮边界。

## 工具意图、Token明细与会话内按需记忆已上线（2026-11-15）

- 授权：先工具误调用/Token、再上下文记忆；不换模型/音色、不接新动画、不改设备OTA。本轮无commit/push/烧录，不重启本机服务或Caddy。
- 当前 `bd639a9-agent-20261115`，父release `bd639a9-cloud-20261115` 和shared配置/数据保留。更新11个后端/页面文件，发布清单hash全部匹配；device_realtime.py/audio_fx.py/voice_transport.py/speech_bridge.py与父release逐字一致。云服务active、NRestarts0、约82MiB；不据此推断真机听感。
- 参考OpenAI Agents SDK的tool input guardrail、LangChain短期记忆持久化/trim/工具读取状态、百炼官方response.done usage。复用TurnTools/ToolRegistry/SQLite/现有实时循环，不安装Agent框架或前置规划模型。
- 文字按当前控制意图筛选可变更工具，所有渠道执行前核对意图与明确目标；拒绝记blocked，要求模型回到原任务，不伪报设备故障。省略话题参考最近对话/实际工具记录，遇新话题停止回溯，裸数字无控制话题不默认调音量，否定后的独立控制分句可解析。实时仅可变更控制工具等待本轮转写Event，沿用新轮取消/迟到隔离，普通音频流不等待。
- 真实云请求会话 `42b94123-040c-492f-b976-da3d98b61794`：报数→`1 2 3`、零工具、输入2236/输出6/总2242；禁止调音量后报数仍零工具；音量30真实调用并报告device_offline，未冒充成功。原误调用会话的真实原问题在执行授权函数中拒绝volume=50，error=control_intent_required。结果 `logs/agent-live-20261115.json`。
- 用量统一保存模态details与缓存子项、响应次数和逐次用量，同项全部报告才累计，缺项非0。音量两次响应2519+43和2636+9，总输入5155/输出52/总5207。旧历史不补算；取消/断链未收到usage仍未报告。系统/工具/历史各占的精确Token供应商未提供，不伪造；缓存为输入子集，不重复相加。
- 活动历史重建按最近6完整轮＋6000字符预算，长单条保留首尾原文并标省略，完整SQLite历史不删。只读历史工具限当前会话，返回有限原文/角色/完成状态/截取位置；无跨会话画像、向量模型、每轮总结。正在运行的百炼实时WS未删除旧item，不能称该连接也已受6轮限制；不套用未确认的delete/truncate。
- 真实旧会话 `80f44b9b-1794-4bcf-a350-65bea8d0cc00` 原20消息，活动12条195字符、8条可检索。端到端“最早用户原话”初次查空，查明模型把“用户原话”当内容关键词；改为可选内容过滤＋时间顺序＋角色，复跑status=ok，完整引用第一条用户原话且未执行其中控制内容。记录 `logs/agent-memory-live-20261115.json` 仅存判据/用量，不复制私人原文。
- Chrome新/旧真实会话明细、1次/2次响应、未报告字段均正确；键盘Enter展开、390px无横溢、JS错误0。脚本 `logs/verify-agent-browser-20261115.cjs`；采用Modern Web Guidance的html/content-first-noise-reduction，用原生details/summary按需展开。
- 边界：设备仍未切云，本轮未验证真人麦克风/扬声器。单连接超长语音上下文、永久记忆、缓存折扣、新动画未实施；已有少量真实调用证据，不为形式化指标批量付费重跑。

## Agent策略调研与Token显示已更新（2026-11-15 18:26）

- 用户要求评估工具调用可靠性、记忆/上下文与成熟项目实践，并把Token显示清楚。本轮只落实前端显示：本地运行页、开发源码和云端release的app.js均将消息脚注改为“本轮Token：输入/输出/合计”，缺项显示未报告，不把unknown当0；脚注提示语音可能含音频Token、工具续答合并、总Token非费用。云端只替换静态JS、更新release文件hash，未重启后端/Caddy、未改稳定实时模块、模型、配置或设备OTA。
- 真正Chrome读取原会话6467803d...：页面显示“输入4,321 / 输出34 / 合计4,355”；被中断报数回合显示“供应商未报告”，JS错误0，390px视口无横向溢出。验证脚本 `logs/verify-token-display-20261115.cjs`，没有新模型调用、注入假数据或模拟麦克风。新app.js SHA256为 `34b192870a23bd9bbc12c0f8de3acf85e73c206c1a08f19ef8fbcab7514f5b64`，服务仍PID266293/NRestarts0。
- 修正上轮解释：实时语音同一WS保留供应商上下文，不是本机每轮重发全历史；文字每次新WS发送选定历史。rebuild_context只取最近六轮完整问答且排除中断助手消息，但同一实时WS未按该六轮删除旧项。截图34为输出总Token，可能包含语音模态；当前代码丢弃input/output details，无法精确复原各模态或系统/历史占比。不能把381字被中断报数说成每轮必然全文重发，也不能把34当纯文本输出。
- 公开一手调研参考Claude Code（按需读取、压缩）、Manus（稳定提示前缀、控制动作可用性）、LangChain短期记忆（持久化与trim/summarize分开）和百炼实时Token/API；建议已写入architecture第1节。当前能力已有闭环但工具选择边界/执行意图校验、输入预算、模态用量明细仍有缺口；优先治理这三处，不新增多Agent/每轮规划模型，不用“报数”单词黑名单代替通用控制意图。策略、摘要/检索记忆、缓存等均为建议，尚未实现。

## 稳定版云端部署完成，设备未切换（2026-11-15 17:35–17:59）

- 用户复核页面时提出“从一数到三”误调音量、隐藏“Windows · 本机服务”文案和短句高Token三个问题。已把本地运行页、源码页及云端release中的该文案删除，不重启服务；云端页面仍200。工具误判只读核对：`control_plan('请从一数到三，只回答这三个数字。')` 返回空，服务端没有强制音量控制；实际云端会话 `a12efee9...` 的模型自行返回 `set_device_volume(volume=50)`，设备离线后回答“调不了音量”。`50`不是代码默认值，是模型生成的参数；未改稳定语音/工具逻辑，修复方案待确认。
- Token证据：截图对应本地会话 `6467803d...`，`海飞`后回答“哎，在呢。”的usage为prompt 4321 + completion 34 = 4355，34为输出总Token，可能混合文本/音频。前一轮被中断的报数约381字符保存在完整历史；在同一实时WS中供应商可保留上下文，但本地重建会排除中断助手消息，不能称每轮都重发全文。云端报数文字会话prompt 5527 + completion 48 = 5575；只有三项总量，不能精确分摊系统、工具、历史和音频占比。前一轮中断未收到usage，所以显示“用量未报告/生成已停止/语音已停止”不能与下一轮4355混为同一输出。
- 用户明确授权开始部署稳定版，设备OTA先不动。使用已有SSH密钥；未要求密码。服务发布 `bd639a9-cloud-20261115`，地址 `https://ryan406.online/xiaoyuan/`。从 `git archive bd639a9` 提取backend/deploy/third_party/scripts及依赖文件，仅合入配置/入口/页面/静态资源/设备URL的base-path支持、日志脱敏、shared配置保存与systemd部署适配；新动画、LVGL、UI事件、固件TCP试验及相关测试均未入包。`realtime.py`、`device_realtime.py` 与稳定Git原文核对一致；远端79项文件hash与发布清单一致。包SHA256 `bf9893d6ba3f2c85f2570be6a5ad8822572c652d1c3856bb2f9be0df75136463`，本地 `.cache/releases/bd639a9-cloud-20261115.tar.gz`，未commit/push。
- 远端独立用户 `voice-assistant`、环境 `/opt/xiaodan/.venv`、发布 `/opt/xiaodan/releases/bd639a9-cloud-20261115`、软链接 `/opt/xiaodan/current`；原配置/配对/tools/音色元数据及两SQLite经SQLite backup一致性快照迁入shared，原文/索引仍在知识库；唯一实际音色样本随release保留，未迁Windows虚拟环境、ASR大模型或固件工具链。两SQLite integrity_check均ok，本机源文件未覆盖。`.env`经SettingsStore解析软链接后保存shared目标，保持跨发布配置位置；data/logs/.cache使用共享目录。
- `xiaodan.service`启用并运行：包装进程PID266293、实际后台266294，管理/网关仅监听127.0.0.1:8010/8013，health配置完整、百炼主线 `qwen3.8-omni-flash-realtime`，实际模型返回后upstream_verified=true；采样内存96464896B（约92MiB）、NRestarts=0。AI_EMBEDDING_ENABLED延续本机true；实时主线不安装本地ASR，gateway的audio_enabled=false仅指未配本地speech worker，不代表百炼实时WS不可用。
- 用户随后明确该服务只自己访问、不对外，取消管理登录要求。已移除 `/xiaoyuan` 的 Basic Auth并 reload Caddy，删除临时登录文件及access.env中未使用的用户名/哈希；页面现无需登录即可打开。设备OTA/WS独立鉴权、同源写保护和代理令牌仍保留。模板不再生成管理员密码，本地私钥/密码均未回显；原站与作品集仍200。
- Caddy仍2.6.4/PID58109，未升级、未重启；备份原主配置/域名配置到 `/opt/xiaodan/incoming/caddy-before-20261115`。新路由放 `/etc/caddy/xiaodan/routes.conf` 并在原域名块导入；2.6.4不支持命名 `log xiaodan`，改用无名 `log` 后候选配置校验通过并reload。全局错误日志/域名访问日志都导入脱敏filter，后台沿用本机包装器的敏感信息脱敏规则。未改DNS或证书；旧voice-studio PID140186仍在，health200，portfolio200。
- 实际公网：未登录管理页401；登录后home/settings/devices/静态JS/CSS/AudioWorklet均200，响应CSP与麦克风权限头完整；跨源写/缺X-Local-Settings均403，设备OTA缺key403且未被网页登录拦住。真实Chrome自动操作聊天→设置→设备页→聊天，无JS异常、失败接口或未带前缀的同站请求；设备页正确生成含前缀的私有OTA，未点击应用或修改设备。证据 `logs/cloud-browser-20261115.json`，执行脚本 `logs/verify-cloud-browser-20261115.cjs`。
- 有限真实模型确认：网页文字请求“请从一数到三，只回答这三个数字。”实际返回“好嘞，这就给你数。设备没连上，调不了音量喵。”，工具记录为set_device_volume/error/device_offline，证明服务端/百炼/页面往返，但业务报数失败、存在工具误判；不能写报数通过，未为此改动稳定逻辑。克隆音色preview另返回86388B WAV、1.8秒/24kHz/单声道，耗时2.78秒；公网网页实时WS到百炼收到ready，耗时0.89秒，随后主动关闭。关闭时稳定代码记录一条realtime_receive_cancelled/CancelledError，为取消清理，服务未重启。未注入假麦克风、未发起设备对话，不等于用户麦克风/扬声器听感通过。
- 云端设备connected=false、last_bootstrap=null，未发送合法设备OTA/bootstrap或修改配对。生成WSS前缀经直接读取hub属性核对正确；未刷机、切Wi-Fi或改设备OTA。本机 `.env`、data/devices.json 与部署前快照SHA一致，运行目录两实时模块仍为bd639a9。后续设备切换须用户另行授权；当前交付为云端稳定代码部署，工具误判、真实设备云端链路及原动画/TCP根因分别保留未解决。

## 用户确定现域名 `/xiaoyuan`，继续只读设计（2026-11-15）

- 用户补充旧voice-studio（合成音频/翻译项目）已放弃，Caddy重载对其可能造成的语音WebSocket中断无需顾虑。该旧站不再阻塞接入时机，也无需等待其空档；仍不主动停止、删除或改动旧项目，除非另获授权。助手使用8010/8013，与其8000端口不冲突。其余路径路由与应用前缀适配方案不变。
- 云端调试边界已核对：服务端用SSH查看 `journalctl -u xiaodan`、应用日志/健康状态和每轮 `device-audio-turns.jsonl`，可按时间与turn_id关联；设备串口/唤醒/显示及本地TCP证据仍需USB采集，服务端只能看WSS/TLS元数据。代码更新在本地稳定发布物上完成，上传到独立版本目录后只重启 `xiaodan`；首次新增 `/xiaoyuan` 路由才需要Caddy reload。
- 设备切云必须修改自定义OTA地址，当前本机实验地址不能继续使用。新地址为 `https://ryan406.online/xiaoyuan/xiaozhi/ota/?key=<设备密钥>`，OTA响应必须返回 `wss://ryan406.online/xiaoyuan/xiaozhi/v1/` 并保留设备鉴权；原厂OTA/绑定记录及固件不主动改。设备可继续使用当前CMCC或其他可上网Wi-Fi/手机热点，但必须实测HTTPS/WSS证书、时钟和网络连通；不能把修改地址当作云端语音已通过。
- 部署版本已确定：Git基线 `bd639a9`，其包含 `ead6381` 的稳定语音修复；云端发布标识暂定 `bd639a9-cloud-20261115`，只增加 `/xiaoyuan` 路径/认证/部署适配。当前工作树中的新动画、UI回调、`esp_tcp.cc` 等待验证改动及 `realtime.py`/`device_realtime.py` 增量均排除，语音处理模块保持 `bd639a9` 原文；不能把发布包冒充原始提交。当前未打包、未提交、未上传。
- 后续改动分层：云端稳定包不应用新动画资源/板级显示、LVGL解码配置、`application.cc` UI通知、`realtime.py`/`device_realtime.py` 的 `ui` 事件await，也不应用未定因的`esp_tcp.cc`等待修改。云端先验证旧固件+旧UI+稳定后端；动画调试另开版本线，先查显示/解码，再查UI事件对语音发送时序的影响，TCP问题须有ACK/窗口/重传证据后再单独验证。禁止把多个变量同时带入稳定服务。
- 用户否定新增子域名，选择 `ryan406.online/xiaoyuan/`，独立后台服务由负责人安排；本轮没有把设计讨论扩大为远端修改授权。SSH复核Caddy仍为2.6.4，现有域名站点在 `Caddyfile.d/voicestudio.caddyfile`，含 `/voiceStudio`、`/api/*`、`/portfolio/*` 和其他静态路由，尚无 `/xiaoyuan`。只读取配置中路由行，未输出凭据、修改配置或重载。
- 设计为同域名站点新增助手路由导入，精确匹配 `/xiaoyuan` 和 `/xiaoyuan/*`，入口规范化到尾斜杠；设备 `/xiaoyuan/xiaozhi/ota/`、`/xiaoyuan/xiaozhi/v1/` 转8013并保留设备独立鉴权，其余管理页面/API/网页语音WS转8010。代理剥离前缀后转给既有内部路由，不占用旧根域名 `/api`；沿用现有证书及DNS。独立目录、虚拟环境、服务不变。
- 代码核查：app.html资源/导航、app.js请求/历史导航/下载链接、voice.js的WebSocket/AudioWorklet/请求均包含根路径；devices.py生成OTA与WS地址也不含前缀。只加代理规则会误请求根路径，故需在稳定版上补部署路径适配，不能依赖HTML base标签或代理响应字符串替换。`AI_PUBLIC_ORIGIN`继续纯HTTPS origin，路径单独配置，不放宽现有同源鉴权含义；语音编解码、音色、唤醒及新动画不在此次路径适配范围。
- Caddy官方文档确认2.8以前指令名为 `basicauth`，现有2.6.4无需为本方案升级。官方同时明确配置reload会默认关闭WebSocket；故不承诺重载对旧语音会话无感，正式接入前须核对使用情况和时机。下方子域名/DNS建议为历史勘查方案，已由本记录取代。仅更新本地文档，未改业务代码、调用模型、部署或操作设备。

## 稳定版云端部署只读勘查（2026-11-15 16:42–16:47）

- 用户说明原网络损坏，授权先只读检查服务器与域名。已通过现有 SSH 密钥连接 `root@47.112.16.195`，无需密码；未上传、安装、创建远端文件或账号、修改配置/DNS、重启服务或切换设备。
- 实机为 Alibaba Cloud Linux3 x86_64、2核、1870MiB内存，可用约1410MiB，无Swap，根盘可用约32GB，负载0。Python3.11.13及venv模块、FFmpeg7.0.2和libopus.so.0已有；8010/8013空闲，`/opt/xiaodan`、`/etc/xiaodan` 和 `voice-assistant` 用户不存在。当前资源具备单设备实时主线迁移基础，尚无云端语音运行及峰值资源证据；不先安装全套本地ASR。
- 旧 `/opt/voice-studio/backend` 的Python进程PID140186监听8000，属于旧登录session而非独立应用systemd单元；不接管或重启。Caddy2.6.4由systemd管理，PID58109，监听80/443；主配置已有 `import Caddyfile.d/*.caddyfile`。根域名 `/voiceStudio`、`/api/*` 代理8000，另有 `/portfolio/*` 静态站；真实health返回200/status=ok，作品集HEAD返回200。旧路由、目录和依赖均保留。
- `ryan406.online` 的A记录为47.112.16.195，NS为dns27/dns28.hichina.com；本机与服务器均成功校验证书/TLS1.3，现有证书只覆盖根域名、有效至2026-12-15。建议独立 `assistant.ryan406.online`，A/AAAA均NXDOMAIN；后续需新增主机assistant的A记录指向服务器，不能占用旧根域名 `/api`。本轮未改DNS或申请证书；未核实阿里云安全组规则。
- 建议 `/opt/xiaodan`＋独立虚拟环境/用户/服务，管理与设备网关分别只绑定127.0.0.1:8010/8013，独立子域名由既有Caddy提供HTTPS/WSS、个人登录和设备鉴权。正式上线需适配Caddy2.6.4的 `basicauth`（现模板为 `basic_auth`）；当前Caddy没有读取拟用环境文件，不能为注入环境变量直接重启旧代理，须调整独立站点凭据配置方式。共享代理reload和同机资源竞争仍需考虑，不能承诺绝对零影响。
- 本轮按忽略CRLF核对运行目录43个受版本管理的后端文件，全部与 `bd639a9` 一致；开发工作树仍保留新动画及TCP改动，不能直接上传。后续获部署授权后从稳定提交准备程序，另迁当前 `.env`、devices/tools/voices/qwen_voices配置及一致性保护的conversations/personal_kb数据库，保留音色、设备配对、历史与知识库原文/索引；不上传Windows虚拟环境、工具链和缓存。未输出私有配置值或发起付费模型调用。
- 原网络既已损坏，不继续要求切回；云端接入后设备仍需可上网的Wi-Fi/热点。迁云可解除对电脑局域网地址的依赖，但不能据此宣称原动画/TCP背压原因已解决。

## 本次无法对话/重启后无法唤醒：电脑已切到手机热点（2026-11-15 16:34）

- 用户报告运行抓包后，设备唤醒但一直聆听，重启后又无法唤醒。本轮实际核对电脑 WLAN 连接为 `OPPO Findx 8 Pro`，IPv4 `10.92.136.114/24`、网关 `10.92.136.22`；设备串口仍连接 `CMCC-g24u`，IP `192.168.1.5/24`、网关 `192.168.1.1`。电脑已不持有设备配置的网关服务地址 `192.168.1.6`，两端当前网络不通；这是本次现象的明确环境原因，不能并入新动画解码或 13:41/14:36 TCP 背压的未定根因。
- 16:30:54.729 本地唤醒实际命中、概率 0.881594，随即 `idle → connecting` 并尝试 `ws://192.168.1.6:8003/xiaozhi/v1/`；后续没有 Session ID、进入 listening、后端新连接或模型调用。用户看到卡住时，设备日志实际停在建连阶段，不能当成模型听到语音而未回答。
- 用户重启/USB 重枚举后，原 COM3 采集在 16:31:28 报 I/O 中止退出；本轮恢复串口采集 PID 6168，未传 `-ResetDevice`。重连获得的 16:33 启动段显示旧形象加载完整、设备连上原 CMCC 网络，16:33:51 进入 activating 并停在 OTA 版本检查，尚无 `Activation done`、idle 或唤醒检测启动；源码中正常待机及唤醒检测位于启动校验完成之后。不能将此时无法唤醒判成唤醒模型损坏。
- 用户本次抓包已实际运行：16:30:51 开始、16:33:52 自动停止并清理筛选器，转换结果 0 包，pcapng 200 字节；路径 `logs/device-tcp-headers-20261115-163051.*`。在当前电脑热点与设备原网分离的状态下，没有采到双方旧地址间的目标流量；这份空包不能用于推断 TCP ACK/窗口/重传原因。
- 后端仍为 PID 17156，8000/8003 监听且 health `ok/configured=true`；没有修改固件、音色、运行后端、设备地址或电脑 Wi-Fi。用户随后说明原网络已损坏，不能继续安排切回原网络；后续按稳定版云端部署只读评估推进，设备网络与地址切换另按授权执行。

## 动画回归只读调查：稳定版也出现同类发送超时（2026-11-15）

- 用户要求保留现稳定版本，查清新动画与语音的冲突原因后再改。本轮只读检查历史/新增日志、原版与新动画源码、当前固定版本的 LVGL/lwIP 和资源包；没有修改业务代码、构建、刷机、重启、改网络设置或发起模型请求。后端仍为 PID 17156，COM3 采集仍为 PID 33684；运行目录两个实时模块再次与 `bd639a9` 原文核对一致。
- 关键反证：串口恢复段第 18852 行，16:02:45.968，旧应用/旧形象/稳定后端同样出现 `TCP send failed errno=116 sent=0 total=154 duration_ms=251`，随后本地关闭、`listening → idle`，与新动画批次的直接断链机制相同。此前 16:02:38.841–43.774 已正常下发/接收 82 包。不能因用户确认恢复就推断所有发送超时仅由新动画引起，也不能因此否认用户报告的新动画版本明显退化；新动画是否放大原有问题仍未证实。
- 16:03:39 再次唤醒后同一连接产生后续多轮回答、打断及结束意图，16:04:27 回 idle，16:04:37 peer close 为结束后的清理。恢复后六个有下行音频的回合，网关发送/设备接收分别 82/82、47/47、46/46、120/120、98/98、5/5，answer CRC 均一致，设备入队丢包均 0；最后两个音频回合归档 interrupted，不能把完整生成和包数一致当作完整播完。用户“恢复了”的现场反馈继续有效，网络偶发断链单独保留。
- 已证实的原有断链机制：稳定版 `EspTcp::Send` 对实时连接使用 MSG_DONTWAIT，EAGAIN 后等待可写，整次发送到 250000us 即 `DoDisconnect(false)`；新旧版本都保留此期限。当前生成配置 `CONFIG_LWIP_TCP_RTO_TIME=1500`，是初始重传配置，不能当作每条已建连接故障当时的实际 RTO。日志没有 sndbuf、pbuf 队列、ACK 进展、对端窗口或重传状态，尚不能区分队列/内存不足、无线 ACK 延迟与对端窗口等最初不可写来源。此前 20ms 重试修改未恢复新动画批次，不能再把 select 通知缺陷当作充分解释。
- 新动画已有两处可直接核实的接入问题/耦合，均不能冒充语音断链定因：①初版 I4/RLE 资源配合 `LV_BIN_DECODER_RAM_LOAD=false`，本地 `lv_bin_decoder.c:1041` 明确拒绝解码，解释早期表情空白；13:41 语音失败当时尚未开启这条 RAM 解压路径，因此不能以随后启用的解压内存开销解释所有失败。②新后端在 next/thinking/activity/idle 等实时回调里 await UI 发送，与 TTS 共用连接发送锁，增加显示对对话时序的依赖；但四次失败的归档均无 speech_stopped/首音，gateway trace 仅含关闭时 stop_audio，无 next/notice/done/error，不能把工具状态或播放显示反馈判为这些早期失败已观察到的起因。
- 新资源 55 个 128×128 独立帧，旧资源 48 个 84×84 帧，帧周期均为 80ms；新编码总量 44087 字节小于旧 PNG 的 102583 字节，但像素面积为旧版约 2.322 倍。本地软件 indexed 解码路径会转 ARGB8888，单帧像素区 65536 字节，另有 RLE 中间缓冲；实际分支/缓存命中与现场耗时未测，不能写成内存已耗尽或动画已抢占语音。新旧唤醒模型和字体一致；音频发送在独立任务，UI 更新调度至主线程，状态栏先释放 Wi-Fi 查询锁再申请显示锁，未找到可证实的新显示锁→音频发送锁死链。
- 当前结论是“表情空白根因已知，语音直接断链位置已知，动画与最初 TCP 背压的具体因果尚未查清”，不是“动画冲突已修复”。下一步最直接的证据是一次真实故障前后的 TCP 包头，核对 ACK、重传、窗口及两端关闭顺序；已有 `logs/capture-device-tcp-headers.ps1` 仅采设备与电脑间 8003 的 54 字节包头，不需要刷机或重启。当前执行身份不是 Windows 管理员，无法在本会话启动 PktMon；尚未启动抓包、提权或增设后台，不能伪造缺失的报文证据。
- 用户首次在管理员 PowerShell 运行该脚本时，脚本用当前 GBK 控制台解码 PktMon 的 UTF-8 中文输出，把“未指定数据包筛选器”误判成已有筛选器而安全退出；当时尚未添加筛选器或开始抓包。已改为 `ProcessStartInfo` 显式 UTF-8 读取 stdout/stderr，并把中文字符判断写成 ASCII 的 `\u` 转义以兼容 PowerShell 5.1。第二次运行显示本机空列表实际输出为“无”，因此再补充 `\u65E0` 匹配；两次均在添加筛选器前退出，没有遗留筛选器或活动抓包。脚本语法解析 0 错误，尚未实际开始抓包，也仍未取得 ACK/窗口/重传证据。

## 用户现场确认恢复（2026-11-15）

- 恢复旧应用、匹配的旧像素资源及稳定后端后，用户反馈“恢复了”，确认现场语音已恢复；本次恢复不再处于等待用户确认状态。用户未逐项描述本次使用过程，不另补写报数、打断、退下再唤醒的独立验证细节。
- 当前保持该稳定运行版本，新动画代码继续保留，暂不重新接入。组合恢复后的现场结果进一步支持按动画接入后的改动范围调查回归，但尚未定位其中哪项改动触发了最初的 TCP 背压。

## 已按授权恢复稳定语音运行版本（2026-11-15 15:59）

- 用户明确同意先恢复截图稳定版本、接受旧形象，同时保留新动画代码。新动画及 TCP 修改完整保留在 `.cache/repo-export` 工作树；本轮没有 checkout/reset/stash、提交或重新编译。恢复前运行中的两个新后端模块及新应用/资源另存 `.cache/device-backups/pre-stable-restore-20261115-1556/`，两个模块的保全副本与新动画工作树逐字节一致。
- 运行目录 `backend/app/device_realtime.py`、`backend/app/realtime.py` 已恢复为 `bd639a9`，按忽略 CRLF 的内容比较与 Git 原文一致；全部 43 个受版本管理的后端文件原先仅这两处不同。工作树中两个模块仍保留新动画逻辑，当前有意与运行目录不同；后续不得将新工作树直接同步覆盖稳定服务，也不得直接重编译当前新动画固件冒充稳定版。
- 停止旧后端 PID 29012 和已核对的 COM3 采集 PID 2928 后，只读核对当前分区/otadata，与 15:27 批次读回逐字节一致；当前启动 ota_0，应用范围 `0x20000–0x2cffff`、assets `0x580000–0x7fffff`。首次向新建备份目录保存分区读回遇到 PermissionError，未发生写闪存；改用既有 `firmware/.tmp/` 后成功，文件为 `stable-restore-partition-20261115.bin`、`stable-restore-otadata-20261115.bin`。
- esptool 4.13.0 单次只写旧应用 `0x20000` 和匹配旧像素资源 `0x580000`，两项均报告 `Hash of data verified`、退出码 0。应用 2745744 字节，SHA256 `ebcc395f613efb9a113e2358e20d9fe8c297103cd4958dfb619e62beddd6a52e`，与上午 10:28 刷入相同；旧像素资源原文件 2613893 字节，SHA256 `fc4244afe4a646d3160e48fe57d17a9d941fea65fd08aee2c7337f19c1740b80`，esptool 按 4 字节补齐写入 2613896 字节。实际擦写仅 `0x00020000–0x002befff`、`0x00580000–0x007fefff`；未写 NVS、otadata、分区表、bootloader 或 ota_1。日志 `logs/flash-stable-bd639a9-app-assets-20261115.log`。
- 稳定后端已启动，实际 PID 17156、8000/8003 分别监听回环/局域网，health `ok/configured=true`、模型 `qwen3.8-omni-flash-realtime`，沿用既有脱敏包装器显式开启 `AI_EMBEDDING_ENABLED=true`。沿用后端日志 `backend-robot-ui-bd639a9-20261115.err.log/.out.log`，新运行段以 `STABLE RESTORE bd639a9` 和新 PID 区分；新启动包装器日志为 `backend-stable-restore-bd639a9-20261115.launcher.log/.err.log`。
- COM3 脱敏采集 PID 33684 已启动，既有串口日志第 18207 行起为 `STABLE RESTORE` 新段；15:59:21 复位，22 秒加载 idle 16/16、listen 12/12、think 10/10、speak 10/10，26 秒进入 idle，27 秒启动 `mn5q8_cn` 唤醒检测，麦克风及 16k 输入持续非零。新启动段未见资源缺失、panic 或启动失败；网关空闲 `connected=false/ready=false/last_error=null`。这些只确认稳定应用/资源/后端已恢复运行，当前尚无恢复后的真人对话，不能写成听感和语音闭环已经重新通过。
- 用户配置、对话、知识库、音色、设备配对均未执行修改或回滚；未发起模型请求。下一步由用户直接叫“塔菲”并交流，主 Bot 结合本次日志继续确认真实语音；新动画接入暂缓，等稳定基线恢复的现场结果后再处理。

## 稳定节点追溯与旧像素资源保全（2026-11-15）

- 用户本轮明确确认：今天替换动画前，叫名字可从待机进入聆听，交流/报数的流畅度与完整度、说话打断、结束后回待机均达到预期；截图标记提交为 `ead6381`、`bd639a9`。这是用户现场确认，先前日志未覆盖的项目不能继续当作用户未确认。当前故障按该稳定节点之后的回归处理。
- 实际 Git 工作树为 `.cache/repo-export`，HEAD `bd639a9`；`E:\xiaodan` 是运行/构建副本。动画接入仍未提交，修改涉及板级显示、动画资源构建、application 显示消息、两个后端实时语音模块及 LVGL 配置，之后另叠加 TCP 等待修改和诊断。核对两个后端模块、application、EspTcp 的运行副本与工作树一致；仅看 HEAD 不能代表已经恢复稳定节点。
- 再次核对 13:41、14:36 失败：唤醒/建连和麦克风输入仍有实际记录，随后设备上行 TCP 在原有 250ms 期限内持续不可写并主动关闭；两次 14:36 回合上行 30/17 帧，回答正文和下行音频均为零，后端 CancelledError 发生在设备断开后的清理阶段。已定位直接中断位置，尚不能证明动画绘制、资源压力或无线传输中的哪一项造成最初背压。15:27 诊断固件启动后，截至本轮读取尚无新对话或 `TCP backpressure` 样本。
- 稳定应用备份 `.cache/device-backups/pre-robot-ui-20261115-115637/xiaozhi.bin` 仍在，SHA256 `ebcc395f613efb9a113e2358e20d9fe8c297103cd4958dfb619e62beddd6a52e`，与 10:28 刷入记录一致。但同目录原 `generated_assets.bin` 只有 24 项基础资源，不含旧显示代码需要的 48 张像素帧；它是当时构建产物，不能冒充上午设备实际资源区的完整备份。
- 从本项目已回收的 `build-tafei-mn5-fix/generated_assets.bin` 找到 72 项旧资源包，复制保全为 `.cache/device-backups/pre-robot-ui-20261115-115637/pixel-assets-recovered-20261115.bin`；未移动或删除回收站原件。文件 2613893 字节，SHA256 `fc4244afe4a646d3160e48fe57d17a9d941fea65fd08aee2c7337f19c1740b80`。包长度/校验和、各项资源 magic 有效，包含旧代码所需 idle 16/listen 12/think 10/speak 10 全部帧；唤醒模型和字体与当前资源逐字节相同。尚无上午资源区读回哈希，故仅确认这是结构匹配的旧像素资源包，不宣称与上午设备全区逐字节一致。
- 若恢复稳定节点，应协调原应用、匹配的旧像素资源和 `bd639a9` 两个后端模块，保留当前新动画工作、私有配置、历史及设备配对；仅 checkout 源码或只刷应用并不能恢复整套运行状态。本轮仅只读调查、复制保全资源及同步本记录，没有修改业务源码、构建、刷机、重启服务或发起模型请求。实际语音尚未恢复，设备恢复操作仍需用户相应授权。

## TCP 背压诊断固件已刷应用区（2026-11-15 15:27）

- 用户授权只刷应用区并进行一次真机测试。停止原 COM3 采集 PID 8008 后重新读取分区表和 OTA 数据，与上次确认的备份逐字节哈希一致：当前 `ota_0` 为 `0x20000–0x2cffff`，assets 自 `0x580000` 起。待刷文件 SHA256 为 `a60a8dc53c91e61cea7a7a33b2fae7206267c19598b53b615972588e3eb33e8c`。
- esptool 仅向 `0x20000` 写入应用 2776416 字节，实际擦写 `0x00020000–0x002c5fff`，报告 `Hash of data verified`，退出码 0；日志 `logs/flash-app-tcp-state-diagnostics-20261115.log`。未写 NVS、OTA 数据、配对信息、assets 或其他分区。
- COM3 采集使用既有脱敏脚本重新启动，PID 2928；`logs/serial-robot-ui-bd639a9-20261115.log` 从第 14385 行进入本次启动段。15:27:15 复位后设备加载 55 个表情资源，15:27:20 进入 idle 并启动“塔菲”唤醒检测；本次连接 Wi-Fi 时 RSSI=-70dBm。后端 PID 29012 未重启，8000/8003 监听、health `ok/configured=true`；该进程此前已核对 embedding 开启。以上不代表语音对话已通过，等待用户实际讲话和听感；如仍失败，须结合本次 `TCP backpressure` 两条记录、既有串口/后端日志及逐回合音频指标分析。

## 重新审查发送背压，诊断固件已编译，根因仍未证实（2026-11-15 15:22）

- 按用户“不要防御性测试，大胆猜测，细心排查”的要求重新核对实际源码、运行环境和旧日志，没有安排模拟 API、额外后台、付费对话或用户重复讲话。仍未找到能证明“新动画阻塞语音发送”的执行链：独立上行任务的失败耗时主要在 TCP 等待，实际 send 调用不足 1ms；这也不能排除 UI 对资源、调度或无线传输的间接影响。此前可写等待修改未恢复真实语音，不能继续将其当作已定因。
- 新查实的环境差异：13:33 启动时设备 RSSI=-70dBm，14:33 最新启动为 -80dBm（扫描 -81dBm），两次连接同一 BSSID、2.4GHz 信道 2；电脑走直接 WLAN 路由、5GHz 信道 149，设备 ARP MAC 与硬件 MAC 相同。只读网络诊断对设备连续 5 次 ICMP 出现一次 1500ms 超时、一次 534ms，另三次 9/5/4ms；同时路由器为 1/16/2/2/1ms。但设备当时处于 MAX_MODEM 待机，源码 listen_interval=10，不能把待机 ICMP 延迟直接等同于通话中的丢包或认定无线已定因。没有修改无线配置或路由器。
- 旧 errno=EAGAIN 不能区分发送字节耗尽、pbuf 队列满、对端窗口关闭或分配失败。业务源码本轮仅在 `main/network/esp_tcp.cc` 补齐真实背压证据：首次 EAGAIN 和最终失败各读取一次当前连接的 sndbuf、pbuf 数量、unsent/unacked 段数、ACK 进展、对端窗口、拥塞窗口、重传计数与定时状态；失败时另记内部 RAM、DMA 和 PSRAM 的空闲量/最大连续块。通过 `tcpip_callback_wait` 在 lwIP 核心上下文拷贝状态，不跨线程遍历或保留 PCB 指针；使用当前固定 ESP-IDF 5.5.2 的 TCP 内部结构，未修改第三方协议栈。正常无背压发送不查询协议栈；首个快照在原 250ms 期限内采集，最终快照在判定失败后采集，只在失败时打印两条 `TCP backpressure`，不记录报文、凭据或录音。
- 本轮没有修改动画、AEC、采样率、声道、use_mclk、语音打断、唤醒、待机或后端业务；没有加大缓冲、延长发送期限、丢帧冒充成功或加入重连兜底。这是诊断固件，尚未修复或验证语音根因；待真实记录说明具体背压来源后才能实施对应修复，不能将编译成功写成语音恢复。
- 工作树与运行副本源码同步；必要构建退出 0，日志 `logs/firmware-build-tcp-state-diagnostics-20261115.log`。最终应用 2776416 字节、分区余 41632 字节，SHA256 `a60a8dc53c91e61cea7a7a33b2fae7206267c19598b53b615972588e3eb33e8c`；assets SHA256 仍为 `3b5897f8fff8e6e49904494f2a7422c149291af547423cc835e2031e9a9f7a2e`，sdkconfig 与构建前一致。当前已刷应用及 elf/assets/config 已保存至 `.cache/device-backups/pre-tcp-state-diagnostics-20261115/`。没有刷机、重启服务/串口、commit 或 push；8000/8003 仍为 PID 29012，COM3 采集仍为 PID 8008。设备上仍运行 14:33 批次应用，不是新生成的诊断固件。

## 表情已由用户确认显示，TCP 修正后语音仍失败（2026-11-15 14:36 批次）

- 用户现场确认“现在表情是有了，语音没有正常”。复核同一串口文件 14:33:00 标记之后、后端新增两个会话和对应逐回合记录；本次没有改业务源码、编译、刷机、重启或调用模型。此结果确认表情显示已恢复，但不补写全部动画状态、顶部时间读数和走时验收。
- 第一次 14:36:10.147 从 idle 建连（未见唤醒词命中，不能推定触发方式），10.212 进入 listening；12.492 上行发送失败：`errno=116 sent=0 total=125 duration_ms=269 first_send_errno=11 send_calls=9 would_block=9 select_timeouts=9 send_call_max_us=379 select_ms=267`，12.516 自动进入 idle。第二次 14:36:16.444 明确命中“塔菲”、概率 0.808230，16.451 开始建连，18.934 进入 listening；20.352 再次失败：`errno=116 sent=0 total=151 duration_ms=268 first_send_errno=11 send_calls=9 would_block=9 select_timeouts=9 send_call_max_us=682 select_ms=265`，20.376 回 idle。第二次至收到 hello 约 2.44s，第一约 52ms，握手耗时也有明显波动，尚无报文证据解释原因。
- 本轮 `TCP write resumed after select timeout` 为 0 条。两次确实执行了 9 次实际 send，9 次均 EAGAIN，没有观察到恢复；最长 send 系统调用仅 379/682us，耗时主要在 select 等待，不是 send 调用本身长时间不返回。上轮“可写通知可能滞后”的等待逻辑修正没有解决本轮真实故障，不能再以该假设作为充分根因或宣称已恢复；最初 TCP 背压的来源仍未定位。
- 回合 `d84b3630-d8cf-4e48-9e86-29cc45ef6ef2` / `10821629-7bc1-40d2-82c2-a2b4ff6f8d00`：上行分别 30/17 帧、队列丢弃均 0、最长排队 250/203ms、云端 append 最长记录均为 0ms、上行慢发送均 0；`reply_chars=0`、TTS/首包时点均空、音频编码和下发均 0 包，结束原因均 `closed`。后端归档使用 UTC（06:36 对应北京时间 14:36），不能将归档时区差异当作屏幕时间偏移。
- 串口两次先记录设备 TCP 超时与本地断开，后端随后收到关闭码 1005。后端仅出现相应 `realtime_receive_cancelled event=awaiting_event`，完整堆栈保留于 `logs/backend-robot-ui-bd639a9-20261115.err.log` 第 87/120 行起：`realtime.py:352 → asyncio.wait_for → websockets.recv/messages.get → CancelledError`；没有 `realtime_receive_failed`、`device_realtime_upstream_closed` 或供应商错误载荷。该取消属于设备关闭后的清理，不能判为后端先断开或崩溃。
- 本轮转写、助手正文、`audio_downlink_start`、进入 speaking、主动 `Abort speaking` 均为 0，两会话 `abort_count=0`。因此没有可评价的长回答卡顿/重复、故事完整播放或播放中打断样本；启动提示音及唤醒提示音不能算助手回答。首次异常回 idle 后再次叫“塔菲”成功，证明该次异常待机后的唤醒检测有效；未见正常结束意图“退下吧”的闭环，不能写成正常退下再唤醒已验收。
- 新启动段未见 LVGL 解码错误、资源缺失或 panic；顶部时间和底部文字没有屏幕遥测，实际显示仍待用户确认。检查时后端 PID 29012、health `ok/configured=true`、COM3 PID 8008 仍运行；网关 `connected=false/ready=false/last_error=null`，麦克风继续输入。HEAD 仍为 `bd639a9` 加未提交修改，已刷应用 SHA256 `fee56694b1a68837098a914193b8a1f7ecee5982aafa2ecc1965d472062b623e`。下一步应追踪 TCP ACK、重传、接收窗口及设备发送队列/内存的实际状态，不能继续靠改等待参数或重复长回答测试推断根因。

## TCP 可写等待与表情解码修正版已刷应用区（2026-11-15 14:33）

- 按用户授权停止原 COM3 采集 PID 21072（命令行核对为本轮采集脚本），未停止后端。刷写前只读确认分区：NVS `0x9000–0xcfff`、otadata `0xd000–0xefff`、`ota_0` `0x20000–0x2cffff`、`ota_1` `0x2d0000–0x57ffff`、assets `0x580000–0x7fffff`；otadata 槽 0 为 `seq=1`、`state=2(VALID)`，按 `bootloader_common_ota_select_crc` 规则核对 CRC 一致，当前启动 `ota_0`。只读文件保存于 `firmware/.tmp/robot-ui2-partition-20261115.bin` 与 `robot-ui2-otadata-20261115.bin`。
- 使用项目 esptool 4.13.0 单次写入 `0x20000 xiaozhi.bin`，日志明确擦写范围仅 `0x00020000–0x002c5fff`，写入 2774880 字节并显示 `Hash of data verified`，退出码 0；日志 `logs/flash-app-tcp-writability-20261115.log`。应用 SHA256 `fee56694b1a68837098a914193b8a1f7ecee5982aafa2ecc1965d472062b623e`。没有写 otadata、NVS、配对数据、`ota_1`、分区表、bootloader 或 assets。
- 新 COM3 采集 PID 8008、115200 UTF-8，14:33:00 写入采集开始和主动复位标记，继续使用既有脱敏日志 `logs/serial-robot-ui-bd639a9-20261115.log`（本轮从第 7500 行起），启动日志另存 `logs/serial-tcp-writability-bd639a9-20261115.launcher.log/.err.log`。设备从 `ota_0` 启动，14:33:01 报告 `RobotDisplay: loaded 55 unique frames`，14:33:05 完成激活、进入 idle 并启动 `mn5q8_cn` 的“塔菲”唤醒检测；启动扫描未见 LVGL 解码错误、资源缺失、panic 或 Guru，麦克风输入持续非零。画面和时间仍待用户现场确认。
- 后端沿用 PID 29012，8000/8003 均监听，health `status=ok/configured=true`、模型 `qwen3.8-omni-flash-realtime`。通过只读进程环境核对实际服务进程 `AI_EMBEDDING_ENABLED=true`，没有输出其他环境变量或凭据。设备空闲时不保持语音 WebSocket，检查时网关 `gateway_running=true/connected=false/ready=false/last_error=null` 属待唤醒状态。
- HEAD 仍为 `bd639a9` 加未提交修改；本轮未改业务源码、assets 或环境，未重启后端、调用模型、commit/push。用户下一轮测试将覆盖表情、短问答、长报数/故事、主动打断及退下后再次唤醒；新增 `TCP write resumed after select timeout` 和 send/select 明细用于验证发送等待修正。

## 新增 UI 路径审查与 TCP 可写等待修正（2026-11-15，编译通过，未刷机）

- 按用户要求继续对照上午顺畅版本，检查 `RobotDisplay`、application UI 消息、WifiManager、WebSocket 发送锁、独立上行任务及后端接收/上传协程。新增 UI 消息通过 `Application::Schedule` 交给主线程，绘图锁没有进入独立 `audio_send` 任务；状态栏先读 Wi-Fi 再取得显示锁，没有发现新增的显示锁与网络锁互相等待链。13:41 两次失败的 TCP 内部耗时 261/256ms、上层发送总耗时 272/266ms，主要耗时已在 TCP 内，不支持将其直接说成主线程等待绘图锁。UI 间接改变资源或调度是否触发最初背压，仍无运行证据。
- 找到并修复可由本地 lwIP 源码证实的等待缺陷：`EspTcp::Send` 在 EAGAIN 后将全部剩余期限交给单次 select，select 超时即断开，期间不再尝试实际发送。lwIP 的 `api_msg.c` 通过发送字节/队列低水位恢复可写通知；当前 MSS=1440、发送缓冲=5760，默认字节低水位为 2881，因而恢复到足够发送约 150 字节的小帧不一定触发通知。失败写入设置 `NETCONN_FLAG_CHECK_WRITESPACE` 后还依赖 ACK 或轮询恢复通知；本地轮询间隔为 2 个 500ms 慢定时周期。不能把“没有可写通知”当成“这个小帧始终无法发送”。
- 本轮业务源码仅修改 `main/network/esp_tcp.cc` 并同步构建副本：保留原 250000us 整次发送期限和 MSG_DONTWAIT；每次 select 最多等待 20000us，未收到通知也回到原循环，在原期限内重新尝试发送。仍按已发送偏移续写，真正失败或到期仍关闭连接，避免半帧与后续帧拼接；未增加缓冲、延长期限、丢弃当前帧继续冒充发送成功或关闭语音打断。HTTP 的非实时发送路径保持原语义。
- 必要诊断与本次等待逻辑放在同一函数内：失败保留最初 send errno、实际 send 调用次数、EAGAIN 次数、select 超时次数、最长 send 调用耗时及累计 select 等待；短暂无通知后发送成功时记录 `TCP write resumed after select timeout`。正常无背压发送不增加日志；不记录载荷、凭据或 Authorization。旧日志未保存这些字段，不能追溯证明两次真机超时都由上述通知缺陷触发，也未定位最初背压来源，不将本轮修正写成真实语音问题已全部解决。
- 构建日志 `logs/firmware-build-tcp-writability-fix-20261115.log`，明确编译本地替换的 `main/network/esp_tcp.cc` 并退出 0。应用 2774880 字节（`0x2a5760`），余 `0xa8a0`，SHA256 `fee56694b1a68837098a914193b8a1f7ecee5982aafa2ecc1965d472062b623e`；二进制已包含新诊断字符串。生成配置与上轮逐字节一致，assets SHA256 仍为 `3b5897f8fff8e6e49904494f2a7422c149291af547423cc835e2031e9a9f7a2e`。`git diff --check` 通过；无既有 C++ 单元测试，本次未添加模拟网络测试或运行无关完整套件。
- 构建前将上轮表情修正版 bin/elf、assets 和配置保存于 `.cache/device-backups/pre-tcp-writability-fix-20261115-142310/`。未改 UI 状态规则、AEC、声道、采样率、use_mclk、唤醒或待机源码；没有刷机、重启、调用模型、commit/push。后端 PID 29012 与 COM3 采集 PID 21072 仍为原实例。后续获准刷入后，由用户验证短问答、长报数/故事、主动语音打断及退下再唤醒，再用新增发送记录判断恢复是否发生在无 select 通知的分支，若仍失败继续定位背压而非继续增大缓冲或期限。

## 表情解码配置修正与上午语音版本对比（2026-11-15，编译通过，未刷机）

- 按用户要求修复表情空白，在 `sdkconfig.tafei-mn5` 与 `sdkconfig.defaults.atoms3r-tafei-mn5` 同时开启 `CONFIG_LV_BIN_DECODER_RAM_LOAD=y`，保留原有 I4/RLE 资源和 `CONFIG_LV_USE_RLE=y`；启用 LVGL ERROR 级 printf 日志，不增加逐帧正常日志。板级 README 同步注明必需配置，工作树与本机构建副本一致；没有更改音频、协议、唤醒或待机源码。
- 首次开启 WARN 日志的构建在本地 LVGL `lv_bin_decoder.c:1130` 遇到其自带格式错误：4 位压缩方法字段提升为 int，却按 `LV_PRIu32` 输出，触发 `-Werror=format`。最终只启用实际需要的 ERROR 级日志，不改第三方依赖或放宽编译器检查。最终生成配置确认 `LV_USE_RLE=true`、`LV_BIN_DECODER_RAM_LOAD=true`、`LV_USE_LOG=true`、`LV_LOG_LEVEL=3`、`LV_LOG_PRINTF=true`。
- 最终构建退出码 0，日志 `logs/firmware-build-robot-ui-decodefix-final-20261115.log`；应用 2774320 字节（`0x2a5530`），处于现有 `0x2b0000` 应用分区内，余 `0xaad0`。应用 SHA256 `3cc95d531705ddc65508bbb868720867151cd2ff6dd7a65c791f244d46b7cf95`；assets 仍为 2555952 字节、SHA256 `3b5897f8fff8e6e49904494f2a7422c149291af547423cc835e2031e9a9f7a2e`，与当前已刷资源完全一致。仅此修正无需再次写资源区。实际屏幕绘制与听感仍待用户上机确认，编译通过不记为真机通过。
- 以用户上午确认顺畅的备份为基线：`.cache/device-backups/pre-robot-ui-20261115-115637/xiaozhi.bin` SHA256 `ebcc395f613efb9a113e2358e20d9fe8c297103cd4958dfb619e62beddd6a52e`，其配置与 HEAD `bd639a9` 完全一致。核对 584 个受版本管理的固件/后端代码及相关构建文件，运行副本与工作树无偏差；相对上午基线，仅既有本轮的显示替换、动画构建、application UI 通知及两个后端 UI 事件文件发生变化。AEC、Codec、AudioService、AFE、原生 TCP、WebSocket 协议、后端设备接收等源码一致；250ms 发送期限上午就存在，上午备份固件内也包含同一发送失败日志和独立上行任务日志。
- 上午实际顺畅的结果继续有效；13:41 两次失败应按接入 UI 后出现的回归调查，不能把原有 250ms 期限当作本轮新增改动，也不能仅因音频源码未改就排除 UI 的资源/调度影响。当前只查实设备发送超时触发关闭，最初不可写的原因仍未确定。本次未调整发送期限、缓冲、AEC、声道、采样率、use_mclk、打断或唤醒参数，不宣称语音异常已修复。
- HEAD 仍为 `bd639a9` 加未提交修改。构建前已将当前已刷应用、assets 和生成配置备份到 `.cache/device-backups/pre-robot-ui-decodefix-20261115-135942/`；本次没有刷机、重启设备/后端/串口、调用模型、提交或推送。`git diff --check` 通过，未运行无关完整测试套件。

## 机器人屏幕本轮异常复核（2026-11-15 13:41 批次）

- 用户反馈表情没有显示，语音回答、打断及待机后再次唤醒存在异常。复核 `logs/serial-robot-ui-bd639a9-20261115.log`、对应后端 err/out 和 `logs/device-audio-turns.jsonl`；本次只读排查并记录，没有改业务源码、编译、刷机、重启或调用模型。
- 表情空白存在确定的代码/构建原因：新资源采用带 COMPRESSED 标记的 I4/RLE，而已刷构建 `config/sdkconfig.json` 为 `LV_USE_RLE=true`、`LV_BIN_DECODER_RAM_LOAD=false`。本地 LVGL 的 `lv_bin_decoder.c:927` 中 `decode_compressed()` 在该开关关闭时直接返回 `LV_RESULT_INVALID`（1041 行错误提示）；`LV_USE_LOG=false` 又使此绘制错误没有出现在串口。`RobotDisplay: loaded 55 unique frames` 只检查资源存在并装载描述符，不能证明解码绘制成功。此前资源像素往返检查没有覆盖实际 LVGL 解码配置；此问题尚未修复。
- 北京时间 13:41:14.059 确实检测到“塔菲”，14.443 进入 listening；15.996 设备上行 `TCP send failed errno=116 sent=0 total=151 duration_ms=261`，16.015 自动进入 idle。第二次 13:41:29.464 从 idle 建连、29.552 进入 listening，31.650 再次发送超时（total=146、256ms），31.670 自动进入 idle；第二次没有唤醒词命中日志，不能断言是语音唤醒。
- 两次失败均由设备现有 250ms 发送期限到期触发本地 `DoDisconnect(false)`，后端随后收到关闭码 1005 并清理云端 receive 协程。后端两个 `realtime_receive_cancelled` 的完整 traceback 为 `realtime.py:352 → asyncio.wait_for → websockets.recv/messages.get → CancelledError`，属于断开后的取消，未见 `realtime_receive_failed` 或 `device_realtime_upstream_closed`。未出现后端进程崩溃或用户手动停服务。现有日志能定位直接断开路径，不能确定最初 TCP 不可写是 Wi-Fi、协议处理或调度中的哪一项，也不能将它归因于表情解码故障。
- 回合 `a4580055-cbf2-4398-ab29-c182d42bb255` / `d41f6cf7-97bc-43ca-b75f-a1001578dfdd` 的上行分别为 18/28 帧，上行队列丢弃均 0、最大排队 16/0ms、云端 append 最长 0/15ms；两回合 `reply_chars=0`，TTS 时点均空，编码和下发音频均 0 包，`end_reason=closed`。未见转写或 model_call success，未进入 speaking；本轮没有形成有效的回答、播放打断或退下后再次唤醒验收。重新建立第二次连接确实成功，但仍在约两秒后超时，不能记为重试已恢复。
- 顶部时间代码沿用 OTA 的 UTC 时间戳加 480 分钟，主循环每秒刷新 HH:MM，未发现其他 TZ/settimeofday 路径；本轮 OTA 请求 200 且没有缺失 server_time 提示，但没有设备时钟读数或屏幕证据，不能确认实际时间、走时和文字显示正确。底部状态存在明确表达缺口：`RobotDisplay::UpdateStatusBar()` 仅以 Wi-Fi 判断连接，TCP 故障进入 idle 时会显示“待机”，未区分本轮语音连接失败；观察到的回待机不是结束意图的正常退下。
- 复核时 HEAD `bd639a9` 加未提交 UI 修改，8000/8003 仍由 PID 29012 监听，health `ok/configured=true`，启动包装器显式保持 embedding=true；COM3 采集 PID 21072 继续写入，麦克风输入持续非零。设备网关当时 `connected=false/ready=false`。后续应先修复实际解码配置并继续定位发送超时，再由用户现场确认画面和语音；不以健康检查代替真机结果。

## 第一版机器人屏幕已刷入、后端和采集已重启（2026-11-15 13:33）

- 按用户授权先停止原 COM3 采集进程 PID 26144，只读设备分区表及 OTA 数据，确认当前有效 OTA 序列为 1、状态 VALID、CRC 正确，对应 `ota_0`。实际分区：NVS `0x9000–0xcfff`、`ota_0` `0x20000–0x2cffff`、`ota_1` `0x2d0000–0x57ffff`、assets `0x580000–0x7fffff`。esptool 的 Python 环境无法向 logs 写入二进制，改写到项目内 `firmware/.tmp/robot-ui-partition-20261115.bin` 和 `robot-ui-otadata-20261115.bin` 后读取；首次只读未执行写入。首次临时 CRC 计算多做了异或，后按项目 ESP-IDF 实现核对并确认正确，不能将首次计算输出误判为 OTA 损坏。
- 使用现有 esptool 4.13.0 单次写入应用 `0x20000 xiaozhi.bin` 和 assets `0x580000 generated_assets.bin`，应用实际擦写 `0x00020000–0x002befff`、资源实际擦写 `0x00580000–0x007f0fff`；两项均报告 `Hash of data verified`，退出码 0。应用 SHA256 `2281de1c75add0247361962d562b59f022ac54e4247f456d53f8d45fe846058a`，assets SHA256 `3b5897f8fff8e6e49904494f2a7422c149291af547423cc835e2031e9a9f7a2e`。没有写入 NVS、OTA 数据、`ota_1`、分区表、bootloader 或其他区域。证据 `logs/flash-app-assets-robot-ui-bd639a9-20261115.log`。
- 后端仅同步 `backend/app/device_realtime.py` 与 `backend/app/realtime.py`，两份运行副本分别与工作树 SHA256 一致；明确停止旧服务属于用户授权重启。新服务实际 PID 29012，8000/8003 均由该进程监听，`/health` 为 `status=ok/configured=true`；项目 `.venv` 脱敏采集包装器显式设置并传递 `AI_EMBEDDING_ENABLED=true`。日志 `logs/backend-robot-ui-bd639a9-20261115.err.log` / `.out.log`。
- 新 COM3 采集 PID 21072、115200 UTF-8，日志 `logs/serial-robot-ui-bd639a9-20261115.log` 持续写入并脱敏。为采集启动证据，在串口已打开时按 esptool 同样的 RTS 脉冲重启设备一次；13:33:07 串口确认 `RobotDisplay: loaded 55 unique frames`，13:33:12 进入 idle 并启动 `mn5q8_cn` 的“塔菲”唤醒检测，后续原始麦克风和 16k 输入非零；启动阶段未见 panic 或资源加载失败。设备没有由 AI 发起语音对话，时间、文字布局、表情、实际听感及真人打断/待机再唤醒仍由用户现场测试。
- HEAD 为 `bd639a9` 加本轮未提交修改；保留 `.env`、data、配对和既有日志，未重新编译、提交或推送。此前针对性检查为 15 passed，本次不把刷写校验、health 或音频采集当作语音体验通过。

## 第一版机器人资源、时间与状态屏已接入（2026-11-15，编译通过，未刷机）

- 按用户选择接入 `E:\浏览器下载\device-animation-pack.zip`，ZIP SHA256 `b3956b12a8707b5ce2d8ddf4c08ab961237589fe3e37ac812f881f4f16a96e88`。15 张原始 PNG 和帧序配置纳入板级 `animations/`，170 帧按 128×128 原坐标和 80ms 节奏转换为 55 张独立 LVGL I4/RLE 帧，图像数据 44087 字节；重复画面共享帧描述符且不重复设图，运行时不做 PNG 解码。独立 FFmpeg 解码与原生 I4/RLE 解压回算逐像素核对 170/170 一致，顶部/底部透明区和未使用网格均合规。
- `robot_display.h` 替换旧四态像素显示：顶部 y=0–17 常驻 HH:MM、中部 y=18–105 保留原表情、底部 y=106–127 显示实际状态。沿用后端 OTA 的 UTC+8 校时，不另加网络校时请求，未校时显示 `--:--`。移除旧向上偏移和底部环形/柱状占位图标；连接与思考分开，支持循环、单次、保持末帧，允许设备事件立即切换；待机约 20s 可播放一次 idle_action，底部仍为待机。
- `application.cc` 只增加显示通知：收到 `ui` 消息调度到主任务更新表情，唤醒与主动打断补充本地显示事件。`device_realtime.py` 在原有 next/thinking/error/idle/无音频收尾事件发送状态，结束意图后以 sleep 表情进入原有 idle，不改电源或唤醒流程。`realtime.py` 只为 device_voice 在工具执行前后补充显示事件；成功基于工具状态、HTTP 状态和控制回读，订单待确认/否认显示澄清，播放期间不让工具显示覆盖说话。activity 保留当前 turn_id 检查。语音采集、AEC、Opus、独立收发/播放任务、取消清队列、采样率、声道和 use_mclk=false 均未修改；打断先执行原有音频停止再通知显示。
- `main/CMakeLists.txt` 将切帧及资源表生成加入正式构建依赖，动画合入 assets 的 extra_files，保留原 srmodels、字体和资源索引。sdkconfig 相比本次构建前只有 `CONFIG_LV_USE_RLE=y` 一项变化。最终 assets 79 项、2555952 字节，位于原 0x280000 分区内、余 65488 字节；srmodels.bin（2203819 字节）和 font_puhui_common_14_1.bin（272172 字节）与构建前逐字节相同。
- 固件最终编译退出码 0：应用 2747712 字节（0x29ed40），适配原 0x2b0000 分区，余 70336 字节；应用 SHA256 `2281de1c75add0247361962d562b59f022ac54e4247f456d53f8d45fe846058a`，assets SHA256 `3b5897f8fff8e6e49904494f2a7422c149291af547423cc835e2031e9a9f7a2e`。日志 `logs/firmware-build-robot-ui-pack1-final-20261115.log`。首次编译发现 Wi-Fi 查询接口引用错误，修正为本项目 WifiManager 后增量编译通过；没有因编译失败改动音频链。
- 现有 `tests/test_realtime_failures.py tests/test_devices.py` 15 passed、退出码 0，只补齐既有测试夹具的状态发送接口，未增加模拟后台或完整套件；日志 `logs/pytest-robot-ui-pack1-20261115.txt`。构建仍有原应用分区余量提示；首次全量构建中的 esp_video/lwIP 宏重定义和 pytest 依赖弃用提示未另行扩改。
- 新固件源和构建配置已同步本机构建目录，后端修改仍留在主工作树，未覆盖运行副本或重启。原构建应用、assets 和配置保存在 `.cache/device-backups/pre-robot-ui-20261115-115637/`。本轮未刷机、未改 NVS/配对/.env/data、未 commit/push、未发模型请求或代替用户真机测试。部署需要应用区和 assets 区同时更新，不能沿用此前“只刷应用、保留旧 assets”的方式；顶部时间、中文状态、动画听感并行、真人打断、退下后再唤醒均待用户现场确认。

## 修复提交与项目冗余清理（2026-11-15）

- 按用户“做到这个程度，先 git，再清理”的要求，将本轮已上机的 AEC/唤醒、发送/播放调度、空转写收尾、上游错误详情、逐回合指标和实际验证记录提交为 `ead6381`（`fix: stabilize device audio streaming and wake lifecycle`）。仅本地提交，未 push；完整故事、不中断报数至一百、退下后再次唤醒的本轮覆盖边界沿用下一节，没有补写验收。
- 检查现有测试用途后保留 11 个 `test_*.py` 和浏览器语音回归脚本，它们仍覆盖现有功能及已发生故障。删除无运行入口引用、固化旧日期和本机输出地址的一次性 `scripts/weather_live_check.py`，以及已由 Git 保存历史的板级 `.official.bak`；主工作树与运行副本同步。删除运行目录根部 `tmp_ab_models.py` 和 output 内 18 个未被其他项目文件引用的 `_*.py` 临时分析脚本，保留正式回归脚本、结果 JSON、截图、日志和音频样本。
- 14 个旧固件构建目录、7 个测试浏览器配置目录、4 个 pytest 临时数据库目录、2 个 pytest 缓存和 9 个项目 Python 缓存目录已移入 Windows 回收站；另清理 `$null` 错误重定向产物和 3 个 IDF 临时环境文件。此部分合计 11159 个文件、1559081093 字节（约 1.45GiB）。目录永久删除曾被自动审批拦截，改用可恢复回收站操作完成；未清空回收站，不将移出项目目录的大小算作磁盘空间已释放。
- 当前 `build-tafei-mn5-ui-anim` 完整构建、应用、assets、sdkconfig、整机备份、工具链、依赖、模型、`.env`、data 与配对信息均保留；清理前后 `.env`、当前 sdkconfig、应用、assets 和整机备份文件 SHA256 一致。补充临时脚本、源码备份和 IDF 临时文件的 Git 忽略规则，同步目录职责说明。没有修改业务代码、重新编译、刷机、重启服务或发起模型调用。

## 发送/播放修正版真机复核（2026-11-15 10:51–10:52）

- 用户现场反馈“特别顺利，而且没有卡顿”。按会话 `7ae295a8-58a1-4891-8627-63d2cfce3c9e` 核对本轮串口、后端和 `logs/device-audio-turns.jsonl`，共 6 条回合归档、4 个有下行音频的回合；未混入此前批次。日期、报数、呼叫应答、闲聊的发送/接收包数分别为 59/59、96/96、27/27、39/39，CRC 分别为 `b6cbedaa/fa8b21f8/ef80e5e3/03f4379c`，均一致，设备入队丢包为 0。用户听感与本轮传输及播放指标一致，不能外推长期稳定性。
- 本轮未出现 AFE 缓冲满、设备慢发送、编码/发送拥塞、慢解码、TCP 发送/接收失败、panic 或后端接收异常/traceback。云端上行 stalls 和队列丢帧均为 0，最大发送耗时 16ms；网关断粮为 0、各有音频回合最大下发间隔 63–79ms。排除回答第一帧前的正常闲置等待后，14 条连续播放采样间隔为 59–60ms，没有回答内部超过 120ms 的播放间隔告警。串口 `gap_ms=9789/10799/2119/2930` 均位于新一段的首帧，不能算作回答中卡顿。
- 报数回合 `706f7693`：10:51:54.024 转写“跟我从一报一百报数”，10:51:54.632 开始 TTS、10:52:00.382 被新语音打断；模型 `cancelled/turn_detected`，文本一至一百顺序正常，未见从头重复段。源/处理后音频约 25.92/21.41s，编码 356 包、实际下发及接收 96 包（5.76s），打断清掉 260 包（15.60s）。随后输入转写“咖啡”，新回合回应“哎，在呢”，设备连接保持。已验证本段连续播放及语音打断，没有完整播放到一百的证据；非静音相邻相同 PCM 块为 0 也不能单独证明语义无复读。
- 本轮会话没有讲故事/笑话请求，不能确认故事正文完整播完。10:52:06.144 的“退一下吧”先被作为闲聊回答“哎呀，退一步海阔天空嘛”；后续回合 `4158c780` 才命中 `end_intent`，10:52:12.928 显示“好的，我先休息了”，12.973 进入 idle、12.986 重启 `mn5q8_cn` 唤醒检测。服务端 idle 分支主动关闭 WebSocket，关闭码 1000；10:52:23 的 `TCP peer closed` 为待机后的连接清理，不是播放中掉线。采集截至 10:59 仅见 10:51:30 的一次唤醒成功，没有退下后第二次唤醒成功样本；不将未覆盖项判成故障或通过。
- HEAD `b8e4a2a`，本轮只复核证据并同步进度，没有改业务源码、重启、刷机、提交或额外调用模型。后端 PID 4896、8000/8003 监听和 health 正常，embedding 延续开启；COM3 采集 PID 26144 继续运行。日志为 `logs/serial-send-playback-finish-b8e4a2a-20261115.log`、对应 `backend-send-playback-finish-b8e4a2a-20261115.err.log/.out.log` 及逐回合归档。

## 新固件应用区已刷入、COM3 采集已启动（2026-11-15 10:28）

- 按用户授权刷入本轮发送/播放/收尾修正版应用，SHA256 `ebcc395f613efb9a113e2358e20d9fe8c297103cd4958dfb619e62beddd6a52e`，2745744 字节。只执行单文件 `write_flash 0x20000 xiaozhi.bin`，实际擦写范围 `0x00020000–0x002befff`，处于现有 ota_0 内；设备哈希校验通过、退出码 0。未写 NVS、配对所在数据分区、OTA 数据、分区表、bootloader 或 assets，未重新编译。证据 `logs/flash-app-send-playback-finish-b8e4a2a-20261115.log`。
- COM3 115200 UTF-8 采集 PID 26144，`logs/serial-send-playback-finish-b8e4a2a-20261115.log` 持续增长，能看到麦克风及输入音频日志，未见采集错误或 panic。采集继续在写盘前脱敏。
- 新后端 PID 4896 继续运行，未重启；8000/8003 正常监听、health `ok/configured=true`，embedding 保持启动时的 true。检查时网关 `connected=false/ready=false/last_error=null`，等待用户唤醒建立语音连接；未由 AI 发起真机对话，不将刷写和采集成功记为听感通过。

## 新后端已启动（2026-11-15 10:21）

- 按用户“服务拉起来”授权，确认 8000/8003 无监听实例后，将六个已修改后端 Python 文件同步至 `E:\xiaodan` 并核对哈希，使用项目 `.venv` 启动 `backend.run_devices`，显式保持 `AI_EMBEDDING_ENABLED=true`。实际服务 PID 4896，8000/8003 均正常监听，health `ok/configured=true`、模型 `qwen3.8-omni-flash-realtime`。
- 新日志 `logs/backend-send-playback-finish-b8e4a2a-20261115.out.log` / `.err.log`，继续在写盘前脱敏凭据。未刷固件、未调用云模型或进行真机测试；检查时 COM3 原采集 PID 已不存在，本次仅启动后端，未启动串口采集。

## 发送、播放调度和空转写收尾修正（2026-11-15，编译通过，未刷入）

- 用户已确认上一批次“阿飞”“海飞”两次均为主动打断，报数/笑话对应的 `next → stop_audio` 与清队列属于正常打断，不再列为回声误触发证据。本轮继续解决独立存在的同步发送阻塞、播放调度耦合、空转写不收尾及上游错误丢细节；HEAD 仍为 `b8e4a2a`，修改未提交。
- 发送链存在两处实际同步等待：设备主循环直接执行 `SendAudio`；后端设备 WebSocket 接收循环直接等待云端 `open/append`，云端等待期间不再消费设备帧。`application.cc/.h` 将上行发送迁至独立任务、继续消费原有设备队列；`device_realtime.py` 与 `devices.py` 将云端建连和上行发送移至独立协程，LAN 接收循环继续处理音频和 MCP。后端新增 40 帧（2.4s）有界上行队列，用于拆开读取与云端等待，未增大设备的发送/播放缓冲；溢出会丢弃最旧帧并显式记录，不伪称无损。逐回合增加 `uplink_queue_dropped`、`max_uplink_queue_ms`；手动停止与音频按 FIFO 顺序提交，避免队列尚未送完就 commit。
- 原生 TCP 的现有实现使用无限等待的 `send`，关闭时直接 close 并等待接收任务最多 10s。新增 `main/network/esp_tcp.cc/.h` 与对应 `esp_network.cc`，由根 `CMakeLists.txt` 仅替换组件的两个原生实现源，不改 managed_components、不升级/下载组件、不加运行时备用通道。语音 WebSocket 使用的 connect_id=1 开启 TCP_NODELAY，以非阻塞 send/select 按整次写入 250ms 期限发送；超时/错误记录 errno、已发送字节、总字节和耗时，明确断开连接，不将半帧与后续 WebSocket 帧拼接。主动关闭先 shutdown 唤醒 recv，再等待接收任务退出；接收超时检查关闭状态，并保留真实接收错误的 errno。OTA/assets HTTP 使用的 connect_id=0 保持普通发送路径。当前只针对实际 LAN `ws://` 原生 TCP 链，未宣称改造 TLS。
- 独立发送引入并发后，`application.cc/.h` 对协议实例持有快照；`websocket_protocol.cc/.h` 对连接持有快照并以 channel epoch 隔离旧连接回调，避免关闭/重新连接时悬空访问或旧回调把新连接切回 idle。控制消息发送失败不再打印整条消息内容。
- `audio_service.cc/.h` 原 Opus 编码和解码共用优先级 2 的任务；现在解码独立为优先级 5 的任务，编码仍为 2、输出仍为 4，队列容量不变。解码重置以原子 epoch 在解码前和 PCM 入队前检查，避免已弹出的旧包在重置后污染解码状态或重新进入播放队列。记录 `audio_decode_slow`，播放输出对超过 120ms 的间隔也记录 `wait_ms/write_ms`，不再仅靠每 16 帧采样，以区分等待解码数据与 Codec 输出耗时。上一轮 859ms 空档没有这些细分观测，仍不能反推其唯一物理原因已被证实。
- `realtime.py` 将“用户转写非空”与“转写事件已结束”分开：收到空转写也可完成音频尾部和 done/tts-stop；模型先完成时仍等待转写事件，保留迟到的真实用户文字，不伪造用户消息。上游 error、转写失败和响应失败保留完整 error/status_details、事件/响应/请求标识、session/turn ID，复用现有脱敏函数遮盖实际模型/语音/工具凭据，再写入异常与完整 traceback。历史 `cadd02c3` 的原始供应商载荷当时已丢弃，无法追溯恢复，本改动用于后续错误。
- 最终应用构建退出码 0，`firmware/xiaozhi-esp32/build-tafei-mn5-ui-anim/xiaozhi.bin` 为 2745744 字节（`0x29e590`），在 `0x2b0000` 应用分区内，余 `0x11a70`；SHA256 `ebcc395f613efb9a113e2358e20d9fe8c297103cd4958dfb619e62beddd6a52e`。最终日志 `logs/firmware-build-send-playback-finish-release-b8e4a2a-20261115.log`。sdkconfig 前后 SHA256 相同（`76bbdeb4e79a9d8339c3e8a043d4add89c476aaa7e5b5dd30d7af3b400ec7217`），未改 use_mclk、AEC、声道或采样率。
- 必要检查：`tests/test_realtime_failures.py tests/test_devices.py` 最终 15 passed、退出码 0，覆盖空转写收尾、错误详情脱敏、云端建连等待期间继续接收及停止顺序；三个变更后端模块语法编译通过，`git diff --check` 通过。证据 `logs/pytest-send-playback-finish-b8e4a2a-20261115.txt`。未运行完整套件或调用付费模型。构建仍有 esp_video/lwIP 头的 `_IO/_IOR/_IOW` 重定义与应用分区余量提示；pytest 有依赖弃用提示，未为此升级依赖。
- 按用户要求本轮未刷机、未重启后端、未操作设备；固件源只同步至现有本机构建目录，三个后端模块的新代码仍留在 Git 工作树，未覆盖运行副本。现场仍运行上一轮固件、后端 PID 30808 和串口采集 PID 7284。新固件/新后端尚未实际联调，不能声称发送不再超时或听感已无卡顿。后续部署两端后由用户验证：唤醒后短问答、不中途打断的一至一百、完整故事/笑话、主动语音打断、退下再唤醒；同时检查上行排队/丢帧、发送 errno、播放 wait/write 与按回合 CRC。

## 本轮真机日志复核（2026-11-15，23:58 至次日 00:00 批次）

- 复核 `logs/serial-afe-turn-metrics-b8e4a2a-20261114.log`、对应后端 `.err.log`、`logs/device-audio-turns.jsonl` 和两个实际会话历史，未改业务源码、重启、刷机或额外调用模型。测试时间为北京时间 2026-11-14 23:58:25 至 2026-11-15 00:00:45；14 条归档含 11 个有下行音频的回合。11 轮均核对网关发送与设备接收包数及 CRC 一致，设备解码入队丢包为 0；所有归档网关断粮为 0，最大下发间隔 78–79ms。字节一致不能证明物理听感或语义不重复。
- 报数回合 `3b2ffd96`：23:59:47 转写“从一数到一百”，文字累计 369 字、含一至一百；23:59:48.671 开始 TTS，23:59:53.634 因 `next → stop_audio` 停止，模型响应 `cancelled / turn_detected`，随后新输入转写“阿飞”。截至取消，源音频 20.48s、处理后 16.929s，已发送/接收 83 包（4.98s、CRC `f9c3b95c`），清空待播 199 包（11.94s）。网关供给最大间隔 78ms、断粮 0，采样 PCM 输出间隔 59–60ms；源/处理后最长低能量段 360/280ms，没有相邻完全相同的非静音 20ms 块。这些排除了本轮已观测的网关断粮/收包丢失证据，但不能据此断言听感没有停顿、合成没有语义重复；“阿飞”是否用户主动打断待用户确认，不能直接记为回声自打断。
- 本轮长正文请求实际是“给我说个笑话吧”，未检索到独立讲故事请求。笑话回合 `874e33be` 已生成含铺垫和包袱的 105 字正文，模型正常 `completed`；源/处理后音频 20.64/17.199s，编码 287 包。但 00:00:24.403 被新输入打断，仅下发/接收 112 包（6.72s、CRC `1209163f`），其余 175 包（10.5s）清空，随后转写“海飞”。不能将正文生成完成或历史 `complete` 当作设备播放完成；历史显示 `complete` 而音频归档为 `interrupted` 的差异已由本轮确认。故事正文完整性仍缺该请求的实际样本。
- 原 AFE 阻塞告警本轮未出现，设备上行发送阻塞期间 AFE/Opus 仍持续产出；但同步 `SendAudio` 有 9 条超帧耗时记录，最大 9856ms，另有 9760ms、3951ms 等，`audio_send_congested` 累计日志至少 272 帧。该耗时测量包含 WebSocket 发送锁与 TCP 发送，现有日志不足以在两者及网络中定因，不能称 AFE 修正已解决网络阻塞。23:58:34.811 招呼阶段另有设备 `playback_tx gap_ms=859`，同轮网关最大下发间隔仅 78ms，设备播放间隔仍有真实异常证据；长报数/笑话采样未出现同样间隔。
- 首轮招呼 `90b00f85` 还有确定的收尾条件缺陷：设备转写为空、模型已正常 `completed` 并生成 17 字回答，但 `realtime.py` 只在 `response_done and self.user and not self.saved` 时完成音频并发送 done；空转写使该分支不执行。归档没有 response_done 时点，设备保持 speaking，直到下一轮 `next` 才停止；这不是模型没有回复，也不能记为正常结束。
- 23:58:43 音量请求 `cadd02c3` 存在真实 `realtime_receive_failed event=error error_type=ValueError`；完整 traceback 只有 `realtime.py:400 receive → raise ValueError() → ValueError`，代码丢掉了上游 error 载荷，无法还原供应商错误码/原因。该轮未下发音频，设备连接仍保持至 23:59:03，首会话总接收 465 帧、丢弃 191 帧（含未监听/失效回合阶段，不能全部归于该错误）。23:59:03 串口出现 `TCP receive failed: -1`，后端收到关闭码 1005；现有证据无法严格判定首次关闭由哪端发起，不能归为后端进程退出。23:59:04 新会话建立，同样音量 80 请求工具 `ok` 且回读 `verified=true`，随后正常下发回答，证明重新发起对话可重试。本轮没有 `device_realtime_upstream_closed`。
- 00:00:44.34 结束意图被处理，服务端 idle 分支主动关闭设备 WebSocket，随后设备 `listening → idle` 并重新启动 `mn5q8_cn` 唤醒检测，关闭码 1000；这是预期待机收尾。此次待机后没有再次唤醒样本，不能补写再次唤醒验收。播放期间可见实际参考信号及较低 AFE 输出，但原始麦克风有 4 条满幅峰值采样，多次短名被转写为“咖啡/阿飞/海飞”，来源及原话需结合用户现场确认。
- 复核时后端 PID 30808、COM3 采集 PID 7284 保持运行，health `ok/configured=true`，网关 `gateway_running=true/connected=false/last_error=null`；用户未提供本轮具体听感和主动打断时点，不记整体通过。

## AFE 新应用已刷入并重启采集（2026-11-14 23:51，待用户真机验证）

- 按用户授权仅将上一节构建的 `xiaozhi.bin` 写入 `ota_0` 地址 `0x20000`，实际擦写范围 `0x00020000–0x002bdfff`，2741696 字节，设备哈希校验通过、刷写退出码 0；SHA256 为 `2442934d562379e24b4005da57f62c8cb1cb4fd6b99d4f37294a7a5534159093`。未写 NVS、OTA 数据、分区表、bootloader 或 assets，未重新编译。证据 `logs/flash-app-afe-turn-metrics-b8e4a2a-20261114.log`。
- HEAD 仍为 `b8e4a2a`，保留既有未提交修改；五个已修改后端 Python 文件重新同步至运行副本并核对哈希，未覆盖 `.env`、`data/` 或配对配置。主动停止原后端 PID 19548/21088 和原采集 PID 19060，这次退出属于授权重启。
- 新后端实际服务 PID 30808，由项目 `.venv` 执行 `python -u -m backend.run_devices`，明确继承 `AI_EMBEDDING_ENABLED=true`。`/health` 返回 `status=ok`、`configured=true`、模型 `qwen3.8-omni-flash-realtime`；8000/8003 均由 PID 30808 监听。运行日志采集脚本在写盘前脱敏凭据，不改请求或业务源码，分别写入 `logs/backend-afe-turn-metrics-b8e4a2a-20261114.out.log` / `.err.log`。
- COM3 115200 UTF-8 采集 PID 7284，`logs/serial-afe-turn-metrics-b8e4a2a-20261114.log` 持续增长，可见新应用运行中的麦克风和音频输入日志。网关 `gateway_running=true`、`connected=false`、`ready=false`、`last_error=null`；未主动唤醒设备、发起对话或调用云模型，当前未建立设备语音 WebSocket。
- 已部署新的按回合音频记录逻辑，实际对话结束后应追加 `logs/device-audio-turns.jsonl`。长报数卡顿/重复、故事正文、真人打断和退下后再次唤醒均等待用户本次真机验证；服务就绪、刷写校验和串口数据不代表听感验收。

## AFE 阻塞、长回答与逐回合音频证据（2026-11-14，已编译，未上机）

- 在上一节已上机版本的基础上继续修改，HEAD 仍为 `b8e4a2a`，未提交。AFE 阻塞的代码链为：上行发送队列满 → Opus 编码被队列容量条件阻止 → 两帧编码输入队列满 → AFE fetch 的输出回调无限等待。移除编码对网络发送队列空位的依赖，AFE 输出入队不再阻塞；容量仍为原值，实际拥塞时淘汰最旧帧并明确记录 `audio_encode_congested` / `audio_send_congested` 累计数量，不把丢帧当成功。主循环每次处理一帧发送，剩余帧重新触发事件，避免积压时长期占用控制循环；超过一帧时长的同步发送记录耗时。未关闭 VAD、ASR 或插话，未扩大缓冲。
- 修复另外查实的下行竞态：原 `tts/start` 只排队给主线程改变 speaking，网络线程紧随收到的音频会因状态仍为 listening 被丢弃；随后 speaking 状态处理还会重置解码队列。现在在网络消息顺序内先完成解码重置，再开放本次 TTS 收包；speaking 只负责状态/界面切换。interrupt 的解码重置也移到对应网络消息处，防止迟到的主线程任务清掉下一轮音频。串口按 `turn_id` 记录接收包数、解码入队丢包数和 CRC32，并采样记录实际 PCM 输出间隔。
- 后端在完整发送、打断、结束意图、错误或关闭时，将对应回合快照追加到 `logs/device-audio-turns.jsonl`，包含稳定 session/turn ID、结束原因、模型音频与语速音调处理后音频的停顿位置/时长/CRC、相邻相同非静音块、编码/发送包数与 CRC、最大供给间隔及其位置、断粮/清队列、向模型上行发送耗时。切换回合前先归档，取消/失败且没有音频也能留下记录；文件写入在后台线程串行执行，不在逐包路径写盘。不保存录音、正文或凭据。设备 CRC 对应网关 `sent_crc32`，用于比对字节传输，不能证明物理出声或语义不重复。
- 故事正文缺失的实际证据仍是模型只生成承诺句后正常结束，不是已证实的本地截断。已补充共享语音提示：长内容直接以正文开头作为首响、同次回答连续完成，故事须含起因经过结尾，不只承诺开始。保留角色、音色、语速音调、普通聊天首响；没有增加自动续写调用、重试或备用模型。新增 `realtime_response_done` 元信息，记录响应 ID、结束状态/原因、文本字数和响应段数，用于区分正常结束、长度截断和取消；模型是否实际遵从长故事要求仍待用户验证，不写成已实跑修好。
- 最终固件构建退出码 0，应用 `0x29d5c0` 字节，适配现有 `0x2b0000` 应用分区；`firmware/xiaozhi-esp32/build-tafei-mn5-ui-anim/xiaozhi.bin` SHA256 `2442934d562379e24b4005da57f62c8cb1cb4fd6b99d4f37294a7a5534159093`。构建日志 `logs/firmware-build-afe-turn-metrics-b8e4a2a-20261114.log`。五个变更 Python 模块语法编译通过；现有转写异常/上游关闭隔离回归 5 passed（只更新既有夹具字段），见 `logs/pytest-afe-turn-metrics-b8e4a2a-20261114.txt`。用已有真实语音样本 `.cache/omni-latency-question.wav` 在实际 FFmpeg 1.2 倍语速、音调 3.0 路径离线运行，2840ms 输入产出 2325.12ms PCM / 39 个 Opus 包；增量 CRC、分块边界一致性与编码 CRC 核对通过，证据 `logs/audio-metrics-offline-b8e4a2a-20261114.json`。这些不代表真机长播已通过。
- 源码已同步 Windows 运行副本；本轮未刷机、未重启后端、未实际对话或调用云模型。设备仍运行上一轮已刷固件，后端 PID 19548 与 COM3 采集保持原状，新指标文件需新后端加载后才生成。待用户在更新应用和后端后验证：故事正文、长报数不中断/重复、正常真人打断、连续两次退下再唤醒；通过回合 ID 对照源音频停顿、发送供给、设备收包/入队和实际 PCM 输出。单纯编译、零异常或校验值一致不能代替现场听感。

## AEC 播放参考与待机唤醒修正（2026-11-14，基础真机已确认，长音频仍有异常）

- 基于 `b8e4a2a` 修改，尚未提交。K147 当前路径为单麦克风 ES8311；AFE 输入实际为 `MR`，`R` 是软件播放参考，不是第二只麦克风。原实现在阻塞 `esp_codec_dev_write` 返回后才缓存整段 PCM，再额外插入 35ms 参考静音，参考时间线没有跟随实际 I2S 播放；`ResetDecoder` 还会清掉参考，但清除软件播放队列不会清除已送入 TX DMA 的音频。
- 参考改取 I2S `on_sent` 回调中实际发送完成、尚未被驱动自动清零的 DMA PCM，静音同样持续进入参考流；固定缓冲容量对应 RX 驱动的五个待取 DMA 块。麦克风延迟两个 DMA 块（当前 24kHz 下为 20ms），给完成回调与 RX 读取留出因果顺序；`M/R` 仍一起重采样到 16kHz，再送现有 ESP-SR AEC。取消猜测的 35ms 参考垫零，以及解码器重置时清除物理播放参考的行为；没有关闭播放期间的 ASR、服务端 VAD 或 `next` 打断路径。`use_mclk=false`、原采样率、音色与资源保持。
- 待机唤醒使用自定义 MultiNet，不是 WakeNet。查实 `CustomWakeWord::Start` 原先只设运行标志，没有重置模型状态；现在线程互斥地调用 ESP-SR `clean`、清输入缓存后重启，并记录模型和命令数量。另修复两个确定的连接状态错误：音频连接已经打开时，唤醒继续函数原先因仍处于 `idle` 而直接返回；连接失败后原先停留在 `connecting`，后续唤醒无法进入正常分支。现在统一进入 `connecting`，失败则恢复 `idle` 和本地检测。现有日志没有唤醒检测内部状态，不能据这些代码缺陷宣称已唯一解释现场未命中的原因。
- 使用项目现有 ESP-IDF 5.5.2 和 `build-mn5-ui-anim.ps1` 编译通过，实际构建退出码 0；应用 `0x29d040` 字节，适配现有 `0x2b0000` 分区。产物为 `firmware/xiaozhi-esp32/build-tafei-mn5-ui-anim/xiaozhi.bin`，SHA256 `de9ce5b6c8c977930396cd1065224516ea4452a84b6eae2b566ece4967616f72`；日志 `logs/firmware-build-aec-wake-b8e4a2a-20261114.log`。链接映射确认回调位于 IRAM、静态参考缓冲所在 codec 对象位于内部 DRAM。源码修改同步至 Windows 运行副本。
- 22:48 用户授权后读取设备分区表，确认当前 OTA 选择 `ota_0`，仅将上述应用写入 `0x20000`；实际擦写范围 `0x20000–0x2bdfff` 位于该应用区，esptool 报告哈希校验通过、退出码 0，未写 NVS、OTA 数据、分区表或 assets。证据 `logs/flash-app-aec-wake-b8e4a2a-20261114.log`。后端原有 PID 19548，8000/8003 监听，health=ok；COM3 UTF-8 采集于 22:49 开始，`logs/serial-aec-wake-b8e4a2a-20261114.log`，已观察到麦克风和重采样数据非零。尚未由用户验证物理体验。
- 上条“尚未由用户验证”是 22:49 启动时的历史状态。22:57–22:59 用户现场确认：待机叫“塔菲”进入 listening、日期问答顺畅、报数期间真人插话打断、说“退下吧”回待机。串口 22:57:58.803 唤醒命中概率 0.948143，22:57:59.363 进入 listening；22:59:10.699 回 idle，随后打印 `Wake detection started model=mn5q8_cn commands=1`。本次仅见一次待机唤醒，不能写成多次“退下后重新唤醒”循环已验证。当前会话 `ed7db03e-14d1-48c9-85b0-81a7a95d0017`，六次模型响应成功，无接收异常、traceback、设备 abort 或 TCP 接收失败，结束意图后正常关闭码 1000。
- 新发现明确异常：22:58:26.599–22:58:36.420 共 542 条 AFE FEED 缓冲满警告，出现在故事请求附近、报数播放之前。源码中 AFE fetch 回调会等待有界编码队列，主任务通过同步 WebSocket/TCP 发送上行，存在发送/编码反压阻塞 fetch 的链路；现有日志不能确定具体阻塞调用，不能简单归因于 Wi-Fi 或 AEC 算法。另“一分钟故事”实际只生成“好呀，那塔菲给你讲一个短故事喵。”并结束，没有故事正文；部分“塔菲”被 ASR 识别成“咖啡”，局部采集仍有满幅峰值。
- 报数播放 22:58:49.184–22:58:59.827 只有一段 speaking，没有反复 speaking/listening；该问题只生成一次完整 1–100 文本，数字顺序和次数正确，无旧式反复生成证据。这不否定用户听到的卡顿和音频重复：52/53 秒播放参考采样为零，当前未留逐包或原始 PCM，不能区分源音频停顿、发送供给、音频处理或设备播放问题。`last_realtime_latency` 已被末轮日期问答覆盖，其 79ms 最大包间隔、0 次断粮仅属于末轮，不得用于证明报数正常。证据已保存 `logs/evidence-aec-wake-b8e4a2a-20261114-225759.json`；本次仅分析采证，未改业务/固件源码、未再刷机或代替用户测试。长音频和多次待机唤醒的稳定性仍待确认。

## 转写完成异常与设备连接隔离（2026-11-13 晚）

- Windows `de3764c` 真机反馈及 `diagnostic-de3764c-20261113` 日志确认：ES8311 原始收音、重采样、AFE、Opus 均恢复非零；按键会话收到 83 帧。最后一条百炼入站事件后，本机先发 CLOSE 1000，之后设备退出 listening。截断的事件日志不能提供完整转写内容或根异常堆栈，不能写成正常回答通过。
- 源码定位到转写分支必经的错误调用：`_is_end_intent` 是模块函数，却被调用成 `self._is_end_intent`，会触发未被原异常列表捕获的 AttributeError。已改为模块函数调用；receive 对本地异常记录事件类型、异常类型/文本及 traceback，取消单独记录并重新抛出，不再统一误报为百炼/额度故障。
- receive 清理前先关闭输入，阻止设备音频在上游关闭期间继续追加。设备桥接分别捕获向百炼 append/finish 时的 ConnectionClosed，只结束本轮上游、清播放并向设备发错误文字；设备路由不再把它当成设备 WebSocket 关闭。设备连接保留，后续显式 listen/start 可重建回合，不自动反复重连/调用模型。
- 本轮仅改后端与相关回归检查，未改固件、AEC、声道、采样率或 use_mclk=false，未操作现场服务或设备。Mac 上 Python 语法检查通过，结束意图函数 4 个输入及调用绑定检查通过。新增 5 项事件处理/连接隔离单元回归供 Windows 执行；本机无 pytest/websockets/FastAPI/Pydantic，未运行完整测试或真实百炼/设备回归。

## 设备全双工与原始收音定位（2026-11-13）

- `d8cad77` 增加设备 AEC 能力声明、软件参考环形缓冲及打断清队列；`4d789cb` 增加分段音频 RMS 日志、15 秒控制查询保活和连接关闭异常捕获。Windows Agent 报告两版均编译/仅刷应用成功，设备相关测试各为 7 passed；不代表全双工可用。
- `4d789cb` 真机反馈：待机及按键进入 listening 后，`mic_raw ret=0` 但 RMS/peak 全零，重采样、AFE、Opus 和后端解码也全零；接收 534 帧、无丢帧、无转写/回答。问题已缩到原始麦克风/codec/I2S 采集，不能归因于 AEC 后级消音。
- 源码核对发现板级没有 MCLK 输出（GPIO_NUM_NC），却省略构造参数并沿用 `use_mclk=true`。M5Stack [官方 M5Unified](https://github.com/m5stack/M5Unified/blob/master/src/M5Unified.inl) 的 `_microphone_enabled_cb_atomic_echo` 明确将 ES8311 时钟配置为 MCLK=BCLK；Espressif [ES8311 驱动](https://github.com/espressif/esp-adf/blob/master/components/esp_codec_dev/device/es8311/es8311.c) 在 `use_mclk=false` 时选择 BCLK 并设置内部时钟倍频。此次仅为 AtomS3R Echo Base 显式传入 `false`，新增启动日志 `clock_source=BCLK`；AEC、采样率和音色保留。此修正尚待 Windows 编译及真机非零收音验证，不能写成根因已修复。
- 撤回此前“固定 20 秒 EspTcp 接收超时”的判断：Windows 核对实际依赖 `78__esp-ml307/src/esp/esp_tcp.cc` 未设置 SO_RCVTIMEO，PING 有独立 PONG 处理；本轮约 32 秒断开。15 秒查询保留为主动保活，不当作断线已修复。TCP 断线原因仍未确定，需实际 errno/关闭码证据。

## 历史进展（2026-11-10～11-11：设备屏幕与像素动画）

- 设备屏幕根因与修复：确认新批次 AtomS3R 使用 ST7735 面板（非旧 GC9107），改用 st7789 驱动 + 面板 gap(2,1) + invert(true)、offset 归零后，方向/花屏/颜色恢复正常；此前 offset 写成 32 导致画面顶出可视区。经串口日志确认帧资源加载成功，问题在绘制层而非数据。
- 像素 UI 与状态动画：待机呼吸、聆听侧转耳前、说话口型、适当眨眼；多态共用同一基准帧（第 0 帧逐像素一致），切状态不跳脸；12.5fps、透明底、像素风。帧因 assets 空间压缩到 84px、15 色；assets 余量约 7.5KB，很紧。
- 说话口型：多次迭代仍反馈偏丑/生硬；改为以基准帧为底、仅局部重绘嘴部（并做嘴位对齐）继续打磨，未定稿。
- 新增两条真机待办（未做）：①叫“塔菲”时用户看不出是否已唤醒，需补明确唤醒反馈（提示音与/或屏幕明确进入聆听）；②说“闭嘴/关机”应回到待机，之后叫名字能重新唤醒，需实现并真机验证。
- 说明：以上为编译与上机层面的观察；真机完整听感/多轮/打断仍未系统验收，AEC 未实现。

## 订单编号确认闭环（2026-11-08，已真实复验；真机与部分 WS 输入仍待验证）

- 新增 `backend/app/order_confirmation.py`：按 session 隔离的跨轮确认状态（pending / 当轮 confirmed / 当轮 denied），支持“是/对/没错”确认、“不是/不对/错了”否认、“不是，是 PH1002”更正；状态只约束当前轮和紧随的确认轮，下一轮用户明确说出编号仍可查询。
- `tool_dialogue.TurnTools` 在真正调用 `retail_query_recent_order` 前校验：用户本条原话中连续写出的完整订单号与候选一致才可直查；分写字母/中文数字须先复述确认。用户原话能归一出单一 token 时优先绑定该编号，例如 `B H 一千零一 → BH1001`，不采用模型猜的 PH1001、不自动改字母；无用户 token 才用模型候选并标 `candidate_source=model_candidate` 与风险。未确认时不发 HTTP；确认后只按确认编号查询。状态按 session 隔离；重启后仅从上一轮最后一条助手消息的完整确认问句恢复，不从普通历史授权。
- 本地验证（不联网、不发模型）：`output/order_confirmation_check.py` 58/58 通过，覆盖复述、确认、犹豫答复判 other（如“嗯……应该是吧/是吧/可能是/大概对/应该不是/不是吗/你说是吗/嗯我再想想/好等我核对一下/是另一个订单”）、否认、更正、同轮重试、跨会话不继承、确认后只按确认编号、模型自己先问再确认、错误前缀不查询、长文引用/普通历史不授权等；证据 `output/order-confirmation-check-20261108.json`。
- 订单开场约束前移（2026-11-08）：`TurnTools.order_state_text` 只在订单工具已选用且本轮问题涉及订单、但没有显式完整编号时，动态追加“第一句只能中性核对订单号、工具 ok 前不得说这就去查/正在查询/查到；自行分写或中文数字归一化候选不等于确认”；`build_tool_instructions` 同步订单专属规则。天气/闲聊无订单语义时不生成该规则。`output/order_prompt_constraint_check.py` 8/8 通过，证据 `output/order-prompt-constraint-check-20261108.json`；未改流式 yield/音频链。
- 文字订单真实回归：整体执行判据 35/35（[原始结果](E:/xiaodan/output/order-confirm-results-20261108-180106.json)）；C8 补跑及审计分页重评 5/5（[补跑](E:/xiaodan/output/order-confirm-results-20261108-181014.json)、[重评](E:/xiaodan/output/order-confirm-c8-recheck-20261108.json)）。首轮复述 BH1001、不出现 PH1001、工具 blocked；确认后审计 id221 实际 `request.order_id=BH1001`，上游 HTTP 400 / INVALID_ORDER_ID，属真实执行后的业务拒绝，不能写成查到订单。测试后已还原 M5+天气+默认库，订单 `enabled=false`。
- 实时 WS 订单首响应 guard 已真实复验：只在“订单工具已选用 + 本轮转写订单语义 + 无单一显式完整编号”时暂存首响应；blocked/denied 丢弃，ok/无工具调用原序释放。普通天气/闲聊/显式完整编号不挂 guard；转写前已有输出记录 `order_guard_early_output`，done 另含丢弃标记及字符/音频字节数。未改 TTS/audio_fx/播放链、未增加模型请求；[本地事件重放](E:/xiaodan/output/realtime-order-guard-check-20261108.json) 11/11。
- [真实 WS 结果](E:/xiaodan/output/voice-order-guard-results-20261108-183734.json)：歧义订单与天气两组合计 14/14，另 1 项未验证。转写“帮我查一下订单号B H一千零一。”，最终问句“你说的订单号是不是 BH1001？”；客户端文字全程无 PH1001/“去查”，工具 `blocked/order_confirmation_required`；done 记录 `order_guard_discarded=true`、丢弃文字 18 字、音频 161280 字节。天气 `guard_discarded=0`、`get_weather ok`，首音 0.85s（基线 0.911s），未见该用例首音回归。
- `/api/voice/turn` 显式“查订单 PH1001”已真实复验：实际请求 PH1001、工具 ok，回答 BayMax（BM-100），`audio_status=streamed`；[结果与配置还原记录](E:/xiaodan/output/voice-explicit-order-20261108-183804.json)。该入口由文字驱动，不能替代显式 PH1001 的 WS 音频输入验证。
- 未验证/未实现：真机麦克风/喇叭、塔菲唤醒、显式 PH1001 的 WS 音频（缺 PCM）；AEC 未实现。以上接口级结果不代表硬件语音全链路通过。

## 首响规则（2026-11-08，已应用并真实复验；听感仍待验证）

- Lead 已仅更新系统提示词：首响为贴合本轮内容的正式回答第一句，工具续答不重复开场；疑义订单先核对，不提前声称查询。沿用塔菲音色、语速/音调及同一生成链路；旧固定七句分析保留为历史依据，不再作为待用户决定事项。
- [新提示词真实语音复核](E:/xiaodan/output/voice-newprompt-recheck-20261108.json)：basic_who/weather 的流式末值、最终回复与历史一致，首句贴合内容、各出现一次、无固定七句；闲聊零工具，天气 `get_weather ok`。首音分别为转写后 0.819s / 0.911s。天气最大接收包间隔 0.759s（工具续答切换附近），是否造成可听空档仍需真机听感；客户端收包不能证明喇叭不卡顿。

## 文字/混合通道预期取消500修复（2026-11-08，已真实复验）

- `main.py` 新增 `stop_active_turn`：`/api/voice/turn` 停止同会话上一回合时不再直接 `service.stop` 裸取消；若当前活跃 task 是文字 `/chat`（存在 cancel marker），先写入本轮专属 token/turn_id 再取消，`/chat` 映射为 `409 turn_cancelled`，不再让 CancelledError 穿出成 500。语音 task、无 marker 的普通取消、turn_id 不匹配的 stop 仍走原 `service.stop`，不会把其他真实异常改成成功；鉴权/迟到隔离未改。
- 本地验证 7/7（[证据](E:/xiaodan/output/cancel-propagation-check-20261108.json)）；[真实取消回归重评](E:/xiaodan/output/cancel-recheck-20261108.json) 21/21、无跳过，覆盖 stop/reset、会话隔离、语音抢停文字与旧回合无迟到 complete。预期取消返回 `409 turn_cancelled`，新语音回合正常完成。首字前取消的历史契约为仅有 `user.interrupted`、无 assistant；有文本后为 `assistant.interrupted`；空历史或取消后出现 complete assistant 均不算通过。重评修正旧判据，不把首字前缺少 assistant 误判为失败。

## 阶段四收口：语音文本保留与检索章节补齐已修复并真实复验（2026-11-08 14:53 起）

- 核心开发本轮两处缺陷修复（Lead 已重启加载，进程 14128，管理 8000 / 设备 8003，health=ok/configured=true/qwen3.8-omni-flash-realtime，未重建索引）：
  1) 实时语音文本保留（realtime.py）：转写改为每个 `response.created` 强制开新段累计（不依赖 `response_id`），delta 只追加当前段、`response.transcript.done` 只校正当前段；修掉“工具续答时末尾完整 transcript 覆盖已说出的开场/正文”。
  2) 知识库检索章节上下文（personal_kb.py）：命中片段把标题留在末尾、正文被切到下一片段时，单步补上紧邻片段；仅同文档、**同 `document_version`**、同所选库/分组范围内补，版本不一致（补齐期间资料被替换）即回退不补；`top_k` 片段数不变，单段正文≤1800 字、整次补齐≤2400 字；不硬编码“第一阶段=P0”、不改原资料。读取时补齐，不需重建索引。
- 本地验证（真实库仅只读打开、零模型调用）：`PY_COMPILE_OK`（realtime.py、personal_kb.py）；转写事件重放 6 例含“无 response_id 也分段、第二段 done 只校正自身”，`TRANSCRIPT_REPLAY_OK`；章节补齐 6 例含“版本不一致回退、库/分组隔离、邻段去重、限长”，`SECTION_CONTEXT_OK`；真实失败查询只读模拟补齐后带入 P0 正文，`QUERY_SIM_OK`。证据 `output/transcript-replay-20261108.json`、`output/section-context-check-20261108.json`、`output/section-context-query-sim-20261108.json`。
- Lead 重启后语音工程师三轮真实模型 WS 复验（基线选择未变：天气+M5+默认库，订单停用）：
  - 知识库原问题：召回 ord 2/9/3/10/1（含 **ord3=P0 正文**），回答覆盖段内多轮、播放中打断、30 秒静默结束唤醒、按键/语音结束、断线恢复、回声适配；单次开场、完整到句尾；usage 15076、首音 8.27s。
  - 天气+知识库组合：`get_weather ok` + `search_personal_knowledge ok`，回答含天气与 P0 正文；单次开场；usage 20220、首音 12.99s。
  - 组合首包取消：`cancelled_by_client`，历史 user `complete` + assistant `interrupted`(77 字)，无迟到回答；已说片段保留、尾部按取消截断属预期。
  - 判读：**文本保留修好**（流式末值/最终回复/历史一致、无丢无重）；**首响规则未改、未验收**——本轮未复现双开场，只能说明文本保留修好，不能写成首响规则通过。以上均为网页实时 WS 接口级，非浏览器麦克风、非设备物理出声。
- 证据：`output/voice-realtime-results/kb-16k-20261108-145436.json`、`combo-16k-20261108-145510.json`、`combo-16k-20261108-145537.json`、`output/voice-realtime-summary-rerun.txt`；当前服务日志 `logs/service-regression-20261108-145322.log`。
- 此节为 14:53 批次历史快照：当时的首响待决定、订单确认与混合通道取消500缺口已由顶部后续真实复验更新；上文“首响规则未改、未验收”仅描述该批次。仍保留真机麦克风/喇叭、塔菲唤醒、显式 PH1001 的 WS 音频及听感验证，AEC 未实现；页面“替换”弹窗当时未实点，外部写/付费确认闭环仍受限。该批次服务 PID、设备在线状态与日志路径仅作历史记录，不代表当前运行状态。

## 单助手能力选择与多库迁移已加载（2026-11-08 12:04 起）

- 实现阶段已启动，替代上一轮“仅同步文档”的工作状态。SettingsStore 新增 API/库选择，旧配置仅一次映射现有已启用 API 与真实默认库；显式空数组表示不开放 API/不检索库，本地声音控制保留。工具注册按选择过滤，执行前重新核对当前注册表；管理页手动 API 调用按资源启停，与助手选入分开。
- 多库底座及管理界面已开发：独立库目录、文档归属、库 CRUD、助手选择读写；检索 SQL 先按库过滤再取结果。资料默认归真实默认库，替换保留归属；未知/重复选择拒绝；已选库、默认库、非空库删除受保护。管理页试查可传当前 library_id，模型工具不接受该范围覆盖。
- Lead 备份：`data/backups/agent-upgrade-20261108-114723`，含两库在线备份、私有配置副本和 manifest；两个备份 quick_check=ok。停止旧 8000/8003 实例后执行显式迁移：回填 1 文档到默认库，文档/片段/向量仍 1/10/10，孤儿 0。原有三表按备份列逐行一致、对话历史逐行一致、迁移时私有配置键值一致；未改原文/向量/声音设置。
- 新服务日志：`logs/service-20261108-120441.log`，管理 8000 / 设备 8003；health=ok、configured=true、qwen3.8-omni-flash-realtime，进程显式保持 AI_EMBEDDING_ENABLED=true。首次启动后选择读回 M5+天气+真实默认库；声音与模型相关设置未纳入选择保存。
- Lead 真实接口验证：默认库查询命中；仅选新建空库时相同查询返回空，显式不选库也返回空；删除已选库 409，未知库 404、未知工具 422；还原默认库后恢复命中。后续已补两个均有文档的库进行关键词双向隔离（见下文资料写入证据）。临时库已删除，最终助手选择恢复为 M5+天气+默认库。
- 界面开发在新服务真实三页只读检查：助手配置提示词 778 字，选项与服务一致；API 列表统一天气/M5，不重复展示个人检索；默认库显示 1 文档/10 段，P0 试查带真实库 ID 命中 3 段，页面零脚本异常。截图 `output/real-role-1120.png`、`output/real-cap-tools-1120.png`、`output/real-kb-1120.png`。早先旧端点失败态已确认加载失败会禁用保存、保存失败保留勾选草稿。
- 阶段三真实文字组合已运行：会话 `71a35073-a11e-4875-a891-5619518983ae`，天气/个人检索两工具均成功且送入模型，2 次模型响应、约 10.64 秒、供应商报告合计 11899 Token，未配价格故费用未知。审计 94/95 的天气三天数值与答复一致，5 个真实片段送入模型；正文未标片段 citation，后台 cited=false，不能把“送入”写成“引用”。证据 `output/assistant-tools-combined-20261108.json` 与 `output/assistant-tools-combined-audit-20261108.json`。
- 空选择真实文字轮曾尝试个人检索，被服务端 tool_not_allowed 拦下且未检索资料，随后如实说明能力不可用；普通寒暄曾主动查询天气，不满足闲聊直接答。证据 `output/assistant-selection-dialogue-20261108.json`。自动化测试使用真实 Settings/注册表/TurnTools 的不联网运行确认：空选择只留四个 local，旧轮允许天气但当前撤掉后 execute 立即 tool_not_allowed、子调用为空。
- 核心开发补动态工具提示（prompt_builder/tool_dialogue）：按实际名字生成专属规则，普通闲聊直接答，文字按返回的 citation 标记引用，语音只提资料名。首次加载日志 `logs/service-20261108-121741.log`；该版复验仍有闲聊天气误调用，后续收紧天气描述后才得到零调用记录（见下文最新证据）。没有修改首响、正文累积或音频播放链。
- 实测缺陷：工具中间轮与最终轮均可能输出开场白，空选择轮出现两句。实时音频代码同有风险，设备离线未复现；不能以丢弃所有中间轮文字/音频修复，否则会损害用户确认的快速首响。待用户审阅“每个用户问题只开场一次，工具续答不重新问候”的保留快首响方案，尚未实施。
- 资料写入实跑通过：用真实 README 上传临时库 B（2 段/2 向量、hybrid），不带库头替换仍在 B 且新版本、原文逐字节一致；同查询选 A 仅命中 A 的资料、选 B 仅命中 B、空选择 0、助手空选择时管理指定 B 仍命中。临时资料/库已用真实 API 删除，最终 1 库 1 文档、助手选择还原。证据 `output/assistant-kb-live-write-20261108.json`；双库关键词隔离该轮已实跑；双库 hybrid 向量隔离随后已在全功能回归实跑（各库只返回本库文档，见全功能回归条）。自动化测试独立只读核对最终库状态一致。
- 阶段三真实文字取消实跑：既有 stop 后历史 user=interrupted、无迟到回答；修复后 `/chat` 对“本请求本轮专属 stop/reset”返回 409 `turn_cancelled`，无关取消仍上抛。证据 `output/assistant-text-cancel-20261108.json`、`output/assistant-chat-cancel-recheck-20261108.json`。
- 最新真实复验：闲聊零工具调用及文字取消 409 见 `output/assistant-chat-cancel-recheck-20261108.json`；组合天气+个人检索均 ok、2 次模型响应、11.45 秒见 `output/assistant-combined-recheck-20261108.json`。自动化测试只读核对最终审计 112–114：5 段送模型，正文实际引用资料1/2/3（cited=true），另两段未引用。证明本次两工具查询后续答，不代表任意前后依赖的多步任务均已验证。较早 `output/assistant-prompts-recheck-20261108.json` 中闲聊仍误调天气，不能作闲聊成功证据；该版空选择已无工具调用且如实说明。
- 已修复接线：三入口提示名单取实际下发的 read/local 定义（排除 write/paid），与扁平/嵌套函数集合一致，真实注册表离线运行已确认。当前服务日志 `logs/service-20261108-122704.log`；仍为管理 8000 / 设备 8003、显式 embedding 开启。
- 最终独立复核结论：文字对话、管理页、资料操作在以上已验证范围内通过，未发现新增执行权限/关键词跨库越界。双库关键词与 hybrid 向量隔离均已实跑。旧轮撤权拒绝执行为真实注册表/TurnTools离线运行，不是付费对话中途撤选实跑。
- 尚未确认：本轮设备/网页语音听感、设备端工具续答取消。外部写/付费确认闭环尚未实现且保持受限；混合通道抢停文字请求仍可能走原有500传播，非本次409映射覆盖范围。双开场已有失败证据，近期单开场不证明已修好，首响提示调整仍待用户决定。当前阶段四收口，不能写成硬件语音全链路通过。
- 全功能回归（进行中，2026-11-08）：管理与 API 读取实测通过（health ok/configured、设备仍 connected=false ready=false、选择 get_weather+search_m5stack+默认库、工具目录 4 项含 disabled 的 retail 订单、默认库 1 文档/10 段、原文 18665 字节、关键词试查 5 段仅 roadmap、洞察 kb57/tools65）。临时业务 API 工具指向本机 /health 完成 创建→读取→调用(success)→编辑→删除→404 并还原；临时库 创建/改名/选入/已选删除409/空库删除204 并有默认库删除拦截，最终仅默认库 1 文档、选择还原。两临时库真实上传 README(2段/2向量)/START(3段/3向量) 后 **hybrid 向量双库隔离实测成立**（各库只返回本库文档）；助手空选择下按 library_id 试查仍命中本库；已清理还原。订单接口以草稿 PH1001 只读实测 HTTP200 business_status=ORDER_FOUND（BayMax、2025-08-01、DELIVERED、IN_WARRANTY），审计 id131 manual_debug ok，未改保存内容、未做外部写/付费。矩阵见 `output/regression-matrix-20261108.md`。本段为当时快照；其后网页文字回归发现闲聊误调天气、业务 API 未调用、组合选段等缺陷，均已修复并按原问题复验，详见顶部“阶段四收口”条与矩阵，不再以“暂未发现功能缺陷”概括现状。

## 文档统一到单硬件语音助手目标（2026-11-08）

- 统一目标：一个硬件语音助手，正常聊天，理解需求、按需调用 API 与所选知识库达成效果，简单、高效、快速；不缩减目标，不扩大为多助手、长期记忆或复杂规划平台。
- 根目录 2 份及 agent 下 26 份，共 28 份自有 Markdown 已同步；群 notice 同步引用当前规范。入口/交接已收敛，旧弹窗/三页签、固定阶段顺序、旧 M1 授权和已完成能力仍写待开发等冲突正文已修正。历史运行证据、失败记录和未确认项不改造成完成；已删除审计 ID 3/4/6 注明只引用当时证据。
- 自动化测试独立逐份复读，发现 7 处残留；Lead 接手修正并复核。最终只读检查输出 documents=28、broken_local_links=[]，针对 7 处问题的 6 组校验全部 true（A5/A15 合并一组）；无新增平行报告或业务验证。
- 本轮只改文档及群 notice，未修改业务代码、运行配置、数据库，未启停服务、操作设备、迁移、下载/安装、调用付费模型或提交/部署。后续按 [architecture](architecture.md) 与 [roadmap](roadmap.md) 的当前依赖顺序增量落实，文档同步不代表待开发功能已实现。

## 多日天气、首响登场与 AEC 核查（2026-11-08 02:10）

- 天气升级（weather.py / tools.py，核心开发）：仅 city=当前实况；city+days(1~16)=今天起每日预报；city+start_date/end_date=指定区间；city 改可选（缺省用常用城市，都没有才 location_required）。`_pick` 重写：裸同名跨省（如“朝阳”）回问并列候选，带省市（辽宁朝阳/辽宁省朝阳市）命中；过去日期拒绝；days>16 截断剔除空尾；缓存键含查询范围；今天按固定 UTC+8。真实免费接口实测（output/weather-live-check.json）：北京当前毛毛雨 1.6℃；北京未来 7 天 2026-11-08~14 每日最高/最低/天气/降雨概率齐；上海 3 天；北京区间 11-10~12；“朝阳”回问（辽宁朝阳市/重庆/山西/黑龙江）；“辽宁朝阳”→“辽宁朝阳市”；缺城市 location_required。
- 首响开场：按用户要求在 AI_SYSTEM_PROMPT 追加【开口首响】（7 句随机：来了喵/塔菲在/在呢喵/小菲来啦/小菲在/塔菲来咯/来咯来咯；极短、不带符号、不带 ~）。用户现场反馈“有快速短句回复、稳定”。
- AEC/打断核查（语音工程师）：设备端 AEC 是固件编译期选项、非运行开关；上游 Kconfig `USE_DEVICE_AEC` 依赖名单不含 M5Stack 此板，官方 v2.2.6 预编译包为默认（AEC 关），代码与文档一致，无现成“开 AEC”固件。Echo Base 有参考回采硬件通道，但开启需改固件源码+刷机（高风险、需授权）。服务端 continuous 在 AEC 关闭时硬开会自打断，不建议。眼下可靠打断=实体键 abort（20:41 实测触发过一次）。设备当前半双工、播放时基本无上行帧（累计推断，固件能力未确认）。
- 短句卡顿：真机 starvations=0、max_send_gap≈78ms、队列耗尽 0，音频约 1 秒内全部到齐→服务端未断供；已加载只读“音频内部静音段”测量，待下一轮真机判定是音频自带停顿还是设备端顿。
- Lead 已重载（02:10 后，health=ok、百炼实时、塔菲 1.2/+3、提示词 778 字含首响、tools=search_m5stack/search_personal_knowledge/get_weather；日志 logs/service-20261108-02*.log）。均 AI 接口级验证，真机听感/打断仍待用户现场。

## 天气工具、统一提示、知识库分段与首响改法已加载（2026-11-08 01:43）

- 用户「开干」后由 Lead 调度并行完成并集成：新增 weather.py（Open-Meteo，无密钥；geocoding count=5 消歧/省全称回退、预报、城市名与坐标短 TTL 缓存、WMO→中文）与 prompt_builder.py（统一系统提示：助手提示词→时间/诚实→朗读/工具规则→本轮状态，替换 realtime/realtime_text/conversation/voice_chat/service 的拼接）。
- 角色设定与回复规范合并为一个「助手提示词」，仍存 system_prompt；能力管理改为「工具/知识库」选项卡，天气并入「已接入工具」列表与其他工具同样勾选启停；知识库补「上传状态/资料列表/查看内容（正文+分段）/试查」。
- 设置新增 weather_enabled / weather_default_city；PUT /api/settings/assistant 改真部分更新（只写提交字段）。分段只读接口 GET /api/knowledge/personal/{id}/chunks?version=&limit=&offset= 返回 {chunks,total,limit,offset,version}，版本不符 409、不存在 404。
- 首响改为正式回答第一句、走同一 TTS/audio 链路，停用预生成缓存口癖（device_realtime.py；ack_audio/audio_fx、data/acks 留档未删）；口癖段测量为空属正常，其余卡顿分段指标保留。
- Lead 已重载（01:43，health=ok、百炼实时、塔菲复刻、tts 1.2/+3 与冰糖均未变；日志 logs/service-20261108-014316.log）。实测：get_weather 已注册 enabled，真实调用北京返回真实天气+数据时间+来源；只传 weather_default_city=上海→人设/模型/音色/语速均未变，已清回空；chunks total=10/分页正常。
- 仍待用户现场：真机/网页语音问天气、日期、首响是否第一句音色一致、知识库上传真实资料问答与出处、卡顿分段指标。以上为 AI 接口级已验证，不等于用户现场与听感确认。

## 口癖首响修复已加载（2026-11-08 00:32）

- 口癖保留 7 句，去掉会被念成“横杠”的 `~` 重生成 4 条（1/2/3/5），其余复用；PCM 保持中性未处理，manifest 记 `normalized_input/sha256/audio_fx_applied:false/neutral:true/voice`，本次 4 次合成 input2931/output122/total3053。本地 ASR 复核 7 条均无“横杠”。
- 设备首响改为读本轮 `rt_voice/tts_rate/tts_pitch`，以中性缓存为源走与正式回答同一 audio_fx 派生（key=voice+normalized_input+sha256+rate+pitch+fx版本，落 `data/ack-derived/`、原子写、命中复用、换音色/参数自动重派生）；口癖首帧与正式回答首帧指标分开，顺接/取消/缓冲不变。正弦定标证实链为 +3 半音、1/1.2 时长。
- Lead 已加载（00:32，health=ok、百炼实时、塔菲，设备离线，已预热 7 条派生缓存）。真机“不念横杠、招呼与回答声音一致、不叠音、日期能答、天气说查不到”仍待用户现场；ASR/正弦定标不等于用户听感。

## 首响缺陷取证、日期与实时数据规则已加载（2026-11-08 00:22）

- 口癖本地 ASR 证据显示三条带 ~ 的缓存含“横杠”；原始口癖未走正式回答的 rate=1.2/pitch=3 音效，因而语速/音高不一致。证据见 output/speech/ack_asr_result.json、ack_pitch_result.json。不能仅据此排除主回答也存在朗读问题；缓存尚未重新生成或修复，等待用户对口癖保留的答复。
- 新增 prompt_context.py，每次构造提示时注入服务器当前北京时间与星期；覆盖 realtime、realtime_text、conversation、voice_chat、service，避免重复。时效信息仅在本轮成功工具结果支持相应地点/日期时据实回答，无来源明确无法获取，不能用角色背景代替当前时间或编造天气。强化朗读符号规则，仍属模型指令约束，不能记作绝对拦截。
- Lead 已重载，8000/8003 正常、health=ok、设备离线；日志 logs/service-20261108-002217.log。未新增付费请求、未操作设备。日期回答与实时信息诚实性尚未真实模型复验，口癖问题仍未解决。

## 朗读规范化与口癖接续/自适应缓冲已加载（2026-11-08 00:06）

- 用户反馈“念横杠”“日期数字念法”。新增 `backend/app/speech_text.py`（`normalize_for_speech`＋朗读指令＋工具结果朗读副本），并接入 realtime/realtime_text 指令与续答、tts 非实时合成前、conversation/voice_chat 文本流水线、tool_dialogue 工具结果朗读副本；原始数据不改坏。样例实跑：2026-11-07→2026年11月7日、1-2→1到2、1.4→一点四、——→，、喵~→喵、100%→百分之百、URL 剔除；GPT-4→GPT4、电话 138-0000→138到0000（已知边角）。
- 卡顿定位修正：旧 375ms 只是“两次服务端发包起点间隔”，不能证明在回答句中或等于扬声器静音；新分段指标用于定位。设备侧改为口癖与续答同队列顺接、`notice` 仅清理旧回答音频、自适应缓冲（默认180ms，测得长间隔后抬至 min(420ms, gap+120ms)，短句立即冲刷，连续三轮无长间隔回落），并按段记录发包耗时/队列耗尽/首帧间隔；不得把本地 29 帧调度通过当作真机已消除。
- Lead 已加载本机开发服务（health=ok、百炼实时、塔菲，设备离线）。真机“横杠/日期数字朗读、卡顿是否缓解、先招呼后回答不叠音”仍待用户现场；建议先把音量降到约70排除扬声器失真。

## 口癖首响与设备播放平滑已加载（2026-11-07 23:35）

- 用户要求每轮先用角色口癖做快速首响、再正式回答。因设备回答用百炼塔菲复刻音色、本地 TTS 为 MiMo 冰糖，二者音色不同，故用当前 `AI_RT_VOICE` 塔菲音色一次性预生成 7 句口癖缓存（`scripts/gen_acks.py`、`data/acks/ack_01..07.pcm`+`manifest.json`，PCM16/24k/单声道，首尾静音已裁，1.13–1.81s，共 7 次短合成、10.52s）。
- 设备侧每轮进入新回答时随机取一条缓存 ack，经现有 Opus+预缓冲先播，随后模型回答按 `audio→done` 顺接；每轮一次、不重叠，缓存缺失静默跳过。另加约 180ms 起播预缓冲（短句立即冲刷）平滑句中卡顿，并记录出站断供指标（outbound_starvations/max_send_gap_ms）。
- Lead 已加载本机开发服务（health=ok、百炼实时、塔菲音色，设备当前离线）。真实设备上的“先招呼后回答、不叠音、卡顿是否缓解、音色一致”仍待用户现场，AI 核对不替代。

## 口语放宽与服务端按数值真执行已加载（2026-11-07 23:15）

- 真机反馈“百分之百没反应”回溯：两次 100% 均为模型未发起工具调用（审计 control_not_executed），旧设备端拦截后静默，非硬件问题。20%/80% 实际真调成功。
- 已改为：放宽口语（省主语、极值、相对“大点声/小声点”、中文/阿拉伯/百分之/％）；模型漏调时服务端按识别数值真执行并回读，相对量先读当前真实值再步进；含糊则反问；否定口令不反向；普通问答不入控制；历史主题继承。控制失败或只有文字时，先屏幕显示真实文本，并在当前百炼实时会话续答出声：续答前 `emit("notice", 真实文本)`（设备清旧播放+显示，不合成、不结束轮次），续答前 `session.update(tools=[])` 且服务端拒绝续答中的工具请求（control_continuation_no_tools）、单次守卫只续一次；异常才回退 text_only，状态如实记 failed/complete。不改用旧 MiMo。
- Lead 已加载本机开发服务：8000/8003 同进程监听，health=ok、模型 qwen3.8-omni-flash-realtime；设备当前离线。真实设备上的识别、执行、回读、续答“有字有声、只说一次、不重调”与听感仍待现场，编译/函数核对不替代。

## 真实设备反馈后的控制校验与诊断已加载（2026-11-07 20:41）

- 用户设备会话 45ca1254-7a96-46f8-9ccc-d8cb485d7b64 中，首次音量调到 80 有真实工具成功与回读；后两次要求 20 却没有工具调用，口头成功不能算执行成功。现有证据不支持工具表被清空或达到工具回合上限，模型漏调用的根因尚未完全证实。
- 新增 get_device_status 设备实时回读；控制/查询回合校验本轮对应工具成功及必要回读，未满足时阻止尚未释放的输出并报告 control_not_executed 等真实错误；每轮更新工具与指令并注入历史控制执行证据。ASR/文字晚于音频时，已经发出的声音无法撤回，不能承诺绝对不误播。
- 设备诊断新增 AEC、真实 abort 次数/原因、轮次结束后的丢帧及 speech_stopped 到音频/首包的时间。此前 34 秒包含等待用户开口，不能作为首响结论；新诊断的真实数值仍待下一次设备会话。
- Lead 已重载本机开发服务：管理 8000 与设备 8003 同进程监听，health=ok，模型 qwen3.8-omni-flash-realtime；语速/音调仍为 1.2/3.0，当前设备 connected=false、ready=false。本次重载未追加付费回合或主动操作设备。
- 当前运行 stdout/stderr 落盘到 logs/service-20261107-204121.log。修复后的真实设备控制、实时查询与播报行为仍待现场运行，编译/导入通过不替代这些结果。

## 本地语音控制工具：真实文字执行成功，语音听感待现场确认（2026-11-07 19:46）

- 用户授权通过对话调音量、语速、音调；共用注册表新增 local 权限内置工具 set_device_volume / set_speech_rate / set_speech_pitch，设备控制复用现有下发与回读，语速/音调更新运行设置并只持久化相应键。
- 首轮真实文字请求未调用工具、参数未变，不能记作成功；随后修正 rate/pitch 与 tts_rate/tts_pitch 的取参映射，并修掉共用提示中本地控制权限的冲突。未调用工具的原因不能仅凭旧提示断定。
- 实时音频处理器改为每段首个分片读取 service.settings 并固定参数；默认直发也按段固定，finish/close 清除参数，工具续答开始前结束上一段。同一连接下一段可取新值；真实连续语音、打断和听感仍待实际运行，不能用源码核对替代。
- Lead 重载本机开发服务后，仅发起一轮 POST /chat：用户指令“把语速调到1.4、音调调到1。”，会话 8c20fa64-53df-4e3f-a61f-5eed7bf72db7。模型真实调用两个控制工具，均 status=ok、sent_to_model=true；GET /api/settings/tts 回读 1.4/1.0。整轮 3953ms、2 次模型响应、3377 Token，未核实费用。
- 随后通过正式工具调用接口还原基线 1.2/3.0，回读一致，.env 所有配置键值与验证前一致。真实音量接口在设备离线时返回 409 device_offline，偏好未变；rate=5 / pitch=9 均返回 422 tool_arguments，配置仍为原值。
- 证据：[真实控制与还原记录](E:/xiaodan/output/speech-control-real-20261107.json)。设备在线音量下发/回读、语音对话自动调用以及同一连接后续实际音频效果尚未验证。本机仍属 Windows 开发环境，未部署云端。

## 设置与数据洞察更新、用户指定记录清理（2026-11-07）

- 设置改为整页两栏，API 工作台整页；洞察采用“知识库记录 / API记录”选项卡，支持关键词、类型/状态/工具名/日期筛选，长文本省略并悬停查看，说明收进标题提示。界面实测见设计组件文档及 output/insight-v3-measurements.json。
- 审计支持单条删除与清空筛选结果，确认与数量变更拦截已实际核对。用户明确要求清理后，仅删除知识库 ID 3、API ID 4/6：各返回 204，详情返回 404，当时数量知识库 7→6、API 9→7；原文、配置、聊天未删。下方历史章节提及这些 ID 均为当时证据，当前不可再读详情；原有输出证据保留。

## 分组修复后，同一问题的实时模式文字 RAG 实际跑通（2026-11-07 16:10）

- 重载分组修复后，手动把文件名 roadmap.md 填为 group 的请求返回 422 kb_group_unknown；工具说明明确“分组不是文件名，用户未指定时省略”。原失败洞察 ID 12 和失败会话未改。
- 使用与首轮完全相同的问题、新会话，经正式 POST /chat 调用现有百炼实时模式文字路径。模型实际调用 search_personal_knowledge，参数仅 query/top_k，未再填错 group；关键词+向量混合召回 5 段，5 段实际送入模型，回答引用 [资料2][资料3]。该次整个文字接口流程约 6391ms（含检索及完整回答），不是设备首声时间。
- 新会话 46f193a0-4fd8-426b-a7b6-65285f3bdd44，洞察 ID 15：answer_type=rag/status=ok；问题和最终回答与实际接口返回一致，session/turn/call 关联完整，含 5 个送入快照、2 个引用标记及 embedding 子调用。聊天历史读取也返回 5 个 sources；该轮 2 次模型响应、供应商合计报告 7312 Token，未估算未核实的费用。
- 真实回答：AI先完成功能开发，用户负责多轮对话、打断等现场测试，引用资料2/3。技术闭环已确认，回答质量并不等于自动评测通过。5 个送入片段不等同于 5 个最终引用。
- 证据：[同问题复验实际记录](E:/xiaodan/output/rag-dialogue-recheck-20261107.json)。界面开发已获调度只读查看新会话与洞察 ID 15，核对聊天来源及 5 送入/2 引用；未安排其新增模型调用。真实 roadmap.md 仍保留供联调。
- 范围限制：目前实际通过的是实时模式的文字 RAG；设备/网页语音工具续答、分模型路径、停止/打断实际回归、视觉/OCR、真实 PDF 提取及云服务器资源仍未确认，不能将本轮记成这些项目通过。embedding 开关仍由当前进程环境启用，尚未持久写入配置。

## 对话接入已加载；首轮真实对话发现分组参数错误（2026-11-07 16:07）

- 已统一重载对话接入版本，8000/8003 正常监听，health=ok、conversation_integration=true。该标志只表示代码接线已加载，不代表真实 RAG 已通过。运行依赖现已声明 pypdf==7.0.0 / jsonschema==4.26.0。
- 两处缺口已走正式接口确认：上传真实 START.md，保留带版本原文链接，再替换为 roadmap.md；旧链接返回 409 kb_version_changed，新版本原文与源文件字节一致。通过真实本机调试接口验证嵌套对象及数组元素中的停用字段均返回 422 tool_arguments；不含停用字段的同一工具正常执行并取得 HTTP 200。临时工具已删除。
- 本轮替换后的 roadmap.md（project-reference 分组）保留供对话联调，10 片段 / 10 向量；不与此前已清理的批次混淆。记录见 [两处缺口实际验证](E:/xiaodan/output/rag-dialogue-gap-verification-20261107.json)。
- 正式 POST /chat 发起真实项目问题，模型实际调用 search_personal_knowledge，但误把文件名 roadmap.md 当作 group。实际分组是 project-reference，错误筛选导致空结果；模型随后称资料库为空。问题、回答、session/turn/call 已关联，洞察 ID 12 为 tool_answer / empty，sources=[]，不能记作 RAG 回答成功。
- 已确认根因是工具分组语义与未知分组处理缺口，而非向量丢失；已派核心开发修复参数说明与不存在分组的明确错误，修后沿用同一问题再验，不靠调整问题隐藏缺口。失败会话与洞察保留。见 [首轮真实对话记录（未通过）](E:/xiaodan/output/rag-dialogue-real-20261107.json)。
- 设备/网页语音的工具续答、分模型路径和实际停止/打断未运行；不以监听正常或文字请求完成替代语音回归。视觉/OCR、真实 PDF 提取和目标服务器运行仍未确认。

## RAG 向量入库、真实评分与洞察回溯（2026-11-07 15:14）

- 用户已接受适配 2 核 2GB 的混合方案并同意知识库接入对话；API 与洞察按四张参考图迭代。此前基础语音和音色仍沿用，不能把当前管理端运行结果记成完整对话 RAG 或用户现场确认。
- Lead 备份现有知识库与聊天库后统一重载，管理 8000 / 设备 8003 同进程运行，进程环境开启 AI_EMBEDDING_ENABLED=true（未写私有 .env，普通启动需显式开启）。
- 正式上传现有 roadmap.md，10 个片段对应 10 个百炼 qwen3.7-text-embedding 向量，每个 1024 维 / 4096 字节，整个上传约 2603ms；不是仅验证查询向量。用真实项目问题混合召回 3 段，同时参与关键词及向量通道，余弦约 0.574 / 0.706 / 0.512，RRF 约 0.0320 / 0.0320 / 0.0315；BM25 原始分单列，分数不表示准确率。
- 洞察 ID 3 保存 3 个当时片段正文、版本、真实分数和 embedding 调用结果。资料替换成 START.md 后为 2 片段 / 2 向量，旧快照保持不变且原文状态为 replaced；随后只删除本轮资料，旧快照仍可读，原文状态 deleted，不链接新版本。人工参考答案用真实片段保存回读后恢复为空。
- 正式 API 保存一份临时 GET /health 工具：output_schema 和 x-enabled:false 保存回读一致；停用字段即使位于原 required 中也不要求提交，实际提交停用字段返回 422 tool_arguments；真实健康响应未经输出定义改写。工具成功调用洞察 ID 4 包含请求/响应/HTTP 200，明确为 manual_tool、无伪造触发问题。真实不存在路径洞察 ID 6 保留 HTTP 404 正文并记 error/manual_debug。新工具随后删除，目录恢复原状。
- 运行摘要见 [RAG 实际记录](E:/xiaodan/output/rag-integration-20261107-1510.json)、[API 洞察实际记录](E:/xiaodan/output/api-insights-integration-20261107-1510.json)。本轮只产生真实文档向量与查询向量调用，没有调用回答生成模型或操作设备；资料与工具均已清理，审计保留。界面开发已获调度按真实 ID 3/4/6 做页面复验。
- 仍待完成：检索接入实时/分模型对话、最终回答与会话/轮次调用链关联、视觉/OCR、真实 PDF 文件提取运行、云服务器资源实测；对话接入已派核心开发，不再重复询问用户授权。pypdf 7.0.0 已装项目 .venv；新增环境依赖声明及 embedding 持久配置仍需随交付核对。

## 网页语音改为独立沉浸式界面（2026-10-31）

- 保留现有录音、ASR、LLM、MiMo流式TTS、停止和历史协议，只改网页呈现：麦克风入口现在打开全屏语音工作区，中心状态球由真实的 connecting/listening/thinking/speaking/error 状态驱动；下方显示当前问答字幕，底部提供开始/结束录音、停止回答、返回文字和结束语音。
- 全屏语音期间底层工作区设为 inert，避免焦点和误触；Escape、键盘按钮与关闭按钮均结束语音模式并回到当前会话，聊天输入恢复焦点。播放期间停止、退出取消仍复用原轮次隔离逻辑。
- 真实Chrome实际进入语音界面后麦克风流成功启动，状态显示“正在录音…再次点击结束”、按钮为“结束并发送”；桌面1365px及390px深色界面无横向溢出，明暗视觉已检查。退出后语音层隐藏、底层恢复交互、文字输入获得焦点，页面无JS错误。
- 本轮页面验证未提交录音，未调用ASR、模型或TTS；真实语音识别→回答→播放→停止仍由用户继续体验，不把界面加载当成完整语音回合验证。

## 修正网页语音结束后用量显示不刷新（2026-10-31）

- 用户实际语音回合的 SQLite 与用量日志均已有 Token：依次为1124、1241、2945；并非上游漏报。原因是流式 `done` 后只更新了状态对象，已显示的助理消息脚注仍保留初始“用量未报告”。
- 已抽出统一的助理消息脚注生成函数；流式完成时更新当前消息脚注，不再等到刷新页面才显示用量。真实 Chrome 只读打开现有会话，三条语音消息分别显示 `1124 Token · 已播放`、`1241 Token · 语音已停止`、`2945 Token · 语音已停止`，页面无JS错误。
- 核对期间未发起模型、ASR或TTS请求；未改历史正文、模型配置、设备或服务器。

## 修正默认输出上限和空正文诊断，等待用户网页实试（2026-10-30）

- 用户手动请求留下的真实日志：一次空正文请求输出512 Token，随后连接测试输出187 Token并成功。旧日志没有结束原因及思考用量，不能确定当次空正文由思考耗尽造成；本轮未补造响应或自动重发模型请求。
- 已核对 TokenDance 官方文字/流式示例与 Spark 官方模型卡，来源及适用边界见 references。撤掉项目默认的 `max_tokens=512`：配置/schema默认可空，未配置时两种模型请求均省略该字段；前端不再用512填补空配置。用户主动指定数值时仍保留校验及发送能力，没有改用猜测的更大数值或增加未经网关确认的思考参数。
- 文字与流式回合保留结束原因和已报告用量；空正文按真实 `length` / `content_filter` / 其他情况给出具体错误。日志新增请求上限、受限结束原因、已报告思考Token数和是否有最终正文，不记录正文、思考文本或原始响应，不自动重试。
- 已重启现有本机8000，通过原配置保存接口仅移除私有配置中的512限制。接口实际返回 `max_tokens=null`，模型及密钥配置保留，会话ID列表不变，设备网关未启动。真实 Chrome 读取后的已保存值和待提交值均为null，页面无JS错误，未发起模型请求。重启后模型调用计数0。
- **未运行**：真实模型输出及流式回合。此次完成的是确定存在的默认请求限制与诊断缺口修正；是否解决原空正文，需要用户在网页手动发送后依据新结果确认，不宣称模型调用已通过。

## 本地继续收敛上下文和网页播放状态（2026-10-30）

- 修正统一会话的上下文筛选：完整历史继续保留失败、中断及部分生成的文字，模型上下文只取已完成的问答；不再把半截失败回答用于后续轮次。完整模型回合未运行，此项为代码修正，尚无真实多轮证据。
- 修正网页语音状态：每轮取消/开始时重置上一轮合成失败状态；仅在合成未失败且收到音频时创建重播按钮，避免失败回合显示完整重播。本轮未调用模型/TTS，失败后再成功的真实回合尚未运行。
- 重启现有本机服务，健康、设置、设备状态、会话和用量接口均200。真实 Chrome 语音/文字切换、参考 WAV 提交和页面刷新无 JS 错误；8.48秒参考 WAV 经正式 ASR 接口返回43字，识别0.450秒、接口451ms。刷新后会话列表仍为空，不能据此宣称问答历史恢复已通过；未触发任何模型请求，调用数0。
- 用同一参考 WAV 的原始 PCM 运行正式 `audio_fx.stream_pcm`，沿用已保存的语速1.0、音调+2，得到84个非空音频分片、约8.468秒输出。没有修改配置、制造模型响应或把参考音频当成真实 MiMo 回答。
- 未连接设备或服务器，未部署、下载、安装、调用付费 API 或提交 Git；没有删除旧编排或此前被自动审批拦截的下载资源。完整 LLM/MiMo 流式播声、活动停止和真实问答 SQLite 刷新恢复仍未运行。

## 本地完成服务器适配代码，尚未部署（2026-10-30）

- worker 不再写死 Windows：按操作系统选择 `.venv-speech/Scripts/python.exe` 或 `.venv-speech/bin/python`，可用 `AI_SPEECH_PYTHON`、`AI_ASR_MODEL_DIR`、`AI_SPEECH_THREADS` 指定真实运行资源；子进程固定项目工作目录，并移除继承的模型 API Key 和管理代理凭据。Linux Opus 走系统库，Windows 继续使用原项目 DLL；音频后处理临时文件固定在项目 `.cache/speech`。
- 核对官方 PyPI 元数据发现：原 NumPy 2.5.4、PyAV 19.0.1 要求 Python >=3.12，与已知服务器 Python 3.11 不兼容。requirements-speech.txt 已按 Python 版本分别锁定 3.11 使用 NumPy 2.3.5 / PyAV 18.0.0，3.12+ 保留现有版本；两项 3.11 Linux x86_64 轮子已由元数据确认存在。本机包未改、未下载新包，Linux 运行仍未验证。
- 新增服务端 `AI_PUBLIC_ORIGIN`，只接受一个不含路径/凭据/查询参数的 HTTPS origin，并要求至少32字符代理凭据。设备 OTA 接入信息和 bootstrap 的 WebSocket 地址改为按已配置 origin 生成 HTTPS/WSS，不依赖请求 Host 或转发头推测；本地模式保留原 LAN HTTP/WS。没有写设备配置或修改设备地址。
- 公网管理采用 Caddy 个人密码认证；应用还校验回环来源和代理专用凭据，所有管理页面/API（含历史、模型请求）在公网模式下都受保护，写请求保留同源/X-Local-Settings校验。可信 Host 仅添加明确域名，部署凭据不回传网页，也不进入浏览器存储。密码与代理信息共用 `/etc/xiaodan/access.env`，模型配置仍为项目私有 `.env`。
- 待部署模板在 deploy/：独立 `/opt/xiaodan` 服务、回环 8010/8013、Caddy 站点片段和凭据环境文件示例。`--public` 缺公网配置时拒绝启动；网关关闭 URI access log，识别日志不再写聊天正文。Caddy 访问日志过滤 OTA query key 与敏感认证头；部署前还需把相同过滤合并到既有全局错误日志，不能只过滤访问日志。模板未在 Caddy/Linux 实跑，不表示可直接发布。
- 实际运行：重启本机原服务后，首页/配置/设备状态/会话读取均200；真实 Chrome 设备设置页无 JS 错误，本地 IP 字段仍正常，原接入 URL 保持。浏览器经真实 ASR 接口提交现有 8.48秒 WAV，返回43字，识别0.291秒，含 worker 启动总计1934ms。部署秘密字段未出现在公共设置响应中；设备入口未启动、无设备连接、模型调用0。
- **未执行/未验证**：未连接服务器、未操作设备、未安装/下载新包、未调用付费 API、未部署或提交 Git。Linux/真实 Caddy 登录、HTTPS/WSS、目标资源和固件兼容未运行；真实 LLM/MiMo 流式回合与问答历史恢复仍未运行。没有用模拟环境填补这些证据。
- 更正上一轮 VAD 根因说明：上游 `vad_last_voice_time` 使用墙钟时间，且连接的 `client_have_voice` 在段内保持为真；快速批量送帧没有经历足够实际静音时间，并非“只在首次窗口跌落时判断”。现有 worker 按处理音频时长结束的适配仍有效，不改此前43字/自动结束的实际结果。

## 依赖安装、VAD 与网页可运行部分验证（2026-10-30）

- 经用户确认，在既有 `.venv-speech` 安装 onnxruntime 1.31.1、flatbuffers 25.12.19、packaging 26.3、protobuf 7.36.2；numpy 保持 2.5.4，`pip check` 返回无损坏依赖。下载缓存和临时目录在项目 `.cache` 内。
- VAD 使用真实正式路径验证：将项目内 `models/voice/taffy-24k.wav` 编码为 142 个 24 kHz/60 ms Opus 帧，送入 `scripts/speech_worker.py --threads 2`。worker 启动 2.528 秒；VAD 初始化成功，检测到 140 个语音帧；显式 stop 得到 43 字、音频 8.512 秒、语音 8.224 秒、识别 0.469 秒。
- 自动结束首次验证暴露批量输入与墙钟时间计时不一致：快速送帧没有等够上游设定的实际静音时长。正式 worker 已按处理音频时间判断连续静音；重跑原 WAV 加 1.5 秒尾静音，在第 151 帧返回 `end_reason=silence`，43 字、音频 9.056 秒、语音 8.288 秒、识别 0.478 秒。不是以 stop 冒充自动结束；不据此宣称上游实时流自动结束失效。
- 真实 Chrome 打开本机页面：页面加载完成、无 JS 错误；语音模式可切换，单一输入框隐藏，无可用麦克风时在录音阶段明确失败并恢复状态。未调用模型。
- 真实浏览器从同源以字节向 `/api/voice/asr` 提交 8.48 秒参考 WAV：HTTP 200、43 字、识别 0.376 秒、接口总耗时 2869 ms（含当次 worker 启动）。这验证浏览器上传到真实 ASR 服务，不代表真实麦克风、VAD 连续收音或用户听感。
- 网页不触发模型的接口验证：`/api/voice/session` 返回新会话；空闲 `/api/voice/stop` 返回 stopped=false；无匹配轮次的 playback 状态返回 ok；缺少 `X-Local-Settings` 的 `/api/voice/turn` 在模型前返回 403，空 body 返回 422。本轮 `/usage` 模型调用数为 0，`upstream_verified=false`。
- **仍未验证**：真实 LLM 流式回答、MiMo 真实合成、浏览器边收边播、活动中停止打断、TTS 播放完成状态、语音问答 SQLite 写入及刷新恢复。用户明确禁止调用真实付费 API，且禁止假 Provider/模拟 API；这些路径不能用替代结果宣称通过。本机最新服务仍运行于 127.0.0.1:8000，未动设备或服务器。

## 统一语音路径接入，依赖待确认（2026-10-30）

- 社区源码、默认 Silero ONNX 与 MIT 许可已按用户授权下载到项目。已裁剪为本项目单一用途的移植：保留上游引号安全分句、Opus 编码、hello/abort 和音频节奏代码，线程回合改为 asyncio 队列；没有直接启动全量上游服务，也没有引入 Java、MySQL、Redis、插件、记忆、声纹或多引擎。差异在 third_party/xiaozhi-server/NOTICE.md 明示。
- 文字 `/chat`、网页 `/api/voice/turn`、设备 DeviceVoice 现在都进入 `ChatService.turn`；会话锁、配置快照、模型客户端在途引用保护和 SQLite 写入集中一处。网页全局 voice_history 已移除，设备不再引用 DeviceConversation；网页携带会话/轮次 ID，停止和迟到结果按该身份处理。完整 LLM/TTS 回合尚未运行，以上是已接入代码状态，不冒充实际模型结果。
- SQLite 保留原表和原数据，启动不再全量加载会话快照；详情按需读取，max_sessions 只限制可淘汰的内存缓存，不再要求删旧历史后才能新建。识别问题、已生成文字、部分失败及中断状态走同一保存路径；TTS 失败继续保留模型文字且不重问模型。语音流式用量没有上游报告时仍为未知，不补造。
- 网页沿用现有页面/设置/主题；正常流式 PCM、停止和播放队列接入新事件，并增加播放结果回传，区分生成完、已发送、已播完及中断。MiMo 专用 Provider 保留原协议/密钥引用，流式语速与音调改为每句一个 FFmpeg 进程处理连续 PCM，不按分片启动进程。真实合成/听感/浏览器播放尚未运行。
- 实际运行：本机最新服务已启动于 `127.0.0.1:8000`；`/health`、首页、JS、设置、TTS 设置、会话列表均返回 200，真实模型调用标记仍为 false。项目现有 8.48 秒参考 WAV 经真实 `/api/voice/asr` 返回 43 字，识别耗时 0.486 秒、含首次模型加载约 4.645 秒；没有将它说成麦克风、VAD 或完整问答通过。当前会话列表为空，刷新恢复尚无真实问答证据。
- 社区 VAD 的代码和模型已接入语音 worker，首次自动收音时才加载；浏览器批量识别不依赖 VAD 初始化。四项依赖后来已获准安装并完成真实 Opus/尾静音验证，见顶部本轮记录。没有调用付费 API、动设备、访问远端或提交 Git。
- 已删除社区未用的管理/记忆/声纹/通用注册等源码。三个旧编排文件已退出主入口，但依原约定待新核心完整真实回合接管后再删除，目前不参与调度。Kokoro 离线资源约 181.09 MiB 已确认不在服务路径，删除请求两次被工具自动审批以 `blocked by policy` 拒绝，尚未清理；现有模型、音色、SQLite 和配置未误删。

## 本轮链路核对及接入边界（2026-10-30）

- 用户已授权实施社区轻量语音核心接管与会话/历史统一，取代此前“暂停业务开发”。本轮已读取入口、PRD、架构、代码及设计规范，核对真实源代码；尚未修改业务代码、下载安装或删除旧编排。
- 文字：`/chat → ChatService.chat → OpenAICompatibleProvider.complete → HistoryStore.save`；网页语音：浏览器录音转 WAV → `/api/voice/asr → SpeechRecognizer.transcribe → SenseVoice`，随后 `/api/voice/turn → voice_chat.run_turn → complete_stream → MiMoTTSProvider.synthesize_stream → SSE PCM → AudioContext`；问答只进全局 `voice_history`，不进 SQLite，浏览器也不传当前文字会话 ID。
- 设备：`devices.py` 已接收并转发音频，不能再称“丢弃麦克风音频”；Opus → 本地语音 worker 的 VAD/SenseVoice → `DeviceConversation → DeviceTurn → LLM/MiMo → PCM/Opus → WebSocket`。设备上下文另存在 `DeviceConversation.history`，未写 SQLite；文字/网页/设备确实存在三套数据路径。
- 需要收敛的实际缺口：网页 PCM 回放无谓调用 `speech.start_pcm()`；网页全局 generation 会让不同页面互相失效；设备停止仅设共享 `stopped`，未取消旧 LLM/TTS，忙碌时还会丢弃新发言；旧编排未提供可靠轮次身份隔离。以上为代码核对，不冒充实际音频运行结果。
- 只读 SSH 核对：远端 Python 3.11.13、FFmpeg 7.0.2 和系统 libopus 已有；Python 3.11 中未安装 numpy、onnxruntime、opuslib-next、av、sherpa-onnx、websockets。旧站进程处于登录 session cgroup，父进程为 1，本次 RSS 约 60 MB；不能据此认定已有可靠的服务恢复配置。未修改或重启远端，未写远端文档。
- 社区源码与默认 VAD 尚需下载确认，清单见 [resources](resources.md)。不把现有不同尺寸的 int8 VAD 模型当作上游 ONNX 状态接口已兼容；不自动装完整 requirements。真实付费 API 未授权，完整流式回合、听感、停止耗时、刷新恢复及设备行为本轮尚未实跑；旧实现全部保留至新核心实际接管。

## 历史工作方式（2026-10-30，当时覆盖更早计划）

已按用户指令撤销隔离、模拟、最小验证和先验收再替换的开发流程；默认直接实现已授权的真实功能，不预建防御框架或测试后台。本次仅更新全局及项目指令，未改应用、远端、设备或安装依赖。以下隔离结果保留为历史事实，不再作为后续执行要求。远端不写文档，既有服务不改；部署、设备、真实API及安装下载边界不因工作方式调整而扩大。

## 远端服务器只读基线（2026-10-30）

- 已使用本机已有SSH密钥建立只读连接，未记录登录信息、未读取私有配置或修改服务器。远端为阿里云Linux 3 x86_64、2 vCPU、1870MiB总内存；当时可用约1400MiB、无Swap，根盘40GB且约32GB可用。
- 现有 `/opt/voice-studio` 后端由 `python3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000` 提供，Caddy监听80/443；8000端口当前对公网绑定。`voice-studio.service` 单元不存在且 `is-active` 为inactive，说明它不是由同名systemd单元管理，启动/恢复路径仍需后续只读核实。
- 该目录是独立既有voice-studio，不是本项目部署；系统默认 `python3` 为3.6.8，但旧站进程使用python3.11。当前项目目录、新服务、新端口和数据库均不存在。2核2GB资源尚未用本项目建设验证：以上只是一次只读空闲快照，不代表社区核心峰值、与旧站并存余量或稳定性通过。
- 已确认可直接SSH操作，但后续仍维持“不动设备、不部署、不调用真实API、安装下载先确认”；先在远端只读核对依赖和最少物料。

## 历史项目快照与暂停点（2026-10-30）

- 用户最新要求先不模拟，询问能否直接访问远端服务器并要求整理现状/待办。现已只读连通服务器，但仍未下载安装、运行新测试、修改应用或操作设备。
- 已有网页、配置、MiMo适配与SQLite；文字/网页语音/设备三套回合和上下文尚未收敛。语音消息同样式显示不等于已写入SQLite。真实API和完整语音体验仍未验收。
- 社区轻量核心只完成公开源码/依赖评估，未下载到运行目录、未安装/启动。此前下载清单未得到确认，当前不继续询问或执行下载。2核2GB属于远端服务器，旧站资源值是历史快照，当前资源未实测。
- 远端连接已确认并通过一次系统/服务盘点；后续只读核对实际依赖；不再安排隔离环境。实际安装和迁移据新授权推进。已有“不动设备/部署、不调用真实API、下载先确认”限制继续有效。[顺序待办见START](../START.md)。

## 历史隔离准备（2026-10-30，计划已撤销、未执行安装）

- 收到用户实施授权，进入“验证先于替换”阶段。已盘点本机开发/语音环境、可复用Opus DLL和FFmpeg，确认需要独立验证环境；没有改现有环境或应用。
- 静态核对固定版社区核心82个模块，所有源码读取/解析成功；核实运行目录26,778,517字节，含默认2,327,524字节VAD模型。发现插件顶层导入会拉入额外依赖，应在无工具验证模式关闭，不安装整套插件。
- 已将明确的源码、依赖、缓存和隔离数据路径列入 [resources](resources.md) 顶部，等待用户确认下载/安装。没有下载源码到磁盘、安装轮子、运行社区核心、接触设备或真实API。
- 用户明确2核2GB是远端云服务器。本机Windows只做功能隔离测试；远端资源实测单独记录，当前未连接/修改云服务。检查本机WSL属于多余环境探查，未安装或修改系统，不作为资源验证依据。

## 社区服务端与现有实现收敛评估（2026-10-30）

- 已完成公开源码与本地实现只读核对；社区固定提交 `1a095d5bed23e49a17f817c7f378e2a86f298dfc`。结论、可复用/保留/删除清单、来源及最小实施步骤统一写入 [architecture](architecture.md)，不另建平行评估文档。
- TokenDance公开目录仍列出普通MiMo TTS与VoiceDesign；小米官方示例确认消息角色、音色字段、Base64 WAV与PCM16流式协议。社区OpenAITTS采用不同的audio/speech schema，不能填模型名即用；应复用现有MiMo逻辑做一个专用Provider。4项现有payload本地断言通过，没有创建HTTP客户端或发起合成。
- 建议优先验证社区轻量核心，保留现有网页、配置原子性/密钥保护和SQLite；接管成功后移除 `voice_chat.py`、`conversation.py/device_turn.py` 等重复回合编排，统一文字/网页语音/设备的会话实现。当前没有删代码或迁移数据。
- 2核2GB：在线ASR/LLM/TTS + ONNX VAD有可行性依据，全量Java/MySQL/Redis不选。社区完整依赖仍重、轻量历史需本地落库适配，旧云机余量是历史快照；社区启动、Linux限额资源和同机并存均未实测，不能宣称部署通过。
- 当前暂停新增功能、设备计划和部署；本轮没有改应用、私有配置、设备或云服务，没有安装下载、读私有聊天、真实API请求或Git提交。

## 语音消息并入普通聊天（2026-10-24，取代上一版独立结果区）

- 按用户最新反馈取消“按住说话”：点麦克风立即开始录音，按钮变为“结束并发送”，再次点击结束识别和提交；键盘仍可切回文字并保留草稿。首页仍是单一输入框。
- 语音识别的用户提问、助理回答复用现有聊天消息节点和 Markdown 渲染；重播、停止放在该条助理消息内，不占独立结果区。TTS失败、模型错误或打断状态保留在对应消息，迟到旧轮不覆盖新消息。
- 输入区状态与流式音频继续复用现有 ASR、模型和 TTS 接口；移动端布局、明暗主题及桌面/语音切换已做隔离验证。真实麦克风、API、音色听感与首声延迟仍未验收。

## 网页语音边收边播与打断（2026-10-24）

- 按本次授权参考 GECX demo 的 PCM 分片排程与停止队列方式，复用现有 `/api/voice/asr`、`/api/voice/turn`、模型流和 MiMo TTS 适配器。音频到达即播放，分片按 24kHz 单声道 PCM16 排队；生成结束后等播放队列耗尽才显示“回答播放完成”，队列暂空时显示正在生成剩余回答。
- 新增“停止”；生成或播放中再次按住说话直接打断。立即取消浏览器请求、停止所有播放源并失效旧轮次；异步权限申请、识别、迟到 SSE 和播放回调不能覆盖新轮次。完整成功且播完后可重播；中断/语音失败不提供完整重播。按住说话支持指针与空格/Enter，松开结束录音。
- 服务端修复非流式模型兜底、满队列取消时的模型流释放；文字分阶段显示，TTS 失败保留文字并反馈部分失败，连接中断不显示回答完成。重置和新轮次使旧流失效，只有完整生成成功才写入现有有界语音上下文；已有 SQLite 聊天历史与配置不变。语音接口补上同源、本机和写请求头保护。
- 隔离验证：`pytest tests/test_voice_chat.py -q` **6 passed**，覆盖首段先出、满队列取消释放、非流式复用、TTS 失败不重试模型、未完成不报成功、接口保护、重置旧轮隔离，以及真实本机 HTTP 断流取消 TTS且不写入上下文。仅使用模拟模型/TTS。
- Chrome 浏览器运行 `tests/voice_browser.cjs`：12 类场景通过，覆盖 done 前开始播放、分片首尾衔接、缓冲空隙反馈、done 后等待播完、重播停止、按住打断、迟到旧结果、模型/TTS 错误、重置失败、授权前松手，以及 1365/390px 明暗主题。结果与截图在 `output/playwright/voice-results.json`、`voice-*.png`；JS 语法检查、界面机械检测通过。
- **未验证**：真实麦克风/ASR/模型/TTS整链路、音色听感、真实网络首声与停止耗时、设备讲话自动打断和云端能力。浏览器本轮为按键打断，未新增持续收音/VAD；服务端首段音频耗时不等于用户说完至扬声器出声。未调用真实付费 API、修改用户配置、安装下载、操作设备、部署或提交 Git。

更新：2026-10-17。当前阶段：文字配置与独立MiMo TTS配置/浏览器草稿试听已实现并完成隔离验证；真实账户调用、M1余项及完整助手尚未验收。最新授权包含统一设置入口与页面精简，不包含设备操作、ASR、设备语音闭环或部署。

## 历史能力表（2026-10-17，当前状态见本文顶部与START）

| 能力 | 实际完成程度 | 证据与限制 |
| --- | --- | --- |
| Windows文字聊天与模型适配 | 有代码与模拟上游测试 | 此前只读核对service/llm/main；真实账户聊天未验收 |
| API配置/模型列表/草稿测试 | 完整配置流程隔离验证通过 | 明确入口、获取/选择与手填、测试/保存独立；失败保留输入，保存生效且保留历史；真实账户未验收 |
| MiMo TTS独立配置与草稿试听 | 两个模型的隔离HTTP合同与可播放WAV通过 | 内置音色/VoiceDesign描述、单独密钥与保存；真实TokenDance合成、听感和计费未验收 |
| Codex风格工作区、明暗主题 | 设置按角色/模型/声音/接入/设备/资料/用量分层，完整流程浏览器验证通过 | 主页面无地址/密钥，同页选模型/声音、试听保存；1365px/390px与明暗主题检查通过 |
| SQLite会话与用量 | 有实现及历史测试 | 本轮未读取私人记录；真实模型对话和目标环境恢复待验收 |
| M5Stack只读检索 | 历史真实连接验证，代码和测试存在 | 不是通用个人知识库，也不是设备工具调用平台 |
| Kokoro离线声音 | 历史三份非空/非静音WAV及性能度量 | 此前复核文件；人工听感、设备播放和实时延迟未验收 |
| 小智兼容网关与控制 | 有实现与真实TCP/WebSocket模拟设备测试 | 当前丢弃麦克风音频；屏幕文字不带实际音频 |
| 原OTA恢复信息 | 用户已查原字段为空，电脑端记录过 | 尚未确认自建地址写入硬件；实际切回结果未验证 |
| 云服务器voice-studio | 此前健康接口正常，edge-tts/api引擎代码存在 | 本次未重新探测；未合成试听、未测ASR、鉴权或机器人兼容性 |
| 完整机器人语音对话 | 未完成 | ASR、Opus处理、TTS回传与生命周期未串联 |
| 双环境约3秒首声与讲话打断 | 未实测 | M3先做目标云端最小闭环验证，不用离线样例或模拟代替 |
| 外网个人管理认证 | 本项目尚未实现并验收 | 现有本机回环/同源保护不是公网认证；M3开放前落实 |
| 长期历史按需加载与容量 | 尚未改造 | 当前全量加载及旧max_sessions限制与长期历史冲突，集中M4解决 |
| 每日独立云备份/30天副本 | 未实施 | 规则已确认，具体目标未配置，未上传或隔离恢复；计划M5 |
| 插件/电脑/家居/长期记忆 | 未交付 | 插件为后续方向；其余不进入当前第一版 |

“历史测试”来自此前项目记录；本轮仅运行下列相关测试及隔离浏览器流程，模拟PCM/WAV只在测试内存生成，没有真实账户合成、修改设备或部署。未读取私人聊天正文或密钥；本机服务已重启提供新页面。当前环境没有Git仓库，未初始化或提交Git。

## 历史界面增量：参考小智设置窗口（2026-10-17）

- 原全宽长页面改为居中、有界的原生dialog；角色/模型/声音/API接入/设备/资料/用量在同一窗口切换，标题与底部保存/取消固定，正文独立滚动。模型与声音各自只显示相关字段，保持既有灰阶主题与共用API设计；角色复用系统提示词；不加入未实现的记忆、声纹或插件。
- 页签切换保留草稿；保存仍走原有原子分组接口并关闭窗口；取消、Escape、关闭恢复已存选择并清空新填密钥，停止试听，返回聊天并恢复可见入口焦点。声音描述在隐藏页签校验失败时会自动切到声音，防止看不到错误字段。
- 本轮只改HTML/CSS/JS，后端协议与数据路径未变，因此未重跑后端46项。Chrome隔离流程`output/playwright/settings-dialog-smoke.js`通过共用API接入、两页签选择、可播放模拟WAV、保存关闭、取消丢稿、隐藏字段校验与键盘/焦点恢复；桌面1365与390窄屏、明暗主题及固定底部操作位置均验证通过。修复验证中发现的手机关闭焦点和内容容器未撑满问题；JS语法、HTML结构及机械检查通过。
- 真实API调用仍未验收；未改用户私有配置/历史，未动设备、部署或新增依赖。本机服务直接提供更新静态文件，刷新可见。

## 历史增量：同服务共用API（2026-10-17）

- API接入默认仅一套地址/密钥，文字和TTS在服务端共用；“语音使用不同服务”勾选后才展开第二套。`AI_TTS_USE_TEXT_CONNECTION`持久化选择，TTS按快照读取有效地址/密钥，不复制存第二份密钥，也不经浏览器取回已有密钥。
- 兼容旧配置：未设置模式时，未存独立语音密钥或两套凭据/地址相同则共用；不同旧凭据保留独立模式，不静默覆盖。显式共用后更换公共密钥立即用于后续文字/TTS请求；独立模式不会退回使用公共密钥；独立配置切回共用时保留私有字段以便切回，仍不回传。
- 相关后端验证**46通过、13无关未选**；新增共用单次配置→合成→密钥更新→重载、独立服务隔离及旧配置推断。Chrome隔离验证一次填Key即可选择模型并合成可播放WAV、刷新恢复共用状态、独立输入按需展开；桌面/390px明暗及机械检查通过。
- 本机8000已重载，私有配置与历史未被迁移或重写；真实API调用仍未验收。此增量取代此前要求文字/TTS无条件独立填写的约定，不涉及设备或部署。

## 本轮：接入与日常配置分层（2026-10-17）

- 依据用户提供的小智截图分析：配置围绕单个助理，按任务分组；供应商接入是底层低频步骤，模型/声音是高频选择，底部固定保存减少滚动定位与丢稿风险。这是截图推断，不冒充小智内部设计结论；未照搬其配色/卡片，也未加入记忆、声纹或插件。
- 修正上一轮只合并导航、仍按接口拆页的负担。设置只保留“模型与声音 / API接入 / 更多”；API页填写地址/密钥，日常页只有对话模型、声音、试听与保存选择。已有设备/资料/用量移至更多，旧路径保留，旧#tts兼容日常页。
- `PUT /api/settings/connections`仅保存文字/语音连接及高级参数，不改已选模型或音色；`PUT /api/settings/assistant`只原子保存模型与声音，不接受密钥/地址字段。两者复用SettingsStore原子.env和同一操作锁；保存失败保持原运行配置及文件，历史保留。
- API接入成功后加载模型列表；刷新日常页会按已保存连接重新获取列表，失败支持手填，不自动改选或测试模型。模型测试/草稿试听仅用已保存连接，未保存的API输入不混进日常请求；声音草稿仍可先试听再保存。日常页面有取消修改与固定保存栏，改稿/离页回收旧音频。
- 相关后端检查**43通过、13无关未选**，新增分组保存的字段隔离/原子性/历史与密钥保留验证，保留两种TTS合同及错误、并发保护检查；未运行设备或资料全量测试。JS语法、HTML结构与界面机械检查通过。
- Chrome隔离流程`output/playwright/tts-settings-smoke.js`通过：接入→加载候选→选模型→选声音→实际播放模拟WAV→保存→刷新恢复；取消选择、必填描述、未保存API草稿不影响试听、历史保留与无浏览器密钥持久化均通过。桌面1365×1000和390×844窄屏、明暗主题检查通过；截图在output/playwright/workflow-*。
- 本机8000已重载，新页面及分组接口可访问。未真实调用用户API、未改设备、未部署或新增依赖，真实账户和M1余项仍未验收。

## 上一轮：独立TTS与入口合并（2026-10-17）

- TokenDance公开模型详情确认两模型为text→audio，并链接小米官方合成文档。按其协议请求`POST /chat/completions`：待朗读文本在assistant，风格/音色描述在user，WAV在`choices[0].message.audio.data`。内置模型发送`audio.voice`，VoiceDesign要求描述且不发送voice。不猜其他参数，不把协议核实当作账户实测。
- 原设置页拆为“文字模型”和“语音合成”；TTS拥有独立地址、密钥、模型、内置音色/描述和超时。`GET/PUT /api/settings/tts`复用同一私有.env和原子SettingsStore，写入沿用operation_lock，字段分组保存不互相覆盖。TTS保存不替换文字适配器、不重置文字用量、不改历史；更换语音地址不复用旧密钥，没有从文字配置自动迁移密钥。
- `POST /api/settings/tts/preview`使用草稿快照返回WAV字节，不保存配置、正文、音频或试听日志，不发第二次模型请求。响应解码并校验WAV，短文本/有界响应/超时及单个在途试听限制保留。网络等待不持有聊天/配置操作锁；浏览器支持取消请求/播放及回收Blob URL，不保证供应商停止处理/计费，不自动重试。
- 文字列表移除已确认的MiMo TTS系列，手填到文字配置也会明确阻止；不再仅因chat-completions协议就当成文字聊天。错误原因直接显示。
- 侧栏四功能合并为一个“设置”，内部文字/语音/设备/资料/用量五个子页；保留旧路由，TTS为`/settings#tts`。文字高级参数、设备接入/恢复、资料筛选和次要用量默认折叠；安全说明保留。用量明确只统计文字、不含TTS试听。
- 相关后端检查累计**39通过**（首批38，补充TTS保存失败/环境覆盖1；13个无关用例未选），覆盖两种合成合同、独立密钥/保存、SQLite历史保留、草稿不保存、失败脱敏/不重试、原子保存失败不覆盖、并发限制及在途配置快照。无新增依赖；只有既有Starlette/httpx弃用警告。
- Chrome隔离流程`output/playwright/tts-settings-smoke.js`通过：模拟WAV实际播放，两模型切换、必填描述、鉴权失败保留输入、独立保存、刷新恢复、取消及浏览器存储无密钥；五个子页×桌面1365/手机390×明暗主题无横向溢出，额外核对高级区与TTS底部操作。HTML无标签错配/重复ID，JS语法检查及界面机械检查通过。
- 真实账户调用、音色听感/稳定性、TTS真实用量/费用、ASR及实机语音均**未验收**，M1未全部完成。未下载安装、未提交Git、未操作设备或部署。

## API配置首轮实现与验证（2026-10-17）

- 复用原设置页和SettingsStore/provider适配器，新增`POST /api/settings/models`。默认只识别已核实的TokenDance与OpenAI官方根地址；未知地址不探测，须明确确认OpenAI列表协议或手填ID。TokenDance公开目录不发送密钥，并依据`supported_protocols`筛选聊天模型；不自动改选或逐个测试。
- 列表成功、空列表、不支持、鉴权失败、权限不足、限流、连接失败、超时和不兼容响应有独立反馈。列表/草稿测试不写配置、不改变聊天统计或历史；保存沿用操作锁和原子替换，后续聊天使用新模型，失败保留旧配置和历史。
- 已存密钥不回传，前端不写浏览器存储，成功保存清空密钥输入。更改根地址时禁止隐式复用旧密钥，必须重新填写；无效密钥格式和上游错误均脱敏。
- 使用项目已有Python环境执行`tests/test_api_configuration.py`及`tests/test_api.py`中受影响配置、HTTP合同、历史保留用例：**25通过、13未选**。覆盖模拟列表/聊天、错误码、无自动重试、保存失败、密钥保护、保存后生效及SQLite重启恢复。唯一警告为既有Starlette/httpx弃用提示，未新增依赖。
- `node --check backend/app/app.js`通过；界面机械检查无发现。真实Chrome + 已有Playwright执行隔离本机8001流程通过（脚本`output/playwright/api-config-smoke.js`），验证选择/手填、草稿与保存、失败保留输入、刷新/历史、错误反馈和浏览器存储无密钥；桌面1365×1000与手机390×844、明暗主题及底部操作区域已截图检查，无横向溢出。所有模拟数据与临时文件在项目内，未接触生产历史和私有配置。
- A3的API配置部分通过隔离验收；A1真实模型、A4真实账户记录恢复、A3硬件部分和M1语音接口等仍未执行。协议文档核实见[references](references.md)，文档核实与模拟成功不代替真实API可用性。

## 此前文档整理与确认记录

- 将第一版三项需求、当前资源、代码职责和真实缺口统一到 agent 文档体系。
- 提取此前已确认的明暗灰阶视觉与工程约束，未改UI与业务代码。
- 按用户要求整合旧文档的有效内容后删除原文件；保留根README与AGENTS作为入口。
- 用户进一步确认Windows开发测试、2核2GB云端独立运行、接受在线语音与费用自行管理；已同步PRD、架构、阶段与验收文档，MiMo-V2.5-TTS列优先验证候选，未实际调用。
- 用户选择1B/2A/3A：唤醒加按键、仅文字历史、不长期保存录音、按唤醒分段且跨段不继承上下文；已同步需求与验收。尚未验证实机唤醒，未修改业务行为。
- 用户下一组选择1A/2B/3A：回答播完后30秒无人继续讲话结束、播放中语音打断必须支持、外网手机/电脑个人登录管理；已同步会话规则与A9/A13/A14验收，均未实施或实机验证。【历史要求；管理登录已由2026-11-15用户明确取消】
- 用户再选择1C/2A/3A：桌面和客厅背景声两种环境都要、首声目标约3秒、文字历史一直保留并手动删除；源码只读核对发现全量历史加载与旧max_sessions冲突。当时列入M1，现由本次依赖审查调整到M4集中改造，未修改代码。
- 用户再选择1A/2A：客厅约1–2米；短暂断网自动重连，保留尚未结束的当前段且不重播旧回答。已同步会话恢复、架构和验收，未执行网络或实机测试。
- 用户再确认1A/2A并补充屏幕按键：语音主动结束、按一下正面屏幕键暂停待机、自动独立备份，记录到需求与A16/A17；当时未定的上下文和目的地方向已由下一条确认，未修改设备或执行备份。
- 用户后续确认1A/2B：按键待机结束本段，再唤醒不继承上下文；独立备份走云存储或另一服务器，不依赖Windows。产品规则已同步，具体备份服务与副本策略待配置，未实施。
- 用户确认每日一次自动备份、保留30天副本。产品交互和基本备份规则已收敛，已同步验收与操作文档；仍未部署或执行备份，在线文字历史不按天数自动清理。

此前文档检查通过本地链接、旧文档引用及模板检查，六份旧文档已整合删除、旧空目录已移除。这些是历史文档结果，不表示本次运行了应用测试或任何新功能验收通过。

## 本次交叉审查结果

- 保留已确认范围，统一R00–R13需求和会话状态，区分30秒静默、请求超时、短断恢复与进程重启；停止/取消和迟到结果规则明确，不复活结束段。
- 修正阶段依赖：M1现有核心/接口，M2实机/恢复，M3目标云端最小闭环及双环境3秒/讲话打断，M4完整交互/设置/按需历史，M5备份/交付。公网认证在首次开放前，不留到最终验收才实施。
- 补齐D01–D29 → R00–R13 → 阶段 → A1–A17覆盖及每项首次/最终验收；明确真实独立备份上传/恢复，30天副本不改变在线历史期限。
- 同步START、统一入口、交接、资源、操作与工程规范；没有新选型、运行测试、调用API、生成录音、部署或实机操作。
- 文档检查通过：本地链接和代码围栏有效，无旧文档引用；D01–D29与R00–R13均有覆盖，A1–A17定义唯一且引用有效，M1–M5顺序一致。该检查只证明文档结构与追溯完整，不证明技术可行或功能可用。

## 历史阻塞与当时下一步（2026-10）

- D30对应的API配置功能已按本轮明确授权实现并隔离验证；API仍由用户后续自行填写，不索取密钥，真实调用未验收。
- 本轮承接D31的开发顺序，只完成API配置功能及必要验证；不自动扩大到M1其他工作或后续阶段。

1. 核心产品选择与每日备份/30天副本已确认，当前无需继续逐项问功能偏好；具体API、访问地址和云存储属于实施前配置，固件能力与约3秒首声需实际验证，见 [剩余实施条件](decisions.md)。
2. 实际模型账户未验收，设备接入/设置/切回未实测，不能进入“已有完整助手”的维护状态。
3. 本轮API配置授权范围已完成。下一次按 [START](../START.md) 在用户配置后验真实路径，或明确授权M1余项；不重复开发已验证流程，不把已收敛产品选择当阻塞。

## 以后如何更新

只在实际能力或验证结论变化时更新对应行，写明输入、输出、环境、日期和仍不支持的部分。失败写失败原因与最近的修复落点，不填模糊百分比，不用“代码已接入”代替可用。

## 设置直接页签与人设增量（2026-10-17）

- 设备/资料/用量直接显示在设置页签栏，取消更多中转；新增角色说明，复用每轮请求的system消息，保留现有锁和原子保存。旧调用不传角色时保留已存值。
- 最小后端验证：`tests/test_settings_workflow.py` 9 passed。确认人设在已有会话下一轮请求中生效、历史与用量不变、持久化恢复、旧客户端兼容、无效输入及写入失败保留旧配置。
- 隔离Chrome浏览器：原模型/声音/API流程通过；七页签直接进入、跨页草稿、角色保存/刷新恢复、取消还原、失败保留输入通过；1365×1000及390×844明暗主题检查通过。未向设备发送控制、未调用真实账户。
- 真实模型遵循人设的效果、真实TokenDance聊天/TTS、实际音色听感仍未验收，不能宣称M1全部完成。

## 设置去冗余与资料连接排查（2026-10-17）

- 删除用量/设备/资料页重复页标题、设备开发阶段说明及屏幕设置重复标题；保留设备真实连接状态、错误/固件信息、操作与必要确认。用量统计范围移入已有底部说明。
- 资料未测试时明确显示未测试，失败原因就地显示；SSE嵌套异常保留协议校验错误，区分超时、网络和HTTP状态，不回显上游原文，不放宽只读工具校验或自动重试。
- 实际路径：本机8000资料连接HTTP200、浏览器测试连接成功，公开固定查询`AtomS3R K147 SDK`返回5个片段。此前失败未复现，无法断定当时原因；排查开始时本机8000无监听，已重新启动为隐藏进程。
- 最小验证：`tests/test_knowledge.py` 12 passed；浏览器模拟超时反馈和真实连接/搜索、三页桌面/390px明暗检查通过，无设备控制调用。真实TokenDance与TTS仍未验收。

## API接入一屏紧凑编辑（2026-10-17）

- 移除请求/费用及语音超时折叠，把全部已有参数改为小尺寸直接编辑控件；连接紧凑行，桌面参数三列、手机两列，缩短技术文案；原字段ID/输入约束、共用密钥与独立服务切换、原子保存和取消路径保留。
- 隔离Chrome验证：1365×1000、1280×720、390×844，明暗主题及公共/独立语音两模式，共12种组合字段区无垂直滚动、无横向溢出，全部参数可见。编辑请求/费用参数保存刷新恢复，旧密钥不回填；JS语法及UI检测通过。未改后端，未重跑无关测试，未改用户API或调用真实模型。

## API测试入口与接入状态（2026-10-17）

- API页补回明确的测试模型入口，复用模型页原调用与结果；未选模型引导选择，接入有未保存修改则先保存，避免把旧连接测试误认为新草稿已通过。测试成功文案明确不自动保存设置。
- 只读本机状态：用户已保存密钥，文字模型尚未选择，文字configured=false；TTS已有配置。未读取/输出密钥或自动调用真实付费API。
- 隔离浏览器验证入口可见、未保存保护、单次模型调用与结果显示通过；1280×720和390×844独立连接模式仍一屏显示。JS语法/UI检测通过。真实模型与试听继续待用户手动执行。

## 统一API、模型与声音（2026-10-17，取代分离页签）

- 按用户最新要求移除模型/声音页签，API接入同页完成连接、文字模型获取/手填/测试、声音模型/音色/描述/草稿试听；角色独立。旧/settings及#tts自动进入统一页。
- 新`PUT /api/settings/api`复用既有operation_lock与原子.env写入，一次保存连接和模型/音色；失败不部分生效，历史保留。草稿列表/文字测试读取当前连接输入；TTS预览可携带未保存连接，快照后调用，不保存密钥、不改正式配置。
- 设备/用量刷新合并到相同的紧凑状态栏，取消孤立大按钮。常规桌面与1280×720公共连接编辑一屏；手机必要滚动，不裁剪控件；试听音频/错误等动态内容可能增加滚动。
- `tests/test_settings_workflow.py tests/test_tts.py` 25 passed；隔离浏览器统一草稿列表/模型测试/可播放试听、保存刷新、取消还原、明暗/桌面/笔记本/390px验证通过，JS语法/UI检测通过。真实账户未调用，M1未宣称全部完成。

## 设置窗口统一尺寸与API页重排（2026-10-17）

- 五个页签共用 920×720 固定窗口，取消API页单独放大到1040×800，切页签不再改变窗口尺寸；标题、页签、底部操作栏钉住，仅内容区滚动。
- API接入页由三块拼接改为左“连接”（服务名/地址/密钥/获取方式/语音独立）与右“模型与声音”两栏，底部参数按“请求”“费用”各三格并排；参数全部直接可见不折叠。修正上一版手机端参数被同一媒体查询内重复声明覆盖成三列、模型按钮被挤出视口的问题。
- 角色页改为设定文本域 + 一行只读摘要（当前模型与音色；未接入时提示到API页），不再有大片空白；保存仅比较角色文本本身。
- 清理上一版遗留：`assistant-connection-state`（从未显示）、`#tts-view` 死选择器、`tts-fields`/`tts-dirty-state` 误命名（改为 `role-fields`/`role-dirty-state`）、`#settings-view` 的过时 aria-label、未使用的 `i-usage` 图标、navigate 中恒为 false 的面板 hidden 控制。
- 主界面：空状态建议改为与设备相关的提问；M5Stack 资料开关从输入框角落小图标移到输入框上方独立一行。
- 隔离验证：四个页签实测尺寸均为920×720、0 JS错误、无缺失元素；1440×900 与 390×844 明暗主题截图核对；`pytest -q` 82 passed。未改后端协议与数据路径，未调用真实API。

## API接入页降噪（2026-10-17）

- 用户反馈该页“堆太多东西”。按使用频率分层：连接与请求/费用改为 `<details>` 折叠，摘要行直接显示当前值（`tokendance · 已接入`、`512 Token · 30／60 秒 · CNY`），M5Stack 开关移到左栏底部常驻。
- 默认收起后可见输入控件由 20 个降至 6 个（模型、合成模型、音色、说话风格、试听文字、资料开关），折叠行与按钮共 6 个可点；未配置连接时自动展开，避免找不到入口。
- 右栏补“对话模型”标签列，与合成模型/音色/说话风格对齐；左栏略宽于右栏，费用标签不折行。删掉独立底部说明区，关键说明并入对应折叠体。
- 精简文案：`66 个可选模型，尚未验证调用`→`66 个模型可选`；`测试和试听会发送请求，不自动保存选择`→`试听会发出真实请求，不保存选择`。
- 验证：默认 connOpen/paramsOpen 均为 false，摘要文案正确，0 JS错误，无缺失元素；桌面收起/展开、390×844 展开、明暗均截图核对，展开后参数在左栏单列两组。后端未改。

## 接入页归属澄清与声音并入角色页（2026-10-17）

- “请求与费用”改为“对话请求与费用”，组标题写明“费用（按对话 Token 估算）”，说明只作用于对话模型；合成等待移出该页。
- 对话模型下拉末尾增加“手动填写模型 ID…”选项，选中才显示输入框，删除原先常驻的折叠入口；移除“N 个模型可选”提示行。
- `POST /api/settings/models` 增加 `speech_models`：按 `openai:chat-completions` 协议识别语音模型（排除需要参考音频的 voiceclone）。`Settings.tts_model`、`TTSSettingsUpdate`、`AssistantUpdate` 由写死的 `Literal` 改为长度受控的字符串，前端下拉由接口填充，保留两个 MiMo 值仅作初始兜底。
- “合成模型”改称“声音模型”，音色、说话风格、试听、合成等待整块移入“角色”页并与角色设定同一次保存（`AssistantUpdate` 新增 `tts_timeout_seconds`）。试听改用已保存连接，不再读取接入页未保存的密钥。API页保存不再携带 tts 字段。
- 已知边界：该目录另有 `seed-tts-2.0`（ark:tts）与 `minimax-speech-*`（minimax:t2a_v2），协议与现有 chat/completions 合成实现不同，未纳入自动列表，需要时须单独适配。
- 验证：接口实测返回 chat 66 个、speech 2 个；手动填写选项显示/收起与值同步通过；四页签尺寸仍为920×720；0 JS错误、无缺失元素；桌面收起/展开、390×844、角色页截图核对；`pytest -q` 82 passed（含更新后的模型列表断言）。

## 角色页收敛：模型提示上移、说话风格并入角色设定（2026-10-17）

- 当前模型提示移到角色页最上方，只作状态提示；删除“保存后从下一轮回复生效”说明。
- 删除独立的“说话风格”输入框：保存时 `tts_instruction` 直接取角色设定文本，语音风格与对话语气由同一段描述决定，不再有两个需要重复填写的框。
- 「合成等待」改称「合成超时」，附说明“最多等多久，超过就放弃本次合成；调小不会让合成更快”，避免被当成提速开关。
- 试听说明改为：会真实调用供应商并按供应商规则计费；音频只存在浏览器内存，不写入本机文件，离开本页即释放。后端合成结果仍以内存 bytes 直接返回，不落盘。
- 验证：`assistantPayload().tts_instruction === system_prompt`、页面无 `#tts_instruction` 元素、0 JS错误、无缺失元素；角色页一屏内完整可见；`pytest -q` 82 passed。

## 接入页去折叠与底栏模型提示（2026-10-17）

- 删除“对话请求与费用”整块：回复上限、聊天等待、币种、输入价、输出价不在界面暴露；`connectionPayload` 不再提交这些字段，`/api/settings/api` 靠 `model_fields_set` 保留本机原值，`/api/settings/test` 与模型列表改用已保存值而非默认值。
- API接入页取消折叠与两栏：连接在上、对话模型在下、M5Stack 收尾，单列限宽 700px；折叠相关的 `<details>`、参数网格与摘要行全部移除。
- 当前模型提示从内容区移到底栏居中，左侧状态、右侧按钮；手机断点隐藏。未接入时该位置改为“文字／语音服务尚未接入”提示，角色页不再保留独立摘要条。
- 角色页：声音模型与音色合并为一行，选择框限宽（模型 260px、音色 150px）；合成超时从界面移除，保存与试听沿用已保存值或默认 60 秒；删除试听下方说明小字。
- 验证：`detailsCount` 为 0、已移除字段全部查无、底栏提示文案正确、手动填写与声音模型选项仍正常；四页签 920×720；0 JS错误、无缺失元素；桌面与 390×844 截图核对；`pytest -q` 82 passed。

## 移除资料与用量页（2026-10-17）

- 用户判断“没啥用”。删除设置窗口中的“资料”和“用量”两个页签及其页面、相关 DOM/JS/CSS；页签收敛为角色、API接入、设备三项。
- 同步删除后端 `/knowledge`、`/usage-view` 两个页面路由（现返回 404），CSP 路径清单同步；`/usage` 与 `/api/knowledge/m5stack/*` 接口保留：前者仍被用量统计与每条回复的 Token 展示使用，后者仍服务聊天时的资料检索，聊天输入框上方的“M5Stack 资料”开关不受影响。
- 用量信息改由每条回复底部的 `模型 · N Token · 估算费用` 承担；资料检索结果仍在回复中以“查看来源”折叠呈现。
- 测试同步：`test_knowledge.py` 移除 `/knowledge` 页面 200 断言，接口与不计 Token 的断言保留。
- 验证：`/`、`/settings`、`/devices` 均 200，`/usage-view`、`/knowledge` 为 404；页签实测为 role/connections/devices 三项、无残留视图；0 JS错误、无缺失元素；`pytest -q` 82 passed。

## 修复底栏右侧露出底色（2026-10-17）

- 用户截图指出设置窗口右下角有一块与底栏不同的空白。实测底栏 `.settings-actions` 宽度为 820，而窗口内容宽 918，右侧 98px 露出 `--surface` 底色；接入页因内容限宽 700 露出 218px。
- 根因：内容限宽 `max-width` 加在了 `page-content` 上，而底栏与字段区同在该容器内，一并被收窄。把限宽下移到字段容器后，又因 flex 交叉轴上 `margin:0 auto` 会取消 stretch，容器收缩到内容宽度（输入框被压到约 200px）；补 `width:100%` 后恢复。
- 结果：两页底栏均满宽 918，内容区按 700／820 居中；0 JS错误、无缺失元素；`pytest -q` 82 passed。

## 文档同步补漏与设备链路实测（2026-10-17）

- 补漏：`docs/operations.md` 页面清单仍写 `/usage-view`、`/knowledge`（实际已 404），`agent/agent.md` 三处与 `design/overview.md` 仍写五页签，`docs/resources.md` 仍提“已有用量页”。以上已改为三页签结构并注明移除事实；`progress.md`、`decisions.md` 的历史条目保持原样，属于当时记录。
- 设备实测：普通 `uvicorn backend.app.main:app` 只起管理服务，`gateway_running` 为 false、8003 不监听；改用 `python -m backend.run_devices` 后网关正常监听 `0.0.0.0:8003`，OTA 路由可达。
- 设备本身未连入：网关启动后 `connected=false`、`last_bootstrap=null`、`device_id` 为空，说明设备从未向本机网关取过配置，OTA 地址仍指向原厂服务，不是本机。页面“设备尚未连接”与真实状态一致。
- 链路可用性单独验证：带 key 的 OTA 请求可返回 `ws://192.168.1.6:8003/xiaozhi/v1/`，说明只需在设备配网页改 OTA 地址即可接通。
- 期间发现 `bootstrap_authorized` 会在 `device_id` 为空时按首次请求的 Device-Id 自动配对并持久化；模拟请求写入的假 MAC 会挡住真实设备，已通过 `PUT /api/devices/setup` 置空清理，当前配对状态为空。
- 未烧录、未向设备发送控制指令、未改变设备原 OTA 设置；实机连通仍待用户在设备侧修改地址后验证。

## 实机联调：OTA 响应缺 firmware 导致设备不连（2026-10-17）

- 实机 AtomS3R（MAC `7c:e8:b1:e4:6e:08`，IP `192.168.1.5`）在设备配网页改到本机 OTA 后，能成功请求 `/xiaozhi/ota/` 并完成自动配对，但始终不发起 WebSocket，`connected` 保持 false。
- 排查关键：设备网关原先 `access_log=False`，可见的 8003 TIME_WAIT 实际来自 OTA 的 HTTP 连接，一度被误判为“握手被拒”。打开访问日志后确认日志里只有 `POST /xiaozhi/ota/ 200`，没有任何来自设备的 `WebSocket` 记录。
- 根因：XiaoZhi 固件要求 OTA 响应带 `firmware` 块，缺失会把响应判为不可用并回退原服务器配置。已补 `firmware: {version: <回显请求中的 application.version，缺省 1.0.0>, url: ""}`，`url` 为空即不触发固件升级，保持“不宣告升级”的既有约束。
- 同时补 `/xiaozhi/v1`（无尾斜杠）WebSocket 路由别名，避免设备按无斜杠地址连接时 404（ws 不支持 307 重定向）。
- 失败握手增加原因记录（`describe_rejection`），只写标识是否匹配、token 有无、协议版本，不回显 token。
- 服务端自检：用真实 token 与配对 MAC 模拟握手，正确返回 hello 与 MCP initialize，排除服务端逻辑问题。
- `test_devices.py` 同步：允许 `firmware` 字段并断言 `url` 为空、版本回显；`pytest -q` 82 passed。
- 真机连通仍待设备重新上电后确认；未烧录、未发送控制指令。

## 实机连通与设置下发验证（2026-10-17）

- 设备：AtomS3R，MAC `7c:e8:b1:e4:6e:08`，IP `192.168.1.5`，固件报文 `atoms3r-echo-base` / `2.2.6`；本机 `192.168.1.6`，网关 8003。
- 修复 `firmware` 块与 `/xiaozhi/v1` 别名后，设备重新上电于 14:04:41 建立控制连接，`connected` 与 `ready` 均为 true，MCP 能力为 `set_volume`、`get_device_status`、`set_brightness`、`set_theme`。
- 实机下发一次已保存设置：音量 30 → `verified`，读回 30；主题 dark → `verified`；亮度 60 → 读回 63，如实标为 `mismatch`（设备按自身档位量化，非失败）；屏幕文字通过协议 `tts` 消息下发，状态 `sent`，该消息无回执通道。
- 设备状态回读：`audio_speaker.volume=30`、`screen.brightness=63`、`screen.theme=dark`、网络 `wifi/CMCC-g24u/weak`，信号弱与先前 600ms 级 RTT 相符。
- 能力清单中没有屏幕文字工具，故“屏幕文字”不走 MCP、无读回；如需可验证的文字能力需另行确认固件支持。
- 未烧录、未修改设备原 OTA 记录；**切回原平台的路径仍未验证**。`pytest -q` 82 passed。

## 本地 ASR 可行性实测（2026-10-17）

- 复用已有 `.venv-speech`（sherpa-onnx 1.13.8），下载 SenseVoice int8 模型到 `models/asr/sensevoice/`（`model.int8.onnx` 229MB + `tokens.txt`）。下载源用 `hf-mirror.com`，GitHub release 直连返回 502。
- 新增 `scripts/asr.py`：读 WAV → 重采样到 16kHz → `OfflineRecognizer.from_sense_voice` 识别，输出耗时、RTF 与文本。该脚本不联网、不读密钥、不碰设备。
- 实测（2 线程，Windows 开发机）：8.626 秒音频解码 0.325 秒，RTF 0.038；6.639 秒音频 0.246 秒，RTF 0.037。加载模型一次性 1.5–1.7 秒，服务常驻时可忽略。
- 内存：Python 基线 37MB，加载模型后 336MB（净增 299MB），识别后 357MB。加 FastAPI 服务后预计 550–600MB，2GB 目标环境可容纳。
- 识别质量：长句（8.6 秒）逐字正确；短指令「把音量调到五十，然后把屏幕调暗一点」出现同音错：「五十→误时」，且 `use_itn=True` 时「调暗→调安」，关闭 ITN 后该处恢复正确但整体丢失标点。
- 结论：`use_itn` 默认关闭（避免主动引入同音错），标点交给下游模型处理。同音字仍建议由 LLM 结合上下文纠正。
- 局限：测试音频均由 Kokoro 合成，非真人；「五十」误识别可能是合成发音问题，需用设备麦克风实录复核。opus 解码尚未接入。
2026-11-07：AtomS3R 与网页语音共用 Omni Realtime WebSocket 适配器，默认百炼北京 qwen3.8-omni-flash-realtime。设备用本机 libopus 解码麦克风帧并编码下行；网页用 AudioWorklet 采集。API 接入可选实时或分模型、北京业务空间或兼容 WSS、模型 ID 和音色，实时服务密钥独立写入私有 .env。用户已保存百炼业务空间和密钥；真实回合「你是谁？」识别正确并返回语音。网页链路从最后有声采样到首段音频 1.481 秒；按设备 WebSocket 协议模拟，从最后有声帧到首段 Opus 1.539 秒。真实 AtomS3R 当时离线，扬声器实际开口和实机打断仍待验证。
2026-11-07 音色复刻：API 接入增加百炼 Qwen3.8/3.5 Omni 实时音色复刻，支持上传单人录音、中文命名、读取空间内已复刻音色、删除及实时生成试听；上传处理后的临时副本在完成后删除，原有音色样本不受影响。已用现存 `models/voice/taffy-24k.wav` 实际创建百炼「塔菲」复刻，生成 6.88 秒试听并被用户确认；音色 ID 已保存，本机原 WAV／MP3 及 MiMo 音色索引仍保留。不要重复创建。

2026-11-07 设置整合：API 接入统一为实时对话／分模型两个分页。实时模式下网页文字和两端语音均走当前实时模型；DeepSeek 配置仅留在分模型页，未删除密钥。资料检索独立为共用能力，文字沿用官方资料检索，实时语音通过函数调用检索。声音模型和音色配置归入 API 页，角色页集中提示词、设备音量、语速、音调和草稿试听；实时音频与复刻试听均应用已有语速／音调处理。音量可单独保存并应用，不下发其他设备设置。已真实调用 Omni 文字回复和调节试听，浏览器确认分页、公共开关、角色控件；本轮设备离线，音量读回和实时语音资料函数调用尚未实机确认。

2026-11-07 后续范围与交接：用户确认基本交流正常，并将外部 API 工具与个人知识库加入 P1；AI 先完成完整开发和可独立进行的实际运行检查，用户再集中现场测试并反馈。roadmap、START 与主 DeepSeek Bot 提示词已按此整理，区分已开发、AI 已确认和待现场体验。此轮仅修改文档，没有创建子 Bot、群聊派工、新功能开发或云端部署。执行依据见 [roadmap](roadmap.md) 和 [handoff](handoff.md)。
