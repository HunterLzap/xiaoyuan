---
description: 自动执行 SlopGuard 门禁检查、消融验证、告警修复与合规提交
---

当完成任何代码修改准备交付时，严格按以下闭环自动执行，无需等待用户逐步确认：

1. **判定任务类型**：根据本次改动意图判断属于【Bug 修复】还是【功能开发/重构】。
2. **运行确定性门禁（在 git commit 之前执行）**：
   - 若为【Bug 修复】：运行 `C:\Users\l\go\bin\slopguard.exe verify --ablation`，确保测试真实经历 `RED -> GREEN` 消融验证。
   - 若为【功能开发/重构】：运行 `C:\Users\l\go\bin\slopguard.exe verify`。
3. **自动修复拦截项（最多循环 3 轮）**：
   - 若退出码非 `0`，逐条读取 `findings` 自行修复（补全复现测试、修复 Lint/报错）。
   - 若命中 `probe:workaround_comment`，实施最小根因修复并移除临时补丁；若命中 `probe:constraint_comment`，优先将该约束改写为 `tests/` 下的 `pytest` 断言并删除注释。
   - 严禁通过添加 `# type: ignore`、`# noqa`、`@ts-ignore` 或 `--no-verify` 绕过检查。
4. **自动提交与精简汇报**：
   - 门禁退出码为 `0` 后，检查 `git status --short` 确认无无关临时文件，按规范提交信息（修 Bug 用 `fix: ...`，新功能用 `feat: ...`）执行 `git add` 与 `git commit`。
   - 向用户输出不超过 5 行的交付回执：提交哈希、修改文件数、门禁与消融状态，以及是否需要用户真机验证。
