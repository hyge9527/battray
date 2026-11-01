# 贡献与新增设备

目前真实协议支持仅覆盖本机已核对的 AULA F98Pro 接收器配置，多设备框架和其他能力不代表任意设备均已认证。

提交新增设备适配前，请先阅读 [详细适配流程](docs/device-adaptation.md)和[当前架构](docs/architecture.md)。报告未知设备也有价值，不必先猜出协议。

## 建议的贡献拆分

1. 只读发现与设备证据：型号、模式、接口与描述符，说明是否存在系统电量来源。
2. 协议解析与测试：独立请求/回复函数、来源与真实样本、错误样本拒绝。
3. 已验证适配器：精确 profile、静态注册、超时/取消/事务与状态处理。
4. 权限与使用指引：需要时另加最窄访问策略，不能扩大原设备权限来迁就新设备。

结构整理、错误修复和新设备行为尽量分开，保留已有设备和测试断言。不要给 UI/调度添加大量品牌分支，普通绑定/标定 JSON 不能获得自动执行未知请求的资格。

## 可独立运行的检查

```bash
python3 -B -m unittest discover -s tests -q
```

可选 GNOME 排序模型开发检查需要 Node；它不是 Python 应用运行依赖：

```bash
node tests/test_tray_position.mjs
```

真实桌面验证脚本可能查询 HID、退出已有实例或截图。先检查下方副作用表，不要把这些脚本直接放进无人值守 CI，更不能让 CI 安装 udev 规则或启用宿主扩展。

## 公开证据前

不要上传密码、令牌、普通键盘输入、宏内容、完整 USB 抓包、未经检查的诊断文件、用户设置或原始桌面截图。型号和 VID/PID 通常是适配所需信息；序列号、个人路径、主机名等分享前自行检查和脱敏。

请区分合成夹具和真实样本、候选解析和已验证协议、单次对照和完整状态验收。未经独立对照，不把某个 0～100 的字节宣称为电量。

引用外部代码或资料时更新 [来源记录](THIRD_PARTY_NOTICES.md)，说明准确版本和复用方式；许可未确认时不要替维护者选择或宣称授权。

## 验证工具的副作用

| 操作 | 是否打开真实 HID / 修改系统 | 使用注意 |
|---|---|---|
| `python3 -B -m unittest discover -s tests -v` | 临时目录、模拟 socket/设备、离线 native GVariant；不访问真实 HID | 优先用于回归；需要允许本地 socket |
| `--help` / 离线 `--decode-report` | 不访问 HID，不改桌面设置 | 可作为文档与输入错误冒烟检查 |
| `--diagnose` | 只读 sysfs/系统总线，不发送 HID 命令 | 需检查宿主会话可访问性 |
| `--once` / `--panel` / `--tray` | 可能主动发送已验证电量查询 | 不把它们当纯静态审查操作 |
| `tools/verify_desktop.py` | 会退出已有工具、启动三次、发送查询、截图并测 CPU | 历史结果见支持设备文档；重跑会影响已有实例 |
| `tools/verify_isolated_desktop.py` | 私有 D-Bus、临时配置/IPC、模拟设备；使用真实 Tk 显示短暂测试窗口 | 不读取 HID，不操作真实运行实例 |
| `tools/verify_debug_panel.py` | 启动 GUI、查询、监听及取消 | 需独立桌面验证安排 |
| `tools/verify_installation.py --launch` | 读安装状态并实际启动/退出应用 | 会影响用户会话，不隐式执行 |
| 权限安装 / `--install-desktop` / `--autostart on/off` | 写真实 udev/桌面/自启 | 只在用户明确操作时执行 |

已有授权可沿用，但先说明具体副作用；不要为运行审查而安装新依赖、重启 GNOME 或解绑输入设备。


硬件实测范围见 [支持设备](docs/supported-devices.md)。隔离桌面验证可在可用 DISPLAY 的会话执行：

```bash
dbus-run-session -- env KEYBOARD_POWER_PRIVATE_TEST_BUS=1 /usr/bin/python3 -B tools/verify_isolated_desktop.py
```

该脚本使用临时配置、私有总线与模拟设备，会显示短暂测试窗口。实机验收脚本含 F98Pro 断言，适配新设备时应先审阅。配置格式分别为设置 schema 2、绑定 schema 1、离线标定 schema 1，不能互换。已运行的进程不会自动加载源代码修改。
