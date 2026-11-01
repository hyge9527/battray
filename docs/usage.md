# 使用与排障引导

本工具当前适配本机 AULA F98Pro 的 2.4G 接收器；并非任意键盘的通用电量工具。
如果只是日常使用，从下表选入口，不需要手动构造 HID 报文。

## 选择入口

| 想做什么 | 入口/命令 | 会发生什么 |
|---|---|---|
| 桌面启动 | 双击“键盘电量.desktop”对应的启动器 | 无终端；首次启动进入托盘；若已有实例则前置面板 |
| 打开面板 | `python3 -B my_devices.py --panel` | 默认一张卡片；有已保存绑定时按绑定生成，自动读取并周期刷新 |
| 常驻托盘 | `python3 -B my_devices.py --tray` | 注册成功后隐藏面板；宿主不可用则保留面板 |
| 看一次电量 | `python3 -B my_devices.py --once` | 主动查询后输出；成功退出码 0，未知/过期/失败为 2 |
| 立即刷新 | 面板按钮或 `--refresh` | 请求已有实例异步刷新，返回状态不等于读取已完成 |
| 查看运行状态 | `python3 -B my_devices.py --status` | 返回本地 IPC JSON，不新建实例 |
| 完全退出 | 面板/菜单“退出”或 `--quit` | 结束已有实例；不是只关闭卡片 |
| 排查环境 | `python3 -B my_devices.py --diagnose` | 只读诊断，不向 HID 发命令；输出本身是 JSON |
| 查看支持与权限步骤 | `python3 -B my_devices.py --onboard` | 只读枚举、匹配及规则预览，不安装、不查询电量 |
| 开发调试 | `python3 -B my_devices.py --debug-panel` | 显示所有 HID 接口和手动操作页 |

以上命令在项目目录执行；不在项目目录时将脚本路径换成绝对路径。
多个入口是同一应用，重复点击不会开出多份后台进程。
直接双击 `my_devices.py` 符号链接是否执行由 GNOME 决定；日常推荐 `.desktop` 启动器。
另一个“键盘电量项目”目录链接只用于打开源码目录，不会启动程序。

## 设备绑定与多卡片

默认不需要配置。需要指定设备或同型号接收器时，可从 `packaging/devices.example.json` 另存一份绑定文件；VID/PID 使用四位大写十六进制。同 VID/PID 的多台设备必须分别填写 `--list-devices` 给出的不同绝对 `usb_path`，不能重叠选择。

```bash
python3 -B my_devices.py --check-config /path/to/devices.json
python3 -B my_devices.py --panel --targets /path/to/devices.json
python3 -B my_devices.py --once-all --targets /path/to/devices.json
```

`--targets` 只对本次面板/`--once-all` 生效，不保存选择。`--once-all` 显式输出 `version=2` 的设备结果集合；原 `--once` 仍按 `--vid/--pid/--usb-path` 读取单设备并保留原 JSON 形态。

确认配置后，显式保存，供下一次面板及登录启动使用：

```bash
python3 -B my_devices.py --set-targets /path/to/devices.json
python3 -B my_devices.py --clear-targets
```

第二条命令是恢复默认设备的可选操作。保存/清除不会改变正在运行实例，退出后重启生效。显式传入 VID/PID/usb-path 会覆盖已保存选择；不能同时传 `--targets`。已有实例选择不同会报错，需要先退出；刷新间隔可以在面板中应用。

绑定文件只指定名称和设备选择，不包含厂商命令；加入卡片不等于协议受支持。未知设备保持“协议未验证”，不会自动试发。离线标定 JSON 不能作为绑定文件。当前托盘只显示配置中第一台设备，面板显示全部绑定卡片。

托盘支持刷新、打开面板和退出。物理左右键映射取决于 GNOME 扩展；如果出现菜单，直接选择对应菜单项。
短暂休眠/超时但有历史电量时，托盘显示灰色的上次数值，悬停说明过期原因；只有确实没有可用数值时显示问号。左右顺序由 GNOME 宿主管理，本机位置固定扩展的安装及重新登录说明见 [可选 GNOME 扩展](../packaging/gnome-tray-position/README.md)。
关闭面板右上角 X：托盘可用时只是隐藏；托盘不可用时退出，避免留下无法操作的后台。

## 首次准备与安装

```bash
python3 -B my_devices.py --diagnose
python3 -B my_devices.py --once
```

先看诊断，再做主动查询。诊断里的 `protocol_unverified` 可能只是“未执行厂商查询”，不能单凭它判断本机 F98Pro 不支持；`--once` 才会尝试已验证配置。

| 条件 | 如何处理 |
|---|---|
| 缺少 tkinter | 在本机终端执行 `sudo apt install python3-tk`，然后用同一解释器重试 |
| 设备节点不可见 | 确认在宿主桌面运行，沙箱可能只看到 sysfs 却没有 `/dev/hidraw*` |
| 节点存在但无权读写 | 本机 F98Pro 可显式运行下方定向权限安装器；其他型号不能照搬 |
| 没有托盘宿主 | 先使用面板；诊断检查 GNOME StatusNotifierWatcher，按桌面环境补齐支持 |

```bash
sudo /usr/bin/python3 -B tools/install_device_access.py
python3 -B my_devices.py --install-desktop
```

