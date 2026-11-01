# Ubuntu 无线键盘电量工具

面向本机 **AULA 狼蛛 F98Pro · 2.4G**，支持按绑定生成的卡片面板、数字托盘和 HID 调试窗口。
仅使用 Python 标准库 + ctypes；GUI 需要系统 `python3-tk`，托盘使用系统 GIO/GLib 与 GNOME SNI 宿主。

默认只显示本机键盘；多卡片已有模拟验证，真实硬件目前只认证该 F98Pro 配置。新增型号先走证据与验证流程，不直接套用现有报文。

## 日常使用

在项目目录运行：

```bash
python3 -B my_devices.py --panel       # 打开面板；重复启动会前置已有实例
python3 -B my_devices.py --tray        # 托盘可用时隐藏面板
python3 -B my_devices.py --once        # 主动读取一次，成功退出码 0，未知/失败为 2
python3 -B my_devices.py --quit        # 完全退出已有实例
```

桌面日常入口是“键盘电量.desktop”启动器；Python 文件链接是否双击执行由 GNOME 决定。
`--install-desktop` 输出三条路径表示链接准备成功，不代表应用已经启动，也不会开启登录自启。
关闭面板 X 通常只是隐藏到托盘；要结束进程请用“退出”。托盘物理左右键映射由扩展决定，可使用菜单完成打开/刷新/退出。

首次检查、权限、自启、状态解释和逐步排障见 **[使用引导](docs/usage.md)**。
默认 60 秒刷新；用户点击“应用”后保存 30～1800 秒的自定义间隔。自启只由用户在面板勾选或执行 `--autostart on` 启用，程序不会自行修复禁用项。

## 按任务阅读

| 任务 | 文档 |
|---|---|
| 准备上传 GitHub：内容拆分、许可核对与推送步骤 | [GitHub 发布引导](docs/GITHUB_PUBLISH.md) |
| 在另一台电脑理解、复用或重建本工具 | [重建与适配说明](readme_rebuild.md) · [可复制重建提示词](prompt_rebuild.md) |
| 启动、安装、退出、权限与排障 | [使用引导](docs/usage.md) |
| 托盘问号、历史数值与固定位置 | [托盘修复及待登录验证](docs/tray-fix.md) |
| 当前模块边界、线程所有权与扩展方式 | [当前架构](docs/architecture.md) |
| 判断架构是否合理、修改会影响哪里 | [架构与间接影响审查](docs/architecture-review.md) |
| 完整重构的目标结构、契约与实施顺序 | [重构方案](docs/refactor-plan.md)与[阶段进度](docs/refactor-progress.md) |
| 新设备适配、哪些步骤能自动化 | [适配流程与自动化边界](docs/device-adaptation.md) |
| 运行测试、维护顺序、选择提示词 | [维护与验证](docs/maintenance.md) |
| 复用设备发现/协议验证/桌面接入/维护过程 | [prompts 目录](prompts/README.md) |
| 真实协议样本、历史硬件验收和本轮离线验证 | [验证记录](VALIDATION.md) |
| 最初需求及历史实施进展 | [prompt.md](prompt.md) |

## 当前支持与边界

- 已核对设备：F98Pro，接收器 `05AC:024F`、`2.4G Dongle`、USB `bcdDevice=0121`、接口 03、精确匹配的 FF60/0061 描述符。USB 版本不是已识别的固件版本。
- 实机电量首次 39% 与键盘屏幕一致，随后读取到 38%、37%。并不证明所有 F98Pro 版本兼容。
- 未编号 Input/Output 载荷各 32B；Linux 写缓冲区额外加 `00`。严格回复校验，休眠超时不伪造为 0%。完整报文见验证记录。
- 系统 power_supply/UPower 来源优先，但必须关联到目标；过期缓存允许已支持适配器尝试更新，失败则保留缓存并说明原因。标准 HID 支持显式 Feature 调试及候选解码，尚未启用通用自动读取。
- JSON 标定可保存、离线换算、配合显式试发；**保存/加载 JSON 不会安装自动读取适配器**。
- GUI 不以 root 运行。权限安装器及 udev 规则只针对当前 F98Pro，不应复制给其他型号。
- 不写应用日志；`--debug` 输出诊断，显式 CLI 命令正常输出结果。用户配置、主动保存的报告与验收截图不属于日志。

## 开发验证

统一匹配、适配器、调度服务、多卡片与版本化配置已落地。阶段备份、实机验收与剩余人工场景见 [重构进度](docs/refactor-progress.md)。

```bash
python3 -B -m unittest discover -s tests -v
```

单元测试使用临时数据与模拟设备；本地 socket 被沙箱禁止时需在宿主执行。
真实桌面验收脚本会关闭已有实例、发送电量查询或截图，运行前先看 [维护文档中的副作用表](docs/maintenance.md)。历史 CPU 和启停结果不能冒充本轮重测。

协议依据：[Linux hidraw](https://www.kernel.org/doc/html/latest/hid/hidraw.html)、[同系列原始实现](https://github.com/Ghost-CR/F75_Initializer/blob/master/aula_hacky/protocol_core.py)。

## 贡献与许可状态

新增设备和问题报告见 [CONTRIBUTING.md](CONTRIBUTING.md)。协议参考与待核对的授权范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；目前尚未添加项目 LICENSE，不宣称已经采用某种开源许可证。
