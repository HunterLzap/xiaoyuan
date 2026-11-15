# 编译配置命令

> 项目说明（2026-11-15）：下方通用编译配置和机器人屏幕段是源码参考，不是当前稳定设备的刷写指令。当前应用/云端基线、暂停事项从仓库根 [AGENTS](../../../../../AGENTS.md) → START读取；新动画/UI/TCP代码在Git保留实验，不直接编译刷入。Git快照不代表部署或设备操作。

**配置编译目标为 ESP32S3：**

```bash
idf.py set-target esp32s3
```

**打开 menuconfig：**

```bash
idf.py menuconfig
```

**选择板子：**

```
Xiaozhi Assistant -> Board Type -> AtomS3R + Echo Base
```

**修改 flash 大小：**

```
Serial flasher config -> Flash size -> 8 MB
```

**修改分区表：**

```
Partition Table -> Custom partition CSV file -> partitions/v2/8m.csv
```

**修改 psram 配置：**

```
Component config -> ESP PSRAM -> SPI RAM config -> Mode (QUAD/OCT) -> Octal Mode PSRAM
```

**编译：**

```bash
idf.py build
```

## 机器人屏幕

以下描述新动画实验源码，使用 `sdkconfig.tafei-mn5`、`sdkconfig.defaults.atoms3r-tafei-mn5` 和 `build-tafei-mn5-ui-anim` 构建；不等于设备当前运行内容。

- `animations/` 保存用户选定的第一版 `device-animation-pack.zip` 的 15 张原始雪碧图；`manifest.json` 定义帧数、80ms 帧间隔、状态文字及循环/单次/保持末帧规则。
- 构建自动调用 `scripts/build_device_animations.py` 切帧、去重并转换为 LVGL 原生 I4/RLE，生成资源与 C++ 帧序清单，再合入默认 assets。原始图片无需运行时 PNG 解码。
- 压缩帧解码必须同时开启 `CONFIG_LV_USE_RLE` 和 `CONFIG_LV_BIN_DECODER_RAM_LOAD`；已在当前配置和板级 defaults 中启用。LVGL 仅输出 ERROR 级日志，绘制失败可从串口查到原因。
- `robot_display.h` 固定使用 128×128 坐标：顶部 `y=0–17` 为 `HH:MM`，中部 `y=18–105` 为表情，底部 `y=106–127` 为当前状态。时间沿用 OTA 后端校时，未校时显示 `--:--`。
- 实验设计中连接、倾听、说话、唤醒和打断跟随设备事件，实时后端通过 `ui` 消息补充状态；它与稳定后端存在发送锁/时序耦合线索，语音回归因果未查清，不能据设计意图宣称不会影响音频或收音。
- 休眠表情只表示本地待机，不改变已有唤醒检测或芯片电源状态。工具成功只依据实际执行结果，订单待确认使用澄清表情，不把普通回答强制标为操作成功。
- 只有用户以后明确恢复该实验并授权刷写时才评估应用/assets配套，保留NVS、配对、分区表和bootloader；本段不授权更新当前设备。
