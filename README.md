# battray

Ubuntu 桌面的无线外设电量工具：提供电量卡片、数字托盘、命令行查询和 HID 调试界面。

当前真实硬件支持为 **AULA 狼蛛 F98Pro 的特定 2.4G 接收器配置**（`05AC:024F`、USB 版本 `0121`、接口 `03`、精确描述符匹配），不保证其他版本或型号兼容。多设备卡片已通过模拟测试，第二种真实设备尚未认证。

## 安装与运行

需要 Python 3.12（已验证版本）、系统 Tk、GIO/GLib；托盘还需要 SNI 宿主。没有第三方 pip 依赖。其他 Python 版本和桌面环境需自行验证。

```bash
git clone https://github.com/hyge9527/battray.git
cd battray
sudo apt install python3-tk
python3 -B my_devices.py --onboard
```

`--onboard` 只检查设备匹配及权限计划。确认是受支持的接收器后，按需安装定向权限规则，再用普通用户运行：

```bash
sudo /usr/bin/python3 -B tools/install_device_access.py
python3 -B my_devices.py --once
python3 -B my_devices.py --panel
```

权限安装器只适用于已支持的 F98Pro 接口，不应用于陌生设备。

## 日常入口

```bash
python3 -B my_devices.py --tray             # 托盘常驻；无宿主时保留面板
python3 -B my_devices.py --install-desktop  # 创建桌面链接和启动器
python3 -B my_devices.py --quit             # 完全退出
```

默认 60 秒刷新，可在面板调整为 30～1800 秒；登录自启由用户显式启用。有历史读数的失败显示灰色旧电量，无可靠读数显示 `?`，不会把超时写成 0%。不写应用日志。

## 文档

- [使用、安装、自启与排障](docs/usage.md)
- [支持设备、协议样本与验证范围](docs/supported-devices.md)
- [代码架构](docs/architecture.md)
- [新增设备适配流程](docs/device-adaptation.md)及[可复制的 AI 适配提示词](docs/prompts/adapt-device.md)
- [贡献与测试](CONTRIBUTING.md)

框架可以扩展新设备，但绑定 JSON 不会自动逆向或安装未知协议。Windows/macOS 需要另行实现平台层。

## 来源与许可

参考来源及待核对的授权事项见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。当前尚未添加 LICENSE，不宣称已采用某种开源许可证。
