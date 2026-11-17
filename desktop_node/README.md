# Desktop Node（个人电脑连接端：Windows & macOS）

轻量、纯本地依赖的桌面连接端，让云端或局域网中的小蛋 Agent 可以安全读取屏幕（Computer Use）、读写剪贴板、浏览与读取非敏感文件、打开应用，并在用户明确确认后执行鼠标/键盘操作与终端命令。

## 安装依赖（Windows 与 macOS 通用）

只需要安装 `websockets`（截屏与键鼠控制全部调用操作系统原生接口，无需繁重原生编译依赖）：

```bash
pip install -r desktop_node/requirements-desktop.txt
```

## 启动连接

打开网页端 **「设置 -> 终端节点」**，直接复制带地址和密钥的启动命令在你的 Mac 或 Windows 电脑上运行：

- **macOS**：
  ```bash
  python3 -m desktop_node --server "wss://你的域名/assistant/desktop/v1/" --token "页面中生成的Token"
  ```
  > 首次截屏或键鼠操控时，请在 `系统设置 -> 隐私与安全性` 中为当前终端/Python 开启「录屏与系统录音」和「辅助功能」权限。

- **Windows**：
  ```powershell
  python -m desktop_node --server "wss://你的域名/assistant/desktop/v1/" --token "页面中生成的Token"
  ```

## 安全开关

- 默认已拒绝读取 `.env`、`.ssh`、`id_rsa`/`id_ed25519`、`.pem`/`.key`、浏览器 Cookie/登录库等敏感路径。
- 如仅希望某台电脑只允许「看屏幕 + 读文件 + 剪贴板」，可附带安全启动参数：
  - `--no-shell`：禁用终端命令执行
  - `--no-gui`：禁用鼠标与键盘操控