权限安装器只支持当前严格匹配的 F98Pro 接收器，添加接口 03 的 uaccess 规则；不更改全部 hidraw 的权限。GUI 始终用普通用户启动。
`--install-desktop` 成功时输出三条路径，只代表符号链接和启动器已准备好，**不会启动程序，也不会开启登录自启**。
GNOME 如提示未受信任，先核对启动器确属本项目，再按桌面提示“允许启动”。这是桌面信任步骤，不代表要以管理员身份运行应用。

## 阅读卡片

| 显示 | 含义/处理 |
|---|---|
| 绿色 ≥60%、黄色 30～59%、红色 <30% | 最近一次有效电量；来源和时间显示在下面 |
| `?` | 尚无可靠百分比；不是 0% |
| 灰色旧百分比 / “上次电量已过期” | 保留的历史值，不是当前实时值；托盘保留灰色数字并在悬停中说明 |
| 超时 | 可能休眠、断开或协议不匹配，不自动断言设备关机 |
| `zero_unverified` | 收到 0，但当前协议未证明它表示空电量；按未知处理 |

若键盘长时间未使用，可用普通按键唤醒后点击“立即刷新”；不要通过恢复出厂设置来排查读取超时。
默认每 60 秒刷新，可设 30～1800 秒。界面输入数字后点击“应用”才会保存。
系统来源没有采样时间时会标为未知，不把本次读取时间伪装成硬件采样时间。

## 登录自启与配置位置

面板勾选“登录桌面后启动”，或明确执行：

```bash
python3 -B my_devices.py --autostart status
python3 -B my_devices.py --autostart on
python3 -B my_devices.py --autostart off
```

| 内容 | 位置 |
|---|---|
| 用户刷新间隔 | `${XDG_CONFIG_HOME:-~/.config}/local.keyboard-power/settings.json` |
| 保存的设备绑定 | 同一 `settings.json`，与刷新间隔共同保存 |
| 旧设置迁移备份 | 首次显式保存时生成同目录 `settings.before-v2.json`，不覆盖已有备份 |
| 登录入口 | `${XDG_CONFIG_HOME:-~/.config}/autostart/local.keyboard-power.desktop` |
| 单实例 / I/O 锁与 IPC | `$XDG_RUNTIME_DIR/local.keyboard-power.*` |
| 项目启动器 | 项目目录下 `local.keyboard-power.desktop` |
| 当前设备权限规则 | `/etc/udev/rules.d/70-keyboard-power.rules` |

程序不在后台自动重建用户禁用的入口。重新打开面板会读取实际状态；“已配置”不等于已完成下一次真实登录验证。
旧的仅含 interval 的设置可直接读取；不会因启动程序而迁移。显式保存才升级为设置 schema 2，并保留未知字段。损坏或未来版本的文件拒绝写入，请先备份检查。设备绑定 schema 1、设置 schema 2 与离线标定 schema 1 用途不同，不可互换。
重插后权限是否恢复、下一次登录是否自启，需要实际场景验证。无需手动删除锁文件来“解锁”：锁跟随进程/fd 生命周期，而不是跟随文件是否存在。

## 常见问题，按顺序排查

| 现象 | 最小检查 | 不应做什么 |
|---|---|---|
| `--status/--refresh/--quit` 报找不到 socket | 先用 `--panel` 启动；确认同一用户和桌面会话 | 不把这个错误当成键盘没有电量 |
| `permission_denied` | 枚举确认当前节点和接口，再检查定向规则/ACL | 不给所有 `/dev/hidraw*` chmod 666，不 sudo 启动 GUI |
| `missing_node` | 在宿主重新枚举；拔插会改变编号 | 不硬编码以前的 hidraw7 |
| 多接收器 `ambiguous_device` | 用 `--usb-path` 指定当前唯一目标 | 不默认使用第一个相同 VID/PID |
| USB 设备版本不匹配 | 记录版本和描述符，走新增设备流程 | 不移除版本检查来“修好”它 |
| `另一项 HID 操作正在进行` | 等调试/刷新结束再重试 | 不绕开事务锁，否则可能抢走其他操作的回复 |
| `没有声明 Feature Report` | 看描述符的报告类型；本机接口 03 本来就没有 Feature | 不扫描所有 Report ID；本机电量走 Input/Output |
| Feature 显示 `unverified_sample` | 这是按标准字段解码的候选值，需与设备实际显示对照 | 不把候选解码当成后台适配成功 |
| 保存 JSON 后常驻显示没变 | JSON 仅用于离线标定，尚未装入读取后端 | 不把加载 JSON 当成自动安装适配器 |
| 移动目录后入口失效 | 先退出，核对旧链接和生成启动器的 Exec 路径；安装器对冲突会拒绝覆盖 | 不批量删除桌面内容或重置全部用户配置 |

需要诊断输出时使用 `--debug`；平时不创建应用日志。
`--diagnose`、`--list-devices`、`--once` 等显式命令正常向控制台输出结果；主动保存的配置/报告不是日志。

## 开发功能的正确入口

调试窗口的接口页是只读枚举。监听或发送仅限纯厂商集合；试发前会显示完整字节要求确认。
标定页支持加载/保存 JSON、离线样本换算；不会自动执行保存的请求。不要把其他设备的请求贴到当前键盘上试验。
`--probe-aula` 用于查看原始样本，故意始终返回 2；**日常读取应使用 `--once`**。

新增设备见 [适配流程](device-adaptation.md)。测试和维护见 [贡献与测试](../CONTRIBUTING.md)。
