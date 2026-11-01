# 可选：GNOME 托盘位置固定

仅针对 GNOME Shell 46，用于把 battray 图标固定在其现有面板区域的最左侧；不改变其他图标之间的相对顺序。主程序不依赖此扩展。

主程序使用固定服务名 `org.keyboardpower.Tray`，但左右顺序仍由托盘宿主管理。该扩展只移动对应图标，不修改系统 Ubuntu AppIndicators 源码，使用事件与一次性 idle 回调，无循环轮询。

## 安装与禁用

从项目根目录以普通用户执行：

```bash
python3 -B tools/install_tray_position.py
```

安装器核对 GNOME 版本，复制到用户扩展目录，并保留其他扩展的启用状态；拒绝覆盖内容不同的已有文件。新扩展可能需要保存工作、注销并重新登录后才被 GNOME 识别。不要自动重启桌面。

禁用：

```bash
gnome-extensions disable keyboard-power-position@local
```

禁用时清理信号与待执行回调，并尽可能恢复原位置。卸载前先禁用，再仅删除用户扩展目录中的 `keyboard-power-position@local` 文件夹。

## 支持边界

排序模型和本机 API 检查通过，但实际重新登录后的固定顺序尚未验收。没有 SNI 宿主、GNOME 版本不同或其他布局扩展同时移动图标时，需要另行验证。Node 仅用于开发模型测试，不是应用运行依赖。
